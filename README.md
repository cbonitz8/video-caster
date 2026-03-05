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
