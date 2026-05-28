import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase, mock

from apple_music_obs_overlay import poller
from apple_music_obs_overlay.payload import build_payload
from apple_music_obs_overlay.providers.base import ArtworkResult


class FakeStopEvent:
    def __init__(self, stop_after_waits):
        self.stop_after_waits = stop_after_waits
        self.wait_count = 0
        self.stopped = False

    def is_set(self):
        return self.stopped

    def wait(self, interval):
        self.wait_count += 1
        if self.wait_count >= self.stop_after_waits:
            self.stopped = True


class DelayedArtworkProvider:
    name = "delayed"

    def __init__(self):
        self.artwork_calls = 0

    def get_nowplaying(self):
        return build_payload("playing", "Song", "Artist", "Album", 1, 120)

    def get_artwork(self, data):
        self.artwork_calls += 1
        if self.artwork_calls == 1:
            return ArtworkResult(error="thumbnail:not_ready")
        return ArtworkResult(file="cover_windows.jpg", source="smtc")


class PollerTests(TestCase):
    def test_retries_provider_artwork_for_same_track_when_initial_attempt_fails(self):
        provider = DelayedArtworkProvider()

        with TemporaryDirectory() as tmp:
            runtime_dir = Path(tmp)
            event = FakeStopEvent(stop_after_waits=2)

            with mock.patch.object(poller, "ARTWORK_RETRY_INTERVAL", 0.0):
                poller.poll_loop(
                    event,
                    provider,
                    runtime_dir,
                    interval=0,
                    country="JP",
                    allow_network_artwork=False,
                )

            data = json.loads((runtime_dir / "nowplaying.json").read_text())

        self.assertEqual(provider.artwork_calls, 2)
        self.assertEqual(data["artworkFile"], "cover_windows.jpg")
        self.assertEqual(data["artworkSource"], "smtc")

    def test_retries_provider_artwork_after_network_fallback_is_shown(self):
        provider = DelayedArtworkProvider()

        with TemporaryDirectory() as tmp:
            runtime_dir = Path(tmp)
            event = FakeStopEvent(stop_after_waits=2)

            with mock.patch.object(poller, "ARTWORK_RETRY_INTERVAL", 0.0):
                with mock.patch.object(
                    poller,
                    "fetch_artwork_from_itunes_search",
                    return_value=("cover_fallback.jpg", ""),
                ) as fetch_artwork:
                    poller.poll_loop(
                        event,
                        provider,
                        runtime_dir,
                        interval=0,
                        country="JP",
                        allow_network_artwork=True,
                    )

            data = json.loads((runtime_dir / "nowplaying.json").read_text())

        self.assertEqual(provider.artwork_calls, 2)
        fetch_artwork.assert_called_once()
        self.assertEqual(data["artworkFile"], "cover_windows.jpg")
        self.assertEqual(data["artworkSource"], "smtc")
