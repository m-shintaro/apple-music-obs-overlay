from __future__ import annotations

import base64
import binascii
import json
import math
import os
from pathlib import Path
import platform
import shutil
import subprocess
import threading
import time
from typing import Any, Dict

from ..artwork.image import convert_artwork_file
from ..payload import build_payload, default_payload, same_track
from .base import ArtworkResult, BaseProvider


INSTALL_HELP = "Install macOS system media support with: brew install media-control"
MAX_METADATA_BYTES = 128 * 1024
MAX_ARTWORK_BYTES = 20 * 1024 * 1024


def find_media_control() -> str | None:
    found = shutil.which("media-control")
    if found:
        return found
    # GUI launches often omit Homebrew from PATH (Apple Silicon and Intel).
    for prefix in ("/opt/homebrew", "/usr/local"):
        candidate = Path(prefix) / "bin/media-control"
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    return None


def _number(value: object, default: float = 0.0) -> float:
    try:
        number = float(value)
        return number if math.isfinite(number) else default
    except (TypeError, ValueError, OverflowError):
        return default


def media_payload(raw: Dict[str, Any], now: float) -> Dict[str, Any]:
    if not raw.get("title") or not raw.get("bundleIdentifier"):
        return default_payload()
    playing = raw.get("playing") is True
    rate = max(0.0, _number(raw.get("playbackRate"), 1.0)) if playing else 0.0
    position = max(0.0, _number(raw.get("elapsedTimeMicros")) / 1_000_000)
    timestamp = _number(raw.get("timestampEpochMicros")) / 1_000_000
    if timestamp > 0 and "elapsedTimeMicros" in raw:
        position += max(0.0, now - timestamp) * rate
    duration = max(0.0, _number(raw.get("durationMicros")) / 1_000_000)
    if duration:
        position = min(position, duration)
    data = build_payload("playing" if playing else "paused", raw["title"],
                         raw.get("artist"), raw.get("album"), position, duration)
    data.update(sourceAppId=str(raw["bundleIdentifier"]),
                trackId=str(raw.get("contentItemIdentifier") or raw.get("uniqueIdentifier") or ""),
                playbackRate=rate)
    return data


class MacOSMediaProvider(BaseProvider):
    """One metadata-only MediaRemote stream; covers are fetched by the artwork worker.

    Uses media-control 0.7.7's JSON interface. A full snapshot replaces the old
    one so missing fields, seeks and app switches cannot retain stale metadata.
    """

    name = "macos-media"

    def __init__(self, runtime_dir: Path, executable: str | None = None, timeout: float = 5.0) -> None:
        self.runtime_dir = runtime_dir
        self.executable = executable or find_media_control()
        self.timeout = timeout
        self._lock = threading.Lock()
        self._ready = threading.Event()
        self._process = None
        self._thread = None
        self._closed = False
        self._error = ""
        self._snapshot: Dict[str, Any] = {}
        self._received_at = 0.0
        self._received_epoch = 0.0

    def _start(self) -> None:
        with self._lock:
            if self._process is not None or self._error or self._closed:
                return
            if platform.system() != "Darwin":
                self._error = "macos-media:unsupported_platform"
            elif not self.executable:
                self._error = f"macos-media:missing_media_control:{INSTALL_HELP}"
            else:
                try:
                    self._process = subprocess.Popen(
                        [self.executable, "stream", "--micros", "--no-diff", "--no-artwork"],
                        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                    )
                except OSError as exc:
                    self._error = f"macos-media:start:{exc}"
            if self._error:
                self._ready.set()
                return
            self._thread = threading.Thread(target=self._read_stream, daemon=True, name="macos-media")
            self._thread.start()

    def _read_stream(self) -> None:
        process = self._process
        try:
            while not self._closed:
                line = process.stdout.readline(MAX_METADATA_BYTES + 1)
                if not line:
                    raise ValueError("stream_ended")
                if len(line) > MAX_METADATA_BYTES:
                    raise ValueError("metadata_too_large")
                event = json.loads(line)
                if (not isinstance(event, dict) or event.get("type") != "data" or
                        event.get("diff") is not False or not isinstance(event.get("payload"), dict)):
                    raise ValueError("invalid_stream_event")
                with self._lock:
                    self._snapshot = event["payload"]
                    self._received_at = time.monotonic()
                    self._received_epoch = time.time()
                self._ready.set()
        except (OSError, ValueError) as exc:
            with self._lock:
                self._error = f"macos-media:{exc}"
        finally:
            self._ready.set()
            self._stop_process()
            process.stdout.close()

    def get_nowplaying(self) -> Dict[str, Any]:
        self._start()
        if not self._ready.wait(self.timeout):
            self.close()
            return default_payload("error", "macos-media:startup_timeout")
        with self._lock:
            if self._closed or self._error:
                return default_payload("error", self._error or "macos-media:closed")
            # Advance from a monotonic anchor, even if the wall clock changes.
            now = self._received_epoch + time.monotonic() - self._received_at
            return media_payload(self._snapshot, now)

    def allow_itunes_fallback(self, data: Dict[str, Any]) -> bool:
        # A YouTube video's title/channel is not an iTunes song/artist pair.
        return data.get("sourceAppId") == "com.apple.Music"

    def _query(self, artwork: bool = False) -> Dict[str, Any]:
        if platform.system() != "Darwin":
            raise ValueError("unsupported_platform")
        if not self.executable:
            raise ValueError(f"missing_media_control:{INSTALL_HELP}")
        command = [self.executable, "get", "--micros"]
        if not artwork:
            command.append("--no-artwork")
        result = subprocess.run(command, capture_output=True, timeout=self.timeout, check=False)
        if result.returncode:
            raise ValueError(f"exit_{result.returncode}")
        raw = json.loads(result.stdout)
        if raw is None:
            return {}
        if not isinstance(raw, dict):
            raise ValueError("invalid_snapshot")
        return raw

    def get_nowplaying_once(self) -> Dict[str, Any]:
        # stream emits an empty startup event before its first native query.
        # A one-shot command must await the actual query instead.
        try:
            return media_payload(self._query(), time.time())
        except subprocess.TimeoutExpired:
            return default_payload("error", "macos-media:query_timeout")
        except (OSError, ValueError) as exc:
            return default_payload("error", f"macos-media:{exc}")

    def get_artwork(self, data: Dict[str, Any], runtime_dir: Path | None = None) -> ArtworkResult:
        try:
            raw = self._query(artwork=True)
            if not raw or not same_track(data, media_payload(raw, time.time())):
                return ArtworkResult(error="macos-media:artwork:track_changed", track_changed=True)
            encoded = raw.get("artworkData")
            if not encoded:
                return ArtworkResult(error="macos-media:artwork:unavailable")
            if not isinstance(encoded, str) or len(encoded) > 4 * ((MAX_ARTWORK_BYTES + 2) // 3):
                return ArtworkResult(error="macos-media:artwork:too_large")
            image = base64.b64decode(encoded, validate=True)
            if len(image) > MAX_ARTWORK_BYTES:
                return ArtworkResult(error="macos-media:artwork:too_large")
            directory = runtime_dir or self.runtime_dir
            path = directory / "cover_media.raw"
            path.write_bytes(image)
            file, error = convert_artwork_file(path, directory, "cover_media")
            return ArtworkResult(file=file, source="mediaremote" if file else "", error=error)
        except subprocess.TimeoutExpired:
            return ArtworkResult(error="macos-media:artwork:timeout")
        except (OSError, ValueError, binascii.Error) as exc:
            return ArtworkResult(error=f"macos-media:artwork:{exc}")

    def _stop_process(self) -> None:
        process = self._process
        if process is not None and process.poll() is None:
            try:
                process.terminate()
                process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=1)
            except ProcessLookupError:
                pass

    def close(self) -> None:
        self._closed = True
        self._ready.set()
        self._stop_process()
        if self._thread is not None:
            self._thread.join(timeout=2)
