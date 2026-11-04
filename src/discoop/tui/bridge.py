"""Bridge between service/scraping workers and the TUI event loop.

Provides thread-safe cancellation tokens and event forwarders for downloads and scraping.
"""

from collections.abc import Callable
from pathlib import Path
import threading
import time
from typing import Any

from discoop.attachments import FileJob, Progress as DownloadProgress
from discoop.errors import DiscoopError
from discoop.models import Channel, ChannelMessages, Server
from discoop.progress import eta_seconds, fraction_done, window_start_id
from discoop.service import Cancelled, Events
from discoop.snowflake import Window

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

    Cancelling is safe at every check. An export is written channel by channel into a staging folder next to the
    target (`<target>.partial`) and put in place only when it is complete, so an earlier export is never damaged.
    A cancelled run keeps the channels it had finished there, `run_messages` reports them with `interrupted`,
    and starting the same export again continues from them (`resumed`).
    """

    def __init__(
        self,
        cancel_token: CancelToken,
        emit: Emit,
        *,
        window: Window | None = None,
        last: int | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        super().__init__(TuiDownloadProgress(cancel_token, emit))
        self.cancel_token = cancel_token
        self.emit = emit
        self.window = window
        self.last = last
        self._clock = clock
        self._started_at: float | None = None
        self._start_id: int | None = None
        self._end_id: int | None = None

    def set_window(self, window: Window | None, last: int | None = None) -> None:
        """Update window and last parameters for subsequent channels."""
        self.window = window
        self.last = last

    def channel_start(self, index: int, total: int, server: Server, channel: Channel) -> None:
        self.cancel_token.check()
        self._started_at = self._clock()
        self._start_id = window_start_id(self.window, channel.id, last=self.last) if self.window is not None else None
        self._end_id = self.window.before_id if self.window is not None else None
        self.emit("channel_start", {"index": index, "total": total, "server": server, "channel": channel})

    def page(self, kept: int, oldest_id: int) -> None:
        self.cancel_token.check()
        payload: dict[str, Any] = {"count": kept, "oldest_id": oldest_id}
        if self.window is not None:
            frac = (
                fraction_done(self._start_id, self._end_id, oldest_id)
                if (self._start_id is not None and self._end_id is not None)
                else None
            )
            elapsed = (self._clock() - self._started_at) if self._started_at is not None else 0.0
            eta = eta_seconds(elapsed, frac)
            payload["fraction"] = frac
            payload["eta_seconds"] = eta
        self.emit("page", payload)

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

    def resumed(self, done: int, total: int) -> None:
        self.emit("resumed", {"done": done, "total": total})

    def interrupted(self, saved: int, total: int, path: Path) -> None:
        self.emit("interrupted", {"saved": saved, "total": total, "path": path})
