from __future__ import annotations

import json
from pathlib import Path
import subprocess
from typing import Any, Dict, Tuple

from ..artwork.image import convert_artwork_file
from ..payload import build_payload, default_payload, safe_float
from .base import ArtworkResult, BaseProvider


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
    trackId: text(() => track.persistentID()),
    position: seconds(() => Music.playerPosition()),
    duration: seconds(() => track.duration())
  });
})()
'''


ARTWORK_SCRIPT = r'''
ObjC.import("Foundation");

function run(argv) {
  const outPath = argv[0];
  const expected = JSON.parse(argv[1]);

  function text(read) {
    try {
      const value = read();
      return value == null ? "" : String(value);
    } catch (error) {
      return "";
    }
  }

  function identity(track) {
    return {
      title: text(() => track.name()),
      artist: text(() => track.artist()),
      album: text(() => track.album()),
      trackId: text(() => track.persistentID())
    };
  }

  function matches(actual, wanted) {
    const keys = ["title", "artist", "album"];
    if (wanted.trackId) keys.push("trackId");
    return keys.every(key => actual[key] === String(wanted[key] || ""));
  }

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

  const sampled = identity(track);
  if (!matches(sampled, expected)) return "missing:track_changed";

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
        // JXA references can resolve again on each Apple Event. Recheck after
        // exporting, including persistent ID when available, before writing.
        if (!matches(identity(track), sampled) ||
            !matches(identity(Music.currentTrack()), sampled)) {
          return "missing:track_changed";
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


class MacOSMusicProvider(BaseProvider):
    name = "macos"

    def __init__(self, runtime_dir: Path) -> None:
        self.runtime_dir = runtime_dir

    def get_nowplaying(self) -> Dict[str, Any]:
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
        except FileNotFoundError:
            return default_payload("error", "nowplaying:osascript_not_found")

        if result.returncode != 0:
            return default_payload("error", result.stderr.strip())

        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError:
            return default_payload("error", result.stdout.strip() or result.stderr.strip())

        data = build_payload(
            str(payload.get("state") or "stopped"),
            str(payload.get("title") or ""),
            str(payload.get("artist") or ""),
            str(payload.get("album") or ""),
            safe_float(payload.get("position") or 0),
            safe_float(payload.get("duration") or 0),
        )
        data["trackId"] = str(payload.get("trackId") or "")
        return data

    def get_artwork(self, data: Dict[str, Any], runtime_dir: Path | None = None) -> ArtworkResult:
        artwork_file, status = self._export_artwork_from_music(data, runtime_dir or self.runtime_dir)
        if artwork_file:
            return ArtworkResult(file=artwork_file, source="music", error="")
        return ArtworkResult(error=status, track_changed=status == "missing:track_changed")

    def _export_artwork_from_music(self, data: Dict[str, Any], runtime_dir: Path) -> Tuple[str, str]:
        raw_path = runtime_dir / "cover_direct.raw"
        raw_path.unlink(missing_ok=True)

        try:
            result = subprocess.run(
                ["osascript", "-l", "JavaScript", "-e", ARTWORK_SCRIPT, str(raw_path),
                 json.dumps({key: data.get(key) or "" for key in
                             ("title", "artist", "album", "trackId")})],
                text=True,
                capture_output=True,
                timeout=8,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return "", "direct:osascript_timeout"
        except FileNotFoundError:
            return "", "direct:osascript_not_found"

        if result.returncode != 0:
            return "", f"direct:osascript:{result.stderr.strip()}"

        status = result.stdout.strip()
        if not status.startswith("ok:"):
            return "", status or "direct:no_status"
        if not raw_path.exists():
            return "", f"{status}:no_file_written"

        artwork_file, error = convert_artwork_file(raw_path, runtime_dir, "cover_direct")
        if artwork_file:
            return artwork_file, status
        return "", f"{status}:{error}"
