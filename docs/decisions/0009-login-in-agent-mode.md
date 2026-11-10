# 0009: `login` refuses in agent mode

- **Status:** Accepted, agent-mode refusal amended by ADR 0022
- **Date:** 2026-11-03
- **Decided by:** the user

## Context

Login requires a human: scanning a QR code with a phone, or entering a token. The QR code is effectively a login link and the token gives full access to the account. If `login` ran in agent mode, they would enter the AI context.

## Decision

In agent mode (`--agent`, `DISCOOP_AGENT=1`, or when stdout is not a terminal), `discoop login` exits:
- with exit code `2`,
- with a message that login must be performed by a human,
- with the advice `ask the user to run discoop login in their own terminal`.

This also applies to `login --token`.

## Consequences

- **A human can force human mode** via `--human` even when stdout is not a terminal.
- **Other commands in agent mode** on missing or invalid token also return code `2` with the same advice.
