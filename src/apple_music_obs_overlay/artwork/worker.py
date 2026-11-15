from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
import threading
from typing import Any, Dict

from .image import normalize_artwork
from .itunes import CONCLUSIVE_ERRORS, fetch_artwork_from_itunes_search
from ..providers.base import NowPlayingProvider


@dataclass
class ArtworkJobResult:
    generation: int
    image: bytes = b""
    source: str = ""
    error: str = ""
    provider_found: bool = False
    track_changed: bool = False
    network_attempted: bool = False
    # The network lookup gave a definitive answer; retrying it is pointless.
    network_conclusive: bool = False


class ArtworkWorker:
    """At most one job, no pending queue. Only the poller publishes results.

    Providers write to per-job scratch space, so a superseded job cannot overwrite
    a cover currently served to OBS. Thread completion synchronizes the result.
    """

    def __init__(self, provider: NowPlayingProvider, country: str) -> None:
        self.provider = provider
        self.country = country
        self.thread: threading.Thread | None = None
        self.result: ArtworkJobResult | None = None
        self.cancel_event = threading.Event()

    @property
    def busy(self) -> bool:
        return self.thread is not None

    def start(self, generation: int, data: Dict[str, Any], network: bool) -> None:
        if self.busy:
            raise RuntimeError("artwork job already running")
        self.cancel_event = threading.Event()
        self.thread = threading.Thread(
            target=self._run, args=(generation, dict(data), network), daemon=True,
            name="overlay-artwork",
        )
        self.thread.start()

    def cancel(self) -> None:
        self.cancel_event.set()

    def close(self) -> None:
        self.cancel()
        if self.thread is not None:
            # Network jobs terminate immediately; native APIs keep their own
            # existing timeouts. Do not hold application shutdown indefinitely.
            self.thread.join(timeout=2)

    def take_result(self) -> ArtworkJobResult | None:
        if self.thread is None or self.thread.is_alive():
            return None
        self.thread.join()
        self.thread = None
        result, self.result = self.result, None
        return result

    def _run(self, generation: int, data: Dict[str, Any], network: bool) -> None:
        result = ArtworkJobResult(generation)
        try:
            with TemporaryDirectory(prefix="obs-overlay-artwork-") as tmp:
                scratch = Path(tmp)
                try:
                    artwork = self.provider.get_artwork(data, runtime_dir=scratch)
                    if self.cancel_event.is_set():
                        return
                    result.error = artwork.error
                    result.track_changed = artwork.track_changed
                    if artwork.track_changed:
                        return
                    if artwork.file:
                        result.image = normalize_artwork((scratch / artwork.file).read_bytes())
                        result.source = artwork.source
                        result.provider_found = True
                        result.error = ""
                except Exception as exc:
                    result.error = f"{self.provider.name}:artwork:{exc}"
                if not result.image and network and not self.cancel_event.is_set():
                    result.network_attempted = True
                    file, error = fetch_artwork_from_itunes_search(
                        data, scratch, self.country, cancel_event=self.cancel_event)
                    if self.cancel_event.is_set():
                        return
                    result.network_conclusive = bool(file) or error in CONCLUSIVE_ERRORS
                    if file:
                        result.image = normalize_artwork((scratch / file).read_bytes())
                        result.source = "itunes"
                        result.error = ""
                    elif not result.error:
                        result.error = error
        except Exception as exc:
            result.error = f"artwork:{exc}"
        finally:
            if self.cancel_event.is_set():
                result.image = b""
                result.error = "artwork:cancelled"
            self.result = result
