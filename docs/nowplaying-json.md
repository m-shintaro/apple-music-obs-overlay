# `runtime/nowplaying.json`

`runtime/nowplaying.json` is the stable interface between the Python backend and
`overlay.html`. Providers can be platform-specific, but they should write this
same shape so the OBS Browser Source URL stays shared across macOS and Windows.

The file is rewritten atomically by the backend. Consumers should poll it and
ignore unknown fields for forward compatibility.

## Example

```json
{
  "state": "playing",
  "title": "Song Title",
  "artist": "Artist Name",
  "album": "Album Name",
  "position": 42.5,
  "duration": 214,
  "positionText": "0:42",
  "durationText": "3:34",
  "progress": 0.1985981308,
  "artworkFile": "cover_<sha256>.png",
  "artworkVersion": "<sha256-of-published-image>",
  "artworkSource": "music",
  "artworkError": "",
  "artworkPending": false,
  "updatedAt": 1779889002.1195467,
  "error": ""
}
```

## Fields

| Field | Type | Description |
| --- | --- | --- |
| `state` | string | Playback state: `playing`, `paused`, `stopped`, or `error`. |
| `title` | string | Track title, or an empty string when unavailable. |
| `artist` | string | Track artist, or an empty string when unavailable. |
| `album` | string | Album title, or an empty string when unavailable. |
| `trackId` | string | Optional macOS Music persistent ID or system media content item ID. Used to correlate artwork with its track; unavailable IDs are empty. |
| `sourceAppId` | string | Optional Windows media-session app ID or macOS bundle identifier. Prevents adopting a different app's cover for otherwise identical metadata. |
| `position` | number | Current playback position in seconds. |
| `duration` | number | Track duration in seconds. |
| `playbackRate` | number | Optional playback speed from macOS system media (e.g. `2` for 2×). The overlay uses `1` when absent; paused playback does not advance. |
| `positionText` | string | Display-ready `M:SS` text for `position`. |
| `durationText` | string | Display-ready `M:SS` text for `duration`. |
| `progress` | number | `position / duration`, clamped from `0` to `1`. |
| `artworkFile` | string | Artwork filename inside `runtime/`, or empty when unavailable. |
| `artworkVersion` | string | SHA-256 of the published image bytes, or empty while artwork is unavailable. Changes only when image content changes. |
| `artworkSource` | string | Artwork source such as `music`, `mediaremote`, `smtc`, or `itunes`. |
| `artworkError` | string | Last artwork retrieval error. Empty when artwork was found or no lookup was attempted. |
| `artworkPending` | boolean | Artwork lookup is pending. The overlay retains its visible cover while the lookup runs, avoiding placeholder flashes between tracks sharing artwork; after a track change it falls back to the placeholder if the lookup is still pending after 2.5 seconds. Missing means false for compatibility. |
| `updatedAt` | number | Unix timestamp written by the backend. |
| `error` | string | Provider or metadata error. Empty when the provider has no diagnostic to report. |

## Provider Notes

- On macOS, `auto` uses `media-control` when it is installed and its self-test (`media-control test`) passes, otherwise Music.app through `osascript` / JXA. `--provider macos` always selects Music.app; `--provider macos-media` requires the helper.
- System media follows macOS's active Now Playing app, including YouTube when the browser publishes metadata. One `media-control stream --micros --no-diff --no-artwork` process supplies full metadata snapshots. A monotonic clock advances position from the native timestamp at the reported playback rate; snapshots replace prior state on seek, pause, app switch or stop. Stream errors clear playback instead of retaining stale state, and the stream is restarted automatically: after 1 second, doubling up to 30 seconds while it keeps failing. Event kinds the backend does not know are ignored. The process is stopped on backend exit.
- System artwork is read separately with `media-control get --micros`, decoded from base64 and checked against the requested app, track ID and metadata. It uses the existing single-worker publication and cache. Stream events trigger a cover refresh (at most once per second), and a five-second periodic check catches image-only changes whose events were suppressed by the metadata-only stream. This replaces placeholders or late thumbnails without waiting for the next track. Browser and other non-Music app metadata is never sent to the iTunes fallback. `--once` and `--diagnose-artwork` use a one-shot native query to avoid the stream's empty startup event.
- Windows uses the OS media session API (SMTC) through the optional `winsdk` dependency.
- Demo mode writes sample playback data and does not attempt artwork lookup.
- Artwork is fetched asynchronously; metadata may arrive first with empty artwork fields.
- Native artwork is accepted only when its sampled track matches the requested metadata. A mismatch is retried on the next poll without consuming the network fallback attempt.
- The iTunes fallback has a 5-second total deadline, including search and image download, measured once its worker process is running, and is cancelled when the track changes. A definitive answer (a cover, or no match) ends the fallback for that track; timeouts and other transient failures are retried, up to 3 lookups per track. Native providers retain their own API timeouts.
- On Windows, a track from a different album that still reports the previous cover's exact thumbnail is retried for up to 2 seconds before that thumbnail is accepted, because SMTC can update text before artwork.
- Without Pillow installed, covers are published unmodified at their original size.
- JSON is written before the optional text output. A locked text file is retried on the next poll without delaying JSON through replacement backoff.
- Ordinary static images are at most 640px, preserving color profiles and transparency. JPEGs already within that size retain their original bytes; other static images use lossless PNG. Animated images and 16-bit grayscale PNGs retain their original bytes and dimensions. All use content-based filenames. The cache retains up to 8 recent covers; files temporarily locked by Windows readers are retried for deletion on the next publication.
- Missing metadata or artwork should be reported in `error` or `artworkError`; it should not stop the HTTP server.
