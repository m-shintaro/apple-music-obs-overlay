import asyncio
from pathlib import Path
from unittest import TestCase, mock

from apple_music_obs_overlay.providers import windows_media
from apple_music_obs_overlay.providers.windows_media import WindowsMediaProvider


class FakePlaybackInfo:
    def __init__(self, status):
        self.playback_status = status


class FakeSession:
    def __init__(self, app_id, status):
        self.source_app_user_model_id = app_id
        self.status = status

    def get_playback_info(self):
        return FakePlaybackInfo(self.status)


class FakeManager:
    def __init__(self, current, sessions):
        self.current = current
        self.sessions = sessions

    def get_current_session(self):
        return self.current

    def get_sessions(self):
        return self.sessions


class FakeMedia:
    title = "Song"
    artist = "Artist"
    album_title = "Album"


class FakeTimeline:
    position = 25
    start_time = 10
    end_time = 70


class FakeTimelineSession(FakeSession):
    async def try_get_media_properties_async(self):
        return FakeMedia()

    def get_timeline_properties(self):
        return FakeTimeline()


class WindowsMediaProviderTests(TestCase):
    def setUp(self):
        self.provider = WindowsMediaProvider(Path("runtime"))
        self.status_api = {
            "PLAYING": "playing",
            "PAUSED": "paused",
        }

    def test_select_session_prefers_apple_music_session(self):
        current = FakeSession("Chrome", "playing")
        apple_music = FakeSession("AppleInc.AppleMusicWin_nzyj5cx40ttqa!App", "paused")
        manager = FakeManager(current, [current, apple_music])

        with mock.patch.object(
            windows_media,
            "_load_playback_status",
            return_value=self.status_api,
        ):
            selected = self.provider._select_session(manager)

        self.assertIs(selected, apple_music)

    def test_select_session_uses_current_when_no_apple_music_session_exists(self):
        current = FakeSession("Spotify", "playing")
        paused_browser = FakeSession("Chrome", "paused")
        manager = FakeManager(current, [current, paused_browser])

        with mock.patch.object(
            windows_media,
            "_load_playback_status",
            return_value=self.status_api,
        ):
            selected = self.provider._select_session(manager)

        self.assertIs(selected, current)

    def test_read_buffer_bytes_supports_mutating_and_returning_readers(self):
        class MutatingReader:
            def read_bytes(self, target):
                target[:] = b"abc"

        class ReturningReader:
            def read_bytes(self, length):
                return b"xyz"[:length]

        self.assertEqual(windows_media._read_buffer_bytes(MutatingReader(), 3), b"abc")
        self.assertEqual(windows_media._read_buffer_bytes(ReturningReader(), 2), b"xy")

    def test_read_nowplaying_offsets_position_by_timeline_start(self):
        session = FakeTimelineSession("AppleInc.AppleMusicWin", "playing")
        manager = FakeManager(session, [session])

        async def request_manager():
            return manager

        with mock.patch.object(
            self.provider,
            "_request_manager",
            side_effect=request_manager,
        ):
            with mock.patch.object(
                windows_media,
                "_load_playback_status",
                return_value=self.status_api,
            ):
                data = asyncio.run(self.provider._read_nowplaying())

        self.assertEqual(data["position"], 15)
        self.assertEqual(data["duration"], 60)


class AppleMusicSessionTests(TestCase):
    def test_apple_music_session_detection(self):
        self.assertTrue(windows_media._is_apple_music_session("Apple Music"))
        self.assertTrue(windows_media._is_apple_music_session("AppleInc.AppleMusicWin"))
        self.assertTrue(windows_media._is_apple_music_session("com.apple.iTunes"))
        self.assertFalse(windows_media._is_apple_music_session("Spotify"))
