"""Fakes for the browser login tests: a local stand-in for a browser's DevTools endpoint (a real WebSocket server),
a fake browser process and a fake `spawn`. No real browser is ever started."""

import asyncio
import json
import logging
import socket
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from http import HTTPStatus
from pathlib import Path
from typing import Any

import pytest
from websockets.asyncio.server import ServerConnection, serve
from websockets.exceptions import ConnectionClosed

from discoop.browser_login import SessionTimings, launch

FAKE_TOKEN = "FAKE-TOKEN-0000.abcdefghijklmnop.0123456789"
OTHER_FAKE_TOKEN = "FAKE-OTHER-TOKEN-1111.zyxwvutsrqponm.9876543210"
ENDPOINT_PATH = "/devtools/browser/fake-endpoint-id"
PAGE_ID = "PAGE-1"
SECOND_PAGE_ID = "PAGE-2"
DISCORD_API = "https://discord.com/api/v9/users/@me"

# The fake server must not log its frames either (they hold the fake token) when a test turns the root logger to DEBUG.
_server_logger = logging.getLogger("fake_cdp.server")
_server_logger.setLevel(logging.WARNING)
_server_logger.propagate = False
_server_logger.addHandler(logging.NullHandler())


@pytest.fixture(autouse=True)
def no_session_left_behind():
    """Every test must end with all browser sessions cleaned up (the module-level registry is empty)."""
    yield
    leftover = list(launch._live_sessions)
    launch._live_sessions.clear()
    assert not leftover, "a BrowserSession was never cleaned up"


@dataclass
class FakeRequest:
    """A Network.requestWillBeSent event the fake emits after Network.enable."""

    url: str
    headers: dict[str, str] = field(default_factory=dict)
    session: str | None = None  # None: the session that enabled the Network domain


def discord_request(token: str, header_name: str = "Authorization") -> FakeRequest:
    return FakeRequest(DISCORD_API, {header_name: token, "Accept": "*/*", "User-Agent": "fake"})


class FakeProcess:
    """Stands in for asyncio.subprocess.Process."""

    def __init__(self, pid: int = 4242, *, ignores_terminate: bool = False) -> None:
        self.pid = pid
        self.returncode: int | None = None
        self.ignores_terminate = ignores_terminate
        self.terminate_calls = 0
        self.kill_calls = 0
        self._exited = asyncio.Event()

    def exit(self, code: int = 0) -> None:
        if self.returncode is None:
            self.returncode = code
            self._exited.set()

    def terminate(self) -> None:
        self.terminate_calls += 1
        if not self.ignores_terminate:
            self.exit(-15)

    def kill(self) -> None:
        self.kill_calls += 1
        self.exit(-9)

    async def wait(self) -> int:
        await self._exited.wait()
        assert self.returncode is not None
        return self.returncode


class FakeCdpBrowser:
    """The browser end of the DevTools Protocol, scripted. Like Chrome, it refuses a connection that carries an Origin
    header and serves only its own endpoint path."""

    def __init__(
        self,
        *,
        storage_token: str | None = None,  # shows up in localStorage ...
        storage_after: int = 0,  # ... after this many answered reads
        raw_storage_value: str | None = None,  # the exact stored text, instead of the JSON encoding of storage_token
        requests: list[FakeRequest] | None = None,  # Network.requestWillBeSent events, emitted after Network.enable
        request_delay: float = 0.02,
        gone_after: int | None = None,  # the page disappears after this many Target.getTargets calls
        empty_polls: tuple[int, ...] = (),  # Target.getTargets call numbers that list no page (a flap)
        second_page: bool = False,  # when the first page is gone, a second one is open
        second_page_from: int | None = None,  # a second page opens (next to the first) at this Target.getTargets call
        page_urls: dict[str, str] | None = None,  # target id -> URL; the default is Discord's login page
        emit_destroyed: bool = False,  # announce the disappearance with Target.targetDestroyed
        drop_after: int | None = None,  # abort the connection once this many commands were received
        reject_security_origin: bool = False,  # a newer browser that wants storageKey
        storage_errors: int = 0,  # the first N storage reads fail ("frame not found")
        errors: dict[str, tuple[int, str]] | None = None,  # method -> error response
        ignore_close: bool = False,  # Browser.close is never answered and does nothing
        hang: tuple[str, ...] = (),  # methods that are never answered
        browser_pid: int = 31337,
    ) -> None:
        self.storage_token = storage_token
        self.storage_after = storage_after
        self.raw_storage_value = raw_storage_value
        self.requests = requests or []
        self.request_delay = request_delay
        self.gone_after = gone_after
        self.empty_polls = empty_polls
        self.second_page = second_page
        self.second_page_from = second_page_from
        self.page_urls = page_urls or {}
        self.emit_destroyed = emit_destroyed
        self.drop_after = drop_after
        self.reject_security_origin = reject_security_origin
        self.storage_errors = storage_errors
        self.errors = errors or {}
        self.ignore_close = ignore_close
        self.hang = hang
        self.browser_pid = browser_pid

        self.port = 0
        self.process: FakeProcess | None = None  # ended by Browser.close
        self.commands: list[tuple[str, str | None]] = []  # (method, sessionId)
        self.origins: list[str | None] = []
        self.paths: list[str] = []
        self.connection_count = 0
        self.get_targets_calls = 0
        self.storage_attempts = 0
        self.storage_reads = 0
        self.storage_shapes: list[str] = []
        self.attached: dict[str, str] = {}  # sessionId -> targetId
        self.close_requested = False
        self.connection_closed = asyncio.Event()
        self._destroyed_sent = False
        self._page_destroyed = False
        self._tasks: set[asyncio.Task] = set()
        self._connections: list[ServerConnection] = []

    @asynccontextmanager
    async def running(self) -> AsyncIterator["FakeCdpBrowser"]:
        async with serve(
            self.handler,
            "127.0.0.1",
            0,
            process_request=self._process_request,
            compression=None,
            logger=_server_logger,
        ) as server:
            self.port = server.sockets[0].getsockname()[1]
            try:
                yield self
            finally:
                for task in self._tasks:
                    task.cancel()

    def commands_named(self, method: str) -> list[str | None]:
        return [session for name, session in self.commands if name == method]

    async def destroy_page(self) -> None:
        """The first page closes right now (and Target.targetDestroyed says so)."""
        self._page_destroyed = True
        await self.emit("Target.targetDestroyed", {"targetId": PAGE_ID})

    async def emit(self, method: str, params: dict[str, Any], session_id: str | None = None) -> None:
        message: dict[str, Any] = {"method": method, "params": params}
        if session_id is not None:
            message["sessionId"] = session_id
        for ws in self._connections:
            try:
                await ws.send(json.dumps(message))
            except ConnectionClosed:
                pass

    # -- the server -------------------------------------------------------------------------------------------

    def _process_request(self, connection: ServerConnection, request: Any):
        self.paths.append(request.path)
        self.origins.append(request.headers.get("Origin"))
        if request.headers.get("Origin") is not None:
            return connection.respond(HTTPStatus.FORBIDDEN, "Rejected an incoming WebSocket connection.\n")
        if request.path != ENDPOINT_PATH:
            return connection.respond(HTTPStatus.NOT_FOUND, "No such endpoint\n")
        return None

    async def handler(self, ws: ServerConnection) -> None:
        self.connection_count += 1
        self._connections.append(ws)
        try:
            async for raw in ws:
                if not await self._handle(ws, json.loads(raw)):
                    break
        except ConnectionClosed:
            pass
        finally:
            self.connection_closed.set()

    async def _reply(self, ws: ServerConnection, message: dict, result: dict | None = None, error: dict | None = None):
        response: dict[str, Any] = {"id": message["id"]}
        if error is not None:
            response["error"] = error
        else:
            response["result"] = result or {}
        if message.get("sessionId"):
            response["sessionId"] = message["sessionId"]
        await ws.send(json.dumps(response))

    async def _handle(self, ws: ServerConnection, message: dict) -> bool:
        method, session_id = message["method"], message.get("sessionId")
        self.commands.append((method, session_id))
        if self.drop_after is not None and len(self.commands) > self.drop_after:
            ws.transport.abort()
            return False
        if method in self.hang:
            return True
        if method in self.errors:
            code, text = self.errors[method]
            await self._reply(ws, message, error={"code": code, "message": text})
            return True
        command = getattr(self, "_cmd_" + method.replace(".", "_"), None)
        if command is None:
            await self._reply(ws, message, error={"code": -32601, "message": f"'{method}' wasn't found"})
            return True
        return await command(ws, message)

    # -- what the pages look like -----------------------------------------------------------------------------

    def _gone(self) -> bool:
        return self._page_destroyed or (self.gone_after is not None and self.get_targets_calls > self.gone_after)

    def _alive_pages(self) -> list[str]:
        gone = self._gone()
        pages = [] if gone else [PAGE_ID]
        opened_later = self.second_page_from is not None and self.get_targets_calls >= self.second_page_from
        if (gone and self.second_page) or opened_later:
            pages.append(SECOND_PAGE_ID)
        return pages

    def _url_of(self, target_id: str) -> str:
        return self.page_urls.get(target_id, "https://discord.com/login")

    def _listed_pages(self) -> list[str]:
        return [] if self.get_targets_calls in self.empty_polls else self._alive_pages()

    def _session_error(self, session_id: str | None) -> dict | None:
        if session_id not in self.attached or self.attached[session_id] not in self._alive_pages():
            return {"code": -32001, "message": "Session with given id not found."}
        return None

    # -- commands ---------------------------------------------------------------------------------------------

    async def _cmd_Target_setDiscoverTargets(self, ws, message) -> bool:
        await self._reply(ws, message)
        return True

    async def _cmd_Target_getTargets(self, ws, message) -> bool:
        self.get_targets_calls += 1
        infos: list[dict[str, Any]] = [
            {"targetId": "WORKER-1", "type": "service_worker", "url": "chrome-extension://fake/sw.js"},
            {"targetId": "UI-1", "type": "browser_ui", "url": "chrome://omnibox-popup.top-chrome/"},
        ]
        infos += [{"targetId": t, "type": "page", "url": self._url_of(t)} for t in self._listed_pages()]
        await self._reply(ws, message, {"targetInfos": infos})
        if self._gone() and self.emit_destroyed and not self._destroyed_sent:
            self._destroyed_sent = True
            await self.emit("Target.targetDestroyed", {"targetId": PAGE_ID})
        return True

    async def _cmd_Target_attachToTarget(self, ws, message) -> bool:
        target_id = message["params"]["targetId"]
        if target_id not in self._alive_pages() or message["params"].get("flatten") is not True:
            await self._reply(ws, message, error={"code": -32602, "message": "No target with given id found"})
            return True
        session = f"SESSION-{target_id}-{len(self.attached) + 1}"
        self.attached[session] = target_id
        await self._reply(ws, message, {"sessionId": session})
        return True

    async def _cmd_DOMStorage_enable(self, ws, message) -> bool:
        error = self._session_error(message.get("sessionId"))
        await self._reply(ws, message, error=error)
        return True

    async def _cmd_Network_enable(self, ws, message) -> bool:
        error = self._session_error(message.get("sessionId"))
        await self._reply(ws, message, error=error)
        if error is None and self.requests:
            task = asyncio.create_task(self._emit_requests(message["sessionId"]))
            self._tasks.add(task)
        return True

    async def _emit_requests(self, session_id: str) -> None:
        await asyncio.sleep(self.request_delay)
        for request in self.requests:
            params = {"requestId": "1", "request": {"url": request.url, "method": "GET", "headers": request.headers}}
            await self.emit("Network.requestWillBeSent", params, request.session or session_id)

    async def _cmd_DOMStorage_getDOMStorageItems(self, ws, message) -> bool:
        self.storage_attempts += 1
        storage_id = message["params"]["storageId"]
        shape = "securityOrigin" if "securityOrigin" in storage_id else "storageKey"
        self.storage_shapes.append(shape)
        error = self._session_error(message.get("sessionId"))
        if error is None and not self._url_of(self.attached[message["sessionId"]]).startswith("https://discord.com/"):
            error = {"code": -32000, "message": "Frame not found for the given storage id"}  # the page is elsewhere
        if error is None and shape == "securityOrigin" and self.reject_security_origin:
            error = {"code": -32602, "message": "Invalid parameters"}
        if error is None and self.storage_attempts <= self.storage_errors:
            error = {"code": -32000, "message": "Frame not found for the given storage id"}
        if error is None and storage_id.get("isLocalStorage") is not True:
            error = {"code": -32602, "message": "Invalid parameters"}
        if error is not None:
            await self._reply(ws, message, error=error)
            return True
        self.storage_reads += 1
        entries = [["theme", json.dumps("dark")], ["settings", json.dumps({"a": 1})]]
        if self.storage_reads > self.storage_after:
            if self.raw_storage_value is not None:
                entries.append(["token", self.raw_storage_value])
            elif self.storage_token is not None:
                entries.append(["token", json.dumps(self.storage_token)])
        await self._reply(ws, message, {"entries": entries})
        return True

    async def _cmd_SystemInfo_getProcessInfo(self, ws, message) -> bool:
        infos = [
            {"type": "renderer", "id": 1, "cpuTime": 0.1},
            {"type": "browser", "id": self.browser_pid, "cpuTime": 0.2},
        ]
        await self._reply(ws, message, {"processInfo": infos})
        return True

    async def _cmd_Browser_close(self, ws, message) -> bool:
        self.close_requested = True
        if self.ignore_close:
            return True
        await self._reply(ws, message)
        if self.process is not None:
            self.process.exit(0)
        await ws.close()
        return False


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


class FakeSpawn:
    """Stands in for asyncio.create_subprocess_exec: records the command, writes DevToolsActivePort into the profile
    it is given, and returns a FakeProcess.

    port_file: "ok" (points at the fake browser), "none", "garbage", "closed" (a port nobody listens on),
        "wrong_path" (the browser answers 404), "partial_then_ok" (only the first line, completed after port_delay).
    exit_code: the process has already exited with it when it is returned (0 plays Edge's relaunch).
    error: raised instead of starting anything.
    port_delay: the file appears only after this many seconds.
    """

    def __init__(
        self,
        browser: FakeCdpBrowser | None = None,
        *,
        port_file: str = "ok",
        exit_code: int | None = None,
        error: Exception | None = None,
        port_delay: float = 0.0,
        ignores_terminate: bool = False,
        pid: int = 4242,
    ) -> None:
        self.browser = browser
        self.port_file = port_file
        self.exit_code = exit_code
        self.error = error
        self.port_delay = port_delay
        self.ignores_terminate = ignores_terminate
        self.pid = pid
        self.calls: list[tuple[str, ...]] = []
        self.kwargs: list[dict[str, Any]] = []
        self.profiles: list[Path] = []
        self.processes: list[FakeProcess] = []
        self._tasks: set[asyncio.Task] = set()

    async def __call__(self, *argv: str, **kwargs: Any) -> FakeProcess:
        self.calls.append(argv)
        self.kwargs.append(kwargs)
        if self.error is not None:
            raise self.error
        profile = next(Path(arg.split("=", 1)[1]) for arg in argv if arg.startswith("--user-data-dir="))
        self.profiles.append(profile)
        process = FakeProcess(self.pid, ignores_terminate=self.ignores_terminate)
        self.processes.append(process)
        if self.exit_code is None and self.browser is not None:
            self.browser.process = process
        if self.exit_code is not None:
            process.exit(self.exit_code)
        if self.port_file == "partial_then_ok":
            assert self.browser is not None
            self._put(profile, f"{self.browser.port}\n")  # a reader may see the file half written
            self._tasks.add(asyncio.create_task(self._write_later(profile)))
        elif self.port_file != "none":
            if self.port_delay:
                self._tasks.add(asyncio.create_task(self._write_later(profile)))
            else:
                self._write(profile)
        return process

    async def _write_later(self, profile: Path) -> None:
        await asyncio.sleep(self.port_delay)
        self._write(profile)

    def _write(self, profile: Path) -> None:
        if self.port_file in ("ok", "partial_then_ok"):
            assert self.browser is not None
            text = f"{self.browser.port}\n{ENDPOINT_PATH}"  # like Chrome: no trailing newline
        elif self.port_file == "wrong_path":
            assert self.browser is not None
            text = f"{self.browser.port}\n/devtools/browser/some-other-id"
        elif self.port_file == "closed":
            text = f"{_free_port()}\n{ENDPOINT_PATH}"
        else:
            text = "this is not a port file"
        self._put(profile, text)

    def _put(self, profile: Path, text: str) -> None:
        (profile / "DevToolsActivePort").write_text(text, encoding="utf-8")


class RecordingListener:
    """Remembers what the flow told it. `hooks` run when the matching event arrives."""

    def __init__(self, **hooks: Any) -> None:
        self.events: list[tuple] = []
        self.deadline: float | None = None
        self.opened = asyncio.Event()
        self._hooks = hooks

    def on_launching(self, browser_name: str) -> None:
        self.events.append(("launching", browser_name))

    def on_opened(self, deadline: float) -> None:
        self.deadline = deadline
        self.events.append(("opened", deadline))
        self.opened.set()
        if "on_opened" in self._hooks:
            self._hooks["on_opened"]()

    def on_captured(self) -> None:
        self.events.append(("captured",))
        if "on_captured" in self._hooks:
            self._hooks["on_captured"]()

    @property
    def kinds(self) -> list[str]:
        return [event[0] for event in self.events]


def fast_timings(**overrides: float) -> SessionTimings:
    """Session timings small enough for tests."""
    values: dict[str, float] = {
        "port_wait": 1.0,
        "connect_wait": 0.5,
        "open_timeout": 1.0,
        "poll": 0.01,
        "pid_query": 0.5,
        "close_command": 0.3,
        "exit_wait": 0.3,
        "terminate_wait": 0.2,
        "kill_wait": 0.2,
        "profile_wait": 0.5,
        "profile_poll": 0.01,
    }
    values.update(overrides)
    return SessionTimings(**values)
