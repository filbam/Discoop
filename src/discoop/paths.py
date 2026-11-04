"""Per-OS locations for discoop's data and config (via platformdirs)."""

from pathlib import Path

from platformdirs import PlatformDirs, user_documents_dir

_dirs = PlatformDirs("discoop", appauthor=False)


def data_dir() -> Path:
    """Windows %LOCALAPPDATA%\\discoop, macOS ~/Library/Application Support/discoop, Linux ~/.local/share/discoop."""
    return Path(_dirs.user_data_dir)


def config_dir() -> Path:
    """Same as data_dir() on Windows and macOS, ~/.config/discoop on Linux."""
    return Path(_dirs.user_config_dir)


def documents_dir() -> Path:
    """The user's Documents folder: Windows (also when moved), macOS ~/Documents, Linux XDG or ~/Documents."""
    return Path(user_documents_dir())


def default_export_dir() -> Path:
    """Where the TUI saves exports without an export-dir in the config: `discoop` in Documents. Not created here."""
    return documents_dir() / "discoop"
