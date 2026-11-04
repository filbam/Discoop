# 0006: Implementation in Python

- **Status:** Accepted
- **Date:** 2026-11-03
- **Decided by:** the user

## Context

The tool must have a nice CLI for humans and plain mode for agents (P7), QR login via WebSocket and RSA ([ADR 0005](0005-qr-login-without-a-browser.md)), and must run on Windows, Linux, and macOS (P13). The old script was in JavaScript.

## Options

- **Python:** Typer + Rich for CLI, `websockets` + `cryptography` for QR login, `segno` for QR in the terminal. Python 3.12 is installed on the user's machine.
- **TypeScript/Node:** builds on the old script, but libraries for QR, RSA, and nice CLI would need to be evaluated first.

## Decision

- **Language:** Python 3.12+.
- **Packages and environment:** uv (installed via `winget install --id astral-sh.uv -e`), project in a `src/` layout with `pyproject.toml` and a committed `uv.lock`.
- **Libraries:**
  - `typer`, `rich` (CLI and output),
  - `httpx` (HTTP),
  - `websockets`, `cryptography`, `segno` (QR login),
  - `keyring`, `platformdirs` (token and data paths).
- **Tests:** `pytest` + `pytest-asyncio`.

## Consequences

- Installation for the user: `uv tool install .` or during development `uv run discoop`.
- On Windows, uv may be outside PATH in old shells after installation. This also applies to Claude, see `CLAUDE.md`.
