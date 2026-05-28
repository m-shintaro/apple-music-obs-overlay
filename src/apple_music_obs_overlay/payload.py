from __future__ import annotations

import time
from typing import Any, Dict


Payload = Dict[str, Any]


def fmt_time(seconds: float) -> str:
    seconds = max(0, int(seconds))
    return f"{seconds // 60}:{seconds % 60:02d}"


def safe_float(value: object) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def clamp(value: float, min_value: float = 0.0, max_value: float = 1.0) -> float:
    return max(min_value, min(max_value, value))


def normalize_state(state: object) -> str:
    value = str(state or "stopped").strip().lower()
    if value in {"playing", "paused", "stopped", "error"}:
        return value
    return value or "stopped"


def default_payload(state: str = "stopped", error: str = "") -> Payload:
    return {
        "state": normalize_state(state),
        "title": "",
        "artist": "",
        "album": "",
        "position": 0,
        "duration": 0,
        "positionText": "0:00",
        "durationText": "0:00",
        "progress": 0,
        "artworkFile": "",
        "artworkVersion": "",
        "artworkSource": "",
        "artworkError": "",
        "updatedAt": time.time(),
        "error": error,
    }


def build_payload(
    state: object,
    title: object,
    artist: object,
    album: object,
    position: object,
    duration: object,
    error: str = "",
) -> Payload:
    position_value = max(0.0, safe_float(position))
    duration_value = max(0.0, safe_float(duration))
    progress = position_value / duration_value if duration_value > 0 else 0
    return {
        "state": normalize_state(state),
        "title": str(title or ""),
        "artist": str(artist or ""),
        "album": str(album or ""),
        "position": position_value,
        "duration": duration_value,
        "positionText": fmt_time(position_value),
        "durationText": fmt_time(duration_value),
        "progress": clamp(progress),
        "artworkFile": "",
        "artworkVersion": "",
        "artworkSource": "",
        "artworkError": "",
        "updatedAt": time.time(),
        "error": error,
    }


def make_track_key(data: Payload) -> str:
    return "|".join(
        [
            str(data.get("title", "")),
            str(data.get("artist", "")),
            str(data.get("album", "")),
            str(data.get("duration", 0)),
        ]
    )
