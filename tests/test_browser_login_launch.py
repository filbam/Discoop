"""Starting the browser: the command line, DevToolsActivePort, the stale-profile sweep, and that the browser is stopped
and the profile deleted in every path (success, errors, cancellation, a failed start, interpreter exit)."""

import asyncio
import logging
import os
import shutil
import stat
import subprocess
import sys
import time
from pathlib import Path

import pytest
from fake_cdp import (
    FakeCdpBrowser,
    FakeSpawn,
    fast_timings,
    no_session_left_behind,  # noqa: F401
)

from discoop.browser_login import (
    LOGIN_URL,
    Browser,
    BrowserSession,
    build_command,
    launch,
    parse_devtools_active_port,
    sweep_stale_profiles,
)
from discoop.errors import DiscoopError, ExitCode

BROWSER = Browser("Chrome", Path("/opt/chrome/chrome"))
TRY_OTHER_HINT = "Try another browser with --browser-path, or use `discoop login --token`."
DAY = 24 * 60 * 60


def profiles(root: Path) -> list[str]:
    return sorted(p.name for p in root.glob("discoop-browser-*")) if root.exists() else []


def make_session(root: Path, spawn: FakeSpawn, **kwargs) -> BrowserSession:
    kwargs.setdefault("timings", fast_timings())
    return BrowserSession(BROWSER, spawn=spawn, profile_root=root, **kwargs)


# -- the command line ------------------------------------------------------------------------------------------


def test_build_command_has_the_required_flags_and_ends_with_the_url():
    profile = Path("/tmp/profile-x")
    command = build_command(BROWSER, profile, LOGIN_URL)
    assert command[0] == str(BROWSER.path)
    assert f"--user-data-dir={profile}" in command
    assert "--remote-debugging-port=0" in command
    assert "--no-first-run" in command
    assert "--no-default-browser-check" in command
    assert command[-1] == "https://discord.com/login" == LOGIN_URL


def test_build_command_adds_no_automation_or_detection_evasion_flag():
    command = build_command(BROWSER, Path("/tmp/p"), LOGIN_URL)
    for forbidden in (
        "--enable-automation",
        "--headless",
        "--disable-blink-features",
        "--remote-allow-origins",
        "--remote-debugging-pipe",
        "--user-agent",
        "--disable-web-security",
        "--no-sandbox",
    ):
        assert not any(arg.startswith(forbidden) for arg in command), forbidden
    # and nothing else sneaks in: exactly these four flags
    flags = sorted(arg.split("=")[0] for arg in command[1:-1])
    assert flags == ["--no-default-browser-check", "--no-first-run", "--remote-debugging-port", "--user-data-dir"]


# -- DevToolsActivePort ----------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "9222\n/devtools/browser/0a1b2c3d-1111-2222-3333-444455556666",  # as Chrome writes it: no trailing newline
        "9222\n/devtools/browser/0a1b2c3d-1111-2222-3333-444455556666\n",
        "9222\r\n/devtools/browser/0a1b2c3d-1111-2222-3333-444455556666\r\n",
        "9222\n/devtools/browser/0a1b2c3d-1111-2222-3333-444455556666\nextra line",
    ],
)
def test_parse_devtools_active_port(text):
    assert parse_devtools_active_port(text) == (9222, "/devtools/browser/0a1b2c3d-1111-2222-3333-444455556666")


@pytest.mark.parametrize(
    "text",
    [
        "",
        "9222",
        "9222\n",  # half written
        "9222\n/devtools/browser/",
        "\n/devtools/browser/abc",
        "port\n/devtools/browser/abc",
        "0\n/devtools/browser/abc",
        "65536\n/devtools/browser/abc",
        "-5\n/devtools/browser/abc",
        "\u0662\u0662\n/devtools/browser/abc",  # non-ASCII digits (Unicode test data)
        "9222\n/json/version",
        "9222\n/devtools/browser/a b",
    ],
)
def test_parse_devtools_active_port_rejects_anything_else(text):
    with pytest.raises(ValueError):
        parse_devtools_active_port(text)


# -- the stale-profile sweep -----------------------------------------------------------------------------------


def age(path: Path, seconds: float) -> None:
    moment = time.time() - seconds
    os.utime(path, (moment, moment))


def stale_dir(root: Path, name: str, seconds: float) -> Path:
    path = root / name
    path.mkdir()
    (path / "Default").mkdir()
    (path / "Default" / "Cookies").write_text("x")
    age(path, seconds)  # after the children exist: creating them touches the folder
    return path


def test_the_sweep_removes_only_old_discoop_browser_folders(tmp_path):
    old = stale_dir(tmp_path, "discoop-browser-old", 25 * 3600)
    young = stale_dir(tmp_path, "discoop-browser-young", 23 * 3600)
    other = stale_dir(tmp_path, "somebody-elses-folder", 48 * 3600)
    a_file = tmp_path / "discoop-browser-a-file"
    a_file.write_text("x")
    age(a_file, 48 * 3600)
    assert sweep_stale_profiles(tmp_path) == 1
    assert not old.exists()
    assert young.exists() and other.exists() and a_file.exists()


def test_the_sweep_honours_max_age_and_now(tmp_path):
    folder = stale_dir(tmp_path, "discoop-browser-x", 100)
    assert sweep_stale_profiles(tmp_path, max_age=200) == 0
    assert sweep_stale_profiles(tmp_path, max_age=50) == 1
    assert not folder.exists()
    again = stale_dir(tmp_path, "discoop-browser-y", 0)
    assert sweep_stale_profiles(tmp_path, now=time.time() + 2 * DAY) == 1
    assert not again.exists()


def test_the_sweep_ignores_a_missing_folder(tmp_path):
    assert sweep_stale_profiles(tmp_path / "nowhere") == 0


def test_the_sweep_never_follows_a_symbolic_link(tmp_path):
    target = stale_dir(tmp_path, "precious", 48 * 3600)
    link = tmp_path / "discoop-browser-link"
    try:
        link.symlink_to(target, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symbolic links are not available here")
    assert sweep_stale_profiles(tmp_path, max_age=0) == 0  # everything is "old" now; the link is still left alone
    assert (target / "Default" / "Cookies").exists()


def test_the_sweep_survives_a_folder_it_cannot_remove(tmp_path, monkeypatch):
    first = stale_dir(tmp_path, "discoop-browser-a", 2 * DAY)
    second = stale_dir(tmp_path, "discoop-browser-b", 2 * DAY)
    real = launch._remove_tree

    def refuse_one(path: Path) -> None:
        if path.name == "discoop-browser-a":
            raise PermissionError(13, "in use")
        real(path)

    monkeypatch.setattr(launch, "_remove_tree", refuse_one)
    assert sweep_stale_profiles(tmp_path) == 1
    assert first.exists() and not second.exists()


async def test_starting_a_session_sweeps_old_profiles_but_not_the_new_one(tmp_path):
    root = tmp_path / "profiles"
    root.mkdir()
    old = stale_dir(root, "discoop-browser-from-an-earlier-crash", 3 * DAY)
    recent = stale_dir(root, "discoop-browser-recent", 3600)
    fake = FakeCdpBrowser()
    async with fake.running():
        spawn = FakeSpawn(fake)
        async with make_session(root, spawn):
            assert not old.exists()
            assert recent.exists() and spawn.profiles[0].exists()
    assert profiles(root) == ["discoop-browser-recent"]


# -- a session that works --------------------------------------------------------------------------------------


async def test_a_session_starts_the_browser_and_removes_the_profile_afterwards(tmp_path):
    root = tmp_path / "profiles"  # does not exist yet: the session creates it
    fake = FakeCdpBrowser()
    async with fake.running():
        spawn = FakeSpawn(fake)
        session = make_session(root, spawn)
        async with session as cdp:
            profile = spawn.profiles[0]
            assert profile.is_dir() and profile.parent == root and profile.name.startswith("discoop-browser-")
            assert (profile / "DevToolsActivePort").is_file()
            assert (await cdp.send("Target.setDiscoverTargets")) == {}
            assert session.exited is False
        process = spawn.processes[0]
        assert fake.close_requested
        assert process.returncode == 0  # it left because Browser.close asked it to
        assert (process.terminate_calls, process.kill_calls) == (0, 0)
        assert not profile.exists()
    assert fake.origins == [None]  # no Origin header: Chrome would refuse a foreign one
    assert fake.paths == ["/devtools/browser/fake-endpoint-id"]


async def test_the_browser_is_started_with_the_expected_command_line(tmp_path):
    fake = FakeCdpBrowser()
    async with fake.running():
        spawn = FakeSpawn(fake)
        async with make_session(tmp_path / "profiles", spawn):
            command = spawn.calls[0]
            assert list(command) == build_command(BROWSER, spawn.profiles[0], LOGIN_URL)
    assert spawn.kwargs[0] == {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}


async def test_the_session_url_can_be_changed(tmp_path):
    fake = FakeCdpBrowser()
    async with fake.running():
        spawn = FakeSpawn(fake)
        async with BrowserSession(
            BROWSER, url="http://127.0.0.1:1/x", spawn=spawn, profile_root=tmp_path, timings=fast_timings()
        ):
            assert spawn.calls[0][-1] == "http://127.0.0.1:1/x"


async def test_a_port_file_that_appears_late_or_half_written_is_waited_for(tmp_path):
    for kind in ("ok", "partial_then_ok"):
        fake = FakeCdpBrowser()
        async with fake.running():
            spawn = FakeSpawn(fake, port_file=kind, port_delay=0.15)
            async with make_session(tmp_path / kind, spawn) as cdp:
                assert (await cdp.send("Target.setDiscoverTargets")) == {}
            assert fake.connection_count == 1
        assert profiles(tmp_path / kind) == []


async def test_exited_turns_true_when_the_window_is_closed_and_cleanup_still_works(tmp_path):
    fake = FakeCdpBrowser()
    async with fake.running():
        spawn = FakeSpawn(fake)
        session = make_session(tmp_path, spawn)
        async with session:
            spawn.processes[0].exit(0)
            assert session.exited is True
        assert (spawn.processes[0].terminate_calls, spawn.processes[0].kill_calls) == (0, 0)
    assert profiles(tmp_path) == []


# -- a browser that relaunches itself (Edge on Windows) -----------------------------------------------------------


async def test_a_process_that_exits_with_zero_before_connecting_is_taken_for_a_relaunch(tmp_path):
    fake = FakeCdpBrowser()
    killed: list[int] = []
    async with fake.running():
        spawn = FakeSpawn(fake, exit_code=0, port_delay=0.1)
        session = make_session(tmp_path, spawn, kill_pid=killed.append)
        async with session as cdp:
            assert (await cdp.send("Target.setDiscoverTargets")) == {}
            assert session.exited is False  # the dead first process says nothing about the real browser
        assert fake.close_requested
        assert fake.commands_named("SystemInfo.getProcessInfo") == [None]
        assert killed == []  # Browser.close was enough
        assert (spawn.processes[0].terminate_calls, spawn.processes[0].kill_calls) == (0, 0)
    assert profiles(tmp_path) == []


async def test_a_relaunched_browser_that_ignores_browser_close_is_stopped_by_process_id(tmp_path):
    fake = FakeCdpBrowser(ignore_close=True, browser_pid=31337)
    killed: list[int] = []

    def kill_pid(pid: int) -> None:
        killed.append(pid)
        for ws in fake._connections:  # the real browser dies, taking its connection with it
            asyncio.get_running_loop().create_task(ws.close())

    async with fake.running():
        spawn = FakeSpawn(fake, exit_code=0)
        async with make_session(tmp_path, spawn, kill_pid=kill_pid):
            pass
    assert killed == [31337]
    assert profiles(tmp_path) == []


async def test_a_nonzero_exit_code_is_a_failed_start_not_a_relaunch(tmp_path):
    spawn = FakeSpawn(exit_code=3, port_file="none")
    with pytest.raises(DiscoopError) as e:
        async with make_session(tmp_path, spawn):
            pass
    assert e.value.message == "Chrome could not be started: it exited right away (code 3)."


# -- a session that fails to start ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("spawn_kwargs", "message"),
    [
        (
            {"error": FileNotFoundError(2, "No such file or directory", "C:/secret/path")},
            "Chrome could not be started: the file was not found.",
        ),
        ({"error": PermissionError(13, "Access is denied")}, "Chrome could not be started: permission denied."),
        ({"error": OSError(8, "Exec format error")}, "Chrome could not be started: Exec format error."),
        ({"error": NotImplementedError()}, "Chrome could not be started: NotImplementedError."),  # no subprocess loop
        ({"exit_code": 3, "port_file": "none"}, "Chrome could not be started: it exited right away (code 3)."),
        ({"exit_code": -11, "port_file": "none"}, "Chrome could not be started: it exited right away (code -11)."),
        ({"port_file": "none"}, "Chrome did not start in time."),
        ({"port_file": "garbage"}, "Chrome did not start in time."),
        ({"exit_code": 0, "port_file": "none"}, "Chrome did not start in time."),
        ({"port_file": "closed"}, "Chrome did not start in time."),
    ],
)
async def test_a_browser_that_does_not_start_is_an_error_and_leaves_nothing_behind(tmp_path, spawn_kwargs, message):
    root = tmp_path / "profiles"
    spawn = FakeSpawn(**spawn_kwargs)
    timings = fast_timings(port_wait=0.3, connect_wait=0.2)
    with pytest.raises(DiscoopError) as e:
        async with make_session(root, spawn, timings=timings):
            pytest.fail("the session must not be entered")
    assert e.value.code == ExitCode.ERROR
    assert e.value.message == message
    assert e.value.hint == TRY_OTHER_HINT
    assert "secret" not in e.value.message
    assert profiles(root) == []
    for process in spawn.processes:  # a live process is stopped; one that had exited is left alone
        assert process.returncode is not None


async def test_a_browser_that_refuses_the_debugging_connection_is_an_error(tmp_path):
    fake = FakeCdpBrowser()
    async with fake.running():
        spawn = FakeSpawn(fake, port_file="wrong_path")
        with pytest.raises(DiscoopError) as e:
            async with make_session(tmp_path, spawn, timings=fast_timings(connect_wait=0.2)):
                pytest.fail("the session must not be entered")
    assert e.value.message == "Chrome could not be started: the debugging connection was refused."
    assert profiles(tmp_path) == []
    assert spawn.processes[0].terminate_calls == 1  # a live process that never answered is stopped


async def test_no_temporary_profile_can_be_created(tmp_path):
    blocker = tmp_path / "a-file"
    blocker.write_text("x")
    with pytest.raises(DiscoopError) as e:
        async with make_session(blocker / "profiles", FakeSpawn()):
            pass
    assert e.value.code == ExitCode.ERROR
    assert e.value.message.startswith("Chrome could not be started: no temporary profile")


# -- stopping a browser that does not want to stop ----------------------------------------------------------------


async def test_a_browser_that_ignores_browser_close_is_terminated(tmp_path):
    fake = FakeCdpBrowser(ignore_close=True)
    async with fake.running():
        spawn = FakeSpawn(fake)
        async with make_session(tmp_path, spawn):
            pass
        process = spawn.processes[0]
        assert fake.close_requested
        assert (process.terminate_calls, process.kill_calls) == (1, 0)
        assert process.returncode == -15
    assert profiles(tmp_path) == []


async def test_a_browser_that_ignores_terminate_too_is_killed(tmp_path):
    fake = FakeCdpBrowser(ignore_close=True)
    async with fake.running():
        spawn = FakeSpawn(fake, ignores_terminate=True)
        async with make_session(tmp_path, spawn):
            pass
        process = spawn.processes[0]
        assert (process.terminate_calls, process.kill_calls) == (1, 1)
        assert process.returncode == -9
    assert profiles(tmp_path) == []


# -- the profile is always removed -----------------------------------------------------------------------------


async def test_an_error_in_the_body_still_cleans_up_and_is_not_masked(tmp_path):
    fake = FakeCdpBrowser()
    async with fake.running():
        spawn = FakeSpawn(fake)
        with pytest.raises(ValueError, match="boom"):
            async with make_session(tmp_path, spawn):
                raise ValueError("boom")
    assert profiles(tmp_path) == []
    assert spawn.processes[0].returncode == 0


async def test_leaving_the_session_through_ctrl_c_cleans_up(tmp_path):
    fake = FakeCdpBrowser()
    async with fake.running():
        spawn = FakeSpawn(fake)
        session = make_session(tmp_path, spawn)
        await session.__aenter__()
        # what `async with` does when the body is left by KeyboardInterrupt
        await session.__aexit__(KeyboardInterrupt, KeyboardInterrupt(), None)
    assert profiles(tmp_path) == []
    assert spawn.processes[0].returncode is not None


async def test_cancelling_the_task_cleans_up(tmp_path):
    fake = FakeCdpBrowser()
    async with fake.running():
        spawn = FakeSpawn(fake)
        entered = asyncio.Event()

        async def body():
            async with make_session(tmp_path, spawn):
                entered.set()
                await asyncio.sleep(30)

        task = asyncio.create_task(body())
        await asyncio.wait_for(entered.wait(), 5)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert fake.close_requested
        assert spawn.processes[0].returncode == 0
    assert profiles(tmp_path) == []


async def test_a_second_cancel_during_the_cleanup_cannot_skip_the_deletion(tmp_path):
    fake = FakeCdpBrowser(ignore_close=True)  # the cleanup waits for an answer that never comes
    async with fake.running():
        spawn = FakeSpawn(fake)
        entered = asyncio.Event()

        async def body():
            async with make_session(tmp_path, spawn, timings=fast_timings(close_command=5.0, exit_wait=5.0)):
                entered.set()
                await asyncio.sleep(30)

        task = asyncio.create_task(body())
        await asyncio.wait_for(entered.wait(), 5)
        task.cancel()
        for _ in range(500):  # the first cancel is being handled: Browser.close is sent and waits for an answer
            if fake.close_requested:
                break
            await asyncio.sleep(0.01)
        assert fake.close_requested and not task.done()
        task.cancel()  # the user presses Esc again
        with pytest.raises(asyncio.CancelledError):
            await task
        assert spawn.processes[0].kill_calls == 1  # stopped without waiting any longer
    assert profiles(tmp_path) == []


async def test_cancelling_while_the_browser_is_still_starting_cleans_up(tmp_path):
    spawn = FakeSpawn(port_file="none")
    task = asyncio.create_task(make_session(tmp_path, spawn, timings=fast_timings(port_wait=30)).__aenter__())
    while not spawn.processes:
        await asyncio.sleep(0.01)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert profiles(tmp_path) == []
    assert spawn.processes[0].returncode is not None


async def test_profile_removal_is_retried_for_a_while(tmp_path, monkeypatch):
    """Windows keeps file locks for a moment after a process exits."""
    real = shutil.rmtree
    attempts: list[object] = []

    def flaky(path, *args, **kwargs):
        attempts.append(path)
        if len(attempts) <= 3:
            raise PermissionError(13, "the file is in use")
        return real(path, *args, **kwargs)

    fake = FakeCdpBrowser()
    async with fake.running():
        spawn = FakeSpawn(fake)
        monkeypatch.setattr(shutil, "rmtree", flaky)
        async with make_session(tmp_path, spawn):
            pass
    assert len(attempts) == 4
    assert profiles(tmp_path) == []


async def test_a_profile_that_cannot_be_removed_is_logged_and_does_not_mask_the_error(tmp_path, monkeypatch, caplog):
    caplog.set_level(logging.DEBUG)
    real = shutil.rmtree

    def locked(*args, **kwargs):
        raise PermissionError(13, "locked")

    fake = FakeCdpBrowser()
    async with fake.running():
        spawn = FakeSpawn(fake)
        monkeypatch.setattr(shutil, "rmtree", locked)
        with pytest.raises(ValueError, match="boom"):
            async with make_session(tmp_path, spawn, timings=fast_timings(profile_wait=0.1)):
                raise ValueError("boom")
        monkeypatch.setattr(shutil, "rmtree", real)
    left = profiles(tmp_path)
    assert len(left) == 1  # it really could not be removed
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING and r.name == "discoop.browser_login"]
    assert len(warnings) == 1
    text = warnings[0].getMessage()
    assert "could not be removed" in text
    assert left[0] not in text and str(tmp_path) not in text  # the path is never logged
    shutil.rmtree(tmp_path / left[0])


async def test_read_only_files_in_the_profile_do_not_stop_the_deletion(tmp_path):
    class ReadOnlySpawn(FakeSpawn):
        def _put(self, profile: Path, text: str) -> None:
            super()._put(profile, text)
            nested = profile / "Default" / "Extensions"
            nested.mkdir(parents=True, exist_ok=True)
            for path in (profile / "locked.bin", nested / "locked.png"):
                path.write_text("x")
                path.chmod(stat.S_IREAD)

    fake = FakeCdpBrowser()
    async with fake.running():
        spawn = ReadOnlySpawn(fake)
        async with make_session(tmp_path, spawn):
            assert (spawn.profiles[0] / "locked.bin").exists()
    assert profiles(tmp_path) == []


@pytest.mark.skipif(os.name != "nt", reason="the 260-character path limit is a Windows matter")
async def test_files_beyond_the_windows_path_limit_are_removed_too(tmp_path):
    """Chrome writes deep paths (seen in Default/Extensions); ordinary calls cannot even find them."""

    class DeepSpawn(FakeSpawn):
        def _put(self, profile: Path, text: str) -> None:
            super()._put(profile, text)
            deep = profile
            for _ in range(8):
                deep = deep / ("d" * 40)
            os.makedirs(launch._fs_path(deep))
            with open(launch._fs_path(deep / "file.bin"), "w") as handle:
                handle.write("x")
            assert len(str(deep / "file.bin")) > 300

    fake = FakeCdpBrowser()
    async with fake.running():
        spawn = DeepSpawn(fake)
        async with make_session(tmp_path, spawn):
            pass
    assert profiles(tmp_path) == []


# -- the interpreter-exit hook -----------------------------------------------------------------------------------


async def test_the_exit_hook_kills_the_browser_and_removes_the_profile_of_a_session_that_never_cleaned_up(tmp_path):
    fake = FakeCdpBrowser()
    async with fake.running():
        spawn = FakeSpawn(fake)
        session = make_session(tmp_path, spawn)
        cdp = await session.__aenter__()
        profile, process = spawn.profiles[0], spawn.processes[0]
        assert session in launch._live_sessions and profile.exists()
        launch.cleanup_leftover_sessions()  # what atexit runs
        assert process.kill_calls == 1 and process.returncode == -9
        assert not profile.exists()
        assert session not in launch._live_sessions
        await session.__aexit__(None, None, None)  # a late normal exit finds nothing left to do
        await cdp.close()


async def test_a_finished_session_is_no_longer_known_to_the_exit_hook(tmp_path):
    fake = FakeCdpBrowser()
    async with fake.running():
        spawn = FakeSpawn(fake)
        async with make_session(tmp_path, spawn) as _:
            assert len(launch._live_sessions) == 1
        assert launch._live_sessions == set()
        launch.cleanup_leftover_sessions()  # harmless
        assert spawn.processes[0].kill_calls == 0


def test_the_exit_hook_is_registered_with_atexit_and_runs_at_interpreter_exit(tmp_path):
    """A real interpreter: a session that was never cleaned up must not leave its profile behind."""
    leftover = tmp_path / "discoop-browser-never-cleaned"
    leftover.mkdir()
    (leftover / "Local State").write_text("x")
    script = (
        "import sys\n"
        "from pathlib import Path\n"
        "from discoop.browser_login import Browser, BrowserSession, launch\n"
        "session = BrowserSession(Browser('Chrome', Path('chrome')))\n"
        "session._profile = Path(sys.argv[1])\n"
        "session._profile_made = True\n"
        "launch._live_sessions.add(session)\n"
    )
    done = subprocess.run([sys.executable, "-c", script, str(leftover)], capture_output=True, timeout=120)
    assert done.returncode == 0, done.stderr.decode(errors="replace")
    assert not leftover.exists()
