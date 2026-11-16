# Video Caster

Cast local video files to Chromecast, Apple TV and DLNA devices on your network. A background
service (the **core**) owns all casting state and serves a phone web app over Tailscale: pick an
episode on your phone, pick a TV, and use the phone as the remote.

![Python](https://img.shields.io/badge/python-3.10+-blue)
![macOS](https://img.shields.io/badge/platform-macOS-lightgrey)

## Features

- **Device discovery**: finds Chromecast, Apple TV and DLNA renderers on the LAN.
- **Library**: Continue Watching, Shows, Movies and Newly Added shelves built from your watch
  folders, with a page per show.
- **Episodes**: season and episode detection from file names, one episode order for Next and
  Continue Watching (crossing into the next season), and watched state per episode.
- **Remote**: play and pause, seek, volume, Stop and Next episode from the phone. Resume picks
  up where you left off.
- **Streaming**: plays the file directly when the TV supports it. Otherwise it remuxes or
  transcodes with FFmpeg, as a pipe or as HLS, depending on what the device can play.
- **Watch history**: SQLite, shared by everyone who uses the core.

## Prerequisites

- macOS (primary target), Python 3.10+
- [FFmpeg](https://ffmpeg.org/) and `ffprobe` on the launch agent's PATH
- [Tailscale](https://tailscale.com/), for phones to reach the core

## Install

```bash
git clone https://github.com/cbonitz8/video-caster.git
cd video-caster
pip install -e .

cp deploy/com.caleb.videocaster.plist ~/Library/LaunchAgents/
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.caleb.videocaster.plist
tailscale serve --bg --https=8443 8485
```

The launch agent runs `python3 -m video_caster.core`, which listens on `127.0.0.1:8485` only.

- **Phone:** open `https://calebs-macbook-pro.tail02eb7f.ts.net:8443` in Safari, then Share → Add
  to Home Screen.
- **Mac:** `http://127.0.0.1:8485`. The Mac can't reach its own tailnet address while the other VPN
  is up.

## Running

```bash
# Restart after code changes
launchctl kickstart -k gui/$(id -u)/com.caleb.videocaster

# Logs
tail -f ~/Library/Logs/video-caster-core.log

# Run by hand instead (stop the launch agent first, or both will drive the same TV)
video-caster-core --port 8485
```

Local-only actions (casting a file outside the watch folders, changing settings) need
`Authorization: Bearer <token>`. The core writes a fresh token on every start to
`~/Library/Application Support/video-caster/core-token`.

## Configuration

`~/Library/Application Support/video-caster/config.toml`:

| Key | Default | Meaning |
|---|---|---|
| `watch_folders` | `["~/Movies"]` | Folders scanned for videos. An empty list is kept as empty. |
| `recently_added_limit` | `20` | Size of the Newly Added shelf. |
| `history_db_path` | `<config dir>/history.db` | SQLite watch history. |

Change settings with `PUT /api/settings` (local token required). The core writes the file
atomically with `tomli_w`. AirPlay pairing credentials live next to it in `credentials.json`.

## Architecture

```
src/video_caster/
├── core/           # The service: engine (all state), HTTP + WebSocket API, auth, static/ phone app
├── casting/        # CastSession adapters (Chromecast, AirPlay, DLNA), stream plans, orchestrator
├── discovery/      # Device descriptors and the LAN scan
├── server/         # aiohttp media server: Range requests, transcoded pipes, HLS
├── transcoding/    # ffprobe, FFmpeg pipe, HlsSession (segment grid and far seeks)
├── storage/        # Watch history (SQLite), episode detection, folder scanning
├── catalogue.py    # Show identity, episode order, watched state
├── library.py      # Library shelves
└── config.py       # TOML config
```

- The engine owns all state. The API talks only to the engine.
- Each adapter turns its library's errors into `TimeoutError` (HTTP 504) or `DeviceRequestFailed`
  (HTTP 502). Any other error is a bug and stays a 500.
- `choose_plan(probe, capabilities)` picks Direct, Pipe or HLS for each file and device type.

## Tests

```bash
pip install -e ".[dev]"
python3 -m pytest -q
node --test tests/web/*.test.mjs
```
