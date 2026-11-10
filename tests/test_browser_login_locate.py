"""Finding the browser: candidate order per OS, the Linux display check, a configured path, the not-found errors."""

import shutil
import sys
from pathlib import Path

import pytest

from discoop.browser_login import Browser, candidate_paths, find_browser
from discoop.browser_login.locate import guess_name
from discoop.errors import DiscoopError, ExitCode

# Forward slashes everywhere, so the expected values read the same on every host OS.
WIN_ENV = {
    "ProgramFiles": "C:/Program Files",
    "ProgramFiles(x86)": "C:/Program Files (x86)",
    "LocalAppData": "C:/Users/test/AppData/Local",
}
HOME = Path("/home/test")
NOT_FOUND_HINT = (
    "Install one of them, or pass --browser-path <file> (or run `discoop config set browser-path <file>`). "
    "Alternatively use `discoop login --token`."
)


def posix(candidates: list[tuple[str, Path]]) -> list[tuple[str, str]]:
    return [(name, path.as_posix()) for name, path in candidates]


def test_candidate_paths_windows_follow_the_required_order():
    pf, pf86, local = "C:/Program Files", "C:/Program Files (x86)", "C:/Users/test/AppData/Local"
    names = [
        ("Chrome", "Google/Chrome/Application/chrome.exe"),
        ("Edge", "Microsoft/Edge/Application/msedge.exe"),
        ("Chromium", "Chromium/Application/chrome.exe"),
        ("Brave", "BraveSoftware/Brave-Browser/Application/brave.exe"),
    ]
    expected = [(name, f"{root}/{tail}") for name, tail in names for root in (pf, pf86, local)]
    assert posix(candidate_paths("win32", WIN_ENV, HOME)) == expected


def test_candidate_paths_windows_skip_roots_that_are_not_set():
    result = posix(candidate_paths("win32", {"LocalAppData": "C:/L"}, HOME))
    assert [name for name, _ in result] == ["Chrome", "Edge", "Chromium", "Brave"]
    assert all(path.startswith("C:/L/") for _, path in result)


def test_candidate_paths_windows_environment_names_are_case_insensitive():
    env = {key.upper(): value for key, value in WIN_ENV.items()}  # os.environ on Windows has upper-case keys
    assert posix(candidate_paths("win32", env, HOME)) == posix(candidate_paths("win32", WIN_ENV, HOME))


def test_candidate_paths_macos():
    result = posix(candidate_paths("darwin", {}, HOME))
    assert result[:2] == [
        ("Chrome", "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
        ("Chrome", "/home/test/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
    ]
    names = [name for name, _ in result]
    assert names == ["Chrome", "Chrome", "Edge", "Edge", "Chromium", "Chromium", "Brave", "Brave"]
    assert result[-1] == ("Brave", "/home/test/Applications/Brave Browser.app/Contents/MacOS/Brave Browser")
    edge_path = next(path for name, path in result if name == "Edge")
    assert edge_path.endswith("Microsoft Edge.app/Contents/MacOS/Microsoft Edge")


def test_candidate_paths_macos_without_a_home_folder():
    assert all(path.startswith("/Applications/") for _, path in posix(candidate_paths("darwin", {}, None)))


def test_candidate_paths_linux_are_command_names_in_order():
    result = [(name, path.as_posix()) for name, path in candidate_paths("linux", {}, HOME)]
    assert result == [
        ("Chrome", "google-chrome"),
        ("Chrome", "google-chrome-stable"),
        ("Edge", "microsoft-edge"),
        ("Edge", "microsoft-edge-stable"),
        ("Chromium", "chromium"),
        ("Chromium", "chromium-browser"),
        ("Brave", "brave-browser"),
    ]


def windows_pick(existing: set[str]) -> Browser:
    return find_browser(platform="win32", env=WIN_ENV, home=HOME, is_file=lambda p: p.as_posix() in existing)


PF = "C:/Program Files"
PF86 = "C:/Program Files (x86)"
LOCAL = "C:/Users/test/AppData/Local"
CHROME_PF = f"{PF}/Google/Chrome/Application/chrome.exe"
CHROME_LOCAL = f"{LOCAL}/Google/Chrome/Application/chrome.exe"
EDGE_PF86 = f"{PF86}/Microsoft/Edge/Application/msedge.exe"
CHROMIUM_PF = f"{PF}/Chromium/Application/chrome.exe"
BRAVE_LOCAL = f"{LOCAL}/BraveSoftware/Brave-Browser/Application/brave.exe"


@pytest.mark.parametrize(
    ("existing", "name", "path"),
    [
        ({EDGE_PF86, BRAVE_LOCAL}, "Edge", EDGE_PF86),  # Edge comes before Brave
        ({EDGE_PF86, CHROME_LOCAL}, "Chrome", CHROME_LOCAL),  # Chrome comes before Edge, wherever it is installed
        ({CHROME_PF, CHROME_LOCAL}, "Chrome", CHROME_PF),  # within one browser, Program Files comes first
        ({BRAVE_LOCAL, CHROMIUM_PF}, "Chromium", CHROMIUM_PF),  # Chromium comes before Brave
        ({BRAVE_LOCAL}, "Brave", BRAVE_LOCAL),
    ],
)
def test_find_browser_windows_takes_the_first_existing_candidate(existing, name, path):
    browser = windows_pick(existing)
    assert browser.name == name
    assert browser.path.as_posix() == path


def test_find_browser_macos_checks_the_user_applications_folder_too():
    wanted = "/home/test/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"
    browser = find_browser(platform="darwin", env={}, home=HOME, is_file=lambda p: p.as_posix() == wanted)
    assert (browser.name, browser.path.as_posix()) == ("Edge", wanted)


def linux_pick(installed: dict[str, str], env: dict[str, str] | None = None) -> Browser:
    return find_browser(platform="linux", env=env or {"DISPLAY": ":0"}, home=HOME, which=installed.get)


def test_find_browser_linux_resolves_commands_with_which_in_order():
    browser = linux_pick({"chromium-browser": "/usr/bin/chromium-browser", "brave-browser": "/usr/bin/brave-browser"})
    assert (browser.name, browser.path) == ("Chromium", Path("/usr/bin/chromium-browser"))
    browser = linux_pick({"google-chrome-stable": "/opt/g", "microsoft-edge": "/opt/e"})
    assert (browser.name, browser.path) == ("Chrome", Path("/opt/g"))
    assert linux_pick({"microsoft-edge-stable": "/opt/e2"}).name == "Edge"


def test_find_browser_linux_without_a_display_fails_first():
    with pytest.raises(DiscoopError) as e:
        linux_pick({"google-chrome": "/usr/bin/google-chrome"}, env={"PATH": "/usr/bin"})
    assert e.value.code == ExitCode.ERROR
    assert e.value.message == "Browser login needs a desktop session: neither DISPLAY nor WAYLAND_DISPLAY is set."
    assert e.value.hint == "Use `discoop login` (QR code) or `discoop login --token` instead."


def test_find_browser_linux_display_check_comes_before_a_configured_path(tmp_path):
    browser_file = tmp_path / "chrome"
    browser_file.write_text("x")
    with pytest.raises(DiscoopError) as e:
        find_browser(browser_file, platform="linux", env={})
    assert "DISPLAY" in e.value.message


def test_find_browser_linux_wayland_alone_is_enough():
    assert linux_pick({"chromium": "/usr/bin/chromium"}, env={"WAYLAND_DISPLAY": "wayland-0"}).name == "Chromium"


def test_find_browser_ignores_the_display_on_windows_and_macos():
    assert windows_pick({"C:/Program Files/Google/Chrome/Application/chrome.exe"}).name == "Chrome"


@pytest.mark.parametrize(
    ("file_name", "expected"),
    [
        ("chrome.exe", "Chrome"),
        ("google-chrome-stable", "Chrome"),
        ("Google Chrome", "Chrome"),
        ("msedge.exe", "Edge"),
        ("Microsoft Edge", "Edge"),
        ("microsoft-edge", "Edge"),
        ("brave.exe", "Brave"),
        ("Brave Browser", "Brave"),
        ("chromium", "Chromium"),
        ("chromium-browser", "Chromium"),
        ("vivaldi", "Browser"),
        ("my-browser.exe", "Browser"),
    ],
)
def test_the_display_name_is_guessed_from_the_file_name(file_name, expected):
    assert guess_name(Path("/some/dir") / file_name) == expected


def test_a_configured_path_wins_and_is_not_searched_for(tmp_path):
    custom = tmp_path / "msedge.exe"
    custom.write_text("not really a browser")
    browser = find_browser(custom, platform="win32", env=WIN_ENV, home=HOME, is_file=lambda p: p == custom)
    assert browser == Browser("Edge", custom)


def test_a_configured_path_may_be_a_string_and_may_start_with_a_tilde():
    seen: list[Path] = []

    def is_file(path: Path) -> bool:
        seen.append(path)
        return True

    browser = find_browser("~/apps/brave", platform="darwin", env={}, home=HOME, is_file=is_file)
    assert browser.name == "Brave"
    assert seen == [Path("~/apps/brave").expanduser()]


def test_a_configured_path_that_is_not_a_file_is_an_error(tmp_path):
    missing = tmp_path / "no-such-browser"
    with pytest.raises(DiscoopError) as e:
        find_browser(missing, platform="win32", env=WIN_ENV)
    assert e.value.code == ExitCode.ERROR
    assert e.value.message == f"Browser not found at {missing}."
    assert e.value.hint == NOT_FOUND_HINT


def test_a_configured_directory_is_not_a_browser(tmp_path):
    with pytest.raises(DiscoopError) as e:
        find_browser(tmp_path, platform="win32", env=WIN_ENV)
    assert e.value.message.startswith("Browser not found at ")


def test_an_empty_configured_path_means_search():
    assert windows_pick({"C:/Program Files/Google/Chrome/Application/chrome.exe"}).name == "Chrome"
    browser = find_browser(
        "", platform="win32", env=WIN_ENV, home=HOME, is_file=lambda p: p.as_posix().endswith("msedge.exe")
    )
    assert browser.name == "Edge"


def test_nothing_found_is_an_error_with_the_hint():
    with pytest.raises(DiscoopError) as e:
        windows_pick(set())
    assert e.value.code == ExitCode.ERROR
    assert e.value.message == "No supported browser was found (Chrome, Edge, Chromium or Brave)."
    assert e.value.hint == NOT_FOUND_HINT
    assert "--browser-path" in e.value.hint and "browser-path" in e.value.hint and "--token" in e.value.hint
    with pytest.raises(DiscoopError) as e:
        linux_pick({})
    assert e.value.message == "No supported browser was found (Chrome, Edge, Chromium or Brave)."


def test_the_real_file_system_is_used_by_default(tmp_path):
    root = tmp_path / "pf"
    edge = root / "Microsoft" / "Edge" / "Application" / "msedge.exe"
    edge.parent.mkdir(parents=True)
    edge.write_text("x")
    browser = find_browser(platform="win32", env={"ProgramFiles": str(root)})
    assert browser == Browser("Edge", edge)


def test_the_platform_environment_and_which_are_read_when_not_given(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    with pytest.raises(DiscoopError):
        find_browser()
    monkeypatch.setenv("DISPLAY", ":1")
    monkeypatch.setattr(shutil, "which", {"brave-browser": "/usr/bin/brave-browser"}.get)
    assert find_browser() == Browser("Brave", Path("/usr/bin/brave-browser"))
