from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict


def ensure_runtime_dir(runtime_dir: Path) -> None:
    runtime_dir.mkdir(parents=True, exist_ok=True)


def atomic_write_text(path: Path, text: str) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def atomic_write_bytes(path: Path, data: bytes) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(data)
    tmp.replace(path)


def write_outputs(data: Dict[str, Any], runtime_dir: Path) -> None:
    if data["state"] == "playing":
        text = (
            f"\u266a {data['artist']} - {data['title']}  "
            f"{data['positionText']} / {data['durationText']}"
        )
    elif data["state"] == "paused":
        text = (
            f"Paused: {data['artist']} - {data['title']}  "
            f"{data['positionText']} / {data['durationText']}"
        )
    else:
        text = ""

    atomic_write_text(runtime_dir / "nowplaying.txt", text)
    atomic_write_text(
        runtime_dir / "nowplaying.json",
        json.dumps(data, ensure_ascii=False, indent=2),
    )
