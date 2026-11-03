"""Bridge between service/scraping workers and the TUI event loop.

Provides thread-safe cancellation tokens and event forwarders for downloads and scraping.
"""

from collections.abc import Callable
import threading
from typing import Any

from discoop.attachments import FileJob, Progress as DownloadProgress
from discoop.errors import DiscoopError
from discoop.models import Channel, ChannelMessages, Server
from discoop.service import Cancelled, Events

__all__ = ["CancelToken", "Cancelled", "TuiDownloadProgress", "TuiEvents"]

Emit = Callable[[str, dict[str, Any]], None]


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
    """Bridges attachment download progress into TUI events with cancellation checks.

    `finish` never raises: the downloader calls it from a `finally` block.
    """

    def __init__(self, cancel_token: CancelToken, emit: Emit) -> None:
        super().__init__()
        self.cancel_token = cancel_token
        self.emit = emit

    def start(self, files: int, total_bytes: int) -> None:
        self.cancel_token.check()
        self.emit("dl_start", {"files": files, "total_bytes": total_bytes})

    def file(self, number: int, total: int, job: FileJob) -> None:
        self.cancel_token.check()
        self.emit("dl_file", {"number": number, "total": total, "job": job})

    def advance(self, size: int) -> None:
        self.cancel_token.check()
        self.emit("dl_advance", {"size": size})

    def finish(self) -> None:
        self.emit("dl_finish", {})

    def note(self, text: str) -> None:
        self.emit("note", {"text": text})


class TuiEvents(Events):
    """Dispatches service events to the TUI listener; progress callbacks raise Cancelled once cancelled.

    Cancelling is safe at every check: a zip is built in a staging folder and moved into place only when complete,
    and a folder keeps `"complete": false` in its manifest until the export has finished.
    """

    def __init__(self, cancel_token: CancelToken, emit: Emit) -> None:
        super().__init__(TuiDownloadProgress(cancel_token, emit))
        self.cancel_token = cancel_token
        self.emit = emit

    def channel_start(self, index: int, total: int, server: Server, channel: Channel) -> None:
        self.cancel_token.check()
        self.emit("channel_start", {"index": index, "total": total, "server": server, "channel": channel})

    def page(self, kept: int, oldest_id: int) -> None:
        self.cancel_token.check()
        self.emit("page", {"count": kept, "oldest_id": oldest_id})

    def pause(self, seconds: float, reason: str) -> None:
        self.cancel_token.check()
        self.emit("pause", {"seconds": seconds, "reason": reason})

    def channel_done(self, result: ChannelMessages) -> None:
        self.emit("channel_done", {"result": result})

    def skipped(self, error: DiscoopError) -> None:
        self.emit("skipped", {"error": error, "reason": error.message})

    def warning(self, text: str) -> None:
        self.emit("warning", {"message": text})

    def note(self, text: str) -> None:
        self.emit("note", {"text": text})
