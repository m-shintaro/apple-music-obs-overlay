import base64
import json
import os
from io import BytesIO
from pathlib import Path
import subprocess
import signal
import sys
from tempfile import TemporaryDirectory
import time
from types import SimpleNamespace
from unittest import TestCase, mock, skipUnless

from PIL import Image

from apple_music_obs_overlay import cli
from apple_music_obs_overlay.artwork.worker import ArtworkWorker
from apple_music_obs_overlay.providers import macos_media
from apple_music_obs_overlay.providers.macos_media import MacOSMediaProvider, media_payload


def snapshot(**changes):
    return dict(dict(title="Video 日本語", artist="Channel", album="", playing=True,
                     bundleIdentifier="com.google.Chrome", contentItemIdentifier="video-1",
                     durationMicros=180_000_000, elapsedTimeMicros=10_000_000,
                     timestampEpochMicros=100_000_000, playbackRate=1), **changes)


class MediaPayloadTests(TestCase):
    def test_elapsed_position_accounts_for_timestamp_and_playback_speed(self):
        data = media_payload(snapshot(playbackRate=2), 103)
        self.assertEqual(data["position"], 16)
        self.assertEqual(data["duration"], 180)
        self.assertEqual(data["sourceAppId"], "com.google.Chrome")
        self.assertEqual(data["trackId"], "video-1")
        self.assertEqual(data["playbackRate"], 2)

    def test_pause_freezes_position_and_seek_replaces_previous_position(self):
        self.assertEqual(media_payload(snapshot(playing=False), 1000)["position"], 10)
        self.assertEqual(media_payload(snapshot(elapsedTimeMicros=2_000_000), 100)["position"], 2)

    def test_live_unknown_duration_and_missing_timestamp(self):
        data = media_payload(snapshot(durationMicros=None, timestampEpochMicros=None), 99999)
        self.assertEqual((data["position"], data["duration"], data["progress"]), (10, 0, 0))

    def test_invalid_numbers_future_timestamp_and_end_are_bounded(self):
        data = media_payload(snapshot(durationMicros="NaN", elapsedTimeMicros="Infinity",
                                      playbackRate="bad"), 100)
        self.assertEqual(data["position"], 0)
        self.assertEqual(data["duration"], 0)
        self.assertEqual(media_payload(snapshot(), 99)["position"], 10)
        self.assertEqual(media_payload(snapshot(), 999)["position"], 180)

    def test_empty_or_incomplete_native_state_clears_playback(self):
        for raw in ({}, snapshot(title=None), snapshot(bundleIdentifier=None)):
            self.assertEqual(media_payload(raw, 100)["state"], "stopped")


class MacOSMediaTests(TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.provider = MacOSMediaProvider(self.root, executable="media-control", timeout=1)
        self.addCleanup(self.provider.close)
        patch = mock.patch.object(macos_media.platform, "system", return_value="Darwin")
        patch.start()
        self.addCleanup(patch.stop)

    def query(self, raw, **options):
        return mock.patch.object(macos_media.subprocess, "run", return_value=SimpleNamespace(
            stdout=json.dumps(raw).encode(), stderr=b"", returncode=options.get("returncode", 0)))

    def test_once_reads_actual_snapshot_without_starting_a_stream(self):
        with self.query(snapshot(playing=False)) as run:
            data = self.provider.get_nowplaying_once()
        self.assertEqual(data["title"], "Video 日本語")
        self.assertIn("--no-artwork", run.call_args.args[0])
        self.assertIsNone(self.provider._process)

    def test_empty_once_is_stopped_and_query_errors_are_reported(self):
        with self.query(None):
            self.assertEqual(self.provider.get_nowplaying_once()["state"], "stopped")
        for raw in ([1], "invalid"):
            with self.query(raw):
                self.assertEqual(self.provider.get_nowplaying_once()["state"], "error")
        with self.query({}, returncode=1):
            self.assertIn("exit_1", self.provider.get_nowplaying_once()["error"])
        with mock.patch.object(macos_media.subprocess, "run", side_effect=subprocess.TimeoutExpired("get", 1)):
            self.assertIn("timeout", self.provider.get_nowplaying_once()["error"])

    def test_missing_tool_has_actionable_error_without_repeated_spawns(self):
        self.provider.executable = None
        with mock.patch.object(macos_media.subprocess, "Popen") as popen:
            for _ in range(3):
                self.assertIn("brew install media-control", self.provider.get_nowplaying()["error"])
            popen.assert_not_called()

    def test_unsupported_platform_is_reported(self):
        with mock.patch.object(macos_media.platform, "system", return_value="Windows"):
            self.assertIn("unsupported_platform", self.provider.get_nowplaying()["error"])

    def start_helper(self, script):
        original_popen = subprocess.Popen
        def spawn(command, **kwargs):
            self.assertEqual(command[1:], ["stream", "--micros", "--no-diff", "--no-artwork"])
            return original_popen([sys.executable, "-u", "-c", script], **kwargs)
        patch = mock.patch.object(macos_media.subprocess, "Popen", side_effect=spawn)
        popen = patch.start()
        self.addCleanup(patch.stop)
        return popen

    def test_stream_reuses_process_and_close_reaps_it(self):
        event = json.dumps(dict(type="data", diff=False, payload=snapshot(playing=False)))
        popen = self.start_helper(f"import time; print({event!r}, flush=True); time.sleep(30)")
        for _ in range(10):
            self.assertEqual(self.provider.get_nowplaying()["position"], 10)
        popen.assert_called_once()
        process = self.provider._process
        self.provider.close()
        self.provider.close()
        self.assertIsNotNone(process.poll())
        self.assertFalse(self.provider._thread.is_alive())

    def test_stream_replaces_snapshots_and_clears_when_playback_disappears(self):
        first = json.dumps(dict(type="data", diff=False, payload=snapshot(playing=False)))
        empty = json.dumps(dict(type="data", diff=False, payload={}))
        marker = self.root / "clear"
        script = (f"from pathlib import Path\nimport time\nprint({first!r}, flush=True)\n"
                  f"while not Path({str(marker)!r}).exists(): time.sleep(.01)\n"
                  f"print({empty!r}, flush=True)\ntime.sleep(30)")
        self.start_helper(script)
        self.assertEqual(self.provider.get_nowplaying()["title"], "Video 日本語")
        marker.touch()
        deadline = time.monotonic() + 2
        while self.provider.get_nowplaying()["state"] != "stopped" and time.monotonic() < deadline:
            time.sleep(.01)
        self.assertEqual(self.provider.get_nowplaying()["title"], "")

    def test_stream_failure_does_not_leave_stale_data_or_spawn_loop(self):
        popen = self.start_helper("print('invalid JSON', flush=True)")
        self.assertEqual(self.provider.get_nowplaying()["state"], "error")
        self.assertEqual(self.provider.get_nowplaying()["state"], "error")
        popen.assert_called_once()

    def test_startup_timeout_terminates_silent_helper(self):
        self.provider.timeout = .1
        self.start_helper("import time; time.sleep(30)")
        self.assertIn("startup_timeout", self.provider.get_nowplaying()["error"])
        self.assertIsNotNone(self.provider._process.poll())

    def event(self, payload=None, **fields):
        return json.dumps(dict(dict(type="data", diff=False,
                                    payload=snapshot(playing=False) if payload is None else payload),
                               **fields))

    def wait_for(self, predicate):
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            data = self.provider.get_nowplaying()
            if predicate(data):
                return data
            time.sleep(.01)
        self.fail(f"condition not reached: {data}")

    def test_ended_stream_reports_error_then_restarts_and_recovers(self):
        marker = self.root / "exit"
        script = (f"from pathlib import Path\nimport time\nprint({self.event()!r}, flush=True)\n"
                  f"while not Path({str(marker)!r}).exists(): time.sleep(.01)")
        popen = self.start_helper(script)
        with mock.patch.object(macos_media, "RESTART_MIN_DELAY", .05):
            self.assertEqual(self.provider.get_nowplaying()["title"], "Video 日本語")
            marker.touch()
            failed = self.wait_for(lambda d: d["state"] == "error")
            self.assertIn("stream_ended", failed["error"])
            self.assertEqual(failed["title"], "", "a dead stream must not keep stale playback")
            marker.unlink()
            self.wait_for(lambda d: d["title"] == "Video 日本語")
        self.assertEqual(popen.call_count, 2)

    def test_startup_timeout_is_retried_and_keeps_its_cause(self):
        self.provider.timeout = .1
        popen = self.start_helper("import time; time.sleep(30)")
        with mock.patch.object(macos_media, "RESTART_MIN_DELAY", .3):
            for _ in range(3):
                self.assertIn("startup_timeout", self.provider.get_nowplaying()["error"])
            popen.assert_called_once()
            time.sleep(.3)
            self.assertIn("startup_timeout", self.provider.get_nowplaying()["error"])
        self.assertEqual(popen.call_count, 2)

    def test_restart_delay_doubles_up_to_a_cap_and_resets_after_a_stable_run(self):
        delays = []
        with mock.patch.object(macos_media.time, "monotonic", return_value=1000.0):
            self.provider._started_at = 1000.0
            for _ in range(7):
                self.provider._record_failure("stream_ended")
                delays.append(self.provider._retry_at - 1000.0)
            self.provider._started_at = 1000.0 - macos_media.RESTART_STABLE_AFTER
            self.provider._record_failure("stream_ended")
            delays.append(self.provider._retry_at - 1000.0)
        self.assertEqual(delays, [1, 2, 4, 8, 16, 30, 30, 1])

    def test_restart_delay_stays_bounded_after_thousands_of_failures(self):
        with mock.patch.object(macos_media.time, "monotonic", return_value=1000.0):
            self.provider._started_at = 1000.0
            for _ in range(2000):
                self.provider._record_failure("stream_ended")
            self.assertEqual(self.provider._retry_at, 1030.0)
            self.assertEqual(self.provider._error, "macos-media:stream_ended")

    def test_unknown_event_kinds_are_skipped(self):
        unknown = json.dumps(dict(type="future-kind", detail=[1, 2]))
        self.start_helper(f"import time; print({unknown!r}, flush=True); "
                          f"print({self.event()!r}, flush=True); time.sleep(30)")
        self.assertEqual(self.provider.get_nowplaying()["title"], "Video 日本語")

    def test_null_payload_means_nothing_is_playing(self):
        null = json.dumps(dict(type="data", diff=False, payload=None))
        self.start_helper(f"import time; print({null!r}, flush=True); time.sleep(30)")
        data = self.provider.get_nowplaying()
        self.assertEqual((data["state"], data["error"]), ("stopped", ""))

    def test_every_stream_event_advances_the_artwork_revision(self):
        # Keep only the periodic component fixed while real process time advances.
        with mock.patch.object(macos_media, "ARTWORK_RECHECK_INTERVAL", float("inf")):
            self.assertEqual(self.provider.artwork_revision(), 0)
            self.start_helper(f"import time; print({self.event()!r}, flush=True); "
                              f"print({self.event()!r}, flush=True); time.sleep(30)")
            self.wait_for(lambda d: self.provider.artwork_revision() == 2)

    def test_artwork_is_rechecked_even_when_image_only_changes_emit_no_event(self):
        self.provider._revision = 4
        with mock.patch.object(macos_media.time, "monotonic", return_value=100.0):
            first = self.provider.artwork_revision()
        with mock.patch.object(macos_media.time, "monotonic", return_value=105.0):
            self.assertGreater(self.provider.artwork_revision(), first)

    def test_monotonic_anchor_ignores_wall_clock_changes(self):
        self.provider._snapshot = snapshot(playbackRate=2)
        self.provider._received_at = 50
        self.provider._received_epoch = 100
        self.provider._ready.set()
        with mock.patch.object(self.provider, "_start"), \
             mock.patch.object(macos_media.time, "monotonic", return_value=52), \
             mock.patch.object(macos_media.time, "time", return_value=999999):
            self.assertEqual(self.provider.get_nowplaying()["position"], 14)

    def test_artwork_is_decoded_into_worker_directory(self):
        out = BytesIO()
        Image.new("RGB", (4, 4), "red").save(out, "PNG")
        raw = snapshot(artworkData=base64.b64encode(out.getvalue()).decode())
        scratch = self.root / "worker"
        scratch.mkdir()
        with self.query(raw) as run:
            result = self.provider.get_artwork(media_payload(raw, 100), runtime_dir=scratch)
        self.assertNotIn("--no-artwork", run.call_args.args[0])
        self.assertEqual(result.source, "mediaremote")
        self.assertEqual((scratch / result.file).read_bytes(), out.getvalue())
        self.assertFalse((self.root / result.file).exists())

    def test_artwork_rejects_app_or_video_switch_even_with_identical_text(self):
        expected = media_payload(snapshot(), 100)
        for changes in (dict(bundleIdentifier="com.apple.Safari"), dict(contentItemIdentifier="video-2")):
            with self.query(snapshot(**changes)):
                result = self.provider.get_artwork(expected)
            self.assertTrue(result.track_changed)
            self.assertFalse(result.file)
        self.assertEqual(list(self.root.iterdir()), [])

    def test_missing_bad_or_oversize_artwork_is_not_published(self):
        expected = media_payload(snapshot(), 100)
        with mock.patch.object(macos_media, "MAX_ARTWORK_BYTES", 2):
            for image in (None, "not-base64!", "YWJj"):
                with self.query(snapshot(artworkData=image)):
                    result = self.provider.get_artwork(expected)
                self.assertFalse(result.file)
                self.assertTrue(result.error)
        self.assertEqual(list(self.root.iterdir()), [])

    def test_browser_artwork_never_uses_itunes_search(self):
        worker = ArtworkWorker(self.provider, "JP")
        with self.query(snapshot()), mock.patch(
                "apple_music_obs_overlay.artwork.worker.fetch_artwork_from_itunes_search") as search:
            worker._run(1, media_payload(snapshot(), 100), True)
            search.assert_not_called()
        self.assertFalse(worker.result.network_attempted)
        self.assertTrue(self.provider.allow_itunes_fallback({"sourceAppId": "com.apple.Music"}))


class MacOSProviderSelectionTests(TestCase):
    def test_auto_uses_system_media_if_available_and_music_otherwise(self):
        args = SimpleNamespace(demo=False, provider="auto")
        with mock.patch.object(cli.platform, "system", return_value="Darwin"):
            with mock.patch.object(cli, "find_media_control", return_value="/opt/homebrew/bin/media-control"):
                with mock.patch.object(cli, "media_control_works", return_value=True) as works:
                    self.assertEqual(cli.resolve_provider_name(args), "macos-media")
                works.assert_called_once_with("/opt/homebrew/bin/media-control")
                # Installed but not functional on this macOS: keep Apple Music working.
                with mock.patch.object(cli, "media_control_works", return_value=False), \
                        mock.patch("sys.stderr") as stderr:
                    self.assertEqual(cli.resolve_provider_name(args), "macos")
                self.assertIn("media-control test", "".join(
                    call.args[0] for call in stderr.write.call_args_list))
            with mock.patch.object(cli, "find_media_control", return_value=None), mock.patch("sys.stderr"):
                self.assertEqual(cli.resolve_provider_name(args), "macos")
        args.provider = "macos"
        self.assertEqual(cli.resolve_provider_name(args), "macos")

    def test_helper_self_test_decides_whether_it_is_usable(self):
        process = mock.Mock(pid=12345)
        process.wait.return_value = 0
        with mock.patch.object(macos_media.subprocess, "Popen", return_value=process) as call:
            self.assertTrue(macos_media.media_control_works("media-control"))
        self.assertEqual(call.call_args.args[0], ["media-control", "test"])
        self.assertTrue(call.call_args.kwargs["start_new_session"])
        process.wait.return_value = 1
        with mock.patch.object(macos_media.subprocess, "Popen", return_value=process):
            self.assertFalse(macos_media.media_control_works("media-control"))
        with mock.patch.object(macos_media.subprocess, "Popen", side_effect=OSError("gone")):
            self.assertFalse(macos_media.media_control_works("media-control"))
        process.wait.side_effect = [subprocess.TimeoutExpired("test", 5), -9]
        with mock.patch.object(macos_media.subprocess, "Popen", return_value=process), \
                mock.patch.object(macos_media.os, "killpg", create=True) as killpg:
            self.assertFalse(macos_media.media_control_works("media-control"))
        killpg.assert_called_once_with(12345, signal.SIGKILL)

    @skipUnless(os.name == "posix", "macOS helper uses POSIX process groups")
    def test_self_test_timeout_stops_its_child_player(self):
        original_popen = subprocess.Popen
        with TemporaryDirectory() as tmp:
            heartbeat = Path(tmp) / "heartbeat"
            script = ("import os, time\nfrom pathlib import Path\n"
                      "if os.fork() == 0:\n"
                      "    while True:\n"
                      f"        Path({str(heartbeat)!r}).write_text(str(time.monotonic()))\n"
                      "        time.sleep(.01)\n"
                      "else:\n    time.sleep(30)\n")
            def spawn(command, **kwargs):
                process = original_popen([sys.executable, "-u", "-c", script], **kwargs)
                def cleanup():
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    process.wait()
                self.addCleanup(cleanup)
                return process
            with mock.patch.object(macos_media.subprocess, "Popen", side_effect=spawn):
                self.assertFalse(macos_media.media_control_works("media-control", timeout=.4))
            last_heartbeat = heartbeat.read_text()
            time.sleep(.1)
            self.assertEqual(heartbeat.read_text(), last_heartbeat)

    def test_cli_closes_provider_even_when_running_fails(self):
        provider = mock.Mock()
        with mock.patch.object(cli, "parse_args"), mock.patch.object(cli, "resolve_provider_name"), \
             mock.patch.object(cli, "ensure_runtime_dir"), \
             mock.patch.object(cli, "create_provider", return_value=provider), \
             mock.patch.object(cli, "run_provider", side_effect=RuntimeError("bind failed")):
            with self.assertRaises(RuntimeError):
                cli.main()
        provider.close.assert_called_once()
