import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase, mock

from apple_music_obs_overlay.providers import macos_music


class MacOSMusicTests(TestCase):
    def test_exports_with_expected_metadata_and_reports_track_changed(self):
        expected = {'title': 'A 日本語 "quoted"', 'artist': 'Artist', 'album': 'Album', 'trackId': 'ABC123'}
        with TemporaryDirectory() as tmp:
            provider = macos_music.MacOSMusicProvider(Path(tmp))
            with mock.patch.object(macos_music.subprocess, 'run', return_value=SimpleNamespace(
                    returncode=0, stdout='missing:track_changed', stderr='')) as run:
                result = provider.get_artwork(expected)
            self.assertEqual(json.loads(run.call_args.args[0][-1]), expected)
            self.assertTrue(result.track_changed)
            self.assertFalse(result.file)
            self.assertEqual(list(Path(tmp).iterdir()), [])

    def test_nowplaying_retains_persistent_id(self):
        with mock.patch.object(macos_music.subprocess, 'run', return_value=SimpleNamespace(
                returncode=0, stdout=json.dumps({'state': 'playing', 'title': 'A', 'trackId': 'ABC123'}), stderr='')):
            data = macos_music.MacOSMusicProvider(Path('.')).get_nowplaying()
        self.assertEqual(data['trackId'], 'ABC123')
