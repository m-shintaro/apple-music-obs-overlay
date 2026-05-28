from __future__ import annotations

import json
from pathlib import Path
import time
from typing import Any, Dict


REPLACE_RETRIES = 5
REPLACE_RETRY_DELAY = 0.05


def ensure_runtime_dir(runtime_dir: Path) -> None:
    runtime_dir.mkdir(parents=True, exist_ok=True)


def replace_with_retry(tmp: Path, path: Path) -> None:
    delay = REPLACE_RETRY_DELAY
    for attempt in range(REPLACE_RETRIES):
        try:
            tmp.replace(path)
            return
        except PermissionError:
            if attempt == REPLACE_RETRIES - 1:
                raise
            time.sleep(delay)
            delay *= 2


def atomic_write_text(path: Path, text: str) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    replace_with_retry(tmp, path)


def atomic_write_bytes(path: Path, data: bytes) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(data)
    replace_with_retry(tmp, path)


def write_outputs(data: Dict[str, Any], runtime_dir: Path) -> None:
    state = str(data.get("state") or "stopped")
    artist = str(data.get("artist") or "")
    title = str(data.get("title") or "")
    position_text = str(data.get("positionText") or "0:00")
    duration_text = str(data.get("durationText") or "0:00")

    if state == "playing":
        text = (
            f"\u266a {artist} - {title}  "
            f"{position_text} / {duration_text}"
        )
    elif state == "paused":
        text = (
            f"Paused: {artist} - {title}  "
            f"{position_text} / {duration_text}"
        )
    else:
        text = ""

    text_error: OSError | None = None
    try:
        atomic_write_text(runtime_dir / "nowplaying.txt", text)
    except OSError as exc:
        text_error = exc

    atomic_write_text(
        runtime_dir / "nowplaying.json",
        json.dumps(data, ensure_ascii=False, indent=2),
    )

    if text_error is not None:
        raise text_error
