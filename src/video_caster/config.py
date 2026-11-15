"""TOML configuration for Video Caster."""

from __future__ import annotations

import os
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

import tomli_w
from platformdirs import user_config_dir

if sys.version_info >= (3, 11):
    import tomllib
else:
    try:
        import tomllib
    except ModuleNotFoundError:
        import tomli as tomllib  # type: ignore[no-redef]

CONFIG_DIR = Path(user_config_dir("video-caster"))
CONFIG_PATH = CONFIG_DIR / "config.toml"

DEFAULT_WATCH_FOLDERS = [Path.home() / "Movies"]
DEFAULT_RECENTLY_ADDED_LIMIT = 20


@dataclass
class Config:
    watch_folders: list[Path] = field(default_factory=lambda: list(DEFAULT_WATCH_FOLDERS))
    recently_added_limit: int = DEFAULT_RECENTLY_ADDED_LIMIT
    history_db_path: Path = field(default_factory=lambda: CONFIG_DIR / "history.db")


def load_config(path: Path = CONFIG_PATH) -> Config:
    """Load config from TOML file, falling back to defaults."""
    if not path.exists():
        return Config()

    with open(path, "rb") as f:
        data = tomllib.load(f)

    if "watch_folders" in data:
        watch_folders = [Path(p).expanduser() for p in data["watch_folders"]]
    else:
        watch_folders = list(DEFAULT_WATCH_FOLDERS)

    return Config(
        watch_folders=watch_folders,
        recently_added_limit=data.get("recently_added_limit", DEFAULT_RECENTLY_ADDED_LIMIT),
        history_db_path=Path(data.get("history_db_path", str(CONFIG_DIR / "history.db"))),
    )


def save_config(config: Config, path: Path = CONFIG_PATH) -> None:
    """Write config to TOML file, replacing the old file only once the new one is whole."""
    path.parent.mkdir(parents=True, exist_ok=True)
    text = tomli_w.dumps({
        "recently_added_limit": config.recently_added_limit,
        "history_db_path": str(config.history_db_path),
        "watch_folders": [str(p) for p in config.watch_folders],
    })
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".config-", suffix=".toml")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(text)
        os.replace(tmp, path)
    except BaseException:
        os.unlink(tmp)
        raise


def ensure_default_config() -> Config:
    """Create default config file if none exists, then load and return it."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    if not CONFIG_PATH.exists():
        save_config(Config())
    return load_config()
