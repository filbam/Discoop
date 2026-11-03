"""Bridge between service/scraping workers and the TUI event loop.

Provides thread-safe cancellation tokens and event forwarders for downloads and scraping.
"""

from collections.abc import Callable
import threading
from typing import Any

from discoop.attachments import Progress as DownloadProgress

try:
    from discoop.service import Cancelled, Events  # type: ignore[import-untyped]
except (ImportError, AttributeError):

    class Cancelled(Exception):  # type: ignore[no-redef]
        """Raised when an operation is cancelled by the user."""

    class Events:  # type: ignore[no-redef]
        """Base events interface when service.py is not yet loaded."""

        def __init__(self, downloads: DownloadProgress | None = None) -> None:
            self.downloads: DownloadProgress = downloads or DownloadProgress()


class CancelToken:
    """Thread-safe cancellation token using threading.Event."""

    def __init__(self) -> None:
        self._event = threading.Event()

    def cancel(self) -> None:
        """Signal cancellation."""
        self._event.set()

    @property
    def is_cancelled(self) -> bool:
        """True if cancellation has been signalled."""
        return self._event.is_set()

    def check(self) -> None:
        """Raise Cancelled if cancellation has been requested."""
        if self._event.is_set():
            raise Cancelled("Stopped by user.")

    def sleep(self, seconds: float) -> None:
        """Wait up to `seconds`, waking immediately and raising Cancelled if cancelled."""
        if self._event.wait(timeout=max(0.0, seconds)):
            raise Cancelled("Stopped by user.")


class TuiDownloadProgress(DownloadProgress):
    """Bridges attachment download progress into TUI events with cancellation checks."""

    def __init__(
        self, cancel_token: CancelToken, emit: Callable[[str, dict[str, Any]], None]
    ) -> None:
        self.cancel_token = cancel_token
        self.emit = emit

    def start(self, files: int, total_bytes: int) -> None:
        self.cancel_token.check()
        self.emit("dl_start", {"files": files, "total_bytes": total_bytes})

    def file(self, number: int, total: int, job: Any) -> None:
        self.cancel_token.check()
        self.emit("dl_file", {"number": number, "total": total, "job": job})

    def advance(self, size: int) -> None:
        self.cancel_token.check()
        self.emit("dl_advance", {"size": size})

    def finish(self) -> None:
        self.cancel_token.check()
        self.emit("dl_finish", {})

    def note(self, text: str) -> None:
        self.cancel_token.check()
        self.emit("note", {"text": text})


class TuiEvents(Events):
    """Dispatches service and scraping events to the TUI event listener."""

    def __init__(
        self, cancel_token: CancelToken, emit: Callable[[str, dict[str, Any]], None]
    ) -> None:
        self.cancel_token = cancel_token
        self.emit = emit
        self.downloads = TuiDownloadProgress(cancel_token, emit)

    def channel_start(self, *args: Any, **kwargs: Any) -> None:
        self.cancel_token.check()
        payload = dict(kwargs)
        if len(args) >= 4:
            payload.setdefault("index", args[0])
            payload.setdefault("total", args[1])
            payload.setdefault("server", args[2])
            payload.setdefault("channel", args[3])
        elif len(args) == 2:
            payload.setdefault("server", args[0])
            payload.setdefault("channel", args[1])
        elif len(args) == 1:
            if isinstance(args[0], dict):
                payload = {**args[0], **kwargs}
            else:
                payload.setdefault("channel", args[0])
        self.emit("channel_start", payload)

    def page(self, *args: Any, **kwargs: Any) -> None:
        self.cancel_token.check()
        payload = dict(kwargs)
        if len(args) >= 2:
            payload.setdefault("count", args[0])
            payload.setdefault("cursor", args[1])
        elif len(args) == 1:
            if isinstance(args[0], dict):
                payload = {**args[0], **kwargs}
            else:
                payload.setdefault("count", args[0])
        self.emit("page", payload)

    def pause(self, *args: Any, **kwargs: Any) -> None:
        self.cancel_token.check()
        payload = dict(kwargs)
        if len(args) >= 2:
            payload.setdefault("seconds", args[0])
            payload.setdefault("reason", args[1])
        elif len(args) == 1:
            if isinstance(args[0], dict):
                payload = {**args[0], **kwargs}
            else:
                payload.setdefault("seconds", args[0])
        self.emit("pause", payload)

    def channel_done(self, *args: Any, **kwargs: Any) -> None:
        payload = dict(kwargs)
        if len(args) == 1:
            if isinstance(args[0], dict):
                payload = {**args[0], **kwargs}
            else:
                payload.setdefault("channel", args[0])
        elif len(args) >= 2:
            payload.setdefault("server", args[0])
            payload.setdefault("channel", args[1])
        self.emit("channel_done", payload)

    def skipped(self, *args: Any, **kwargs: Any) -> None:
        payload = dict(kwargs)
        if len(args) == 1:
            if isinstance(args[0], dict):
                payload = {**args[0], **kwargs}
            else:
                payload.setdefault("reason", args[0])
        elif len(args) >= 2:
            payload.setdefault("channel", args[0])
            payload.setdefault("reason", args[1])
        self.emit("skipped", payload)

    def warning(self, *args: Any, **kwargs: Any) -> None:
        payload = dict(kwargs)
        if len(args) == 1:
            if isinstance(args[0], dict):
                payload = {**args[0], **kwargs}
            else:
                payload.setdefault("message", args[0])
        self.emit("warning", payload)

    def note(self, *args: Any, **kwargs: Any) -> None:
        payload = dict(kwargs)
        if len(args) == 1:
            if isinstance(args[0], dict):
                payload = {**args[0], **kwargs}
            else:
                payload.setdefault("text", args[0])
        self.emit("note", payload)
