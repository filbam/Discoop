"""Diagnostic logging for Discoop: optional, safe, structured stderr/file logging."""

import logging
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path

from discoop import __version__

LOGGER_NAME = "discoop"
_active_handlers: list[logging.Handler] = []
_saved_levels: dict[str, int] = {}
_saved_propagate: bool = True
_saved_discoop_level: int = logging.NOTSET


class DiscoopFormatter(logging.Formatter):
    """Formats log records as ISO timestamp, level, short logger name, and message."""

    def format(self, record: logging.LogRecord) -> str:
        dt = datetime.fromtimestamp(record.created, tz=timezone.utc)
        ts = dt.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
        name = record.name
        if name.startswith(f"{LOGGER_NAME}."):
            short_name = name[len(LOGGER_NAME) + 1 :]
        elif name == LOGGER_NAME:
            short_name = LOGGER_NAME
        else:
            short_name = name
        return f"{ts} {record.levelname} {short_name} {record.getMessage()}"


def setup_logging(debug: bool, log_file: Path | None) -> None:
    """Configure diagnostic logging to stderr and/or a file.

    Disabled by default when debug=False and log_file is None.
    Idempotent: tears down any previous configuration first.
    """
    global _saved_propagate, _saved_discoop_level

    # Always teardown any existing configuration first to avoid duplicate handlers
    teardown_logging()

    if not debug and log_file is None:
        return

    discoop_logger = logging.getLogger(LOGGER_NAME)
    _saved_discoop_level = discoop_logger.level
    _saved_propagate = discoop_logger.propagate

    discoop_logger.setLevel(logging.DEBUG)
    discoop_logger.propagate = False

    # Silence verbose 3rd party loggers to prevent leaking full URLs/headers
    for name in ("httpx", "httpcore", "websockets"):
        logger = logging.getLogger(name)
        _saved_levels[name] = logger.level
        logger.setLevel(logging.WARNING)

    formatter = DiscoopFormatter()

    if debug:
        sh = logging.StreamHandler(sys.stderr)
        sh.setFormatter(formatter)
        discoop_logger.addHandler(sh)
        _active_handlers.append(sh)

    if log_file is not None:
        path = Path(log_file)
        path.parent.mkdir(parents=True, exist_ok=True)
        fh = logging.FileHandler(path, mode="a", encoding="utf-8")
        fh.setFormatter(formatter)
        discoop_logger.addHandler(fh)
        _active_handlers.append(fh)

    # Log header block
    discoop_logger.info(
        "discoop %s (%s %s, Python %s)",
        __version__,
        platform.system(),
        platform.release(),
        platform.python_version(),
    )
    discoop_logger.info("IDs in this log identify private servers and channels. Do not publish it.")


def teardown_logging() -> None:
    """Remove and close all handlers attached by setup_logging and restore previous state."""
    global _saved_propagate, _saved_discoop_level

    discoop_logger = logging.getLogger(LOGGER_NAME)
    for handler in list(_active_handlers):
        discoop_logger.removeHandler(handler)
        handler.close()
    _active_handlers.clear()

    discoop_logger.propagate = _saved_propagate
    discoop_logger.setLevel(_saved_discoop_level)

    for name, level in _saved_levels.items():
        logging.getLogger(name).setLevel(level)
    _saved_levels.clear()
