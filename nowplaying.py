#!/usr/bin/env python3
import argparse
import json
import pathlib
import signal
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

APP_DIR = pathlib.Path(__file__).resolve().parent
RUNTIME_DIR = APP_DIR / "runtime"
TEXT_FILE = RUNTIME_DIR / "nowplaying.txt"
JSON_FILE = RUNTIME_DIR / "nowplaying.json"

NOWPLAYING_SCRIPT = r'''
(() => {
  const empty = {
    state: "stopped",
    title: "",
    artist: "",
    album: "",
    position: 0,
    duration: 0
  };

  function text(read) {
    try {
      const value = read();
      return value == null ? "" : String(value);
    } catch (error) {
      return "";
    }
  }

  function seconds(read) {
    try {
      const value = Number(read());
      return Number.isFinite(value) ? value : 0;
    } catch (error) {
      return 0;
    }
  }

  let Music;
  try {
    Music = Application("/System/Applications/Music.app");
  } catch (error) {
    try {
      Music = Application("Music");
    } catch (fallbackError) {
      return JSON.stringify(empty);
    }
  }

  if (!Music.running()) {
    return JSON.stringify(empty);
  }

  const state = text(() => Music.playerState()) || "stopped";
  if (state === "stopped") {
    return JSON.stringify({ ...empty, state });
  }

  const track = Music.currentTrack();
  return JSON.stringify({
    state,
    title: text(() => track.name()),
    artist: text(() => track.artist()),
    album: text(() => track.album()),
    position: seconds(() => Music.playerPosition()),
    duration: seconds(() => track.duration())
  });
})()
'''

ARTWORK_SCRIPT = r'''
ObjC.import("Foundation");

function run(argv) {
  const outPath = argv[0];

  function message(error) {
    if (!error) {
      return "";
    }
    if (error.message) {
      return String(error.message);
    }
    return String(error);
  }

  function dataFromArtwork(artwork, getterName) {
    try {
      const value = artwork[getterName]();
      if (value && typeof value.writeToFileAtomically === "function") {
        return value;
      }
      return $.NSData.dataWithData(value);
    } catch (error) {
      throw new Error(`${getterName}:${message(error)}`);
    }
  }

  function artworkCandidates(track) {
    const candidates = [];
    const errors = [];

    try {
      if (track.artworks && track.artworks[0]) {
        candidates.push({ source: "index", artwork: track.artworks[0] });
      }
    } catch (error) {
      errors.push(`index:${message(error)}`);
    }

    try {
      const artworks = track.artworks();
      if (Array.isArray(artworks) && artworks.length) {
        candidates.push({ source: "call", artwork: artworks[0] });
      }
    } catch (error) {
      errors.push(`call:${message(error)}`);
    }

    return { candidates, errors };
  }

  let Music;
  try {
    Music = Application("/System/Applications/Music.app");
  } catch (error) {
    return `missing:application:${message(error)}`;
  }

  if (!Music.running()) {
    return "missing:not_running";
  }

  try {
    if (String(Music.playerState()) === "stopped") {
      return "missing:stopped";
    }
  } catch (error) {
    // Some Music states throw here; currentTrack below gives a better diagnostic.
  }

  let track;
  try {
    track = Music.currentTrack();
  } catch (error) {
    return `missing:current_track:${message(error)}`;
  }

  const artworkResult = artworkCandidates(track);
  if (!artworkResult.candidates.length) {
    return `missing:no_artworks:${artworkResult.errors.join("|")}`;
  }

  const attempts = [];

  for (const candidate of artworkResult.candidates) {
    for (const getterName of ["rawData", "data"]) {
      try {
        const nsData = dataFromArtwork(candidate.artwork, getterName);
        if (!nsData || Number(nsData.length) === 0) {
          attempts.push(`${candidate.source}.${getterName}:empty`);
          continue;
        }
        const ok = nsData.writeToFileAtomically($(outPath), true);
        if (ok) {
          return `ok:${candidate.source}.${getterName}`;
        }
        attempts.push(`${candidate.source}.${getterName}:write_failed`);
      } catch (error) {
        attempts.push(`${candidate.source}.${message(error)}`);
      }
    }
  }

  return `missing:${attempts.join("|")}`;
}
'''

DEMO_TRACKS = [
    {
        "title": "Midnight Current",
        "artist": "Sample Artist",
        "album": "OBS Preview",
        "duration": 214,
    },
    {
        "title": "Signal in Bloom",
        "artist": "Apple Music Demo",
        "album": "Local Overlay",
        "duration": 188,
    },
]


def ensure_runtime_dir() -> None:
    RUNTIME_DIR.mkdir(exist_ok=True)


def atomic_write_text(path: pathlib.Path, text: str) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def atomic_write_bytes(path: pathlib.Path, data: bytes) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(data)
    tmp.replace(path)


def fmt_time(seconds: float) -> str:
    seconds = max(0, int(seconds))
    return f"{seconds // 60}:{seconds % 60:02d}"


def safe_float(value: str) -> float:
    try:
        return float(value or 0)
    except ValueError:
        return 0.0


def clamp(value: float, min_value: float = 0.0, max_value: float = 1.0) -> float:
    return max(min_value, min(max_value, value))


def default_payload(state: str = "stopped", error: str = "") -> dict:
    return {
        "state": state,
        "title": "",
        "artist": "",
        "album": "",
        "position": 0,
        "duration": 0,
        "positionText": "0:00",
        "durationText": "0:00",
        "progress": 0,
        "artworkFile": "",
        "artworkVersion": "",
        "artworkSource": "",
        "artworkError": "",
        "updatedAt": time.time(),
        "error": error,
    }


def build_payload(state: str, title: str, artist: str, album: str, position: float, duration: float) -> dict:
    progress = position / duration if duration > 0 else 0
    return {
        "state": state,
        "title": title,
        "artist": artist,
        "album": album,
        "position": max(0, position),
        "duration": max(0, duration),
        "positionText": fmt_time(position),
        "durationText": fmt_time(duration),
        "progress": clamp(progress),
        "artworkFile": "",
        "artworkVersion": "",
        "artworkSource": "",
        "artworkError": "",
        "updatedAt": time.time(),
        "error": "",
    }


def get_nowplaying() -> dict:
    try:
        result = subprocess.run(
            ["osascript", "-l", "JavaScript", "-e", NOWPLAYING_SCRIPT],
            text=True,
            capture_output=True,
            timeout=5,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return default_payload("error", "nowplaying:osascript_timeout")

    if result.returncode != 0:
        return default_payload("error", result.stderr.strip())

    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        return default_payload("error", result.stdout.strip() or result.stderr.strip())

    return build_payload(
        str(payload.get("state") or "stopped"),
        str(payload.get("title") or ""),
        str(payload.get("artist") or ""),
        str(payload.get("album") or ""),
        safe_float(str(payload.get("position") or 0)),
        safe_float(str(payload.get("duration") or 0)),
    )


def make_track_key(data: dict) -> str:
    return "|".join(
        [
            data.get("title", ""),
            data.get("artist", ""),
            data.get("album", ""),
            str(data.get("duration", 0)),
        ]
    )


def detect_image_suffix(data: bytes) -> str:
    if data.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return ".gif"
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return ".webp"
    if data.startswith((b"MM\x00*", b"II*\x00")):
        return ".tiff"
    return ""


def convert_artwork_file(raw_path: pathlib.Path, stem: str = "cover_direct") -> tuple[str, str]:
    data = raw_path.read_bytes()
    if not data:
        return "", "direct:empty_file"

    suffix = detect_image_suffix(data)
    if suffix in {".jpg", ".png", ".gif", ".webp"}:
        out = RUNTIME_DIR / f"{stem}{suffix}"
        atomic_write_bytes(out, data)
        raw_path.unlink(missing_ok=True)
        return out.name, ""

    out = RUNTIME_DIR / f"{stem}.png"
    result = subprocess.run(
        ["sips", "-s", "format", "png", str(raw_path), "--out", str(out)],
        text=True,
        capture_output=True,
        timeout=5,
        check=False,
    )
    raw_path.unlink(missing_ok=True)

    if result.returncode == 0 and out.exists() and out.stat().st_size > 0:
        return out.name, ""

    head = data[:16].hex()
    detail = (result.stderr or result.stdout).strip()
    return "", f"direct:unknown_image_format:first_bytes={head}:sips={detail}"


def export_artwork_from_music() -> tuple[str, str]:
    raw_path = RUNTIME_DIR / "cover_direct.raw"
    raw_path.unlink(missing_ok=True)

    try:
        result = subprocess.run(
            ["osascript", "-l", "JavaScript", "-e", ARTWORK_SCRIPT, str(raw_path)],
            text=True,
            capture_output=True,
            timeout=8,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return "", "direct:osascript_timeout"

    if result.returncode != 0:
        return "", f"direct:osascript:{result.stderr.strip()}"

    status = result.stdout.strip()
    if not status.startswith("ok:"):
        return "", status or "direct:no_status"
    if not raw_path.exists():
        return "", f"{status}:no_file_written"

    artwork_file, error = convert_artwork_file(raw_path, "cover_direct")
    if artwork_file:
        return artwork_file, status
    return "", f"{status}:{error}"


def fetch_artwork_from_itunes_search(data: dict, country: str) -> str:
    title = data.get("title") or ""
    artist = data.get("artist") or ""
    if not title and not artist:
        return ""

    params = {
        "term": f"{artist} {title}".strip(),
        "country": country,
        "media": "music",
        "entity": "song",
        "limit": "1",
    }
    search_url = "https://itunes.apple.com/search?" + urllib.parse.urlencode(params)

    try:
        with urllib.request.urlopen(search_url, timeout=5) as res:
            payload = json.loads(res.read().decode("utf-8"))

        results = payload.get("results") or []
        if not results:
            return ""

        artwork_url = results[0].get("artworkUrl100")
        if not artwork_url:
            return ""

        large_url = (
            artwork_url.replace("100x100bb", "600x600bb")
            .replace("100x100-75", "600x600-75")
            .replace("100x100", "600x600")
        )

        try:
            with urllib.request.urlopen(large_url, timeout=5) as img_res:
                image = img_res.read()
        except Exception:
            with urllib.request.urlopen(artwork_url, timeout=5) as img_res:
                image = img_res.read()

        out = RUNTIME_DIR / "cover_fallback.jpg"
        atomic_write_bytes(out, image)
        return out.name
    except Exception:
        return ""


def write_outputs(data: dict) -> None:
    if data["state"] == "playing":
        text = f"♪ {data['artist']} - {data['title']}  {data['positionText']} / {data['durationText']}"
    elif data["state"] == "paused":
        text = f"Paused: {data['artist']} - {data['title']}  {data['positionText']} / {data['durationText']}"
    else:
        text = ""

    atomic_write_text(TEXT_FILE, text)
    atomic_write_text(JSON_FILE, json.dumps(data, ensure_ascii=False, indent=2))


def demo_payload(start_time: float) -> dict:
    elapsed = time.time() - start_time
    track_index = int(elapsed // 28) % len(DEMO_TRACKS)
    track = DEMO_TRACKS[track_index]
    duration = track["duration"]
    position = elapsed % min(28, duration)
    return build_payload(
        "playing",
        track["title"],
        track["artist"],
        track["album"],
        position,
        duration,
    )


def poll_loop(
    stop_event: threading.Event,
    interval: float,
    country: str,
    allow_network_artwork: bool,
    demo: bool,
) -> None:
    last_track_key = ""
    last_artwork_file = ""
    last_artwork_source = ""
    last_artwork_error = ""
    demo_started_at = time.time()

    while not stop_event.is_set():
        data = demo_payload(demo_started_at) if demo else get_nowplaying()

        if data["state"] in ("playing", "paused"):
            track_key = make_track_key(data)
            if track_key != last_track_key:
                artwork_file = ""
                artwork_source = ""
                artwork_error = ""

                if not demo:
                    artwork_file, artwork_error = export_artwork_from_music()
                    if artwork_file:
                        artwork_source = "music"

                if not artwork_file and allow_network_artwork and not demo:
                    artwork_file = fetch_artwork_from_itunes_search(data, country)
                    if artwork_file:
                        artwork_source = "itunes"
                        artwork_error = ""

                last_artwork_file = artwork_file
                last_artwork_source = artwork_source
                last_artwork_error = "" if artwork_file else artwork_error
                last_track_key = track_key

            data["artworkFile"] = last_artwork_file
            data["artworkVersion"] = last_track_key
            data["artworkSource"] = last_artwork_source
            data["artworkError"] = last_artwork_error
        else:
            last_track_key = ""
            last_artwork_file = ""
            last_artwork_source = ""
            last_artwork_error = ""

        write_outputs(data)
        stop_event.wait(interval)


class OverlayHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(APP_DIR), **kwargs)

    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def log_message(self, format: str, *args) -> None:
        return


def serve(port: int, bind: str) -> None:
    server = ThreadingHTTPServer((bind, port), OverlayHandler)
    print(f"OBS Browser Source URL (1080p): http://localhost:{port}/overlay.html", flush=True)
    print(f"OBS Browser Source URL (4K): http://localhost:{port}/overlay.html?profile=4k", flush=True)
    print("Press Ctrl+C to stop.", flush=True)
    server.serve_forever()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Apple Music now-playing overlay for OBS on macOS.")
    parser.add_argument("--port", type=int, default=8765, help="HTTP server port. Default: 8765")
    parser.add_argument("--bind", default="127.0.0.1", help="HTTP server bind address. Default: 127.0.0.1")
    parser.add_argument("--interval", type=float, default=0.25, help="Polling interval in seconds. Default: 0.25")
    parser.add_argument("--country", default="JP", help="iTunes Search API country code. Default: JP")
    parser.add_argument("--no-network-artwork", action="store_true", help="Disable iTunes Search API artwork fallback.")
    parser.add_argument("--demo", action="store_true", help="Run with sample data for layout preview.")
    parser.add_argument("--once", action="store_true", help="Write nowplaying files once and exit.")
    parser.add_argument("--diagnose-artwork", action="store_true", help="Try direct Music.app artwork export once and print diagnostics.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    ensure_runtime_dir()

    if args.diagnose_artwork:
        data = get_nowplaying()
        artwork_file, artwork_status = export_artwork_from_music()
        print(
            json.dumps(
                {
                    "track": data,
                    "artworkFile": artwork_file,
                    "artworkStatus": artwork_status,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    if args.once:
        data = demo_payload(time.time()) if args.demo else get_nowplaying()
        write_outputs(data)
        print(JSON_FILE)
        return 0

    stop_event = threading.Event()
    poller = threading.Thread(
        target=poll_loop,
        args=(
            stop_event,
            args.interval,
            args.country,
            not args.no_network_artwork,
            args.demo,
        ),
        daemon=True,
    )
    poller.start()

    def stop(_signum, _frame) -> None:
        stop_event.set()
        sys.exit(0)

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    serve(args.port, args.bind)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
