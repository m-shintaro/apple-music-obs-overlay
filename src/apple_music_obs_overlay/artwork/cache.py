from __future__ import annotations

from collections import OrderedDict
import hashlib
from pathlib import Path
import re
from typing import Tuple

from ..output import atomic_write_bytes
from .image import detect_image_suffix


MAX_CACHED_ARTWORK = 8
_MANAGED_COVER = re.compile(r"cover_[0-9a-f]{64}\.(?:jpg|png|gif|webp)\Z")


class ArtworkCache:
    """Publish immutable content URLs and retain only a small set of covers."""

    def __init__(self, runtime_dir: Path) -> None:
        self.runtime_dir = runtime_dir
        self.recent: OrderedDict[str, None] = OrderedDict()

    def publish(self, image: bytes) -> Tuple[str, str]:
        version = hashlib.sha256(image).hexdigest()
        suffix = detect_image_suffix(image)
        if suffix not in (".jpg", ".png", ".gif", ".webp"):
            raise OSError("Unsupported published artwork format")
        file = f"cover_{version}{suffix}"
        path = self.runtime_dir / file
        if not path.exists():
            atomic_write_bytes(path, image)
        self.recent[file] = None
        self.recent.move_to_end(file)
        while len(self.recent) > MAX_CACHED_ARTWORK:
            self.recent.popitem(last=False)
        # Retry deletion next time if a Windows reader temporarily holds a file.
        # Never delete raw diagnostic images or files owned by another feature.
        for old in self.runtime_dir.glob("cover_*.*"):
            if _MANAGED_COVER.fullmatch(old.name) and old.name not in self.recent:
                try:
                    old.unlink(missing_ok=True)
                except OSError:
                    pass
        return file, version
