"""Log in through the user's own Chromium-family browser and read the token over the DevTools Protocol.

Used by `discoop login --browser` when QR login fails (for example because Discord asks for a captcha, which a
terminal cannot solve). See docs/analyses/browser-login.md.
"""

from discoop.browser_login.cdp import CdpClient, CdpConnectionLost, CdpError, CdpEvent, CdpTimeout
from discoop.browser_login.flow import BrowserListener, wait_for_browser_token
from discoop.browser_login.launch import (
    LOGIN_URL,
    BrowserSession,
    SessionTimings,
    build_command,
    parse_devtools_active_port,
    sweep_stale_profiles,
)
from discoop.browser_login.locate import Browser, candidate_paths, find_browser

__all__ = [
    "LOGIN_URL",
    "Browser",
    "BrowserListener",
    "BrowserSession",
    "CdpClient",
    "CdpConnectionLost",
    "CdpError",
    "CdpEvent",
    "CdpTimeout",
    "SessionTimings",
    "build_command",
    "candidate_paths",
    "find_browser",
    "parse_devtools_active_port",
    "sweep_stale_profiles",
    "wait_for_browser_token",
]
