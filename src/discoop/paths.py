"""Per-OS locations for discoop's data and config (via platformdirs)."""

from pathlib import Path

from platformdirs import PlatformDirs

_dirs = PlatformDirs("discoop", appauthor=False)


def data_dir() -> Path:
    """Windows %LOCALAPPDATA%\\discoop, macOS ~/Library/Application Support/discoop, Linux ~/.local/share/discoop."""
    return Path(_dirs.user_data_dir)


def config_dir() -> Path:
    """Same as data_dir() on Windows and macOS, ~/.config/discoop on Linux."""
    return Path(_dirs.user_config_dir)
