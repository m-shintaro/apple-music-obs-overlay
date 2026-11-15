import hashlib
import json
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
import threading
import time
from unittest import TestCase, mock

from PIL import Image
from apple_music_obs_overlay import poller
from apple_music_obs_overlay.artwork import worker
from apple_music_obs_overlay.artwork.image import normalize_artwork
from apple_music_obs_overlay.payload import build_payload, make_track_key
from apple_music_obs_overlay.providers.base import ArtworkResult


def image_bytes(color='red'):
    out = BytesIO()
    Image.new('RGB', (600, 600), color).save(out, 'PNG')
    return out.getvalue()


class Provider:
    name = 'test'

    def __init__(self, fail_first=False):
        self.title = 'Song'
        self.calls = 0
        self.fail_first = fail_first
        self.duration = 240

    def get_nowplaying(self):
        return build_payload('playing', self.title, 'Artist', 'Album', 1, self.duration)

    def get_artwork(self, data, runtime_dir=None):
        self.calls += 1
        if self.fail_first and self.calls == 1:
            return ArtworkResult(error='not_ready')
        (runtime_dir / 'cover.png').write_bytes(image_bytes())
        return ArtworkResult(file='cover.png', source='test')


class PollerTests(TestCase):
    def run_until(self, provider, predicate, network=False):
        stop = threading.Event()
        captured = []
        deadline = time.monotonic() + 3
        original = poller.write_outputs
        def write(data, root):
            original(data, root)
            captured.append(dict(data))
            if predicate(data) or time.monotonic() > deadline:
                stop.set()
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            with mock.patch.object(poller, 'write_outputs', side_effect=write):
                poller.poll_loop(stop, provider, root, .005, 'JP', network)
            self.assertTrue(predicate(captured[-1]), captured[-1])
            covers = {p.name: p.read_bytes() for p in root.glob('cover_*.jpg')}
        return captured, covers

    def test_retries_provider_artwork(self):
        provider = Provider(fail_first=True)
        with mock.patch.object(poller, 'ARTWORK_RETRY_INTERVAL', .01):
            data, covers = self.run_until(provider, lambda d: bool(d['artworkFile']))
        self.assertEqual(provider.calls, 2)
        self.assertEqual(data[-1]['artworkSource'], 'test')
        self.assertEqual(data[-1]['artworkVersion'], hashlib.sha256(next(iter(covers.values()))).hexdigest())

    def test_retries_provider_after_fallback_without_repeating_network(self):
        provider = Provider(fail_first=True)
        def fallback(data, root, country):
            (root / 'fallback.png').write_bytes(image_bytes('blue'))
            return 'fallback.png', ''
        with mock.patch.object(poller, 'ARTWORK_RETRY_INTERVAL', .01):
            with mock.patch.object(worker, 'fetch_artwork_from_itunes_search', side_effect=fallback) as fetch:
                data, _ = self.run_until(provider, lambda d: d['artworkSource'] == 'test', True)
        self.assertEqual(provider.calls, 2)
        fetch.assert_called_once()
        self.assertIn('itunes', [d['artworkSource'] for d in data])

    def test_duration_changes_do_not_change_identity_or_refetch(self):
        provider = Provider()
        samples = 0
        def done(data):
            nonlocal samples
            if data['artworkFile']:
                samples += 1
                provider.duration = 0 if provider.duration else 240
            return samples >= 100
        self.run_until(provider, done)
        self.assertEqual(provider.calls, 1)
        self.assertEqual(make_track_key({'title': 'Song', 'duration': 0}),
                         make_track_key({'title': 'Song', 'duration': 240}))

    def test_slow_old_job_does_not_block_metadata_or_publish_stale_image(self):
        entered, release = threading.Event(), threading.Event()
        provider = Provider()
        def artwork(data, runtime_dir=None):
            provider.calls += 1
            if data['title'] == 'Song':
                entered.set()
                release.wait(3)
                color = 'red'
            else:
                color = 'blue'
            (runtime_dir / 'cover.png').write_bytes(image_bytes(color))
            return ArtworkResult(file='cover.png', source='test')
        provider.get_artwork = artwork
        stop = threading.Event()
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            thread = threading.Thread(target=poller.poll_loop, args=(stop, provider, root, .005, 'JP', False))
            thread.start()
            try:
                self.assertTrue(entered.wait(2))
                provider.title = 'New Song'
                for _ in range(200):
                    data = json.loads((root / 'nowplaying.json').read_text())
                    if data['title'] == 'New Song':
                        break
                    time.sleep(.005)
                self.assertEqual(data['title'], 'New Song')
                self.assertFalse(data['artworkFile'])
                self.assertTrue(data['artworkPending'])
                self.assertEqual(provider.calls, 1)
                self.assertEqual(list(root.glob('cover*')), [])
                release.set()
                for _ in range(400):
                    data = json.loads((root / 'nowplaying.json').read_text())
                    if data['artworkFile']:
                        break
                    time.sleep(.005)
                expected = normalize_artwork(image_bytes('blue'))
                self.assertEqual((root / data['artworkFile']).read_bytes(), expected)
                self.assertEqual(data['artworkVersion'], hashlib.sha256(expected).hexdigest())
                self.assertEqual(provider.calls, 2)
                self.assertFalse(data['artworkPending'])
            finally:
                release.set()
                stop.set()
                thread.join(3)
            self.assertFalse(thread.is_alive())

    def test_identical_artwork_reuses_file_and_version_across_tracks(self):
        provider = Provider()
        first = []
        def done(data):
            if data['artworkFile']:
                if not first:
                    first.append((data['artworkFile'], data['artworkVersion']))
                    provider.title = 'Second song'
                elif data['title'] == 'Second song':
                    self.assertEqual((data['artworkFile'], data['artworkVersion']), first[0])
                    return True
            return False
        _, covers = self.run_until(provider, done)
        self.assertEqual(provider.calls, 2)
        self.assertEqual(len(covers), 1)
