import json
import multiprocessing
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory
import threading
import time
from unittest import TestCase, mock

from apple_music_obs_overlay.artwork import itunes


class LocalArtworkServer:
    """Real loopback sockets: a per-read timeout cannot stop a drip feed."""

    def __init__(self, mode='ok'):
        self.mode = mode
        self.entered = threading.Event()
        self.release = threading.Event()
        self.requests = []
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                owner.requests.append(self.path)
                try:
                    if self.path.startswith('/search'):
                        if owner.mode == 'headers':
                            self.wfile.write(b'HTTP/1.1 200 OK\r\nX-Slow: ')
                            self.wfile.flush()
                            owner.entered.set()
                            while not owner.release.wait(.04):
                                self.wfile.write(b'a')
                                self.wfile.flush()
                            return
                        data = json.dumps({'results': [{'artworkUrl100':
                            f'http://127.0.0.1:{self.server.server_port}/100x100bb.jpg'}]}).encode()
                    else:
                        if owner.mode == 'small' and '600x600' in self.path:
                            self.send_error(404)
                            return
                        data = b'original artwork bytes'
                        if owner.mode == 'body':
                            self.send_response(200)
                            self.send_header('Content-Length', '1000000')
                            self.end_headers()
                            owner.entered.set()
                            while not owner.release.wait(.04):
                                self.wfile.write(b'a')
                                self.wfile.flush()
                            return
                        if owner.mode == 'stall':
                            owner.entered.set()
                            owner.release.wait(10)
                            return
                    self.send_response(200)
                    self.send_header('Content-Length', str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                except (BrokenPipeError, ConnectionResetError):
                    pass

        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.url = f'http://127.0.0.1:{self.server.server_port}/search'
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def __enter__(self):
        self.thread.start()
        self.patch = mock.patch.object(itunes, 'SEARCH_URL', self.url, create=True)
        self.patch.start()
        return self

    def __exit__(self, *args):
        self.release.set()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(2)
        self.patch.stop()


class ItunesTests(TestCase):
    def setUp(self):
        self.children_before = {p.pid for p in multiprocessing.active_children()}

    def tearDown(self):
        self.assertEqual({p.pid for p in multiprocessing.active_children()}, self.children_before)

    def test_success_and_small_url_fallback_preserve_downloaded_bytes(self):
        for mode in ('ok', 'small'):
            with self.subTest(mode=mode), TemporaryDirectory() as tmp, LocalArtworkServer(mode) as server:
                file, error = itunes.fetch_artwork_from_itunes_search({'title': 'Song'}, Path(tmp), 'JP')
                self.assertEqual(error, '')
                self.assertEqual((Path(tmp) / file).read_bytes(), b'original artwork bytes')
                self.assertIn('/600x600bb.jpg', server.requests)
                if mode == 'small':
                    self.assertIn('/100x100bb.jpg', server.requests)

    def test_total_deadline_covers_drip_headers_body_and_stalled_response(self):
        for mode in ('headers', 'body', 'stall'):
            with self.subTest(mode=mode), TemporaryDirectory() as tmp, LocalArtworkServer(mode) as server:
                with mock.patch.object(itunes, 'NETWORK_ARTWORK_TIMEOUT', .8):
                    start = time.monotonic()
                    file, error = itunes.fetch_artwork_from_itunes_search({'title': 'Song'}, Path(tmp), 'JP')
                    elapsed = time.monotonic() - start
                self.assertTrue(server.entered.is_set(), 'must reach a real socket before the deadline')
                self.assertEqual((file, error), ('', 'itunes:timeout'))
                self.assertGreaterEqual(elapsed, .8)
                self.assertLess(elapsed, 1.8)
                self.assertEqual(list(Path(tmp).iterdir()), [])

    def test_cancellation_reaps_child_before_next_lookup(self):
        with TemporaryDirectory() as tmp, LocalArtworkServer('body') as server:
            for _ in range(5):
                server.entered.clear()
                cancel = threading.Event()
                result = []
                thread = threading.Thread(target=lambda: result.append(
                    itunes.fetch_artwork_from_itunes_search({'title': 'Song'}, Path(tmp), 'JP', cancel)))
                thread.start()
                try:
                    self.assertTrue(server.entered.wait(3))
                    start = time.monotonic()
                    cancel.set()
                    thread.join(1.5)
                    self.assertFalse(thread.is_alive())
                    self.assertLess(time.monotonic() - start, 1.5)
                    self.assertEqual(result, [('', 'itunes:cancelled')])
                    self.assertEqual({p.pid for p in multiprocessing.active_children()}, self.children_before)
                finally:
                    cancel.set()
                    thread.join(3)
            self.assertEqual(list(Path(tmp).iterdir()), [])

    def test_pre_cancelled_lookup_does_not_start_process(self):
        cancel = threading.Event()
        cancel.set()
        with mock.patch.object(itunes.multiprocessing, 'get_context') as context:
            self.assertEqual(itunes.fetch_artwork_from_itunes_search(
                {'title': 'Song'}, Path('.'), 'JP', cancel), ('', 'itunes:cancelled'))
        context.assert_not_called()
