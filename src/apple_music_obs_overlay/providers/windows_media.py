from __future__ import annotations

import asyncio
from datetime import timedelta
from pathlib import Path
import platform
from typing import Any, Dict, Iterable, Tuple

from ..artwork.image import write_runtime_image
from ..payload import build_payload, default_payload
from .base import ArtworkResult, BaseProvider


WINDOWS_EXTRA_HELP = 'install the Windows extra with: py -3 -m pip install ".[windows]"'
MAX_THUMBNAIL_BYTES = 20 * 1024 * 1024


class WindowsMediaUnavailable(RuntimeError):
    """Raised when the Windows media API cannot be loaded."""


class WindowsMediaProvider(BaseProvider):
    name = "windows"

    def __init__(self, runtime_dir: Path, timeout: float = 5.0) -> None:
        self.runtime_dir = runtime_dir
        self.timeout = timeout

    def get_nowplaying(self) -> Dict[str, Any]:
        if platform.system() != "Windows":
            return default_payload("error", "windows:unsupported_platform")

        try:
            return asyncio.run(asyncio.wait_for(self._read_nowplaying(), timeout=self.timeout))
        except WindowsMediaUnavailable as exc:
            return default_payload("error", f"windows:{exc}")
        except asyncio.TimeoutError:
            return default_payload("error", "windows:smtc_timeout")
        except Exception as exc:
            return default_payload("error", f"windows:{_error_detail(exc)}")

    def get_artwork(self, data: Dict[str, Any]) -> ArtworkResult:
        if platform.system() != "Windows":
            return ArtworkResult(error="windows:unsupported_platform")

        try:
            image, source, error = asyncio.run(
                asyncio.wait_for(self._read_thumbnail_bytes(), timeout=self.timeout)
            )
        except WindowsMediaUnavailable as exc:
            return ArtworkResult(error=f"windows:{exc}")
        except asyncio.TimeoutError:
            return ArtworkResult(error="windows:thumbnail_timeout")
        except Exception as exc:
            return ArtworkResult(error=f"windows:thumbnail:{_error_detail(exc)}")

        if error:
            return ArtworkResult(error=error)

        artwork_file, write_error = write_runtime_image(image, self.runtime_dir, "cover_windows")
        if artwork_file:
            return ArtworkResult(file=artwork_file, source=source, error="")
        return ArtworkResult(error=f"windows:thumbnail:{write_error}")

    async def _read_nowplaying(self) -> Dict[str, Any]:
        manager = await self._request_manager()
        session = self._select_session(manager)
        if session is None:
            return default_payload("stopped")

        status = self._read_playback_state(session)
        if status == "stopped":
            return default_payload("stopped")

        errors = []
        try:
            media = await session.try_get_media_properties_async()
        except Exception as exc:
            return default_payload("error", f"windows:media_properties:{_error_detail(exc)}")

        title = _text_attr(media, "title")
        artist = _text_attr(media, "artist") or _text_attr(media, "album_artist")
        album = _text_attr(media, "album_title")

        if not title:
            errors.append("title_unavailable")
        if not artist:
            errors.append("artist_unavailable")
        if not album:
            errors.append("album_unavailable")

        position = 0.0
        duration = 0.0
        try:
            timeline = session.get_timeline_properties()
            position = _timespan_to_seconds(getattr(timeline, "position", 0))
            start = _timespan_to_seconds(getattr(timeline, "start_time", 0))
            end = _timespan_to_seconds(getattr(timeline, "end_time", 0))
            if end > start:
                position = max(0.0, position - start)
                duration = max(0.0, end - start)
            else:
                position = max(0.0, position)
                duration = max(0.0, end)
        except Exception as exc:
            errors.append(f"timeline_unavailable:{_error_detail(exc)}")

        return build_payload(
            status,
            title,
            artist,
            album,
            position,
            duration,
            error="windows:" + "|".join(errors) if errors else "",
        )

    async def _read_thumbnail_bytes(self) -> Tuple[bytes, str, str]:
        manager = await self._request_manager()
        session = self._select_session(manager)
        if session is None:
            return b"", "", "windows:thumbnail:no_media_session"

        try:
            media = await session.try_get_media_properties_async()
        except Exception as exc:
            return b"", "", f"windows:thumbnail:media_properties:{_error_detail(exc)}"

        thumbnail = getattr(media, "thumbnail", None)
        if thumbnail is None:
            return b"", "", "windows:thumbnail:unavailable"

        api = _load_streams_api()
        reader = None
        stream = None
        try:
            stream = await thumbnail.open_read_async()
            size = int(getattr(stream, "size", 0))
            if size <= 0:
                return b"", "", "windows:thumbnail:empty"
            if size > MAX_THUMBNAIL_BYTES:
                return b"", "", f"windows:thumbnail:too_large:{size}"

            buffer = api["Buffer"](size)
            read_buffer = await stream.read_async(
                buffer,
                size,
                api["InputStreamOptions"].READ_AHEAD,
            )
            if read_buffer is not None:
                buffer = read_buffer
            length = int(getattr(buffer, "length", 0))
            if length <= 0:
                return b"", "", "windows:thumbnail:empty"

            reader = api["DataReader"].from_buffer(buffer)
            return _read_buffer_bytes(reader, length), "smtc", ""
        except Exception as exc:
            return b"", "", f"windows:thumbnail:{_error_detail(exc)}"
        finally:
            _close_quietly(reader)
            _close_quietly(stream)

    async def _request_manager(self):
        media_manager = _load_media_manager()
        return await media_manager.request_async()

    def _select_session(self, manager):
        current = manager.get_current_session()
        candidates = []
        seen = set()

        def add(session, is_current: bool) -> None:
            if session is None:
                return
            marker = id(session)
            if marker in seen:
                return
            seen.add(marker)
            candidates.append((session, is_current))

        add(current, True)
        for session in _session_list(manager):
            add(session, session is current)

        if not candidates:
            return None

        return max(
            candidates,
            key=lambda item: self._session_score(item[0], item[1]),
        )[0]

    def _session_score(self, session, is_current: bool = False) -> int:
        score = 0
        app_id = str(getattr(session, "source_app_user_model_id", "") or "").lower()
        if _is_apple_music_session(app_id):
            score += 100
        if is_current:
            score += 30
        state = self._read_playback_state(session)
        if state == "playing":
            score += 20
        elif state == "paused":
            score += 10
        return score

    def _read_playback_state(self, session) -> str:
        try:
            playback_info = session.get_playback_info()
            status = playback_info.playback_status
        except Exception:
            return "stopped"

        api = _load_playback_status()
        if status == api["PLAYING"]:
            return "playing"
        if status == api["PAUSED"]:
            return "paused"
        return "stopped"


def _load_media_manager():
    try:
        from winsdk.windows.media.control import (
            GlobalSystemMediaTransportControlsSessionManager,
        )
    except ImportError as exc:
        raise WindowsMediaUnavailable(f"winsdk_missing:{WINDOWS_EXTRA_HELP}") from exc
    return GlobalSystemMediaTransportControlsSessionManager


def _load_playback_status() -> Dict[str, Any]:
    try:
        from winsdk.windows.media.control import (
            GlobalSystemMediaTransportControlsSessionPlaybackStatus,
        )
    except ImportError as exc:
        raise WindowsMediaUnavailable(f"winsdk_missing:{WINDOWS_EXTRA_HELP}") from exc
    return {
        "PLAYING": GlobalSystemMediaTransportControlsSessionPlaybackStatus.PLAYING,
        "PAUSED": GlobalSystemMediaTransportControlsSessionPlaybackStatus.PAUSED,
    }


def _load_streams_api() -> Dict[str, Any]:
    try:
        from winsdk.windows.storage.streams import Buffer, DataReader, InputStreamOptions
    except ImportError as exc:
        raise WindowsMediaUnavailable(f"winsdk_missing:{WINDOWS_EXTRA_HELP}") from exc
    return {
        "Buffer": Buffer,
        "DataReader": DataReader,
        "InputStreamOptions": InputStreamOptions,
    }


def _session_list(manager) -> Iterable[Any]:
    try:
        return list(manager.get_sessions())
    except Exception:
        return []


def _is_apple_music_session(app_id: str) -> bool:
    normalized = app_id.lower().replace(" ", "")
    return "applemusic" in normalized or "itunes" in normalized


def _text_attr(obj: object, name: str) -> str:
    value = getattr(obj, name, "")
    if callable(value):
        value = value()
    return "" if value is None else str(value)


def _timespan_to_seconds(value: object) -> float:
    if value is None:
        return 0.0
    if isinstance(value, timedelta):
        return value.total_seconds()
    if hasattr(value, "total_seconds"):
        try:
            return float(value.total_seconds())
        except Exception:
            return 0.0
    try:
        raw = float(value)
    except (TypeError, ValueError):
        return 0.0
    if abs(raw) > 100000:
        return raw / 10000000.0
    return raw


def _read_buffer_bytes(reader: object, length: int) -> bytes:
    target = bytearray(length)
    try:
        reader.read_bytes(target)
        return bytes(target)
    except TypeError:
        data = reader.read_bytes(length)
        return bytes(data)


def _error_detail(exc: Exception) -> str:
    return (str(exc).strip() or exc.__class__.__name__).replace("\n", " ")


def _close_quietly(obj: object) -> None:
    if obj is None:
        return
    for method_name in ("close", "dispose"):
        method = getattr(obj, method_name, None)
        if callable(method):
            try:
                method()
            except Exception:
                pass
            return
