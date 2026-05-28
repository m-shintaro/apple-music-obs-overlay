from __future__ import annotations

from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


def make_handler(app_dir: Path):
    class OverlayHandler(SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(app_dir), **kwargs)

        def end_headers(self) -> None:
            self.send_header("Cache-Control", "no-store")
            super().end_headers()

        def log_message(self, format: str, *args) -> None:
            return

    return OverlayHandler


def serve(port: int, bind: str, app_dir: Path) -> None:
    server = ThreadingHTTPServer((bind, port), make_handler(app_dir))
    print(f"OBS Browser Source URL (1080p): http://localhost:{port}/overlay.html", flush=True)
    print(f"OBS Browser Source URL (4K): http://localhost:{port}/overlay.html?profile=4k", flush=True)
    print("Press Ctrl+C to stop.", flush=True)
    server.serve_forever()
