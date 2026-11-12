# 0015: Public repo and installation via `uv tool`

- **Status:** Superseded by ADR 0024
- **Date:** 2026-11-04
- **Decided by:** the user

## Context

The user wants (P22) the tool to work directly via the `discoop` command without `uv run`, to install very quickly on
Windows, Linux, and macOS, and to be downloaded from GitHub. The user stated that the repo `github.com/filbam/Discoop` is already public
(ADR 0002 had assumed private).

## Options

1. **`uv tool install` from GitHub.** Chosen.
2. **Standalone binaries for each OS.** Rejected: they would have to be built separately for each OS, and antiviruses
   frequently flag them as false positives.
3. **Installation scripts `install.sh` and `install.ps1`.** Not for now, the user did not request them.

## Decision

- The repo `filbam/Discoop` is **public**.
- User installation: `uv tool install git+https://github.com/filbam/Discoop`, upgrade
  `uv tool upgrade discoop`. Instructions for each OS are in [README.md](../../README.md).
- `uv run` remains for development within the repo.
- The git identity `filbam` from [ADR 0002](0002-private-repo-and-identity.md) remains.

## Consequences

- No tokens, cookies, or other people's names or message texts may ever enter git. `Temp/` and `prototype/out/` remain
  ignored by git.
- History check 2026-11-04 `[VERIFIED]`: 34 commits, no Discord token pattern found, neither `Temp/` nor `prototype/out/`
  were ever in git.
- Users only receive what is pushed. On 2026-11-04, GitHub is at commit `75f0310`, with 9 unpushed commits locally,
  so until pushed, installation gives an older version without the new TUI.
- `[VERIFIED]` (Windows, uv 0.13.7): `uv tool install` from a local clone via `git+file://` in isolated directories
  takes under 6 s with a warm cache, creates `discoop.exe`, `discoop --version` and `--help` work, `discoop.tcss` is
  installed, `uv tool upgrade discoop` picked up the new commit. Anonymous `git ls-remote` to GitHub works.
- `[ASSUMPTION]`: installation directly from GitHub, Linux, macOS, automatic Python download by uv, and running the TUI from such
  an installation.
