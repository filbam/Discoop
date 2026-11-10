# 0023: Version 1.0.0 and single source of truth

- **Status:** Accepted
- **Date:** 2026-11-10
- **Decided by:** the user

## Context

`pyproject.toml` and `src/discoop/__init__.py` both carried a placeholder `"0.1.0"` string literal. Duplicating the version in two places risks drift on release, and earlier `0.x` numbers were never published. With browser login (`discoop login --browser`, [ADR 0022](0022-browser-login.md)) and its TUI integration complete and checked on a real account on Windows 10, the tool is ready for its first `1.x` release under Semantic Versioning.

## Options

1. **Store the version solely in `pyproject.toml` (`project.version`) and read `discoop.__version__` from installed package metadata (`importlib.metadata.version("discoop")`).** Chosen. Keeps the version in the standard Python packaging file without extra build dependencies or tooling, and preserves `__version__` for every existing caller (`api.py`, `cli.py`, `export.py`, `logs.py`).
2. **Maintain literals in both `src/discoop/__init__.py` and `pyproject.toml`.** Rejected: two places must be edited on every release and can drift apart.
3. **Use Hatchling dynamic versioning reading `__version__` from `src/discoop/__init__.py`.** Rejected: keeps a single source, but puts the version inside Python source code instead of in the standard `pyproject.toml` metadata table.
4. **Generate `_version.py` from git VCS tags (e.g., `hatch-vcs`).** Rejected: introduces extra build tooling/dependencies, and no git tags exist in the repository yet.

## Decision

1. **First release is `1.0.0` under SemVer (`MAJOR.MINOR.PATCH`).** Earlier `0.x` placeholder numbers were never published.
2. **One source of truth (`pyproject.toml`):** `project.version` in `pyproject.toml` is the only place that stores the current version number.
3. **Runtime lookup:** `src/discoop/__init__.py` sets `__version__` via `importlib.metadata.version("discoop")`, falling back to `"0+unknown"` on `PackageNotFoundError` when imported from an uninstalled source tree.
4. **Documentation rule:** project docs do not repeat the current version number; they point to `pyproject.toml` or `discoop --version`, except in dated historical records (`CHANGELOG.md` headings, ADRs, and `docs/journal.md`).
5. **Lockfile rule:** `uv.lock` is updated via `uv lock` rather than edited by hand (only reverting and editing the `discoop` package version line by hand if `uv lock` would otherwise upgrade unrelated dependencies).

## Consequences

- Releasing a new version means updating `project.version` in `pyproject.toml`, running `uv lock` and `uv sync` (so the lockfile and editable install metadata match), renaming `[Unreleased]` in `CHANGELOG.md` (with a fresh empty `[Unreleased]` above it), and adding a journal entry in `docs/journal.md`.
- An already installed user copy (`uv tool install`) only shows the new version after upgrading (`uv tool upgrade discoop`) or reinstalling.
- `tests/test_version.py` enforces that `discoop.__version__` equals `importlib.metadata.version("discoop")` and `pyproject.toml`, matches `MAJOR.MINOR.PATCH`, falls back to `"0+unknown"` when metadata is missing, and that no tracked source file under `src/` hardcodes `__version__` or the current version literal.
