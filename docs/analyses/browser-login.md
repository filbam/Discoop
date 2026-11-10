# Browser Login Analysis (Chromium DevTools Protocol)

Date: 2026-11-10. Subject: how `discoop login --browser` gets a Discord token out of the user's own Chrome, Edge,
Chromium or Brave, as built in the package `discoop.browser_login` (with the CLI command and the `browser-path`
config key; the TUI comes in a later step). Decision record: [ADR 0022](../decisions/0022-browser-login.md), requirements P31 to P33 in
[requirements.md](../requirements.md).

**Legend:** **[VERIFIED]** = observed on 2026-11-10 in a local check (section 4) or by the test suite; the source and
the browser version are named. **[ASSUMPTION]** = general knowledge, documentation, or reasoning that has not been
observed here. Everything that concerns Discord's own web client or the user's real account is an assumption until the
checklist in section 6 has been done.

**Methodology and privacy:**
- The local check ran on Windows 10 Education 10.0.19045 with the installed Chrome **157.0.8103.38** and Edge
  **157.0.4341.42**, Python 3.12.10 and `websockets` 17.4. Both browsers were started **headless** (`--headless=new`) with
  a fresh temporary `--user-data-dir`, on tiny pages served from `127.0.0.1`. Discord was never contacted and no browser
  was navigated to `discord.com`.
- The user's own Chrome and Edge windows were open during the check and were not touched: every browser the check started
  had its own profile folder, and the only processes ever stopped were ones whose command line named that folder.
- The check scripts are one-off and live outside the repository. All tokens are made up (`FAKE-...`).

---

## 1. Goal

QR login (`discoop login`) sometimes fails because Discord asks for a captcha, which a terminal cannot solve
([discord-login.md](discord-login.md), sections 2.6 and 6.2). `login --browser` lets the user finish the login in a normal
browser window instead (password, QR code on the web page, captcha, 2FA, passkey), and Discoop reads the token from that
window. The caller verifies the token with `GET /users/@me` and stores it; the engine only returns the string.

Decisions already made by the user: the system Chrome or Edge through the DevTools Protocol (CDP), no Playwright, no new
dependency (`websockets` is already used for the QR gateway).

---

## 2. Mechanism

1. **Find a browser** (`find_browser`): the configured path, or the first installed of Chrome, Edge, Chromium, Brave. On
   Linux a desktop session (`DISPLAY` or `WAYLAND_DISPLAY`) is required.
2. **Start it as a separate instance** (`BrowserSession`): `--user-data-dir=<fresh temp folder>
   --remote-debugging-port=0 --no-first-run --no-default-browser-check https://discord.com/login`, all output to
   `DEVNULL`. No automation or detection-evasion flag is passed (a test asserts the exact flag set). The user's own browser
   keeps running, untouched.
3. **Connect**: wait for `<profile>/DevToolsActivePort`, connect to `ws://127.0.0.1:<port><path>` without an Origin header,
   no proxy, no keepalive pings.
4. **Attach to the page** over the browser endpoint: `Target.setDiscoverTargets`, `Target.getTargets`,
   `Target.attachToTarget {flatten: true}`, then `DOMStorage.enable` and `Network.enable` on that session. Nothing else is
   enabled: no `Runtime`, no `Page`, nothing the page could notice by side effect.
5. **Watch two sources at once; the first hit wins:**
   - `DOMStorage.getDOMStorageItems` for the `https://discord.com` local storage every `poll_interval` seconds, looking at
     the key `token` (a JSON-encoded string).
   - `Network.requestWillBeSent` events for URLs under `https://discord.com/api/`, looking at the `Authorization` header
     (every other header is dropped on the spot).
   A value counts as a token if it is a string of at least 20 characters without whitespace. Nothing more is checked: the
   caller verifies it against Discord.
6. **Finish**: tell the listener (`on_captured`, never with the token), `Browser.close`, wait for the browser to go away
   (terminate, then kill, if it does not), delete the profile, and only then return the token.
7. **Failures**: window closed (connection lost, process exited, or no page for two consecutive polls) is exit code 2,
   time out is exit code 2, a browser that cannot start or misbehaves is exit code 1 (section 5).

---

## 3. Facts

### 3.1 The DevTools endpoint and the connection

| # | Fact | Status |
|---|---|---|
| B1 | With `--remote-debugging-port=0` the browser picks a free port and writes `<user-data-dir>/DevToolsActivePort`: two lines, the port, then `/devtools/browser/<uuid>`. The file was 60 bytes, LF only, **no trailing newline**, and appeared 0.25 s after the start. | **[VERIFIED]** Chrome 157 and Edge 157, Windows 10, headless (local check, section 4). The same on Linux and macOS: **[ASSUMPTION]** (shared code base). |
| B2 | The file may be read half-written, and may appear a little before the server accepts connections. The parser treats anything short of two valid lines as "not ready yet", and the connect is retried for a few seconds, re-reading the file each time. | **[ASSUMPTION]** (not seen in the local runs, where the first attempt always worked); covered by tests (`partial_then_ok`, late file). |
| B3 | A WebSocket handshake **without** an `Origin` header is accepted; one with `Origin: http://example.invalid` is answered with **HTTP 403**. So the client sends no Origin, and `--remote-allow-origins` is not needed (and is not passed). | **[VERIFIED]** Chrome 157, Edge 157. |
| B4 | `Browser.getVersion` answers with the product (`Chrome/157.0.8103.38`, `Edg/157.0.4341.42`). `Browser.close` answers `{}` and the browser then exits: the Chrome process exited with code 0 about 0.1 s later (0.11 and 0.14 s in two runs) and the DevTools connection dropped without a close frame (`ConnectionClosedError`); after Edge's `Browser.close` no browser main process of its profile was left 0.5 s later. | **[VERIFIED]** Chrome 157, Edge 157, headless. |
| B5 | `Target.getTargets` lists more than pages: `service_worker` and `browser_ui` in Chrome, `service_worker` and `background_page` (extensions) in Edge. Only `type == "page"` is the window the user logs in in. | **[VERIFIED]** Chrome 157, Edge 157. |
| B6 | After the only page is closed (`Target.closeTarget`), headless Chrome and Edge **keep running**: the connection stays up and `Target.getTargets` lists no page. A headed browser on macOS is expected to behave the same when its last window is closed (the app stays alive), so "no page target for two consecutive polls" (one empty poll can be a page that is being replaced) is a closed-window signal next to the other two (connection lost, process exited). On Windows and Linux, closing the last window of a headed browser is expected to quit it, which those other two signals catch. | Headless: **[VERIFIED]** Chrome 157, Edge 157 (local check, section 4). Headed behaviour on all three systems: **[ASSUMPTION]**. |
| B7 | The `websockets` library (17.4) logs every frame at DEBUG: short frames in full, longer ones as their first 48 and last 24 characters, so a token would leak wholly or in part into any log that has the root logger at DEBUG. The engine therefore gives `connect` a logger of its own that goes nowhere. | **[VERIFIED]** (experiment with an echo server, `caplog` in the tests). |
| B8 | The whole `localStorage` of a busy site can exceed the library's default 1 MiB message limit. The engine allows 64 MiB per message. | **[ASSUMPTION]** (size of Discord's storage not measured). |

### 3.2 Reading the token

| # | Fact | Status |
|---|---|---|
| T1 | `DOMStorage.getDOMStorageItems` answers `{"entries": [[key, value], ...]}` for `storageId` `{"securityOrigin": "<origin>", "isLocalStorage": true}` **and** for `{"storageKey": "<origin>/", "isLocalStorage": true}`. Both worked in Chrome 157 and in Edge 157, so `securityOrigin` is still accepted there. The engine tries `securityOrigin` first, falls back to `storageKey` when a browser rejects it, and remembers which one works. | **[VERIFIED]** Chrome 157, Edge 157. Older and future versions: **[ASSUMPTION]** (the reason for the fallback). |
| T2 | `DOMStorage.enable` is **not required** before reading (the reads worked before and after it). The engine still enables the domain, as the documented way to use it. | **[VERIFIED]** Chrome 157, Edge 157. |
| T3 | For an origin that no frame of the page has, the read fails with error code -32000 `Frame not found for the given storage id`. So reads fail while the page is still loading and while the user is on another site, which is why an error from this one command only means "not now" and never ends the login. | **[VERIFIED]** Chrome 157, Edge 157. |
| T4 | `Network.requestWillBeSent` events arrive on the browser WebSocket with the page's `sessionId`; `request.headers` carries the `Authorization` header a page script set, under the spelling the page used (`Authorization`). The engine compares the name case-insensitively. Cookies are not read. | **[VERIFIED]** Chrome 157, Edge 157, for a header set by a script on a local page. |
| T5 | Discord's web client keeps the token in the localStorage key `token` as a JSON-encoded string (the value is the token wrapped in double quotes). The engine decodes it with `json.loads` and, if the value is not JSON, takes it as it is. | **[ASSUMPTION]** until checked on a real account (checklist, section 6). A page script set the same shape in the local check (**[VERIFIED]** that the engine reads that shape). |
| T6 | Discord's web client hides `window.localStorage` from page scripts, which is why the passive DOMStorage domain is used and `Runtime.evaluate` is not. | **[ASSUMPTION]** |
| T7 | Once a token exists, the web client's HTTP client adds `Authorization` to every request under `/api/` ([discord-login.md](discord-login.md), section 4.2: function `prepareRequest` in the client JS). So the header source should fire shortly after the login, and it is a second chance if T5 turns out wrong. | Client JS: **[VERIFIED]** in the earlier analysis. Seen through CDP on a real login: **[ASSUMPTION]**. |

### 3.3 The process and the profile

| # | Fact | Status |
|---|---|---|
| P1 | **Edge 157 relaunches itself on this Windows 10 machine.** The `msedge.exe` that was started exits with **code 0 after about 0.05 s**; a second `msedge.exe` (the real browser, with the extra flag `--edge-skip-compat-layer-relaunch` on its command line) carries on. The port file appears 0.25 s after the start. `SystemInfo.getProcessInfo` reports a browser process id that is **not** the id of the process that was started. Chrome 157 does not do this (its reported id equals the started one). Consequences: an exit with code 0 before the port file is **not** a failed start; the exit code and handle of the first process say nothing about the window afterwards; the real browser is closed through `Browser.close` and, only if that is ignored, stopped by the process id from `SystemInfo.getProcessInfo`. | **[VERIFIED]** Edge 157 and Chrome 157, Windows 10 (process listing and local check, section 4). Why Edge does it (the flag name suggests an application-compatibility relaunch): **[ASSUMPTION]**. |
| P2 | On Windows, a profile in a folder with a long path cannot be deleted by ordinary calls: Chrome writes files such as `Default\Extensions\<id>\<version>\images\...` and `OptimizationGuideModelsManifest\...`, the full path passes 260 characters, and `unlink`/`rmdir` fail with WinError 3 and 145 although the files are listed. Deleting through the extended-length form (`\\?\` prefix) worked on the very same leftover profile. The engine always deletes that way on Windows. A normal `%TEMP%` path is short, so this is a safety net; it was found because the check's profile root was deep. | **[VERIFIED]** Chrome 157, Windows 10 (failed without the prefix, succeeded with it); also a test on Windows. |
| P3 | After `Browser.close`, headless Chrome and Edge profiles were deleted at once (0 retries, 0.11 to 0.17 s). Windows may keep file locks for a moment after a headed browser exits, which is why the deletion is retried for up to 10 s. | Headless: **[VERIFIED]**. Headed: **[ASSUMPTION]**. |
| P4 | A hard-killed Discoop (power loss, `kill -9`) cannot clean up, and its profile holds a live Discord web session. At the start of each run, `discoop-browser-*` folders in the temp folder older than 24 hours are deleted (never through a symbolic link). Within a normal run, cleanup also runs on success, error, timeout, task cancellation (Esc in the TUI), Ctrl+C, a failed start, and a second cancel during the cleanup; an `atexit` hook handles what is left. | **[VERIFIED]** by tests, including a real interpreter exit. (The symbolic-link test needs link rights and was skipped on this Windows machine.) |
| P5 | A GUI browser on Windows does not receive Ctrl+C from the terminal, while on Linux and macOS it sits in the terminal's process group and does. Either way the cleanup is explicit, so the outcome is the same. | **[ASSUMPTION]** |

### 3.4 Discord, the user's browser, and the real account

| # | Fact | Status |
|---|---|---|
| D1 | Chrome 136 and newer refuse remote debugging on the **default** profile; a custom `--user-data-dir` is mandatory. The engine always uses one (and it keeps the user's own profile and windows out of it). The default profile was deliberately not tried: it would touch the user's own browser. | **[ASSUMPTION]** (from Chrome's published change; a custom profile works in 157, see B1). |
| D2 | `discord.com/login` may open the Windows Security passkey dialog in real Chrome or Edge as well, as it did in the embedded browser ([discord-login.md](discord-login.md), section 8): the login page asks for a conditional passkey on every display. The user can cancel it. | **[ASSUMPTION]** |
| D3 | A fresh Edge profile may show first-run or sign-in screens even with `--no-first-run`. They are part of the window the user is in anyway. | **[ASSUMPTION]** |
| D4 | On macOS, closing the last window may not quit the app (see B6), and the app is started by running the binary inside the `.app` bundle directly, which opens a separate instance for a different `--user-data-dir`. | **[ASSUMPTION]** |
| D5 | A snap or flatpak Chromium on Linux may be unable to use a profile folder under the temp folder (a private `/tmp` or no access) and then never writes `DevToolsActivePort`; the result is "did not start in time" and `--browser-path` to a non-confined browser is the way out. | **[ASSUMPTION]** |
| D6 | The token stays valid after the window is closed (closing it does not log out), and Discord lists the web login as a new session under Devices. | **[ASSUMPTION]** |
| D7 | The engine adds no automation flag and, besides target discovery, enables only the `DOMStorage` and `Network` domains on the page, so the page is not told anything beyond a normal window with an open debugging port. Whether Discord can tell that the port is open is not known. | **[ASSUMPTION]** |

---

## 4. Local verification (2026-11-10)

**Method.** Two throw-away scripts outside the repository. A tiny HTTP server on `127.0.0.1` served pages that set
`localStorage.token` to a JSON-encoded fake token and/or sent a `fetch` with a fake `Authorization` header (every 300 ms, or
once after 1.2 s). The system Chrome and Edge were started headless with a fresh `--user-data-dir` and
`--remote-debugging-port=0`.
- The first script spoke raw CDP and printed the facts B1, B3 to B5, T1 to T4 and P1.
- The second ran the real package against the same pages (the engine's Discord origin and API prefix were pointed at the
  local server for the run) through six scenarios per browser and checked, after each one, that no profile folder and no
  browser process of the check was left.
- A third small probe closed the only page (B6); a fourth experiment looked at what `websockets` logs (B7).

**Result of the six end-to-end scenarios** (the same in Chrome 157 and Edge 157 in every run; times in seconds from the
last of four runs, Chrome / Edge, including start-up and cleanup; poll interval 0.5 s):

| Scenario | Expected | Observed |
|---|---|---|
| Token in `localStorage` (set after 1.2 s) | token returned, source `storage` | as expected (2.2 / 2.5) |
| Token only as an `Authorization` header (sent after 1.2 s) | token returned, source `header` | as expected (1.8 / 2.1) |
| The only page closed with `Target.closeTarget` | exit code 2, "window was closed" | as expected (0.7 / 0.4) |
| The browser process killed (by the id `SystemInfo.getProcessInfo` reported for this check's own instance) | exit code 2, "window was closed" | as expected (0.1 / 0.1) |
| Nobody logs in, `timeout=4` | exit code 2, "not finished within 4 seconds" | as expected (4.7 / 5.0) |
| The task cancelled while waiting | `CancelledError` propagates | as expected (0.2 / 0.4) |

After every scenario: no `discoop-browser-*` profile left, no browser process of the check left. The Edge runs went
through the relaunch handling (P1) every time.

**What the check did not and could not cover:** Discord itself (T5 to T7), a headed window and a human closing it (B6,
P3), Linux and macOS, captcha, 2FA and passkeys.

### Side effects of the check

1. **A mistake in the first Edge probes.** They treated the early exit of `msedge.exe` as a failed start, deleted the
   profile folder, and moved on, while the relaunched browser kept running. Five launches (one run of the first script and
   four variants of a small follow-up probe) left five headless Edge process trees running against five temporary profile
   folders. They were found with a read-only process listing, identified by the unique `discoop-localcheck-` folder name on
   their command lines, stopped by process id (only the five main processes; their helper processes exited with them),
   and the folders were deleted. Nothing of the user's own Chrome or Edge was touched. This is exactly the case the
   engine's relaunch handling (P1) exists for.
2. **A profile root deeper than 260 characters** made the check's own cleanup fail once (P2); the leftover folder was
   deleted afterwards with the extended-length form.
3. **The check script's safety net once ended the shell that ran it.** The net looks for browser processes whose command
   line names the check's private profile folder; one command line of mine contained that folder name as text, so the net
   matched the shell hosting my command and terminated it. Nothing else was affected, and the orphaned script finished on its
   own with no profile or process left behind. The net now only matches `chrome.exe` and `msedge.exe`.
4. No request went to Discord, no token or cookie of any account was read, no browser was navigated to `discord.com`.

---

## 5. How the engine behaves (consequences of the facts)

| Situation | Exit code | Message (hint) |
|---|---|---|
| No desktop session on Linux | 1 | `Browser login needs a desktop session: neither DISPLAY nor WAYLAND_DISPLAY is set.` (use `discoop login` or `--token`) |
| Configured browser path is not a file | 1 | `Browser not found at <path>.` (install one, `--browser-path`, `config set browser-path`, or `--token`) |
| No supported browser installed | 1 | `No supported browser was found (Chrome, Edge, Chromium or Brave).` (same hint) |
| The browser cannot be started or exits at once with a failure code | 1 | `<name> could not be started: <short reason>.` (try another browser, or `--token`) |
| `DevToolsActivePort` never appears, the connection is never accepted, or no page opens | 1 | `<name> did not start in time.` (same hint) |
| A setup command is refused or unanswered | 1 | `The browser did not respond as expected (<method> failed).` (the command name only, never parameters or results) |
| The window is closed before the login finishes | 2 | `The browser window was closed before the login finished.` (run again) |
| The time is up (`timeout`, default 300 s) | 2 | `The login was not finished within <5 minutes>.` (run again, `--timeout`) |

Rules that follow from the facts above:
- **No Origin header, no proxy, no pings, no compression, a silenced library logger** (B3, B7, B8).
- **`type == "page"` only**; prefer the page that shows `discord.com`; if the page we watch disappears but another is open,
  or is somewhere else while another page shows Discord, attach to that one (B5, B6). A page that already shows Discord is
  never swapped for another one.
- **A failed storage read is "not yet"** (T3). Only the setup commands and `Target.getTargets` are strict. Even if storage
  never works, the header source can still end the wait, and if neither works the result is a timeout, not an error.
- **An exit with code 0 before the endpoint is known is a relaunch**, not a failure (P1). Then the window's fate is read from
  the DevTools connection, not from the process handle.
- **Cleanup order:** `Browser.close` over CDP (at most 1.5 s, errors ignored); close the WebSocket; wait up to 3 s for the
  process, then `terminate()`, wait 2 s, then `kill()`; delete the profile, retrying for up to 10 s. The last step is
  synchronous and runs in a `finally`, so a second cancel cannot skip it. If the profile still cannot be removed, a WARNING
  without the path is logged and the original exception is not masked.
- **Logging ([ADR 0018](../decisions/0018-logging.md)):** logger `discoop.browser_login`, short `key=value` events at DEBUG (`browser=Chrome`,
  `source=storage`, `profile_removed=true`). Never the token, a header, a storage entry, a URL with a query, CDP parameters
  or results, or the profile path. The listener never receives the token. Tests check this with the root logger at DEBUG.

---

## 6. Open checks for the user's real account

These turn the Discord-specific assumptions (T5, T6, T7, D1 to D7) and the headed-browser assumptions (B6, P3) into facts.
Nothing here sends anything but the login itself. Run with `--debug` where possible: the log says which source found the
token (`source=storage` or `source=header`) and must not contain the token.

1. **Chrome, password login.** `discoop login --browser`: a window opens on `discord.com/login`; log in (with 2FA if the
   account has it). The window closes by itself and the command reports the account. Record the `source=` line.
2. **Chrome, QR code on the web page** (scan it with the phone), and a **captcha** if Discord shows one: this is the case
   the feature exists for.
3. **Edge**, the same login (`--browser-path` or auto-detected). Note any first-run or sign-in screen.
4. **Closing the window before logging in** (the X button): exit code 2 with the "window was closed" message within a few
   seconds; afterwards no `discoop-browser-*` folder in the temp folder and no leftover Chrome or Edge process.
5. **Ctrl+C in the terminal** while the window is open: the window closes, the folder is gone, and the command stops
   (exit code 130, as for the other commands).
6. **A short `--timeout`** (for example 30 s) and doing nothing: exit code 2 after 30 s, window closed, folder gone.
7. **In the TUI**, start the browser login and press Esc while the window is open: the window closes and the folder is gone
   (once the TUI step exists).
8. **A hard kill** of the terminal while the window is open: the window stays open and its `discoop-browser-*` folder stays
   in the temp folder; a later `discoop login --browser` deletes such folders once they are older than 24 hours (or delete
   the folder by hand after closing the window).
9. **The passkey dialog** (Windows Security) may appear on the login page: cancel it and log in with the password or the QR
   code.
10. **Afterwards:** `discoop status` works the next day (the token stays valid after the window closed), and Discord's
    Settings, Devices lists a new web session.
11. **Headed behaviour:** note how long the window takes to disappear and whether the temp folder is deleted at once or only
    after retries (the log shows `profile_removed=true`, or a WARNING if it was not).
