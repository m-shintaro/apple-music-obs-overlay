import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase, mock

from apple_music_obs_overlay import output
from apple_music_obs_overlay.output import write_outputs


class OutputTests(TestCase):
    def test_locked_text_never_sleeps_or_delays_json_and_recovers_latest_value(self):
        original_replace = Path.replace
        attempts = []
        with TemporaryDirectory() as tmp:
            root = Path(tmp)

            def locked_text(path, target):
                if target.name == 'nowplaying.txt':
                    # JSON must already contain this poll, not the previous one.
                    self.assertTrue((root / 'nowplaying.json').exists(), 'JSON must be written first')
                    attempts.append(json.loads((root / 'nowplaying.json').read_text())['title'])
                    raise PermissionError('Windows reader lock')
                return original_replace(path, target)

            with mock.patch.object(Path, 'replace', locked_text), mock.patch.object(output.time, 'sleep') as sleep:
                for i in range(5):
                    with self.assertRaises(PermissionError):
                        write_outputs({'state': 'playing', 'title': str(i)}, root)
                sleep.assert_not_called()
            self.assertEqual(attempts, ['0', '1', '2', '3', '4'])
            write_outputs({'state': 'playing', 'title': 'Latest'}, root)
            self.assertIn('Latest', (root / 'nowplaying.txt').read_text())
            self.assertEqual(list(root.glob('*.tmp')), [])

    def test_locked_json_still_updates_text_and_keeps_json_retries(self):
        original_replace = Path.replace
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            def locked_json(path, target):
                if target.name == 'nowplaying.json':
                    raise PermissionError('JSON locked')
                return original_replace(path, target)
            with mock.patch.object(Path, 'replace', locked_json), mock.patch.object(output.time, 'sleep') as sleep:
                with self.assertRaises(PermissionError):
                    write_outputs({'state': 'playing', 'title': 'Latest'}, root)
            self.assertEqual(sleep.call_count, output.REPLACE_RETRIES - 1)
            self.assertIn('Latest', (root / 'nowplaying.txt').read_text())

    def test_write_outputs_tolerates_missing_optional_fields(self):
        with TemporaryDirectory() as tmp:
            runtime_dir = Path(tmp)

            write_outputs({"state": "playing", "title": "Song"}, runtime_dir)

            self.assertIn("Song", (runtime_dir / "nowplaying.txt").read_text())
            self.assertIn('"title": "Song"', (runtime_dir / "nowplaying.json").read_text())

    def test_write_outputs_still_updates_json_when_text_output_is_locked(self):
        original_write = output.atomic_write_text

        def write_or_lock(path, text, **kwargs):
            if path.name == "nowplaying.txt":
                raise PermissionError("locked")
            original_write(path, text, **kwargs)

        with TemporaryDirectory() as tmp:
            runtime_dir = Path(tmp)

            with mock.patch.object(output, "atomic_write_text", side_effect=write_or_lock):
                with self.assertRaises(PermissionError):
                    write_outputs({"state": "playing", "title": "Song"}, runtime_dir)

            self.assertFalse((runtime_dir / "nowplaying.txt").exists())
            self.assertIn('"title": "Song"', (runtime_dir / "nowplaying.json").read_text())
