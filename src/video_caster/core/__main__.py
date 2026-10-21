"""Entry point: python -m video_caster.core (launch agent com.caleb.videocaster)."""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import shutil
import signal
import sys
from pathlib import Path

from aiohttp import web

from video_caster.casting.orchestrator import CastOrchestrator
from video_caster.config import CONFIG_DIR, Config, ensure_default_config
from video_caster.core.api import create_app
from video_caster.core.auth import new_token, save_token
from video_caster.core.engine import Engine
from video_caster.posters import POSTERS_DIR
from video_caster.storage.history import HistoryStore

HOST = "127.0.0.1"
DEFAULT_PORT = 8485
TOKEN_PATH = CONFIG_DIR / "core-token"
TAILNET_HOST = "calebs-macbook-pro.tail02eb7f.ts.net"

log = logging.getLogger("video_caster.core")


def missing_tools() -> list[str]:
    return [tool for tool in ("ffmpeg", "ffprobe") if shutil.which(tool) is None]


async def serve(port: int, *, config: Config, token_path: Path) -> int:
    POSTERS_DIR.mkdir(parents=True, exist_ok=True)
    engine = Engine(config, CastOrchestrator(), HistoryStore(config.history_db_path))
    token = new_token()
    runner = web.AppRunner(create_app(engine, token, extra_hosts=(TAILNET_HOST,)))
    await runner.setup()
    try:
        await web.TCPSite(runner, HOST, port).start()
    except OSError as e:
        log.error("Cannot listen on %s:%d: %s", HOST, port, e)
        await runner.cleanup()
        engine.history.close()
        return 1
    # Only the instance that owns the port may publish its token; a second instance
    # that loses the bind must not lock the running one's local clients out.
    save_token(token_path, token)

    await engine.start()
    log.info("Core listening on http://%s:%d", HOST, port)

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)
    await stop.wait()

    log.info("Shutting down")
    await engine.shutdown()
    await runner.cleanup()
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(prog="video-caster-core")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    args = parser.parse_args()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    missing = missing_tools()
    if missing:
        log.error(
            "Not found on PATH: %s. Install FFmpeg, and check the PATH in the launch agent plist "
            "(current PATH: %s).",
            ", ".join(missing),
            os.environ.get("PATH"),
        )
        sys.exit(1)
    sys.exit(asyncio.run(serve(args.port, config=ensure_default_config(), token_path=TOKEN_PATH)))


if __name__ == "__main__":
    main()
