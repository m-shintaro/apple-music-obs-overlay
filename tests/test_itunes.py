import json
import multiprocessing
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import queue
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


class FakeConnection:
    def __init__(self, messages):
        self.messages = messages
        self.item = None

    def poll(self, timeout):
        try:
            self.item = (self.messages.get(timeout=timeout),)
            return True
        except queue.Empty:
            return False

    def recv(self):
        item, self.item = self.item, None
        return item[0]

    def send(self, message):
        self.messages.put(message)

    def close(self):
        pass


class SlowStartContext:
    """A worker whose start-up takes `startup` seconds before it reports in."""

    def __init__(self, startup, work):
        self.startup = startup
        self.work = work
        self.stop = threading.Event()

    def Pipe(self, duplex=False):
        connection = FakeConnection(queue.Queue())
        return connection, connection

    def Process(self, target, args, daemon):
        context, send = self, args[-1]

        class Process:
            def start(self):
                def run():
                    if context.stop.wait(context.startup):
                        return
                    send.send(None)
                    if not context.stop.wait(context.work):
                        send.send(('cover_fallback.jpg', ''))
                self.thread = threading.Thread(target=run, daemon=True)
                self.thread.start()

            def is_alive(self):
                return self.thread.is_alive()

            def terminate(self):
                context.stop.set()

            kill = terminate

            def join(self, timeout=None):
                self.thread.join(timeout)

            def close(self):
                pass

        return Process()


class WorkerStartTests(TestCase):
    def lookup(self, context):
        with mock.patch.object(itunes.multiprocessing, 'get_context', return_value=context), \
                mock.patch.object(itunes, 'NETWORK_ARTWORK_TIMEOUT', .3), \
                mock.patch.object(itunes, 'WORKER_START_TIMEOUT', .6):
            return itunes.fetch_artwork_from_itunes_search({'title': 'Song'}, Path('.'), 'JP')

    def test_worker_start_up_does_not_use_the_network_deadline(self):
        self.assertEqual(self.lookup(SlowStartContext(startup=.4, work=.1)), ('cover_fallback.jpg', ''))

    def test_network_deadline_applies_once_the_worker_is_running(self):
        self.assertEqual(self.lookup(SlowStartContext(startup=0, work=5)), ('', 'itunes:timeout'))

    def test_worker_that_never_starts_is_reported_separately(self):
        self.assertEqual(self.lookup(SlowStartContext(startup=5, work=0)),
                         ('', 'itunes:worker_start_timeout'))
