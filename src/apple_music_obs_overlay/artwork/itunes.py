from __future__ import annotations

import json
import multiprocessing
from pathlib import Path
import threading
import time
from typing import Any, Dict, Tuple
import urllib.parse
import urllib.request

from ..output import atomic_write_bytes


SEARCH_URL = "https://itunes.apple.com/search"
NETWORK_ARTWORK_TIMEOUT = 5.0
# Starting the worker process can be slow (cold start, antivirus scanning) and
# must not use up the network budget.
WORKER_START_TIMEOUT = 10.0
# Answers that will not change on a retry; anything else may be transient.
CONCLUSIVE_ERRORS = frozenset(
    {"itunes:no_search_terms", "itunes:no_results", "itunes:no_artwork_url"}
)
MAX_SEARCH_BYTES = 1024 * 1024
MAX_ARTWORK_BYTES = 20 * 1024 * 1024


def fetch_artwork_from_itunes_search(
    data: Dict[str, Any],
    runtime_dir: Path,
    country: str,
    cancel_event: threading.Event | None = None,
) -> Tuple[str, str]:
    title = data.get("title") or ""
    artist = data.get("artist") or ""
    if not title and not artist:
        return "", "itunes:no_search_terms"

    params = {
        "term": f"{artist} {title}".strip(),
        "country": country,
        "media": "music",
        "entity": "song",
        "limit": "1",
    }
    search_url = SEARCH_URL + "?" + urllib.parse.urlencode(params)
    if cancel_event is not None and cancel_event.is_set():
        return "", "itunes:cancelled"

    # urllib's timeout is per socket operation, so trickling headers/bodies and
    # DNS can exceed it. Isolate the whole lookup, including both image URLs,
    # in one killable process with a wall-clock deadline. Never leave abandoned
    # downloading threads behind when the song changes. The deadline starts
    # once the worker reports that it is running.
    ready = False
    deadline = time.monotonic() + WORKER_START_TIMEOUT
    context = multiprocessing.get_context("spawn")
    receive, send = context.Pipe(duplex=False)
    process = context.Process(target=_fetch_in_process,
                              args=(search_url, str(runtime_dir), send), daemon=True)
    started = False
    try:
        process.start()
        started = True
        send.close()
        while True:
            if cancel_event is not None and cancel_event.is_set():
                return "", "itunes:cancelled"
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return "", "itunes:timeout" if ready else "itunes:worker_start_timeout"
            if receive.poll(min(0.05, remaining)):
                message = receive.recv()
                if message is not None:
                    return message
                ready = True
                deadline = time.monotonic() + NETWORK_ARTWORK_TIMEOUT
                continue
            if not process.is_alive():
                return "", "itunes:worker_exited"
    except Exception as exc:
        detail = str(exc).strip() or exc.__class__.__name__
        return "", f"itunes:{detail}"
    finally:
        # Reap before returning: the next job must not overlap a cancelled one
        # or delete its scratch directory while it is still writing there.
        if started:
            if process.is_alive():
                process.terminate()
            process.join(0.5)
            if process.is_alive():
                process.kill()
                process.join()
        process.close()
        receive.close()
        send.close()


def _fetch_in_process(search_url: str, runtime_dir: str, send) -> None:
    try:
        send.send(None)  # Running: the parent starts the network deadline now.
        send.send(_download_artwork(search_url, Path(runtime_dir)))
    finally:
        send.close()


def _read_limited(response, limit: int) -> bytes:
    data = response.read(limit + 1)
    if len(data) > limit:
        raise ValueError("response_too_large")
    return data


def _download_artwork(search_url: str, runtime_dir: Path) -> Tuple[str, str]:
    try:
        with urllib.request.urlopen(search_url, timeout=5) as res:
            payload = json.loads(_read_limited(res, MAX_SEARCH_BYTES).decode("utf-8"))

        results = payload.get("results") or []
        if not results:
            return "", "itunes:no_results"

        artwork_url = results[0].get("artworkUrl100")
        if not artwork_url:
            return "", "itunes:no_artwork_url"

        large_url = (
            artwork_url.replace("100x100bb", "600x600bb")
            .replace("100x100-75", "600x600-75")
            .replace("100x100", "600x600")
        )

        try:
            with urllib.request.urlopen(large_url, timeout=5) as img_res:
                image = _read_limited(img_res, MAX_ARTWORK_BYTES)
        except Exception:
            with urllib.request.urlopen(artwork_url, timeout=5) as img_res:
                image = _read_limited(img_res, MAX_ARTWORK_BYTES)

        out = runtime_dir / "cover_fallback.jpg"
        atomic_write_bytes(out, image)
        return out.name, ""
    except Exception as exc:
        detail = str(exc).strip() or exc.__class__.__name__
        return "", f"itunes:{detail}"
