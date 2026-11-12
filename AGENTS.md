# Discoop — Agent Instructions

CLI tool for downloading messages and attachments from Discord servers the user is a member of.
The output serves for AI analysis of study materials (mainly the VUT FIT server).
It is a personal project for study purposes; the user knows scraping violates Discord's Terms of Service.

## Language: English Only

Everything that is committed to the repository is English (docs, code, comments, identifiers, commit messages, tests and fixtures, file and folder names, tool texts). The conversation with the user may be in Slovak or any language, but nothing of it enters the repository. Quoted Discord content in tests and docs is made up and English, except small fixtures that test Unicode handling (accents, emoji, normalisation), which state so in a comment. See [ADR 0021](docs/decisions/0021-english-only-repository.md).

## Commands

- `uv sync`: sync dependencies into `.venv`.
- `uv run pytest`: run test suite (all tests must pass offline); runs in parallel by default (`-n auto --dist worksteal`, [ADR 0026](docs/decisions/0026-parallel-tests.md)).
- `uv run pytest -n0 tests/test_x.py`: run serially, for one file or for debugging with `print`/`pdb`.
- `uv run pytest --ignore-glob="tests/test_tui_*.py"`: quick run without the TUI tests (about 18 s).
- `uv run discoop …`: run the CLI tool during development.
- uv missing from PATH: if missing in the agent's shell:
  `export PATH="$PATH:/c/Users/Filip/AppData/Local/Microsoft/WinGet/Packages/astral-sh.uv_Microsoft.Winget.Source_8wekyb3d8bbwe"`

## Hard Rules

- **No Discord API, Discord CDN, or GitHub API calls:** agents must NEVER call Discord API, Discord CDN, or GitHub API directly.
- **Offline tests:** all tests must run strictly offline with fake Discord/CDP or mocks (`httpx.MockTransport`).
- **No secrets or other people's data:** no tokens, cookies, passwords, or personal names or message texts. Anonymise examples.
- **No new dependencies:** do not add new dependencies without asking the user first.
- **Line endings:** `.py` files and workflow YAML files (such as `.github/workflows/release.yml`) must use LF (`\n`) line endings in git (keep in mind Windows `core.autocrlf=true` working-copy checkouts).
- **Single-source version and releases:** `pyproject.toml` (`project.version`) is the single source of truth ([ADR 0023](docs/decisions/0023-version-and-single-source.md)); ongoing docs do not repeat the current version literal. Releases use annotated `vX.Y.Z` tags pushing through `.github/workflows/release.yml` to update `stable` and publish GitHub Releases ([ADR 0024](docs/decisions/0024-releases-tags-and-stable-branch.md)); tags and pushes happen only on the user's explicit instruction.
- **Protected paths:** do not touch or modify `temp/` (or `Temp/`), `exports/`, or `prototype/out/`.

## Git Rules

- Sub-agents never run git commands (git is reserved strictly for the coordinator / main Claude).
- When instructed to commit: commit only when the task explicitly says so, stage explicit paths (never `git add .`), write commit messages in English with a Co-Authored-By line, and never push unless the user explicitly asks.

## Documentation Map

Record everything in the repository and version it in git ([ADR 0001](docs/decisions/0001-record-everything-and-version-it.md)).

| What | Where |
|---|---|
| The user's requirements | [docs/requirements.md](docs/requirements.md) |
| Tool design | [docs/design.md](docs/design.md) |
| Analyses, research, measurements | `docs/analyses/<topic>.md` |
| Decisions (ADR) | `docs/decisions/NNNN-name.md` + line in [index](docs/decisions/README.md) |
| Project changes | [CHANGELOG.md](CHANGELOG.md), `[Unreleased]` section |
| Work progress, incidents, next steps | [docs/journal.md](docs/journal.md) |

## Evidence Markers & Conventions

- In analyses and docs, distinguish facts using `[VERIFIED]` and `[ASSUMPTION]`.
- Always use absolute ISO dates (e.g. `2026-11-04`).
- ADR statuses: `Accepted`, `Proposed`, or `Superseded by ADR NNNN`.

## Orchestration Note

CLAUDE.md has the Claude-specific orchestration workflow (ADR 0010). Keep AGENTS.md and CLAUDE.md consistent.
