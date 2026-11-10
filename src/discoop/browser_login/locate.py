"""Find an installed Chromium-family browser (Chrome, Edge, Chromium or Brave) to log in with."""

import os
import shutil
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

from discoop.errors import DiscoopError, ExitCode

NOT_FOUND_HINT = (
    "Install one of them, or pass --browser-path <file> (or run `discoop config set browser-path <file>`). "
    "Alternatively use `discoop login --token`."
)
NO_DESKTOP_HINT = "Use `discoop login` (QR code) or `discoop login --token` instead."

# (display name, location below an installation root), in the order the browsers are tried.
_WINDOWS_BROWSERS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Chrome", ("Google", "Chrome", "Application", "chrome.exe")),
    ("Edge", ("Microsoft", "Edge", "Application", "msedge.exe")),
    ("Chromium", ("Chromium", "Application", "chrome.exe")),
    ("Brave", ("BraveSoftware", "Brave-Browser", "Application", "brave.exe")),
)
_WINDOWS_ROOTS = ("ProgramFiles", "ProgramFiles(x86)", "LocalAppData")  # environment variable names
_MACOS_BROWSERS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Chrome", ("Google Chrome.app", "Contents", "MacOS", "Google Chrome")),
    ("Edge", ("Microsoft Edge.app", "Contents", "MacOS", "Microsoft Edge")),
    ("Chromium", ("Chromium.app", "Contents", "MacOS", "Chromium")),
    ("Brave", ("Brave Browser.app", "Contents", "MacOS", "Brave Browser")),
)
_LINUX_COMMANDS: tuple[tuple[str, str], ...] = (
    ("Chrome", "google-chrome"),
    ("Chrome", "google-chrome-stable"),
    ("Edge", "microsoft-edge"),
    ("Edge", "microsoft-edge-stable"),
    ("Chromium", "chromium"),
    ("Chromium", "chromium-browser"),
    ("Brave", "brave-browser"),
)
# Substring of the lower-cased file name -> display name; the first match wins ("chromium" must come before "chrome").
_NAME_HINTS = (("brave", "Brave"), ("edge", "Edge"), ("chromium", "Chromium"), ("chrome", "Chrome"))


@dataclass(frozen=True)
class Browser:
    """A browser executable that Discoop can launch."""

    name: str  # "Chrome", "Edge", "Chromium", "Brave", or "Browser" for an unrecognised custom path
    path: Path


def _env(env: Mapping[str, str], name: str) -> str | None:
    """Look an environment variable up case-insensitively (Windows spells them inconsistently)."""
    wanted = name.lower()
    for key, value in env.items():
        if key.lower() == wanted and value:
            return value
    return None


def candidate_paths(platform: str, env: Mapping[str, str], home: Path | None) -> list[tuple[str, Path]]:
    """Where a browser may be installed, most preferred first. Pure: touches no file.

    Windows and macOS give absolute file paths. Linux gives bare command names (as `Path`), which the caller
    resolves with `which`. The order is Chrome, Edge, Chromium, Brave, and within one browser the roots in turn.
    """
    if platform == "win32":
        roots = [Path(root) for root in (_env(env, name) for name in _WINDOWS_ROOTS) if root]
        return [(name, root.joinpath(*parts)) for name, parts in _WINDOWS_BROWSERS for root in roots]
    if platform == "darwin":
        roots = [Path("/Applications")] + ([home / "Applications"] if home is not None else [])
        return [(name, root.joinpath(*parts)) for name, parts in _MACOS_BROWSERS for root in roots]
    return [(name, Path(command)) for name, command in _LINUX_COMMANDS]


def guess_name(path: Path) -> str:
    """Display name for a custom browser path, guessed from the file name."""
    lowered = path.name.lower()
    for hint, name in _NAME_HINTS:
        if hint in lowered:
            return name
    return "Browser"


def find_browser(
    configured: str | os.PathLike[str] | None = None,
    *,
    platform: str | None = None,
    env: Mapping[str, str] | None = None,
    home: Path | None = None,
    which: Callable[[str], str | None] | None = None,
    is_file: Callable[[Path], bool] | None = None,
) -> Browser:
    """The browser to launch: the configured file, or the first installed candidate.

    The keyword-only arguments exist for tests (they replace the platform, environment, home folder, `which` and
    file checks); callers pass only `configured`.
    """
    platform = sys.platform if platform is None else platform
    env = os.environ if env is None else env
    which = shutil.which if which is None else which
    is_file = Path.is_file if is_file is None else is_file

    if platform not in ("win32", "darwin") and not (_env(env, "DISPLAY") or _env(env, "WAYLAND_DISPLAY")):
        raise DiscoopError(
            ExitCode.ERROR,
            "Browser login needs a desktop session: neither DISPLAY nor WAYLAND_DISPLAY is set.",
            NO_DESKTOP_HINT,
        )

    if configured is not None and os.fspath(configured) != "":
        path = Path(configured).expanduser()
        if not is_file(path):
            raise DiscoopError(ExitCode.ERROR, f"Browser not found at {path}.", NOT_FOUND_HINT)
        return Browser(guess_name(path), path)

    if home is None and platform == "darwin":
        home = _home()
    for name, path in candidate_paths(platform, env, home):
        if platform in ("win32", "darwin"):
            if is_file(path):
                return Browser(name, path)
        else:
            found = which(str(path))
            if found:
                return Browser(name, Path(found))
    raise DiscoopError(
        ExitCode.ERROR, "No supported browser was found (Chrome, Edge, Chromium or Brave).", NOT_FOUND_HINT
    )


def _home() -> Path | None:
    try:
        return Path.home()
    except RuntimeError:  # no home folder can be determined; the /Applications candidates still work
        return None
