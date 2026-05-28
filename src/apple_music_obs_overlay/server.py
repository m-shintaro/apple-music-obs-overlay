from __future__ import annotations

from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import posixpath
from pathlib import Path
import urllib.parse


def make_handler(app_dir: Path, runtime_dir: Path):
    class OverlayHandler(SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(app_dir), **kwargs)

        def translate_path(self, path: str) -> str:
            runtime_path = self._translate_runtime_path(path)
            if runtime_path is not None:
                return str(runtime_path)
            return super().translate_path(path)

        def _translate_runtime_path(self, path: str) -> Path | None:
            request_path = urllib.parse.urlsplit(path).path
            if request_path == "/runtime":
                return runtime_dir
            if not request_path.startswith("/runtime/"):
                return None

            relative = urllib.parse.unquote(request_path.removeprefix("/runtime/"))
            normalized = posixpath.normpath(relative)
            parts = [
                part
                for part in normalized.split("/")
                if part and part not in (".", "..")
            ]
            return runtime_dir.joinpath(*parts)

        def end_headers(self) -> None:
            self.send_header("Cache-Control", "no-store")
            super().end_headers()

        def log_message(self, format: str, *args) -> None:
            return

    return OverlayHandler


def serve(port: int, bind: str, app_dir: Path, runtime_dir: Path | None = None) -> None:
    runtime_dir = app_dir / "runtime" if runtime_dir is None else runtime_dir
    server = ThreadingHTTPServer((bind, port), make_handler(app_dir, runtime_dir))
    print(f"OBS Browser Source URL (1080p): http://localhost:{port}/overlay.html", flush=True)
    print(f"OBS Browser Source URL (4K): http://localhost:{port}/overlay.html?profile=4k", flush=True)
    print("Press Ctrl+C to stop.", flush=True)
    server.serve_forever()
