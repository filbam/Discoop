# 0008: Fallback login `discoop login --token`

- **Status:** Accepted, browser option and captcha hint superseded by ADR 0022
- **Date:** 2026-11-03
- **Decided by:** the user

## Context

QR login ([ADR 0005](0005-qr-login-without-a-browser.md)) depends on an unofficial protocol. Discord may change it or start requiring a captcha from clients outside the browser. In that case, an alternative login path is needed.

## Options

1. **Manual token entry:** works always and everywhere, and is simple.
2. **Browser-based login (Playwright):** heavy dependency on every OS, accompanied by a passkey dialog on Windows.
3. **Email/password + TOTP via API:** likely to hit captcha frequently, and the tool would have to handle passwords.

## Decision

`discoop login --token`:
- **Where the token is read from:**
  - in a terminal, from a hidden prompt (`getpass`),
  - when input is not a terminal, from stdin.
- **Never from a command-line argument**, so it does not remain in shell history.
- **Verification and storage:** the token is verified via `GET /users/@me` and stored in the same way as after QR login.

Options 2 and 3 are not in v1.

## Consequences

- If QR login fails on captcha or an unknown response, the error message recommends `--token`.
- The user must know how to obtain the token (browser DevTools). The procedure will be added to the help or README.
