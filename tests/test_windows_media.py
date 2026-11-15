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


class ThumbnailIdentityTests(TestCase):
    def exercise(self, titles, expected=None, on_read=None):
        from tempfile import TemporaryDirectory
        from types import SimpleNamespace
        from io import BytesIO
        from PIL import Image
        image = BytesIO()
        Image.new('RGB', (32, 32), 'blue').save(image, 'PNG')
        content = image.getvalue()
        closed = []
        opened = []
        remaining = iter(titles)

        class Buffer:
            def __init__(self, size):
                self.length = size

        class Reader:
            @classmethod
            def from_buffer(cls, buffer):
                return cls()

            def read_bytes(self, buffer):
                buffer[:] = content

            def close(self):
                closed.append('reader')

        class Stream:
            size = len(content)

            async def read_async(self, buffer, size, options):
                if on_read:
                    on_read()
                return buffer

            def close(self):
                closed.append('stream')

        class Thumbnail:
            async def open_read_async(self):
                opened.append(True)
                return Stream()

        class Session(FakeSession):
            async def try_get_media_properties_async(self):
                return SimpleNamespace(title=next(remaining), artist='', album_artist='Artist',
                                       album_title='Album', thumbnail=Thumbnail())

        session = Session('AppleMusic', 'playing')
        manager = FakeManager(session, [session])
        async def request():
            return manager

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            provider = WindowsMediaProvider(root)
            with mock.patch.object(windows_media.platform, 'system', return_value='Windows'), \
                    mock.patch.object(provider, '_request_manager', side_effect=request), \
                    mock.patch.object(windows_media, '_load_playback_status', return_value={'PLAYING': 'playing', 'PAUSED': 'paused'}), \
                    mock.patch.object(windows_media, '_load_streams_api', return_value={
                        'Buffer': Buffer, 'DataReader': Reader, 'InputStreamOptions': SimpleNamespace(READ_AHEAD=1)}):
                result = provider.get_artwork(expected or {'title': 'A', 'artist': 'Artist', 'album': 'Album', 'sourceAppId': 'AppleMusic'})
            files = list(root.iterdir())
        return result, files, opened, closed

    def test_different_track_snapshot_is_rejected_before_opening_thumbnail(self):
        result, files, opened, closed = self.exercise(['B'])
        self.assertFalse(result.file, 'must not publish track B artwork for track A')
        self.assertTrue(result.track_changed)
        self.assertEqual(result.error, 'windows:thumbnail:track_changed')
        self.assertEqual((files, opened, closed), ([], [], []))

    def test_switch_during_read_rejects_image_and_closes_native_handles(self):
        result, files, opened, closed = self.exercise(['A', 'B'])
        self.assertFalse(result.file, 'must discard a cover if the track changed during its read')
        self.assertTrue(result.track_changed)
        self.assertEqual(files, [])
        self.assertEqual(opened, [True])
        self.assertEqual(closed, ['reader', 'stream'])

    def test_matching_snapshot_uses_album_artist_and_publishes_cover(self):
        result, files, opened, closed = self.exercise(['A', 'A'])
        self.assertFalse(result.track_changed)
        self.assertTrue(result.file)
        self.assertEqual(result.source, 'smtc')
        self.assertEqual(len(files), 1)
        self.assertEqual(closed, ['reader', 'stream'])

    def test_matching_names_from_a_different_app_are_rejected(self):
        result, files, opened, closed = self.exercise(['A'], {
            'title': 'A', 'artist': 'Artist', 'album': 'Album', 'sourceAppId': 'OtherApp'})
        self.assertTrue(result.track_changed)
        self.assertEqual(files, [])
        self.assertEqual(opened, [])


class StaleThumbnailTests(TestCase):
    PNG = b'\x89PNG\r\n\x1a\n'

    def setUp(self):
        from tempfile import TemporaryDirectory
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.provider = WindowsMediaProvider(self.root)
        self.image = self.PNG + b'first'
        self.now = 100.0

        async def read(expected):
            return self.image, 'smtc', ''

        for patcher in (
            mock.patch.object(windows_media.platform, 'system', return_value='Windows'),
            mock.patch.object(self.provider, '_read_thumbnail_bytes', side_effect=read),
            mock.patch.object(windows_media, 'monotonic', side_effect=lambda: self.now),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def artwork(self, title, album):
        return self.provider.get_artwork(
            {'title': title, 'artist': 'Artist', 'album': album, 'sourceAppId': 'AppleMusic'})

    def test_previous_cover_under_a_new_album_is_retried_until_it_changes(self):
        self.assertTrue(self.artwork('A', 'First').file)
        stale = self.artwork('B', 'Second')
        self.assertEqual((stale.file, stale.error), ('', 'windows:thumbnail:stale'))
        self.assertTrue(stale.track_changed, 'must retry promptly without the network fallback')
        self.image = self.PNG + b'second'
        self.assertTrue(self.artwork('B', 'Second').file)

    def test_identical_cover_is_accepted_after_the_grace_period(self):
        self.assertTrue(self.artwork('A', 'First').file)
        self.assertTrue(self.artwork('B', 'Second').track_changed)
        self.now += windows_media.STALE_THUMBNAIL_GRACE
        accepted = self.artwork('B', 'Second')
        self.assertFalse(accepted.track_changed)
        self.assertTrue(accepted.file)

    def test_tracks_of_one_album_share_a_cover_immediately(self):
        self.assertTrue(self.artwork('A', 'First').file)
        self.assertTrue(self.artwork('B', 'First').file)
