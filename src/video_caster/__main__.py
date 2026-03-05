import logging
import shutil
import sys
from pathlib import Path

from video_caster.config import CONFIG_DIR

LOG_PATH = CONFIG_DIR / "debug.log"

OLD_CONFIG_DIR = Path.home() / ".config" / "video-caster"


def _migrate_old_config() -> None:
    """Move config from ~/.config/video-caster to the platform-standard location."""
    if OLD_CONFIG_DIR.is_dir() and not CONFIG_DIR.exists():
        CONFIG_DIR.parent.mkdir(parents=True, exist_ok=True)
        OLD_CONFIG_DIR.rename(CONFIG_DIR)


def main():
    for tool in ("ffmpeg", "ffprobe"):
        if not shutil.which(tool):
            print(f"Error: {tool} not found on PATH. Please install FFmpeg.")
            sys.exit(1)

    _migrate_old_config()
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        filename=str(LOG_PATH),
        level=logging.DEBUG,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
        filemode="w",
    )

    from video_caster.config import ensure_default_config
    from video_caster.app import VideoCasterApp

    config = ensure_default_config()
    app = VideoCasterApp(config=config)
    app.run()


if __name__ == "__main__":
    main()
