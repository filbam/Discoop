# 0005: QR login in the terminal without a browser

- **Status:** Accepted, browser rejection superseded by ADR 0022
- **Date:** 2026-11-03
- **Decided by:** the user (requirements P13 and P14), technical solution based on [analyses/discord-login.md](../analyses/discord-login.md)

## Context

The original design logged in via Chrome controlled by Playwright. The user wants login by scanning a QR code in the terminal (P14) and the tool must run on Windows, Linux, and macOS (P13). A browser as a dependency differs on each OS and is heavy.

Analysis showed that Discord QR login is a straightforward protocol:
- WebSocket `wss://remote-auth-gateway.discord.gg/?v=2` with JSON messages,
- RSA-OAEP-SHA256,
- one REST POST `/users/@me/remote-auth/login`.

It needs nothing that only a browser can do.

## Options

1. **QR login via remote auth gateway directly from the tool.** Does not need a browser, 2FA is handled by confirmation on mobile.
2. **Browser-based login (Playwright).** Can handle captcha and passkey, but requires Chrome or Chromium on each OS. On Windows, `discord.com/login` also directly triggers a system passkey dialog.
3. **Email/password + TOTP via API.** The tool would handle passwords and likely face frequent captchas.

## Decision

The primary login path is **option 1**:
- **Libraries:** `websockets`, `cryptography`, `httpx`, `segno` (QR in terminal).
- **Connection:** with header `Origin: https://discord.com`.
- **Token storage:** keyring.

Playwright is dropped from the primary path. Fallback paths are an open decision ([design.md, section 15](../design.md#open-decisions), items 7 and 8).

## Consequences

- **The prototype must verify:**
  - whether the gateway requires `Origin`,
  - whether `remote-auth/login` from a non-browser client requests captcha,
  - real frames after scanning.
- **Protocol change risk:** Discord may change it; `v=2` is already the second version. On an unknown message or close code, the tool must exit with a clear error and offer a fallback path.
- **The QR code is effectively a login link.** Neither the QR code nor the token may enter the logs.
- **Fewer dependencies:** both Playwright and browser profile are eliminated.
