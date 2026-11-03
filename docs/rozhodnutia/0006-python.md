# 0006: Implementácia v Pythone

- **Stav:** Prijaté
- **Dátum:** 2026-11-03
- **Rozhodol:** používateľ

## Kontext

Nástroj musí mať pekné CLI pre človeka aj plain režim pre agentov (P7), QR login cez WebSocket a RSA (ADR 0005)
a musí bežať na Windows, Linuxe aj macOS (P13). Starý skript bol v JavaScripte.

## Možnosti

- **Python:** Typer + Rich na CLI, `websockets` + `cryptography` na QR login, `segno` na QR v termináli.
  Python 3.12 je u používateľa nainštalovaný.
- **TypeScript/Node:** nadväzuje na starý skript, ale knižnice na QR, RSA a pekné CLI by bolo treba najprv preveriť.

## Rozhodnutie

- **Jazyk:** Python 3.12+.
- **Balíky a prostredie:** uv (nainštalované cez `winget install --id astral-sh.uv -e`), projekt v `src/` layoute
  s `pyproject.toml` a commitnutým `uv.lock`.
- **Knižnice:**
  - `typer`, `rich` (CLI a výstup),
  - `httpx` (HTTP),
  - `websockets`, `cryptography`, `segno` (QR login),
  - `keyring`, `platformdirs` (token a cesty k dátam).
- **Testy:** `pytest` + `pytest-asyncio`.

## Dôsledky

- Inštalácia pre používateľa: `uv tool install .` alebo pri vývoji `uv run discoop`.
- Na Windows môže byť uv po inštalácii mimo PATH v starých shelloch. Platí to aj pre Claude, pozri `CLAUDE.md`.
