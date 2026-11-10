"""A minimal Chrome DevTools Protocol (CDP) client: one WebSocket, JSON commands, flat sessions.

It connects to the browser endpoint (`/devtools/browser/<id>`) WITHOUT an Origin header: Chrome refuses a foreign
Origin unless it is launched with `--remote-allow-origins`, and a missing Origin is accepted
(docs/analyses/browser-login.md).

Nothing here logs or prints a command, its parameters, a result or an event: they can carry the Discord token.
"""

import asyncio
import json
import logging
from dataclasses import dataclass, field
from typing import Any

from websockets.asyncio.client import ClientConnection, connect
from websockets.exceptions import ConnectionClosed

from discoop.browser_login._log import logger

MAX_MESSAGE_BYTES = 64 * 1024 * 1024  # a localStorage listing of a busy site can be several megabytes
CLOSE_TIMEOUT = 2.0

# websockets logs every frame at DEBUG, and a frame can hold a token: give it a logger that goes nowhere.
_wire_logger = logging.getLogger("discoop.browser_login.wire")
_wire_logger.setLevel(logging.WARNING)
_wire_logger.propagate = False
_wire_logger.addHandler(logging.NullHandler())

_LOST = object()  # queue marker: the connection is gone


class CdpError(Exception):
    """The browser answered a command with an error response."""

    def __init__(self, method: str, code: int | None, message: str | None = None) -> None:
        super().__init__(f"{method} failed (code {code})")
        self.method = method
        self.code = code
        self.message = message  # the browser's own text; for tests, never logged or shown


class CdpTimeout(Exception):
    """The browser did not answer a command in time."""

    def __init__(self, method: str) -> None:
        super().__init__(f"{method} timed out")
        self.method = method


class CdpConnectionLost(Exception):
    """The WebSocket is closed: the browser exited or was closed."""

    def __init__(self) -> None:
        super().__init__("the DevTools connection is closed")


@dataclass(frozen=True)
class CdpEvent:
    """A message from the browser that answers no command. The parameters stay out of `repr`: they may hold secrets."""

    method: str
    params: dict[str, Any] = field(repr=False)
    session_id: str | None = None


class CdpClient:
    """Send commands and receive events over one DevTools WebSocket. Create it with `CdpClient.connect`."""

    def __init__(self, ws: ClientConnection) -> None:
        self._ws = ws
        self._next_id = 0
        self._pending: dict[int, asyncio.Future[dict[str, Any]]] = {}
        self._events: asyncio.Queue[Any] = asyncio.Queue()
        self._lost = asyncio.Event()
        self._reader = asyncio.get_running_loop().create_task(self._read(), name="discoop-cdp-reader")

    @classmethod
    async def connect(cls, url: str, *, open_timeout: float = 5.0) -> "CdpClient":
        """Open the WebSocket (no Origin, no proxy, no keepalive pings, no compression) and start reading."""
        ws = await connect(
            url,
            origin=None,
            user_agent_header=None,
            compression=None,
            proxy=None,
            ping_interval=None,
            open_timeout=open_timeout,
            close_timeout=CLOSE_TIMEOUT,
            max_size=MAX_MESSAGE_BYTES,
            logger=_wire_logger,
        )
        return cls(ws)

    @property
    def lost(self) -> bool:
        """True once the connection is gone (closed by the browser or by `close`)."""
        return self._lost.is_set()

    async def wait_lost(self, timeout: float) -> bool:
        """Wait until the connection is gone. True if it is, False if `timeout` seconds passed first."""
        try:
            await asyncio.wait_for(self._lost.wait(), timeout)
        except TimeoutError:
            return False
        return True

    async def send(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        *,
        session_id: str | None = None,
        timeout: float = 10.0,
    ) -> dict[str, Any]:
        """Run one command and return its `result` object.

        Raises CdpError (error response), CdpTimeout, or CdpConnectionLost.
        """
        if self.lost:
            raise CdpConnectionLost()
        self._next_id += 1
        message_id = self._next_id
        message: dict[str, Any] = {"id": message_id, "method": method}
        if params:
            message["params"] = params
        if session_id is not None:
            message["sessionId"] = session_id
        future: asyncio.Future[dict[str, Any]] = asyncio.get_running_loop().create_future()
        self._pending[message_id] = future
        try:
            try:
                await self._ws.send(json.dumps(message))
                response = await asyncio.wait_for(future, timeout)
            except ConnectionClosed as e:
                raise CdpConnectionLost() from e
            except TimeoutError as e:
                raise CdpTimeout(method) from e
        finally:
            self._pending.pop(message_id, None)
        error = response.get("error")
        if isinstance(error, dict):
            code, text = error.get("code"), error.get("message")
            raise CdpError(method, code if isinstance(code, int) else None, text if isinstance(text, str) else None)
        result = response.get("result")
        return result if isinstance(result, dict) else {}

    async def next_event(self, timeout: float | None = None) -> CdpEvent | None:
        """The next event, or None if none arrives within `timeout`. Raises CdpConnectionLost once the queue is drained
        and the browser is gone."""
        if timeout is not None and timeout <= 0:
            return self.pending_event()
        try:
            item = await asyncio.wait_for(self._events.get(), timeout)
        except TimeoutError:
            return None
        return self._unwrap(item)

    def pending_event(self) -> CdpEvent | None:
        """An event that is already queued, or None. Never waits. Raises CdpConnectionLost like `next_event`."""
        try:
            item = self._events.get_nowait()
        except asyncio.QueueEmpty:
            return None
        return self._unwrap(item)

    async def close(self) -> None:
        """Close the WebSocket and stop the reader. Safe to call more than once."""
        try:
            await self._ws.close()
        except Exception:  # noqa: BLE001 - closing is best effort
            pass
        self._reader.cancel()

    def abort(self) -> None:
        """Drop the connection at once, without the closing handshake. For a cleanup that must not wait."""
        try:
            self._ws.transport.abort()
        except Exception:  # noqa: BLE001 - best effort (the event loop may already be closed at interpreter exit)
            pass
        try:
            self._reader.cancel()
        except Exception:  # noqa: BLE001
            pass

    def _unwrap(self, item: Any) -> CdpEvent:
        if item is _LOST:
            self._events.put_nowait(_LOST)  # keep reporting the loss to later callers
            raise CdpConnectionLost()
        return item

    async def _read(self) -> None:
        try:
            async for raw in self._ws:
                self._dispatch(raw)
        except ConnectionClosed:
            pass
        except Exception as e:  # noqa: BLE001 - an odd frame must not leave callers waiting forever
            logger.debug("cdp reader stopped error=%s", type(e).__name__)
        finally:
            self._lost.set()
            for future in self._pending.values():
                if not future.done():
                    future.set_exception(CdpConnectionLost())
            self._events.put_nowait(_LOST)

    def _dispatch(self, raw: str | bytes) -> None:
        try:
            message = json.loads(raw)
        except ValueError:
            return
        if not isinstance(message, dict):
            return
        message_id = message.get("id")
        if isinstance(message_id, int):
            future = self._pending.get(message_id)
            if future is not None and not future.done():
                future.set_result(message)
            return
        method = message.get("method")
        if isinstance(method, str):
            params = message.get("params")
            session_id = message.get("sessionId")
            self._events.put_nowait(
                CdpEvent(
                    method,
                    params if isinstance(params, dict) else {},
                    session_id if isinstance(session_id, str) else None,
                )
            )
