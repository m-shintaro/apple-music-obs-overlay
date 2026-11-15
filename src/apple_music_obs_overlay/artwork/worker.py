from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
import threading
from typing import Any, Dict

from .image import normalize_artwork
from .itunes import fetch_artwork_from_itunes_search
from ..providers.base import NowPlayingProvider


@dataclass
class ArtworkJobResult:
    generation: int
    image: bytes = b""
    source: str = ""
    error: str = ""
    provider_found: bool = False


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

    @property
    def busy(self) -> bool:
        return self.thread is not None

    def start(self, generation: int, data: Dict[str, Any], network: bool) -> None:
        if self.busy:
            raise RuntimeError("artwork job already running")
        self.thread = threading.Thread(
            target=self._run, args=(generation, dict(data), network), daemon=True,
            name="overlay-artwork",
        )
        self.thread.start()

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
                    result.error = artwork.error
                    if artwork.file:
                        result.image = normalize_artwork((scratch / artwork.file).read_bytes())
                        result.source = artwork.source
                        result.provider_found = True
                        result.error = ""
                except Exception as exc:
                    result.error = f"{self.provider.name}:artwork:{exc}"
                if not result.image and network:
                    file, error = fetch_artwork_from_itunes_search(data, scratch, self.country)
                    if file:
                        result.image = normalize_artwork((scratch / file).read_bytes())
                        result.source = "itunes"
                        result.error = ""
                    elif not result.error:
                        result.error = error
        except Exception as exc:
            result.error = f"artwork:{exc}"
        self.result = result
