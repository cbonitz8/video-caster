"""TOML configuration for Video Caster."""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

if sys.version_info >= (3, 11):
    import tomllib
else:
    try:
        import tomllib
    except ModuleNotFoundError:
        import tomli as tomllib  # type: ignore[no-redef]

CONFIG_DIR = Path.home() / ".config" / "video-caster"
CONFIG_PATH = CONFIG_DIR / "config.toml"

DEFAULT_WATCH_FOLDERS = [Path.home() / "Movies"]
DEFAULT_RECENTLY_ADDED_LIMIT = 20
DEFAULT_RECENTLY_ADDED_DAYS = 30


@dataclass
class Config:
    watch_folders: list[Path] = field(default_factory=lambda: list(DEFAULT_WATCH_FOLDERS))
    recently_added_limit: int = DEFAULT_RECENTLY_ADDED_LIMIT
    recently_added_days: int = DEFAULT_RECENTLY_ADDED_DAYS
    history_db_path: Path = field(default_factory=lambda: CONFIG_DIR / "history.db")
    web_remote_port: int = 8484


def load_config() -> Config:
    """Load config from TOML file, falling back to defaults."""
    if not CONFIG_PATH.exists():
        return Config()

    with open(CONFIG_PATH, "rb") as f:
        data = tomllib.load(f)

    watch_folders = [
        Path(p).expanduser() for p in data.get("watch_folders", [])
    ] or list(DEFAULT_WATCH_FOLDERS)

    return Config(
        watch_folders=watch_folders,
        recently_added_limit=data.get("recently_added_limit", DEFAULT_RECENTLY_ADDED_LIMIT),
        recently_added_days=data.get("recently_added_days", DEFAULT_RECENTLY_ADDED_DAYS),
        history_db_path=Path(data.get("history_db_path", str(CONFIG_DIR / "history.db"))),
        web_remote_port=data.get("web_remote_port", 8484),
    )


def save_config(config: Config) -> None:
    """Write config to TOML file."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    lines = [
        f'# Video Caster configuration\n',
        f'recently_added_limit = {config.recently_added_limit}\n',
        f'recently_added_days = {config.recently_added_days}\n',
        f'history_db_path = "{config.history_db_path}"\n',
        f'web_remote_port = {config.web_remote_port}\n',
        f'\n',
    ]
    # Write watch folders as a TOML array
    folder_entries = ", ".join(f'"{p}"' for p in config.watch_folders)
    lines.append(f'watch_folders = [{folder_entries}]\n')

    with open(CONFIG_PATH, "w") as f:
        f.writelines(lines)


def ensure_default_config() -> Config:
    """Create default config file if none exists, then load and return it."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    if not CONFIG_PATH.exists():
        save_config(Config())
    return load_config()
