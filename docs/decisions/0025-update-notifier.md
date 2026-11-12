# 0025: Update notifier

- **Status:** Accepted
- **Date:** 2026-11-12
- **Decided by:** the user

## Context

With proper SemVer tags, GitHub Releases, and the `stable` branch ([ADR 0024](0024-releases-tags-and-stable-branch.md)), users installed via `uv tool install` can upgrade cleanly with `uv tool upgrade discoop`, but they do not know when a new release is published unless they check GitHub manually.

Discoop is run interactively in both the CLI and the TUI (`discoop ui`), and non-interactively by scripts and AI agents (`--plain`, `--format json`, `--format jsonl`, `--progress-json`). Any update check must therefore be non-blocking, strictly privacy-preserving, easy to switch off, harmless to exit codes and machine-readable stdout, and clear to AI agents so they never upgrade or reinstall `discoop` on the user's behalf.

## Options

1. **Passive, cached check against the GitHub Releases API (`releases/latest`) surfaced in CLI stderr, the TUI, and `discoop doctor`.** Chosen: uses existing `httpx` with a short timeout and atomic local cache, never sends user or GitHub tokens, respects off switches and non-interactive runs, and never blocks or alters command exit codes.
2. **Automatic self-upgrade (`uv tool upgrade discoop`) or interactive confirmation prompts.** Rejected: mutating an installed tool automatically or prompting in the middle of a command breaks scripts and surprises the user.
3. **Checking git tags or branch refs with `git ls-remote`.** Rejected: requires `git` on `PATH` and does not distinguish published GitHub Releases (with release notes URLs) from unannounced tags.
4. **No update notifier.** Rejected: users miss released fixes and improvements unless they visit the repository manually.

## Decision

1. **Source & privacy:**
   - Query `GET https://api.github.com/repos/filbam/Discoop/releases/latest` (returns the latest non-draft, non-prerelease release).
   - Send headers `Accept: application/vnd.github+json` and `User-Agent: discoop/<version>`.
   - **Never** send an `Authorization` header or any user data (even when `GITHUB_TOKEN` or `GH_TOKEN` is set in the environment).
   - Use a `2` s timeout with the existing `httpx` dependency (no new dependencies).

2. **Status & errors:**
   - HTTP `404` means no release is published yet: treated as "nothing newer" and prints nothing in CLI or TUI.
   - Any other HTTP status, network failure, timeout, or invalid payload prints nothing to the user and logs at `DEBUG` level via standard `logging` (captured by `--debug` and `--log`, [ADR 0018](0018-logging.md)).

3. **Versions & URLs:**
   - Parse `tag_name` matching `vX.Y.Z` or `X.Y.Z` and compare as an integer triple `(X, Y, Z)` (any other tag format is ignored).
   - Read the current version from `discoop.__version__` ([ADR 0023](0023-version-and-single-source.md)); a non-`X.Y.Z` value such as `"0+unknown"` never notifies.
   - Notify only when the remote version is strictly newer.
   - Use `html_url` from the response if it starts with `https://github.com/filbam/Discoop/releases/`; otherwise fall back to `https://github.com/filbam/Discoop/releases/tag/<tag>`.
   - Keep version literals out of `src/` (`tests/test_version.py`).

4. **Cache (`paths.data_dir() / "update-check.json"`):**
   - Store Unix-second fields `checked_at`, `latest_version`, `latest_url`, `failed_at`, and `notified_at`.
   - Treat a missing or corrupt file as an empty cache.
   - Write atomically via the existing `replace_file` (`os.replace`) helper.
   - Check at most once per `24` h after a successful check; after a failure, retry no sooner than `1` h while preserving any previous `latest_version` and `latest_url` values.

5. **Off switches:**
   - `DISCOOP_NO_UPDATE_NOTIFIER` environment variable when truthy.
   - `discoop config set update-check off` (`on`/`off`, default `on`; displayed by `discoop config list` in both text and JSON output).
   - `CI` environment variable when truthy (for the CLI notice).
   - When turned off, no network request is made at all.

6. **CLI notice:**
   - Printed to `stderr` after command completion (after command output and any error), at most once per `24` h (`notified_at`), and never changes the exit code.
   - Eligible only when all of the following hold:
     - `stderr` is a TTY (`isatty()`),
     - `CI` is not truthy,
     - the notifier is not turned off,
     - a subcommand ran and is not `ui` / `--ui`,
     - not `--version`,
     - not help (`--help` or bare invocation with no subcommand),
     - not `--format json`, `--format jsonl`, or `--progress-json`,
     - not Ctrl+C (exit code `130`).
   - ASCII 3-line text (yellow in Rich/human mode, unstyled in plain mode):
     ```
     A new release of discoop is available: <current> -> <latest>
     To upgrade, run: uv tool upgrade discoop
     <url>
     ```
   - When a check is due, start a daemon thread at command start and wait at most `1` s for it at command end.

7. **TUI (`discoop ui`):**
   - Add an `#update-indicator` label in `#top-bar` right after `#mode-indicator`, hidden until a newer release is known, then displaying `↑ <latest>` in the warning colour; responsive layouts (`75x28`, `80x24`, `140x40`) remain valid.
   - Run the check in a separate thread worker after mount (`exit_on_error=False`, not in the `net` worker group), with an injectable seam on `DiscoopApp` for testing.
   - Not limited by `notified_at` and never writes `notified_at`.
   - Log once per session in the Log pane:
     `New release <latest> is available (you have <current>). Quit and run: uv tool upgrade discoop. Release notes: <url>`

8. **`discoop doctor`:**
   - Add a new `update` row right after `version` (7 checks total).
   - Always check fresh (ignoring the `24` h interval) and update `update-check.json`.
   - Status is always `OK` and never changes the exit code.
   - Detail variants:
     - `up to date (latest <latest>)`
     - `<latest> available: uv tool upgrade discoop`
     - `no release published yet`
     - `skipped (update-check is off)`
     - `could not check: <short reason>`

9. **AI agents:**
   - `discoop agent-guide` and `.claude/skills/discoop/SKILL.md` state that the update notice is informational and terminal-only, and if an agent sees it or `doctor`'s `update` row, it tells the user and **never** runs `uv tool upgrade`, `uv tool install`, or reinstalls `discoop` itself.

## Consequences

- Users receive passive upgrade notifications across the CLI, TUI, and `discoop doctor` without blocking normal or offline commands and without leaking user or GitHub credentials.
- Requirement P34 is added to [requirements.md](../requirements.md) and documented in [design.md](../design.md).
- `[ASSUMPTION]` Live GitHub Releases detection for an installed release will be verified once `v1.0.0` / `v1.1.0` releases are published on GitHub.
