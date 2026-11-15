from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any, Dict

from .artwork.worker import ArtworkWorker
from .artwork.cache import ArtworkCache
from .output import write_outputs
from .payload import default_payload, make_track_key
from .providers.base import NowPlayingProvider
from .providers.demo import DemoProvider


ARTWORK_RETRY_INTERVAL = 5.0
# Network lookups per track when they end without a definitive answer
# (timeout, connection error, failed publication).
MAX_NETWORK_ARTWORK_ATTEMPTS = 3
# Minimum spacing of lookups triggered by provider change signals, which can
# arrive in bursts (seeking, a track change published in several steps).
ARTWORK_REFRESH_INTERVAL = 1.0


def poll_loop(
    stop_event: threading.Event,
    provider: NowPlayingProvider,
    runtime_dir: Path,
    interval: float,
    country: str,
    allow_network_artwork: bool,
) -> None:
    worker = ArtworkWorker(provider, country)
    cache = ArtworkCache(runtime_dir)
    generation = 0
    last_track_key = ""
    artwork_file = artwork_version = artwork_source = artwork_error = ""
    last_attempt_at = None
    attempt_revision = 0
    network_attempts = 0
    provider_found = False
    is_demo = isinstance(provider, DemoProvider)

    try:
        while not stop_event.is_set():
            data = _safe_nowplaying(provider)
            playable = data.get("state") in ("playing", "paused")
            track_key = make_track_key(data) if playable else ""
            if track_key != last_track_key:
                worker.cancel()
                generation += 1
                last_track_key = track_key
                artwork_file = artwork_version = artwork_source = artwork_error = ""
                last_attempt_at = None
                network_attempts = 0
                provider_found = False

            result = worker.take_result()
            if result is not None and result.generation == generation and playable:
                # A sampled track mismatch needs a fresh snapshot immediately;
                # other misses retry five seconds after completion.
                last_attempt_at = None if result.track_changed else time.monotonic()
                published = False
                if result.image:
                    try:
                        artwork_file, artwork_version = cache.publish(result.image)
                        artwork_source, artwork_error = result.source, ""
                        provider_found = result.provider_found
                        published = True
                    except OSError as exc:
                        artwork_error = f"artwork:publish:{exc}"
                elif not artwork_file:
                    artwork_error = result.error
                if result.network_attempted:
                    # Only a definitive answer ends the fallback for this track.
                    # A transient failure must not cost the track its cover.
                    settled = result.network_conclusive and (published or not result.image)
                    network_attempts = (
                        MAX_NETWORK_ARTWORK_ATTEMPTS if settled else network_attempts + 1
                    )

            if playable:
                data.update(artworkFile=artwork_file, artworkVersion=artwork_version,
                            artworkSource=artwork_source, artworkError=artwork_error,
                            artworkPending=not is_demo and (last_attempt_at is None or worker.busy))

            # Metadata keeps moving while the single artwork worker is busy.
            _safe_write_outputs(data, runtime_dir)
            now = time.monotonic()
            if not stop_event.is_set() and playable and not is_demo and not worker.busy:
                revision = provider.artwork_revision()
                # An accepted cover can be a placeholder or the previous
                # track's image that the source replaces a moment later.
                changed = (revision != attempt_revision and last_attempt_at is not None and
                           now - last_attempt_at >= ARTWORK_REFRESH_INTERVAL)
                retry = (not provider_found and last_attempt_at is not None and
                         now - last_attempt_at >= ARTWORK_RETRY_INTERVAL)
                if last_attempt_at is None or changed or retry:
                    network = (allow_network_artwork and
                               network_attempts < MAX_NETWORK_ARTWORK_ATTEMPTS)
                    last_attempt_at = now
                    attempt_revision = revision
                    worker.start(generation, data, network)
            stop_event.wait(interval)
    finally:
        worker.close()


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
