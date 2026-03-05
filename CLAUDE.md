# Video Caster

## What is this?
A Python TUI app (Textual) for casting local video files to Chromecast, Apple TV, and DLNA devices on the local network.

## Running
```bash
# From project root
python3 -m video_caster

# Or if installed
video-caster
```

## Prerequisites
- Python 3.10+ (dev machine uses 3.14)
- FFmpeg and ffprobe on PATH
- Dependencies: `pip install -e .`

## Project Structure
```
src/video_caster/
  __main__.py          # Entry point, FFmpeg check, logging setup
  app.py               # Main Textual App, screen layout, keybindings
  app.tcss             # Textual CSS styles
  config.py            # TOML config for watch folders, recently-added limits, history DB path
  ui/
    branding.py        # ASCII art logo header widget for the left panel
    home.py            # Home tab: Continue Watching, Up Next, Newly Added lists
    file_browser.py    # VideoBrowser (DirectoryTree filtered to video files)
    watch_folders.py   # Watch folder browser — collapsible DirectoryTree per folder
    device_list.py     # DeviceList widget + DeviceSelected message
    playback_controls.py  # Progress bar, time display, volume
    settings_screen.py # Modal settings screen for managing watch folders
  casting/
    base.py            # CastHandler ABC + PlaybackStatus dataclass
    orchestrator.py    # CastOrchestrator — probes, transcodes, serves, casts
    chromecast.py      # Chromecast handler (pychromecast)
    airplay.py         # AirPlay handler (pyatv)
    dlna.py            # DLNA handler (async-upnp-client)
  discovery/
    device.py          # Device dataclass + DeviceType enum
    scanner.py         # scan_all() — discovers Chromecast, Apple TV, DLNA
  server/
    media_server.py    # aiohttp server with Range support + stream serving
  storage/
    episode.py         # Episode detection and next-episode suggestion
    history.py         # SQLite watch history and session persistence
    scanner.py         # Watch folder scanner — finds videos sorted by mtime
  transcoding/
    formats.py         # Codec tables, VIDEO_EXTENSIONS, needs_transcode()
    probe.py           # FFprobe wrapper
    transcoder.py      # FFmpeg transcoding
  utils/
    network.py         # get_local_ip helpers
```

## Config
- Config file: `~/.config/video-caster/config.toml` (watch folders, recently-added limits, history DB path)
- Watch history: SQLite database (default `~/.config/video-caster/history.db`)
- Logs: `~/.config/video-caster/debug.log`

## Architecture Notes
- The app uses a 2x2 grid layout: file browser (left, full height), device list (top-right), playback controls (bottom-right)
- The left panel has a Home tab (Continue Watching, Up Next, Newly Added) and a Browse tab (watch folder trees)
- CastOrchestrator is the central coordinator: it probes files, decides if transcoding is needed, starts the media server, and sends play commands
- All cast handlers implement the CastHandler ABC with connect/disconnect/play/pause/resume/stop/seek/set_volume/get_status
- The media server (aiohttp) serves files directly or as transcoded streams, with HTTP Range support for seeking
- Device discovery runs Chromecast, Apple TV, and DLNA scans concurrently
- Watch history is stored in SQLite; episode detection parses filenames for series/season/episode info
