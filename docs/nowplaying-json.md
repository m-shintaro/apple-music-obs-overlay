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
  "artworkFile": "cover_direct.jpg",
  "artworkVersion": "Song Title|Artist Name|Album Name|214",
  "artworkSource": "music",
  "artworkError": "",
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
| `position` | number | Current playback position in seconds. |
| `duration` | number | Track duration in seconds. |
| `positionText` | string | Display-ready `M:SS` text for `position`. |
| `durationText` | string | Display-ready `M:SS` text for `duration`. |
| `progress` | number | `position / duration`, clamped from `0` to `1`. |
| `artworkFile` | string | Artwork filename inside `runtime/`, or empty when unavailable. |
| `artworkVersion` | string | Cache-busting track key used by the overlay when loading artwork. |
| `artworkSource` | string | Artwork source such as `music`, `smtc`, or `itunes`. |
| `artworkError` | string | Last artwork retrieval error. Empty when artwork was found or no lookup was attempted. |
| `updatedAt` | number | Unix timestamp written by the backend. |
| `error` | string | Provider or metadata error. Empty when the provider has no diagnostic to report. |

## Provider Notes

- macOS uses Music.app through `osascript` / JXA and can directly export Music.app artwork.
- Windows uses the OS media session API (SMTC) through the optional `winsdk` dependency.
- Demo mode writes sample playback data and does not attempt artwork lookup.
- Missing metadata or artwork should be reported in `error` or `artworkError`; it should not stop the HTTP server.
