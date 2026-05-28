from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any, Dict, Tuple

from .artwork.itunes import fetch_artwork_from_itunes_search
from .output import write_outputs
from .payload import default_payload, make_track_key
from .providers.base import NowPlayingProvider
from .providers.demo import DemoProvider


ARTWORK_RETRY_INTERVAL = 5.0


def poll_loop(
    stop_event: threading.Event,
    provider: NowPlayingProvider,
    runtime_dir: Path,
    interval: float,
    country: str,
    allow_network_artwork: bool,
) -> None:
    last_track_key = ""
    last_artwork_file = ""
    last_artwork_source = ""
    last_artwork_error = ""
    last_artwork_attempt_at = 0.0
    last_network_artwork_key = ""
    last_provider_artwork_found = False
    is_demo = isinstance(provider, DemoProvider)

    while not stop_event.is_set():
        data = _safe_nowplaying(provider)

        if data.get("state") in ("playing", "paused"):
            track_key = make_track_key(data)
            track_changed = track_key != last_track_key
            now = time.monotonic()
            should_retry_artwork = (
                not track_changed
                and not is_demo
                and not last_provider_artwork_found
                and now - last_artwork_attempt_at >= ARTWORK_RETRY_INTERVAL
            )

            if track_changed:
                last_artwork_file = ""
                last_artwork_source = ""
                last_artwork_error = ""
                last_artwork_attempt_at = 0.0
                last_network_artwork_key = ""
                last_provider_artwork_found = False
                last_track_key = track_key

            if track_changed or should_retry_artwork:
                last_artwork_attempt_at = now
                artwork_file, artwork_source, artwork_error = _resolve_provider_artwork(
                    provider,
                    data,
                    is_demo,
                )

                if artwork_file:
                    last_provider_artwork_found = True
                    last_artwork_file = artwork_file
                    last_artwork_source = artwork_source
                    last_artwork_error = ""
                elif not last_artwork_file:
                    last_artwork_error = artwork_error

                if (
                    not last_artwork_file
                    and allow_network_artwork
                    and not is_demo
                    and last_network_artwork_key != track_key
                ):
                    last_network_artwork_key = track_key
                    fallback_file, fallback_error = fetch_artwork_from_itunes_search(
                        data,
                        runtime_dir,
                        country,
                    )
                    if fallback_file:
                        last_artwork_file = fallback_file
                        last_artwork_source = "itunes"
                        last_artwork_error = ""
                    elif not last_artwork_error:
                        last_artwork_error = fallback_error

            data["artworkFile"] = last_artwork_file
            data["artworkVersion"] = last_track_key
            data["artworkSource"] = last_artwork_source
            data["artworkError"] = last_artwork_error
        else:
            last_track_key = ""
            last_artwork_file = ""
            last_artwork_source = ""
            last_artwork_error = ""
            last_artwork_attempt_at = 0.0
            last_network_artwork_key = ""
            last_provider_artwork_found = False

        _safe_write_outputs(data, runtime_dir)
        stop_event.wait(interval)


def _resolve_provider_artwork(
    provider: NowPlayingProvider,
    data: Dict[str, Any],
    is_demo: bool,
) -> Tuple[str, str, str]:
    if is_demo:
        return "", "", ""

    try:
        artwork = provider.get_artwork(data)
        return artwork.file, artwork.source, artwork.error
    except Exception as exc:
        detail = str(exc).strip() or exc.__class__.__name__
        return "", "", f"{provider.name}:artwork:{detail}"


def _safe_nowplaying(provider: NowPlayingProvider) -> Dict[str, Any]:
    try:
        return provider.get_nowplaying()
    except Exception as exc:
        detail = str(exc).strip() or exc.__class__.__name__
        return default_payload("error", f"{provider.name}:{detail}")


def _safe_write_outputs(data: Dict[str, Any], runtime_dir: Path) -> None:
    try:
        write_outputs(data, runtime_dir)
    except OSError:
        return
