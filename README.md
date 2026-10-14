# Video Caster

Cast local video files to Chromecast, Apple TV, and DLNA devices on your network — all from a terminal UI built with [Textual](https://textual.textualize.io/).

![Python](https://img.shields.io/badge/python-3.10+-blue)
![macOS](https://img.shields.io/badge/platform-macOS-lightgrey)

## Features

- **Device discovery** — automatically finds Chromecast, Apple TV, and DLNA devices on your network
- **Watch folders** — configure folders to scan for video files
- **Home screen** — Continue Watching, Up Next, and Newly Added sections
- **Playback controls** — play, pause, seek, and volume from the TUI
- **Web remote** — control playback from your phone via a QR code link
- **Transcoding** — automatic FFmpeg transcoding when a device doesn't support the source format
- **Watch history** — tracks progress per file with SQLite, supports resume and episode detection

## Prerequisites

- Python 3.10+
- [FFmpeg](https://ffmpeg.org/) and `ffprobe` on your PATH

## Installation

```bash
git clone https://github.com/cbonitz8/video-caster.git
cd video-caster
pip install -e .
```

## Usage

```bash
video-caster
# or
python -m video_caster
```

### Layout

The app uses a split-panel layout:

- **Left panel** — Home tab (Continue Watching, Up Next, Newly Added) and Browse tab (watch folder trees)
- **Right panel** — Device list (top) and playback controls (bottom)

## Configuration

Config is stored at `~/.config/video-caster/config.toml` and includes watch folders, display limits, and the history database path.

Watch history is persisted in a SQLite database at `~/.config/video-caster/history.db`.

## Architecture

```
src/video_caster/
├── app.py              # Main Textual app and screen layout
├── config.py           # TOML config management
├── casting/            # Cast handlers (Chromecast, AirPlay, DLNA) + orchestrator
├── discovery/          # Network device scanning
├── server/             # Media server (aiohttp) with Range support + web remote
├── storage/            # Watch history (SQLite), episode detection, folder scanning
├── transcoding/        # FFprobe, FFmpeg transcoding, format compatibility
├── ui/                 # Textual widgets (home, device list, playback controls, etc.)
└── utils/              # Network helpers
```

## Requirements

- macOS (primary target)
- Python 3.10+
- FFmpeg / ffprobe

## Core service (phone and Mac app backend)

A background service that owns casting state and serves the API the phone web app and the
Mac app use. It listens on `127.0.0.1:8485` only. The terminal app (`video-caster`) is
separate: don't run both at once, because both would drive the same Chromecast.

Install (once):

```bash
cp deploy/com.caleb.videocaster.plist ~/Library/LaunchAgents/
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.caleb.videocaster.plist
tailscale serve --bg --https=8443 8485
```

- Phones (tailnet): `https://calebs-macbook-pro.tail02eb7f.ts.net:8443`
  Open it in Safari and use Share → Add to Home Screen for the phone app (Library + Remote).
- On the Mac: `http://127.0.0.1:8485` (the Mac can't reach its own tailnet address while the other VPN is up)
- Logs: `~/Library/Logs/video-caster-core.log`
- Restart after code changes: `launchctl kickstart -k gui/$(id -u)/com.caleb.videocaster`
- Local-only actions (open any file, change settings) need `Authorization: Bearer <token>`, where the token is in `~/Library/Application Support/video-caster/core-token`.

Tests: `python3 -m pip install -e ".[dev]" && python3 -m pytest`, and for the phone app's JS: `node --test tests/web/*.test.mjs`
