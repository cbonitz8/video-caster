import logging
import sys
import shutil
from pathlib import Path

LOG_PATH = Path.home() / ".config" / "video-caster" / "debug.log"


def main():
    for tool in ("ffmpeg", "ffprobe"):
        if not shutil.which(tool):
            print(f"Error: {tool} not found on PATH. Please install FFmpeg.")
            sys.exit(1)

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
