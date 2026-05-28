from __future__ import annotations

import threading
from pathlib import Path
from typing import Any, Dict

from .artwork.itunes import fetch_artwork_from_itunes_search
from .output import write_outputs
from .payload import default_payload, make_track_key
from .providers.base import NowPlayingProvider
from .providers.demo import DemoProvider


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
    is_demo = isinstance(provider, DemoProvider)

    while not stop_event.is_set():
        data = _safe_nowplaying(provider)

        if data["state"] in ("playing", "paused"):
            track_key = make_track_key(data)
            if track_key != last_track_key:
                artwork_file = ""
                artwork_source = ""
                artwork_error = ""

                if not is_demo:
                    try:
                        artwork = provider.get_artwork(data)
                        artwork_file = artwork.file
                        artwork_source = artwork.source
                        artwork_error = artwork.error
                    except Exception as exc:
                        detail = str(exc).strip() or exc.__class__.__name__
                        artwork_error = f"{provider.name}:artwork:{detail}"

                if not artwork_file and allow_network_artwork and not is_demo:
                    fallback_file, fallback_error = fetch_artwork_from_itunes_search(
                        data,
                        runtime_dir,
                        country,
                    )
                    if fallback_file:
                        artwork_file = fallback_file
                        artwork_source = "itunes"
                        artwork_error = ""
                    elif not artwork_error:
                        artwork_error = fallback_error

                last_artwork_file = artwork_file
                last_artwork_source = artwork_source
                last_artwork_error = "" if artwork_file else artwork_error
                last_track_key = track_key

            data["artworkFile"] = last_artwork_file
            data["artworkVersion"] = last_track_key
            data["artworkSource"] = last_artwork_source
            data["artworkError"] = last_artwork_error
        else:
            last_track_key = ""
            last_artwork_file = ""
            last_artwork_source = ""
            last_artwork_error = ""

        write_outputs(data, runtime_dir)
        stop_event.wait(interval)


def _safe_nowplaying(provider: NowPlayingProvider) -> Dict[str, Any]:
    try:
        return provider.get_nowplaying()
    except Exception as exc:
        detail = str(exc).strip() or exc.__class__.__name__
        return default_payload("error", f"{provider.name}:{detail}")
