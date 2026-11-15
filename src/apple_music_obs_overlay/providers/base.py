from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Protocol


@dataclass
class ArtworkResult:
    file: str = ""
    source: str = ""
    error: str = ""
    # The sampled artwork cannot be attributed to the requested track (yet):
    # retry promptly with a fresh snapshot instead of falling back to network.
    track_changed: bool = False


class NowPlayingProvider(Protocol):
    name: str

    def get_nowplaying(self) -> Dict[str, Any]:
        ...

    def get_nowplaying_once(self) -> Dict[str, Any]:
        ...

    def get_artwork(self, data: Dict[str, Any], runtime_dir: Path | None = None) -> ArtworkResult:
        ...

    def artwork_revision(self) -> int:
        ...

    def close(self) -> None:
        ...


class BaseProvider:
    name = "base"

    def get_nowplaying_once(self) -> Dict[str, Any]:
        return self.get_nowplaying()

    def close(self) -> None:
        pass

    def artwork_revision(self) -> int:
        """Changes whenever the current track's artwork may have changed.

        Lets a provider that learns about updates have an accepted cover read
        again; providers without such a signal keep the constant default.
        """
        return 0

    def allow_itunes_fallback(self, data: Dict[str, Any]) -> bool:
        return True

    def get_artwork(self, data: Dict[str, Any], runtime_dir: Path | None = None) -> ArtworkResult:
        return ArtworkResult()
