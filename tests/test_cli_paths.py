from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from unittest import TestCase, mock

from apple_music_obs_overlay import cli


class CliPathTests(TestCase):
    def test_frozen_app_serves_bundled_overlay_and_writes_next_to_exe(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            bundle_dir = root / "_internal"
            exe_dir = root / "dist"
            bundle_dir.mkdir()
            exe_dir.mkdir()
            (bundle_dir / "overlay.html").write_text("", encoding="utf-8")
            exe = exe_dir / "OBSAppleMusicProgressBar.exe"

            with mock.patch.object(sys, "frozen", True, create=True):
                with mock.patch.object(sys, "_MEIPASS", str(bundle_dir), create=True):
                    with mock.patch.object(sys, "executable", str(exe)):
                        app_dir = cli.find_app_dir()
                        runtime_dir = cli.find_runtime_dir(app_dir)

            self.assertEqual(app_dir, bundle_dir)
            self.assertEqual(runtime_dir, exe_dir / "runtime")

