from __future__ import annotations

import argparse
import json
from pathlib import Path
import platform
import signal
import sys
import sysconfig
import threading

from .output import ensure_runtime_dir, write_outputs
from .poller import poll_loop
from .providers.base import NowPlayingProvider
from .providers.demo import DemoProvider
from .providers.macos_music import MacOSMusicProvider
from .providers.windows_media import WindowsMediaProvider
from .server import serve


def is_frozen_app() -> bool:
    return bool(getattr(sys, "frozen", False))


def frozen_bundle_dir() -> Path | None:
    if not is_frozen_app():
        return None

    candidates = []
    meipass = getattr(sys, "_MEIPASS", "")
    if meipass:
        candidates.append(Path(meipass))
    candidates.append(Path(sys.executable).resolve().parent)

    for candidate in candidates:
        if (candidate / "overlay.html").exists():
            return candidate
    return None


def executable_dir() -> Path:
    if is_frozen_app():
        return Path(sys.executable).resolve().parent
    return Path.cwd()


def find_app_dir() -> Path:
    bundle_dir = frozen_bundle_dir()
    if bundle_dir is not None:
        return bundle_dir

    repo_dir = Path(__file__).resolve().parents[2]
    if (repo_dir / "overlay.html").exists():
        return repo_dir
    cwd = Path.cwd()
    if (cwd / "overlay.html").exists():
        return cwd
    data_dir = Path(sysconfig.get_path("data")) / "share" / "apple-music-obs-overlay"
    if (data_dir / "overlay.html").exists():
        return data_dir
    return repo_dir


def find_runtime_dir(app_dir: Path) -> Path:
    if is_frozen_app():
        return executable_dir() / "runtime"
    if app_dir == Path.cwd() or app_dir == Path(__file__).resolve().parents[2]:
        return app_dir / "runtime"
    return executable_dir() / "runtime"


APP_DIR = find_app_dir()
RUNTIME_DIR = find_runtime_dir(APP_DIR)
JSON_FILE = RUNTIME_DIR / "nowplaying.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Apple Music / now-playing overlay for OBS."
    )
    parser.add_argument(
        "--provider",
        choices=("auto", "macos", "windows", "demo"),
        default="auto",
        help="Now-playing provider. Default: auto",
    )
    parser.add_argument("--port", type=int, default=8765, help="HTTP server port. Default: 8765")
    parser.add_argument(
        "--bind",
        default="127.0.0.1",
        help="HTTP server bind address. Default: 127.0.0.1",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=0.25,
        help="Polling interval in seconds. Default: 0.25",
    )
    parser.add_argument("--country", default="JP", help="iTunes Search API country code. Default: JP")
    parser.add_argument(
        "--no-network-artwork",
        action="store_true",
        help="Disable the iTunes Search API artwork fallback.",
    )
    parser.add_argument(
        "--demo",
        action="store_true",
        help="Alias for --provider demo. Kept for compatibility.",
    )
    parser.add_argument("--once", action="store_true", help="Write nowplaying files once and exit.")
    parser.add_argument(
        "--diagnose-artwork",
        action="store_true",
        help="Try provider artwork export once and print diagnostics.",
    )
    return parser.parse_args()


def create_provider(name: str, runtime_dir: Path) -> NowPlayingProvider:
    if name == "macos":
        return MacOSMusicProvider(runtime_dir)
    if name == "windows":
        return WindowsMediaProvider(runtime_dir)
    if name == "demo":
        return DemoProvider()
    raise ValueError(f"Unknown provider: {name}")


def resolve_provider_name(args: argparse.Namespace) -> str:
    if args.demo:
        return "demo"
    if args.provider != "auto":
        return args.provider

    system = platform.system()
    if system == "Darwin":
        return "macos"
    if system == "Windows":
        return "windows"

    print(
        f"Unsupported platform for auto provider ({system}); using demo provider.",
        file=sys.stderr,
        flush=True,
    )
    return "demo"


def main() -> int:
    args = parse_args()
    ensure_runtime_dir(RUNTIME_DIR)
    provider = create_provider(resolve_provider_name(args), RUNTIME_DIR)

    if args.diagnose_artwork:
        data = provider.get_nowplaying()
        artwork = provider.get_artwork(data)
        print(
            json.dumps(
                {
                    "provider": provider.name,
                    "track": data,
                    "artworkFile": artwork.file,
                    "artworkSource": artwork.source,
                    "artworkError": artwork.error,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    if args.once:
        data = provider.get_nowplaying()
        write_outputs(data, RUNTIME_DIR)
        print(JSON_FILE)
        return 0

    stop_event = threading.Event()
    poller = threading.Thread(
        target=poll_loop,
        args=(
            stop_event,
            provider,
            RUNTIME_DIR,
            args.interval,
            args.country,
            not args.no_network_artwork,
        ),
        daemon=True,
    )
    poller.start()

    def stop(_signum, _frame) -> None:
        stop_event.set()
        sys.exit(0)

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    serve(args.port, args.bind, APP_DIR, RUNTIME_DIR)
    return 0
