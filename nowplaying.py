#!/usr/bin/env python3
"""Compatibility entry point for the OBS now-playing overlay."""

from pathlib import Path
import sys


APP_DIR = Path(__file__).resolve().parent
SRC_DIR = APP_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from apple_music_obs_overlay.cli import main


if __name__ == "__main__":
    raise SystemExit(main())
