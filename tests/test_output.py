from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase, mock

from apple_music_obs_overlay import output
from apple_music_obs_overlay.output import write_outputs


class OutputTests(TestCase):
    def test_write_outputs_tolerates_missing_optional_fields(self):
        with TemporaryDirectory() as tmp:
            runtime_dir = Path(tmp)

            write_outputs({"state": "playing", "title": "Song"}, runtime_dir)

            self.assertIn("Song", (runtime_dir / "nowplaying.txt").read_text())
            self.assertIn('"title": "Song"', (runtime_dir / "nowplaying.json").read_text())

    def test_write_outputs_still_updates_json_when_text_output_is_locked(self):
        original_write = output.atomic_write_text

        def write_or_lock(path, text):
            if path.name == "nowplaying.txt":
                raise PermissionError("locked")
            original_write(path, text)

        with TemporaryDirectory() as tmp:
            runtime_dir = Path(tmp)

            with mock.patch.object(output, "atomic_write_text", side_effect=write_or_lock):
                with self.assertRaises(PermissionError):
                    write_outputs({"state": "playing", "title": "Song"}, runtime_dir)

            self.assertFalse((runtime_dir / "nowplaying.txt").exists())
            self.assertIn('"title": "Song"', (runtime_dir / "nowplaying.json").read_text())
