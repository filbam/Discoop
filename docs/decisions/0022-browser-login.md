# 0022: Browser login `discoop login --browser`

- **Status:** Accepted
- **Date:** 2026-11-10
- **Decided by:** the user (plan approved on 2026-11-10)

## Context

QR login ([ADR 0005](0005-qr-login-without-a-browser.md)) can fail. After the user confirms the login on the phone, Discoop calls `POST /users/@me/remote-auth/login`, and Discord can answer it with HTTP 400 and a `captcha_key` field instead of a token. A terminal cannot solve a captcha. Discoop recognises this response, but its only advice so far was `discoop login --token`. The first real QR login on 2026-11-03 passed without a captcha ([analyses/discord-login.md](../analyses/discord-login.md), section 7), so the failure is not constant.

The only fallback, `discoop login --token` ([ADR 0008](0008-fallback-login-token.md)), sends the user into the browser DevTools to copy the token by hand.

Earlier decisions kept a browser out of the tool:
- [ADR 0005](0005-qr-login-without-a-browser.md) dropped Playwright and browser login because the dependency is heavy and differs on every OS.
- [ADR 0008](0008-fallback-login-token.md) deferred browser login ("Options 2 and 3 are not in v1").
- [ADR 0009](0009-login-in-agent-mode.md) makes `login` refuse in agent mode (called plain mode since [ADR 0012](0012-rename-agent-mode-to-plain.md)), because the QR code and the token must not enter an AI context.

A real browser solves the captcha naturally: the user logs in on Discord's own web page. What was missing is a way to get the token out of that browser without a heavy dependency and without Discoop ever handling the user's password. The user approved a plan for this on 2026-11-10 (requirements P31 to P33; P31 refines P14).

## Options

1. **Launch the user's installed Chromium-family browser as a separate instance with a temporary profile and read the token over the Chrome DevTools Protocol (CDP).** Chosen. It needs no new dependency (`websockets` is already used for the QR gateway) and talks to the browser through one protocol on every OS.
2. **Playwright.** Rejected: a heavy dependency that downloads its own Chromium, which is the reason [ADR 0005](0005-qr-login-without-a-browser.md) dropped it. The browser the user already has is enough.
3. **An embedded webview (for example pywebview).** Rejected: also a heavy dependency, with a different native backend on each OS, so the token would have to be read through a different mechanism per OS instead of through one protocol.
4. **The user's regular browser profile or an already running browser.** Rejected: Chrome 136 and newer refuses remote debugging on the default profile, and even where it worked it would expose all of the user's real sessions to Discoop, not only the Discord login it needs.
5. **A browser extension.** Rejected: it must be installed separately into every browser and needs a bridge back to the CLI, which is far more setup than one command, and it would stay in the user's real browser afterwards.
6. **Email and password typed into the terminal.** Rejected: it meets the same captcha, and Discoop would handle the user's password and 2FA code. Already rejected in [ADR 0005](0005-qr-login-without-a-browser.md) and [ADR 0008](0008-fallback-login-token.md) (option 3 in both).

## Decision

1. **New mode `discoop login --browser`** and a **"Log in with browser" row (key `b`)** in the TUI login dialog (opened with `F3`, see [ADR 0014](0014-tui-keyboard-one-tree.md)).
   - Discoop launches the user's installed Chromium-family browser as a **separate instance** with a fresh temporary profile (`--user-data-dir`) and `--remote-debugging-port=0`, opened on `https://discord.com/login`.
   - Browsers are tried in this order: Chrome, Edge, Chromium, Brave. Firefox is not supported (it does not offer the Chrome DevTools Protocol).
   - The user logs in in that window themselves: password, the QR code shown on the web page, 2FA, captcha.
   - Discoop reads the token over CDP through the existing `websockets` dependency. The main source is the `token` key of localStorage, read through the `DOMStorage` domain. The second source is the `Authorization` header of requests to `https://discord.com/api/`.
   - Then Discoop closes the window, verifies the token with `GET /users/@me` and stores it exactly like the other modes. **No new dependency.**
2. **Profile and flags:**
   - The temporary profile is **always deleted** (after success, failure, timeout and Ctrl+C), because it holds a live web session.
   - The user's regular browser profile is never used, read or copied.
   - No automation flags such as `--enable-automation`.
3. **Plain mode and machine-readable output:**
   - `login --browser` is **allowed** in plain mode ([ADR 0012](0012-rename-agent-mode-to-plain.md)) and together with `--format json` and `--progress-json`. The human does the login in the browser window, and an agent never sees a password, a QR code or the token (Discoop stores the token and prints none).
   - `login` without `--browser` and `login --token` **stay refused** in plain mode with exit code `2`, as in [ADR 0009](0009-login-in-agent-mode.md). ADR 0009 is amended, not dropped.
   - **Rule for AI agents:** before running `discoop login --browser`, tell the user that a browser window will open in which they must log in themselves, and wait for their consent. Never type into that window and never read the token.
4. **Captcha advice:** when QR login fails because Discord asks for a captcha, the error recommends `discoop login --browser` first and `discoop login --token` as a last resort. This holds in the CLI and in the TUI.
5. **Waiting and exit codes:**
   - Discoop waits 300 seconds by default (`--timeout SECONDS`).
   - The user closing the window, or the timeout, exits with code `2` (`AUTH_REQUIRED`).
   - A missing browser, a browser that cannot be started, no desktop session (for example a headless Linux server) or a protocol failure exits with code `1` (`ERROR`).

## Consequences

- **Earlier ADRs are superseded in part:**
  - [ADR 0005](0005-qr-login-without-a-browser.md): its rejection of browser-based login (option 2). Still valid: QR login as the primary path, its protocol, libraries and token storage. Playwright stays dropped, and the "fewer dependencies" consequence still holds because this mode adds no dependency.
  - [ADR 0008](0008-fallback-login-token.md): the sentence "Options 2 and 3 are not in v1" as far as option 2 (browser login) is concerned, and the consequence that the captcha error recommends `--token` (Decision 4). Still valid: `login --token` as designed, and email and password stay out (option 3).
  - [ADR 0009](0009-login-in-agent-mode.md): the blanket refusal of `login` in agent mode now has one exception, `login --browser` (Decision 3). Still valid: exit code `2`, the advice for other commands on a missing token, and `--human` to force human mode.
- **Token handling is unchanged.** The token is verified, stored like after QR login, and never printed or logged (see [ADR 0005](0005-qr-login-without-a-browser.md) and [ADR 0018](0018-logging.md)).
- **Rules for agents extend [ADR 0003](0003-rules-for-agents-in-the-users-browser.md) to the window Discoop opens:** an agent does not type into it and does not read the token. Discoop reads the token, not the agent.
- **Passkey dialog on Windows.** `discord.com/login` starts passkey autofill every time the form is shown, and Windows can turn that into a system Windows Security dialog ([ADR 0003](0003-rules-for-agents-in-the-users-browser.md), [analyses/discord-login.md](../analyses/discord-login.md), section 8). Before the window opens, Discoop warns the user (in the CLI and in the TUI): a dialog may appear, it can be cancelled, and the login then continues with the password or the QR code on the page.
- **Requirements:** P31 (browser login), P32 (captcha advice) and P33 (consent before an agent runs it) in [requirements.md](../requirements.md). `discoop agent-guide` and the `discoop` skill must carry the rule from Decision 3 (P33).
- **Unverified, to be checked on a real account:**
  - `[ASSUMPTION]` Discord may treat a browser with an attached DevTools session differently from a normal one (for example more captchas or a verification of the new login).
  - `[ASSUMPTION]` The `token` key of localStorage and the `Authorization` header of requests to `https://discord.com/api/` are the right sources. Neither has been checked on a real account yet.
  - Linux and macOS are unverified (browser locations, launch flags, detection of a desktop session).
- **Analysis:** the technical details (launch flags, CDP calls, checks) are in the analysis `docs/analyses/browser-login.md`.
