from __future__ import annotations

import time
from typing import Any, Dict, Optional

from ..payload import build_payload
from .base import BaseProvider


DEMO_TRACKS = [
    {
        "title": "Midnight Current",
        "artist": "Sample Artist",
        "album": "OBS Preview",
        "duration": 214,
    },
    {
        "title": "Signal in Bloom",
        "artist": "Apple Music Demo",
        "album": "Local Overlay",
        "duration": 188,
    },
]


class DemoProvider(BaseProvider):
    name = "demo"

    def __init__(self, start_time: Optional[float] = None) -> None:
        self.start_time = time.time() if start_time is None else start_time

    def get_nowplaying(self) -> Dict[str, Any]:
        elapsed = time.time() - self.start_time
        track_index = int(elapsed // 28) % len(DEMO_TRACKS)
        track = DEMO_TRACKS[track_index]
        duration = track["duration"]
        position = elapsed % min(28, duration)
        return build_payload(
            "playing",
            track["title"],
            track["artist"],
            track["album"],
            position,
            duration,
        )
