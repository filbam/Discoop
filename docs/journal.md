# Journal

Chronological record of work: what was done, what was decided, incidents, and next steps. Newest on top.

---

## 2026-11-12

**Release pipeline, `@stable` branch, and passive update notifier (P34–P35, [ADR 0024](decisions/0024-releases-tags-and-stable-branch.md), [ADR 0025](decisions/0025-update-notifier.md), [analysis](analyses/release-process.md)):**
- **What was done (Waves 1–3 on `feature/releases-and-update-notifier`):**
  - **Wave 1 (`A1` release pipeline, `B1` update-check core/config, `D1` ADRs & design):**
    - `A1`: added `.github/workflows/release.yml` (tag trigger `v[0-9]+.[0-9]+.[0-9]+`, top-level `permissions: contents: read`, only `actions/checkout@v6` and `astral-sh/setup-uv@v10.3.3`; 3-OS `test` matrix running `uv sync --locked` and `uv run pytest`; `release` job with `needs: test`, `ubuntu-latest`, `permissions: contents: write`, `fetch-depth: 0` running `scripts/release_notes.py`, `uv build`, non-forced `git push origin "$GITHUB_SHA:refs/heads/stable"`, and `gh release create ... --verify-tag` with `GH_TOKEN`), stdlib-only `scripts/release_notes.py` outside `src/`, `tests/test_release_notes.py`, and isolated `%TEMP%` `uv tool` `@stable` / bare-remote push verification in [release-process.md](analyses/release-process.md).
    - `B1`: added `src/discoop/update_check.py` (passive unauthenticated `GET https://api.github.com/repos/filbam/Discoop/releases/latest` using `httpx` with `2` s timeout, `Accept` and `User-Agent` headers only, never `Authorization`/cookies/user data; `404` -> no release yet; errors silent to users and `DEBUG`-logged via `discoop.update_check` with `NullHandler`; strict ASCII integer-triple SemVer comparison against `discoop.__version__`; `html_url` prefix check; atomic `paths.data_dir() / "update-check.json"` via `replace_file` with `24` h check interval and `1` h failure backoff preserving `latest_*`; off switches `DISCOOP_NO_UPDATE_NOTIFIER`, `config update-check`, and `CI` for CLI), added `update-check` (`on`/`off`, default `on`) to `src/discoop/config.py`, set `DISCOOP_NO_UPDATE_NOTIFIER=1` by default in `tests/conftest.py` (`isolated_env`), and added tests in `tests/test_update_check.py` (40) and `tests/test_config.py` (12 total).
    - `D1`: recorded [ADR 0024](decisions/0024-releases-tags-and-stable-branch.md) (`Accepted`, superseding [ADR 0015](decisions/0015-public-repo-and-installation.md)), [ADR 0025](decisions/0025-update-notifier.md) (`Accepted`), [ADR index](decisions/README.md), requirements `P34` and `P35` in [requirements.md](requirements.md), and [design.md](design.md) updates (sections 3, 4.6–4.9, 10, 13, 16, and 17).
  - **Wave 2 (`B2` CLI/doctor/AI guide, `B3` TUI, `A1-fix` CRLF test fix):**
    - `B2`: wired CLI background checks via `_CliCommand`, `profiles_app`, and `Output.update_notice` (`cli.py`, `output.py`; daemon thread capped at `1` s wait at command end, 3 ASCII lines to `stderr` in yellow or plain, `soft_wrap=True`, `24` h `notified_at` throttle, suppressed for non-TTY/`CI`/disabled/`ui`/`--ui`/`--version`/help/usage errors/`--format json`/`jsonl`/`--progress-json`/exit `130`, never altering exit codes); added 7th `doctor` row `update` right after `version` (always checks fresh with `force=True`, `include_ci=False`, updates cache while preserving `notified_at`, single HTTP request on TTY, always `OK`/exit `0`); added the no-self-upgrade rule to `src/discoop/agent_guide.py` and `.claude/skills/discoop/SKILL.md`; verified with `tests/test_cli_update_notice.py` (40), `tests/test_doctor.py` (21 total), and `tests/test_agent_guide.py` (16 total).
    - `B3`: added `#update-indicator` (`↑ <latest>` in `$warning`, hidden until a newer release is known) in `#top-bar` right after `#mode-indicator` (`src/discoop/tui/app.py`, `src/discoop/tui/discoop.tcss`), mount worker `@work(thread=True, group="update", exit_on_error=False)` isolated from `net` with injectable `DiscoopApp(..., update_check_fn=...)` seam, ignoring/never writing `notified_at`, logging one reminder line in `#event-log`, layout checks at `75x28`, `80x24`, and `140x40`, and 33 tests in `tests/test_tui_update.py`.
    - `A1-fix`: updated `tests/test_release_notes.py` so `_decode_workflow_bytes` normalizes working-copy `\r\n` to `\n` without adding `.gitattributes` (plus 2 new tests covering LF/CRLF normalization, bringing `tests/test_release_notes.py` to 24 tests), resolving the Windows `core.autocrlf=true` failure of `test_release_workflow_yaml_structure` recorded in the parallel-tests entry below.
  - **Wave 3 (`D2` user docs & project records):** updated `README.md` (`@stable` install, one-time `--force` switch note, update notifier, 7 `doctor` checks), `CLAUDE.md` and `AGENTS.md` (status, `stable` branch / release steps, no GitHub API calls, LF/autocrlf note, version rule), `CHANGELOG.md` (`[Unreleased]` `### Added`), and `docs/journal.md`.
- **Notable discoveries & decisions:**
  - `astral-sh/setup-uv` stopped maintaining floating major tags (`@v8+`), so `.github/workflows/release.yml` pins the explicit release `@v10.3.3` (`[ASSUMPTION]` until run on GitHub Actions).
  - `typer.core._main` catches `KeyboardInterrupt` and returns exit code `130` before `cli.main`'s `except (typer.Abort, KeyboardInterrupt)` handler runs; checking `if show_notice and exit_code != 130:` ensures Ctrl+C never displays an update notice.
  - Normalizing working-copy `\r\n` in `tests/test_release_notes.py` avoids `.gitattributes` churn while preserving strict validation of tabs, bare CR, trailing newline, and workflow YAML structure across Windows `core.autocrlf=true` clones.
- **Verified and test count** (2026-11-12, Windows 10, strictly offline):
  - `uv run pytest` (parallel across 16 workers): **1340 passed, 1 skipped** (the skip is the Windows symlink-privilege test in `tests/test_browser_login_launch.py`).
  - `uv lock --check` passed; allowed manual CLI checks (`uv run discoop --version`, `uv run discoop --plain agent-guide`, `uv run discoop --plain config list --format json`) passed cleanly.
  - Isolated `%TEMP%` `uv tool` `@stable` install, `uv tool upgrade discoop`, one-time `--force` switch, and non-forced bare-remote `stable` fast-forward/rejection verified in [release-process.md](analyses/release-process.md).
  - `[ASSUMPTION]` / unverified on live GitHub: `.github/workflows/release.yml` execution across the 3-OS runner matrix (and GitHub runner parallel test timing), remote `stable` fast-forward push, GitHub Release creation, live HTTPS `uv tool install ...@stable` / `uv tool upgrade discoop`, and live `releases/latest` detection once releases are published.
- **Next:**
  - Owner manually tags `4788d98` as `v1.0.0` (`git tag -a v1.0.0 4788d98 -m "discoop 1.0.0"`) and creates its GitHub Release (and optionally initializes `stable` at `4788d98`) when ready.
  - Review and merge `feature/releases-and-update-notifier` into `main`, then (only on explicit user instruction) prepare `1.1.0` (`pyproject.toml`, `uv lock`, `uv sync`, `CHANGELOG.md`, `docs/journal.md`), commit on `main`, tag `v1.1.0`, and push `main v1.1.0` to trigger `.github/workflows/release.yml` for the first workflow-driven release and live GitHub verification.
  - Remaining real-account checks from `2026-11-10` and `2026-11-04` (QR on web page, captcha, X-close, `Esc` in TUI browser login, passkey dialog, Edge first-run screens, `source=header`, Settings > Devices, next-day `status`, hard kill, real console Ctrl+C, TUI forum/Ctrl+C, large forum, Linux/macOS).

**Parallel tests by default (P36, [ADR 0026](decisions/0026-parallel-tests.md), [analysis](analyses/test-speed.md)):**
- **What was done:**
  - The full serial suite took about 3:46, so the user asked to run the tests in parallel. Recorded requirement P36 in [requirements.md](requirements.md) and [ADR 0026](decisions/0026-parallel-tests.md) (`Accepted`).
  - `uv add --dev pytest-xdist`: `pytest-xdist>=3.8.0` in the `dev` group of `pyproject.toml`; `uv.lock` only gained `pytest-xdist 3.8.0` and its dependency `execnet 2.1.2` (no other package changed). The runtime `dependencies` are unchanged.
  - `pyproject.toml` `[tool.pytest.ini_options]`: `addopts = ["-n", "auto", "--dist", "worksteal"]`, so plain `uv run pytest` is parallel for people, agents and the release workflow (`.github/workflows/release.yml` unchanged).
  - Commands in `CLAUDE.md` and `AGENTS.md`: `uv run pytest` is parallel by default, `uv run pytest -n0 tests/test_x.py` for one file or for debugging, `uv run pytest --ignore-glob="tests/test_tui_*.py"` as a quick run without the TUI tests. Measurements in [test-speed.md](analyses/test-speed.md); entry in `CHANGELOG.md` `[Unreleased]` under Changed.
- **Decisions:**
  - Chosen: pytest-xdist with `-n auto --dist worksteal` by default. Rejected: keeping the serial run (3:46) and xdist only on request (easy to forget; agents run plain `uv run pytest`). Not now: speeding up the TUI tests themselves (the slowest test bounds the parallel run).
  - `-n0` stays the way to run serially (one small file, `print`, `pdb`); `PYTEST_XDIST_AUTO_NUM_WORKERS` caps the worker count when several runs share the machine.
- **Verified and test count** (2026-11-12, Windows 10, 16 logical cores, in a separate worktree on branch `chore/parallel-tests` based on `e76423a`):
  - Owner's earlier measurements on `main` at `4788d98`: serial 1190 passed, 1 skipped in 226.6 s; `-n auto` 36.5 s and 36.2 s; `-n 8` 40.8 s; `-n auto --dist worksteal` 34.9 s; without the TUI files 17.8 s in parallel (41.2 s serially).
  - With the new default: `uv run pytest` twice: 1252 passed, 1 skipped, 1 failed in 34.50 s and 35.09 s (`created: 16/16 workers`); serially (`-n0`) the same 1254 tests took 212.37 s, so the parallel run is about 6 times faster; `--ignore-glob="tests/test_tui_*.py"`: 978 passed, 1 skipped, 1 failed in 16.61 s; `uv run pytest -n0 tests/test_config.py`: 12 passed in 0.35 s without workers (5.26 s in parallel); `uv lock --check` passed.
  - The one failure, `tests/test_release_notes.py::test_release_workflow_yaml_structure`, is not caused by xdist: the worktree was checked out with `core.autocrlf=true`, so `.github/workflows/release.yml` has CRLF in the working copy (LF in git), and the test fails the same way with `-n0`.
- **Review fix (Claude):** 2 of 5 full parallel runs failed `tests/test_tui_r4g.py::test_footer_lists_p_and_o_and_not_the_ctrl_keys` and 1 of 5 `tests/test_tui_app.py::test_footer_key_runs_the_binding` (both read the footer after a single `pilot.pause()`; they pass on their own). Both now wait with `wait_until`; afterwards 6 full parallel runs in a row passed apart from the line-ending failure above ([analysis](analyses/test-speed.md), section 7).
- **Next:**
  - Decide how to keep LF in fresh Windows checkouts so `test_release_workflow_yaml_structure` passes there (for example a `.gitattributes` with `eol=lf`, or a test that reads the committed blob); not started.
  - Measure the first GitHub Actions run of the release workflow (fewer cores, not measured yet).

## 2026-11-10

**Browser login `discoop login --browser`, AI consent rule, and TUI integration (P31–P33, [ADR 0022](decisions/0022-browser-login.md), [analysis](analyses/browser-login.md)):**
- **What was done:**
  - **Decision and requirements:** Recorded [ADR 0022](decisions/0022-browser-login.md) (`Accepted`; partially supersedes/amends [ADR 0005](decisions/0005-qr-login-without-a-browser.md), [ADR 0008](decisions/0008-fallback-login-token.md), and [ADR 0009](decisions/0009-login-in-agent-mode.md)) and added requirements P31–P33 in [requirements.md](requirements.md).
  - **Engine (`src/discoop/browser_login/`):** Built `find_browser` (Chrome, Edge, Chromium, Brave; `DISPLAY`/`WAYLAND_DISPLAY` check on Linux), `BrowserSession` (separate instance with temporary `--user-data-dir`, `--remote-debugging-port=0`, no automation flags, Edge relaunch handling, cleanup in every exit path, Windows extended-length `\\?\` profile deletion, 24 h stale profile sweep, `atexit`), CDP client (`cdp.py` over `websockets` with silenced frame logger), and `wait_for_browser_token` (`flow.py`, watching `localStorage` `token` and `Authorization` headers to `/api/`, exit code 2 on window close or timeout, exit code 1 on browser/protocol failure).
  - **CLI and config (`login.py`, `cli.py`, `config.py`, `remote_auth/protocol.py`, `errors.py`):** Added `discoop login --browser` with `--browser-path`, `--timeout` (30–1800 s, default 300 s), `--format json` (lower-case `browser` id), and `--progress-json` (`browser_launch`, `browser_open`, `token_captured`, `logged_in` on stderr); added config key `browser-path` (Settings modal preserves any configured value); added `CaptchaRequired` + `BROWSER_HINT`, updated `TOKEN_HINT` and `AUTH_HINT`, and allowed `login --browser` in plain mode while keeping QR and `--token` refused with exit code 2.
  - **AI instructions (`agent_guide.py`, `.claude/skills/discoop/SKILL.md`):** Added the `LOGGING IN` rule requiring AI agents to tell the user a browser window will open (and a passkey dialog may appear), wait for explicit consent, use a timeout > 5 min or background execution, never interact with the window or read secrets, and handle exit codes 0/1/2; verified by `tests/test_agent_guide.py` (`RULE_PHRASES`).
  - **TUI (`tui/modals.py`, `tui/discoop.tcss`):** Added `[ Log in with browser (b) ]` (`#row-login-browser`) right below QR login in `LoginModal`, binding `b` (`Browser`), `-browser` view state (status updates, reused countdown, passkey and `Esc` notices, fitting in 80x24 and 140x40), `GUIDE_KEYS` entry for `b`, constructor-injected seams (`find_browser_fn`, `wait_for_browser_token_fn`), `Esc` cancellation reaching the engine, error hints in `LoginModal` (`CaptchaRequired` pointing to `b` and focusing `#row-login-browser`), and CLI-matching error text when Discord rejects a token read from the browser.
- **Decisions:**
  - In `--format json`, `browser` uses the lower-case id (`"chrome"`, `"edge"`, `"chromium"`, `"brave"`, `"browser"`) matching `--progress-json`, while human text keeps display names.
  - A token rejected by Discord after browser capture exits with code 2 and its own message instead of "stored token is invalid"; `config set browser-path` requires an existing file; an empty explicit path counts as not given; `login --format json` omits `data_dir`; notices use `Output.note`.
  - In the TUI, added `("b", "login dialog: log in with browser")` to `GUIDE_KEYS` (updating `test_help_lists_the_keys_of_the_adr`), updated `test_login_modal_paste_token_and_logout` navigation by one row for `#row-login-browser`, and treated `-browser` like `-qr` for form focus in `test_every_visible_row_of_a_dialog_shows_text` while verifying `Esc` cancellation directly.
  - Version `1.0.0` ([ADR 0023](decisions/0023-version-and-single-source.md)): released as the first `1.x` version under SemVer (earlier `0.x` placeholders were never published); `pyproject.toml` (`project.version`) is the single source of truth, `discoop.__version__` reads installed metadata via `importlib.metadata` (fallback `"0+unknown"`), and `tests/test_version.py` guards against hardcoded versions in `src/`.
- **Verified and test count:**
  - `uv run pytest`: **1186 passed, 1 skipped** (the skip is the symlink test on Windows requiring symlink privileges; offline tests using `FakeCdpBrowser`, `FakeSpawn`, `httpx.MockTransport`, and `MemoryKeyring`).
  - Review follow-up fixes: `--browser-path ""` / whitespace-only CLI option is handled as `str | None` so it counts as not given instead of resolving `Path("")` to `.`; `LoginModal.action_generate_qr` clears any prior browser status/countdown before showing `-qr`; and `docs/handover.md` no longer says TUI browser login is unstarted.
  - Flaky test fix (round 5): during the owner's review of round 4 (1185 passed, 1 failed), `tests/test_tui_app.py::test_a_long_folder_placeholder_keeps_its_end` failed across a minute boundary because `default_name()` changed mid-test; fixed by fixing the clock (`discoop.tui.state.export_stamp`) in `test_a_long_folder_placeholder_keeps_its_end` and `test_folder_and_name_rows_show_the_defaults_and_the_typed_values` (tests only, no `src/` change).
  - Round 6 (`1.0.0` release & single-source version): `uv lock --check` passed, `uv run discoop --version` printed `discoop 1.0.0`, and `uv run pytest` passed **1190 passed, 1 skipped** (+4 tests in `tests/test_version.py`).
  - `[VERIFIED]` locally (2026-11-10): `discoop.browser_login` engine tested against local headless Chrome 157.0.8103.38 and Edge 157.0.4341.42 on Windows 10 using local pages (`127.0.0.1`), never contacting Discord.
  - `[VERIFIED]` on the owner's real account (2026-11-10, Windows 10, [analysis](analyses/browser-login.md) section 7): Chrome `discoop --debug login --browser` (2 runs: `storage readable=true` in 1.0–1.5 s, `token found source=storage`, `profile_removed=true` in 0.41 s and 0.50 s with no WARNING, `GET /users/@me` 200, stored in `WinVaultKeyring`, window closed), Edge `discoop login --browser --browser-path <msedge.exe>` (without `--debug`: succeeded and stored), `discoop login --browser --timeout 30` (2 runs: second run showed `"The login was not finished within 30 seconds."`, hint, and exit code `2`), no leftover `discoop-browser-*` folders or processes after the first 5 runs (not re-checked after the second timeout run), and `discoop ui` started with no reported problem (specific TUI steps unstated).
- **Incidents:**
  1. Edge on Windows relaunches itself: the process Discoop starts exits with code 0 after about 0.05 s and the real browser carries on under another process id. The engine handles it ([analysis](analyses/browser-login.md), fact P1).
  2. During its local check the engine's author left five headless Edge process trees running against five temporary profile folders (its early probes took the relaunch for a failed start). It found them with a read-only process listing, stopped only those five main processes (identified by a unique marker in their command lines) and deleted the folders. The owner's own Chrome and Edge windows were not touched.
  3. A one-off safety-net script of that check once matched and ended its own shell; nothing else was affected.
  4. That agent ran two read-only `git log` commands at the start, although sub-agents never run git.
  5. The agent that wrote the CLI side ran `discoop --plain status` once by mistake: one read-only `GET /users/@me` request went to Discord with the owner's stored real token, and the account's display name and id were printed into that agent's tool output only (nothing was written to the repository). All its other runs of the real CLI were local.
- **Next:**
  - Remaining real-account checks ([analysis](analyses/browser-login.md), sections 6–7): QR code on the web page, a real captcha, closing the window with X, Ctrl+C (exit code 130), `Esc` in the TUI during browser login, the Windows Security passkey dialog, Edge first-run screens, the `header` source (`source=header`), the new entry under Discord Settings > Devices, `discoop status` the next day, a hard kill, and Linux and macOS (plus the earlier unverified round 2 real-account items below).
  - Possible follow-ups (not started): a browser check in `discoop doctor`, and a `browser-path` row in the TUI Settings dialog (`F2`).
  - Pushing and tagging the `1.0.0` release are the owner's decision (push/tag only on instruction).

## 2026-11-09

**Agent skill for using Discoop:**
- Added `.claude/skills/discoop/SKILL.md`, an English skill that explains to an AI agent how to use the tool (rules, workflow, exports, resume, incremental updates, exit codes, recipes). Written at the user's request.
- Verified against the code: `discoop messages --help`, `discoop --help`, `discoop channels --help` and the exit code table from `discoop agent-guide` / `src/discoop/errors.py` (all match).
- Written directly by the main Claude (a single documentation file, no code change); no Discord calls were made and tests were not rerun.
- Follow-up (2026-11-09): description now triggers on read/download/export/analyse Discord data; added "Step 0" (always run `discoop agent-guide` first, fall back to `--help` if it fails, tool information overrides the skill).
- **Next:** the skill duplicates parts of `discoop agent-guide`, so update both when options or exit codes change.

## 2026-11-04

**Antigravity round 2 — resilient export, threads and forums, `--since-last`, disk space check, profiles, token splitting, `agent-guide` and TUI improvements (P26–P30, [ADR 0017](decisions/0017-reliable-export-and-partial-success.md), [ADR 0019](decisions/0019-threads.md), [ADR 0020](decisions/0020-since-last.md)):**
- **Who and how (for a reader who wasn't there):**
  - The brief is in [docs/briefs/antigravity-round-2.md](briefs/antigravity-round-2.md): completing the rest of the plan all at once (resilient export, threads and forums, `--since-last`, token splitting, profiles, `agent-guide`, TUI improvements).
  - Implementation was done by Antigravity: coordinator Argon and Gemini Flash agents, across 6 sequential phases by packages (R2-A, R2-C, R3, R4-D, R4-G, R5-H, R5-G, R5-R, R6-DOC). Their own report is in `prototype/out/antigravity-kolo-2-sprava.md` (local file, git-ignored).
  - Then the result was reviewed by the main Claude (diff, tests), who had the findings fixed by two reviewer agents according to [ADR 0010](decisions/0010-work-through-agents.md). Findings and fixes are in the "Review by the main Claude" section below.
  - Phase descriptions below are aligned with the current code, not with what Antigravity originally delivered.
- **Phase 1 (packages R2-A and R2-C):**
  - **R2-A (resilient export in service, CLI, TUI, [ADR 0017](decisions/0017-reliable-export-and-partial-success.md)):**
    - `service.py` and `ExportWriter` (`src/discoop/export.py`) write incrementally channel by channel into staging folder `<target>.partial` (for zip `<name>.zip.partial`), without keeping the full history in memory.
    - Automatic resume: on request match (`request_fingerprint`), completed channels and their downloaded attachments are skipped and export continues with remaining channels. Event `Events.resumed(done, total)` informs the user; CLI prints `Continuing an unfinished export: N of M channels are already saved.`. Relative time window (`--from 1d`) is calculated from the original `Resume.created` timestamp during resume.
    - Interruption (Ctrl+C / `Cancelled` in TUI / error): writer closes with `complete=False` and triggers `Events.interrupted`. Ctrl+C in CLI exits with standard Unix exit code 130.
    - New exit code `ExitCode.PARTIAL = 9`: CLI reports code 9 when skipping a channel due to missing permissions (403 `NO_ACCESS`, 404 `NOT_FOUND`), attachment download failure (`failed`), or skipped thread. Files omitted by the user (`--no-files` or `--max-file-size`) remain under code 0.
    - The `--print` option combined with resume where completed channels already exist is safely rejected with code 8 before downloading messages.
    - In TUI, `_keep_export_name()` locks the generated name after error/interruption so `F5` automatically continues in the same `.partial`.
  - **R2-C (threads in renderer and export):**
    - Support for nested threads under parent channel: `ChannelMessages.threads` and metadata `thread: Thread | None`. A forum has no messages of its own; content consists of threads.
    - Rendering: in `render/text.py` and markdown export, sections for individual threads with their titles, tags, and messages; in `render/jsonout.py`, flat format with `thread` attribute. Without threads present, output remains byte-for-byte identical to the previous format.
    - Thread attachments go to `files/<parent_folder>/` with deduplication and unique attachment IDs.
- **Phase 2 (package R3, [ADR 0019](decisions/0019-threads.md)):**
  - **Threads in service and CLI:**
    - `MessagesRequest.threads: bool = True` (enabled by default per ADR 0011), can be disabled via `--no-threads`.
    - Forum channels (type 15) and media channels (type 16) are full-fledged targets for `messages`; a forum with `--no-threads` is rejected with code 8.
    - Downloading active and archived threads via `threads/search` with `limit=25`, offset-based pagination, and end detection via empty or partial page (verified in [docs/analyses/thread-probe-2026-11-04.md](analyses/thread-probe-2026-11-04.md)).
    - `--max-messages` and `--last N` limits apply independently to the parent channel and to each individual thread.
    - Error handling: HTTP 403/404 on an individual thread skips the thread with a warning and execution continues with exit code 9 result.
    - New command `discoop threads -s SERVER -c CHANNEL [--from ...] [--to ...] [--refresh] [--format text|json]` for listing a channel's threads cleanly without downloading messages (Rich table in human mode, TSV in plain mode, JSON array with `--format json`).
    - Event `Events.thread` for `--progress-json` emits only channel ID, thread ID, and sequence counts without texts or names.
- **Phase 3 (packages R4-D and R4-G):**
  - **R4-D (`--since-last` and disk space check, [ADR 0020](decisions/0020-since-last.md)):**
    - New module `src/discoop/syncstate.py`: saving last sync state to `sync-state.json` in `paths.data_dir()`, keyed by account ID. Independent from SQLite cache (survives `clear_cache`).
    - Option `messages --since-last` (mutually exclusive with `--from`, `--to`, `--last`): downloads messages with ID greater than `saved_id` (exclusive lower bound `min_id = int(saved_id) + 1`). For a channel without previous state, a default 24-hour window is used with an informational note.
    - Advancing the state occurs only after successful and full completion of export (`complete=True`) and only for channels without limit truncation (`truncated`) and without failed files or threads.
    - Skipping inactive channels: if a channel has saved state and `Channel.last_message_id <= saved_id`, a channel without thread support (or any channel with `--no-threads`) is skipped entirely (0 requests). A text or announcement channel with threads enabled does not download its own messages, but its threads continue to be read. Forum and media channels are never skipped (thread replies do not change the parent's `last_message_id`, `[ASSUMPTION]`). Even the reliability of a text channel's `last_message_id` is an `[ASSUMPTION]`: confirmed on two samples from thread probe and during the real account check on 2026-11-04 (20 of 25 readable channels matched, see the "Real account test" block below). Originally, Antigravity did not skip text channels with threads at all; added after review.
    - After an interrupted and resumed `--since-last` run, channels saved by the interrupted run retain their old state and will be downloaded again next time (duplicates, nothing lost). The run warns about this with a note.
    - Disk space check: before downloading attachments for each channel (`service._check_disk_space`), actual size of new files is calculated (`ExportWriter.bytes_to_download`) and compared against `shutil.disk_usage`. If at least a 50 MB safety margin does not remain, the run fails with code 1 before sending requests to the CDN.
  - **R4-G (TUI: persistent state, profiles, thread switch, folder opening, percentages):**
    - New module `src/discoop/tui/tuistate.py`: persistent state saving to `tui-state.json` in the config folder tied to account ID (restoration of channel selection, time windows, `safe`/`fast` mode, `Folder`/`Name` fields, thread selection, and channel last-exported dates; restored against cached channels, IDs not found there are discarded). State is saved only after loading the account's saved state, disk failure does not crash TUI, and the export date is not written during preview (see review below).
    - `Threads` toggle in the export form switches thread downloading and reflects in the equivalent command in the bottom bar.
    - Profile support via keyboard shortcuts: `P` (uppercase) opens modal to save current selection, time window, and mode as a profile; `p` (lowercase) opens modal to load a saved profile. `L` is "load all servers' channels". A manually edited profile with incorrect value types is tolerated by TUI. Hidden shortcuts `Ctrl+S` and `Ctrl+O` from the first version were removed after review.
    - Keyboard shortcut `o` opens the folder of the last export (for zip, the folder where the zip resides) in the system file explorer (`os.startfile` on Windows, `xdg-open` on Linux, `open` on macOS; safely mocked in tests). It is active after completed export and not while a task is running.
    - Display of completion percentages and estimated time remaining (ETA) in TUI progress bar according to `progress.py`.
    - Formatting functions `format_activity` and `format_last_exported` in `tuistate.py`. Antigravity left them unwired (not displayed in the tree). Wired up only after review: each channel in the tree has a dimmed right-aligned suffix with time since last activity (`now`, `5m`, `3h`, `2d`, `4mo`, `1y`, from `Channel.last_message_id`) and for a channel exported from this account, the last export date (`exp 11-03`, local date, with year if from another year). In a narrow row, export date drops first, then activity; channel name is never truncated. Suffixes refresh after export, after restoring saved state, and every 60 s (rendering in `ChannelTree`, `widgets.py`).
- **Phase 4 (packages R5-H and R5-G):**
  - **R5-H (token splitting, token estimation, and profiles in CLI):**
    - New module `src/discoop/split.py`: pure function `split_markdown(text, max_tokens)` for splitting `messages.md` into parts of at most `max_tokens` with headers `<!-- discoop part X of Y -->`. The function splits only at true message boundaries (line `[YYYY-MM-DD HH:MM]` following a blank line) and channel/thread headings. A message larger than the limit goes into a part by itself with a warning. The original version split even in the middle of a message that contained a line `# Heading`, fixed after review. Known limitation: a line in the body of a message that looks exactly like `[2026-01-01 10:00] x` immediately after a blank line cannot be distinguished from a message header.
    - CLI option `--max-tokens N`: generates files `parts/part-NNN.md`. Antigravity implemented it only with `--out` (rejected with `--zip`) and wrote parts only after export completion. After review, it works with both `--out` and `--zip` (without them, code 8 before API call): parts are written to staging folder or zip on `close(complete=True)` and published together with the export, so a crash before the end leaves no `parts/` in the target, and repeated export into a folder replaces old `parts/part-*.md`. Parts are not included in the manifest.
    - Token estimation in export summary: line `tokens: ~... (estimate, about 4 characters per token)` computed from `messages.md`.
    - Profile support in CLI: `--profile NAME` (loading a profile), `--save-profile NAME` (saving settings before execution), command `discoop profiles` (profile list with `--format json` support), and `discoop profiles delete NAME`.
  - **R5-G (`agent_guide.py` module):**
    - New module `src/discoop/agent_guide.py`: pure function `build_guide(app: typer.Typer) -> str` generating compact text for AI without ANSI colours: fixed sequence `status` → `servers` → `channels` → `messages`, exit code table directly from `ExitCode`, and dynamic list of all registered commands from the Typer app with their single-line descriptions.
- **Phase 5 (package R5-R):**
  - Registration of new CLI command `discoop agent-guide` calling `agent_guide.build_guide(app)` without Rich wrapping (plain text even in human mode) and adding a link to the command in the `NOTE FOR AI AGENTS` section of `--help`.
- **Phase 6 (package R6-DOC):**
  - Complete documentation update: requirements P26–P30 in `docs/requirements.md`, `[Unreleased]` section in `CHANGELOG.md`, update of `docs/design.md`, examples of new options and code 9 in `README.md`, handover update in `docs/handover.md`, confirmation of ADR 0017, 0019, and 0020 as `Accepted` in `docs/decisions/README.md`, and test status in `CLAUDE.md`. This documentation was written by Antigravity before the code was changed after review. Therefore, an agent later went through it and aligned it with the code (keys `P`/`p`/`o`, `--max-tokens` with zip, skipping rule for `--since-last`, tree suffixes, test count).
- **Review by the main Claude (2026-11-04):** after Antigravity, the main Claude reviewed the diff and tests. Found and had fixed:
  - Export resume fingerprint (`request_fingerprint`) ignored `threads` and `since_last`: an interrupted export with threads was resumed even by a run with `--no-threads` (and vice versa for `--since-last`). It now includes them.
  - Modules `split`, `syncstate`, and `tui/tuistate` reported errors via Python `warnings` (`UserWarning`). In terminal TUI, Textual would render them onto the screen; in CLI, they are noise. They now go to the log, and for `split` and `syncstate`, also via a `warning` event. `profiles.load()` still emits `UserWarning` on corrupted file (open item).
  - `split_markdown` split even a message containing a `# Heading` line. It now splits only on real boundaries.
  - Disk check reached into private attributes of `ExportWriter` and repeatedly scanned the old zip. It is now `ExportWriter.bytes_to_download` (zip is read at most once) and `service._check_disk_space`.
  - Some tests had weakened or conditional assertions. Restored to strict assertions.
  - Monkeypatch `FakeDiscord` in tests was applied already upon module import, not just during the test. Fixed.
  - `service.run_messages` had roughly 420 lines. Split into small functions (`_Run` class with steps, e.g. `open_export`, `fetch_channels`, `fetch_channel`, `finish`), behavior unchanged.
  - TUI: startup race condition when saving state (saving before loading saved state could overwrite `tui-state.json` with default values). It is now saved only after loading (`_state_loaded`). Disk failure does not crash TUI (warning in log). `last_exported` is not written on preview. A manually edited profile with wrong value types is tolerated.
  - `format_activity` returned text `0y ago` for some ages. It now gives days under 30 days, months under 365 days (at most `11mo`), years from one year on.
- **Forums and media channels in TUI (2026-11-04, addition):** `SelectionState.is_selectable` also accepts `FORUM_TYPES`, so they can be selected by key, via category, `a`, filter, profile, and saved state. With Threads = no and a forum selected, the form shows a warning and `F5` start is rejected before calling Discord. Help fixed (voice and stage channels can be selected, categories cannot). Channel log with threads also reports their count. Verified only by tests with fake Discord (`tests/test_tui_forums.py`), not on a real account.
- **Completed parts that Antigravity knowingly omitted:** `--max-tokens` also with zip, `--since-last` for text channels with threads (own messages are skipped, threads are read), and channel row suffixes in TUI tree (export date and activity time). Their description is in the phases above.
- **Verified `[VERIFIED]`:**
  - `uv run pytest`: all **870 automated tests** pass (status after review by the main Claude). All run offline against fake Discord (`httpx.MockTransport`).
  - All new scenarios verified by offline tests (resilient export, staging `.partial`, crash and resume, `--threads/--no-threads` switch, forum end-to-end, `threads` CLI, `--since-last`, survival across `clear_cache`, disk check before CDN, `split_markdown`, token limits, profiles, TUI modals and state restoration, `agent-guide`).
- **Real account test (2026-11-04, [analysis](analyses/real-account-check-2026-11-04.md)):** the main Claude ran the tool on the user's real account (VUT FIT server) upon his explicit request, in `safe` mode and with small windows. Exports were saved to a temporary folder which was deleted afterwards.
  - `[VERIFIED]` `doctor` (all 6 checks OK), `status`, `servers`, and `channels` work. The user independently confirmed that `discoop ui` works and that he logged in through it (QR login in TUI works).
  - `[VERIFIED]` `discoop threads` on forum: `--from 3d` listed 2 threads in 5.9 s, `--from 90d --refresh --format json` 61 unique threads (50 archived) sorted by last activity descending in 17 s, across 4 `threads/search` pages (1 active + 3 archived of 25 each). `has_more` was again `true` on the last archived page; the end was reached by the window (`reached_start`). An active thread older than the window was dropped by the window filter.
  - `[VERIFIED]` Forum export (`messages -c <forum> --from 3d --no-files --out DIR`): 2 posts, 22 messages, 11.6 s, full manifest (`messages 0, threads 2, thread_messages 22`), `## thread "..."` sections with header lines (creation, last activity, messages, files, tags), and field `thread: {id, name, parent_id, tags}` in `messages.jsonl`. New finding: `message_count` in the thread list does not include the initial post message (list showed 9 and 11, download returned 10 and 12 messages).
  - `[VERIFIED]` Interrupted export (real network, `KeyboardInterrupt` triggered by script from CLI events, not console signal): after 2nd of 3 channels exit code 130, `<target>.partial` with `complete: false, interrupted: true` and 2 channels, without target; the same command downloaded only the 3rd channel, published target (`complete: true`), deleted `.partial`, and exited with code 0. In the middle of the first channel of forum export (during the 2nd thread) exit code 130, no `.partial`, target, or `.part` files, and retry ran normally.
  - `[VERIFIED]` `--since-last` (state file redirected to temporary file): 2nd run on two study text channels reported own messages as unchanged, downloaded 0 messages, called `threads/search` twice per channel and `/messages` not at all; on two forums 2nd run downloaded 0 messages (1st run 1 thread with 1 message and saved 3 state records).
  - `[VERIFIED]` `last_message_id` (read-only, 25 readable channels out of 28 sampled): field matched the newest available message in 20, in 4 pointed to a newer message (`[ASSUMPTION]` deleted, safe direction for the skip rule), and in 1 the newest message was newer than the field (`[ASSUMPTION]` arrived during sampling, unproven).
  - `[VERIFIED]` `--zip --max-tokens 300 --max-file-size 1` on 3 study text channels over 7 days: 16 messages, 43.5 s, valid zip (`testzip` clean) with `parts/part-001.md` through `part-003.md`, parts are not in the manifest, header of part 1 `<!-- discoop part 1 of 3 -->`, summary `tokens: ~742`.
  - `[VERIFIED]` Two real `--debug --log` logs (13 and 30 lines) contain no token, `Authorization`/`Bearer`, signed URL parameters, server and channel names, or words from exported messages (they contain channel and thread IDs). `--progress-json` produced 4 valid JSON lines on forum export (`channel_start`, 2x `thread`, `channel_done`) without names.
  - `[VERIFIED]` `safe` mode pauses dominate: about 4 to 6 s per thread. `[ASSUMPTION]` A full download of a forum with ~1800 posts would take roughly 2 to 3 hours.
  - **Known limitation (unfixed):** an attachment described differently by the API than by the CDN (in test `size` 25238 and `image/webp`, CDN sent PNG with 36731 B) was re-downloaded upon repeated export into the same folder (`downloaded: 1, already_present: 0`): reuse by ID and size does not recognize it. Observed on a single attachment. Harmless, see section 4 of the analysis.
  - **Open observations:** at exit code 130, `main()` did not print the "Interrupted." line (code has `out.error(...)`, branch appears unreachable, harmless). Not verified whether thread message pages emit `page` events in `--progress-json`.
- **Unverified `[ASSUMPTION]`:**
  - Behavior of `threads/search` across all different Discord channel types beyond the `#help-center` forum and the sample text channel verified in probe analysis ([thread-probe-2026-11-04.md](analyses/thread-probe-2026-11-04.md)).
  - Reaction of real Discord API to unindexed threads (HTTP 202) and private threads (type 12): did not appear in the real account test on 2026-11-04.
  - End-to-end export of a forum with hundreds of posts and export with numerous attachments (on 2026-11-04 on real account, only small windows were tested and 1 attachment was seen).
  - True Ctrl+C from console while waiting for network or during file download (interruption on real account was tested only via script) and a thread receiving a new reply between two `--since-last` runs.
  - Reliability of `Channel.last_message_id` (skip rule for `--since-last`): on real account 2026-11-04, the field matched in 20 of 25 readable channels, in 4 pointed to a newer message, and in 1 the message was newer than the field. Whether replies in threads advance the parent's `last_message_id` remains an `[ASSUMPTION]` (3 threads in the sample were inconclusive).
  - TUI: the user confirmed only that `discoop ui` works and that he logged in via QR. Ctrl+C in TUI, forum selection, and Threads switch on a real account remain unverified. Independently unconfirmed are also shortcut `o`, profiles `P`/`p`, tree suffixes, and persistence of `tui-state.json`.
  - Linux and macOS.

**Next:**
1. Finish testing on a real account what is not yet verified (in detail in [analysis](analyses/real-account-check-2026-11-04.md), section 6):
   - Real Ctrl+C from console (while waiting for network and during file download) and Ctrl+C in TUI, then re-running.
   - TUI on a real account: forum selection, Threads toggle, profiles (`P` saves, `p` loads), opening folder via `o`, channel row suffixes in tree, and persistence of `tui-state.json`.
   - End-to-end export of a forum with hundreds of posts.
   - `--since-last` with a thread receiving a new reply between two runs.
   - Private threads (type 12), HTTP 202, and export with numerous attachments.
2. Open minor items:
   - Linux and macOS are untested.
   - Attachment described differently by API than by CDN (different size and content type) is re-downloaded on repeated export: reuse by ID and size does not recognize it ([analysis](analyses/real-account-check-2026-11-04.md), section 4). Unfixed and harmless. Possible fix: relax size check or save actual size into manifest.
   - At exit code 130, the "Interrupted." line is not printed, even though code has `out.error(...)`. The branch appears unreachable.
   - `--progress-json`: not verified whether thread message pages emit `page` event.
   - `PreviewScreen`: "Save" saves into `export-dir` or `exports` in current folder, not `Documents/discoop` like export from form. Whether it stays this way remains an open question.
   - Repo lacks a `LICENSE` file.
   - `profiles.load()` still emits Python `UserWarning` on corrupted file.
   - `_save_tui_state` is not debounced: writes `tui-state.json` on every selection or form change.
3. The user will decide on pushing commits to GitHub (push only on his instruction).
4. Decision 9 (channel access calculation) remains deferred with low priority.

**Reworked TUI (`discoop ui`, P18–P20, [ADR 0014](decisions/0014-tui-keyboard-one-tree.md)):**
- **User's finding** (2026-11-03, after trying the TUI from ADR 0013 for the first time): many unlabeled buttons, broken arrow keys, channels not collapsed, sluggish interface. Wanted keyboard as primary control, simpler and more terminal-like UI.
- **Causes and fixes:**
  - Blank buttons: `height: 1` with default tall border, border took up the whole row.
  - Sluggishness: entire tree was rebuilt on each selection and cursor jumped to the top. Navigating servers called the network and concurrent workers bypassed safe pacing.
  - Categories were always expanded. A category with no selectable channels showed `[✓]` (`all([])`). Enter on a category expanded it and selected channels at the same time.
  - Preview did not work: sent `--print` and `--no-files` without `--out`, which the service rejected.
  - API pauses could not be interrupted and "Load all" could not be stopped. `q` did not stop execution. `space` and `e` took effect regardless of focus.
  - On invalid token, green `@user` was displayed. Token verification blocked the UI thread, logout occurred without confirmation.
  - Settings from config (`mode`, `delay`, `export-dir`) were not reflected in TUI.
  - "Finished successfully" message appeared even with skipped channels. Summary now lists channels, messages, skipped, truncated, and attachment status.
  - Log was not visible without scrolling. Enter in time window field did not save. Mode in Settings was free text.
  - Preview and Help treated square brackets as markup. Saving preview overwrote the file. Help did not match keys.
  - Variation selectors in names threw off alignment (`display_name()`, display only).
  - `WindowSpec.slug()`/`label()` on `from_=None` and zip path ending with a slash.
  - `filter_channels` matched numbers as substring of ID, now full ID only.
  - `TuiEvents` guessed arguments via `*args`, dead fallback copies of classes were in `state.py` and `bridge.py`.
- **New layout:**
  - Single tree (servers → categories → channels, all collapsed by default), Export panel on the right (selection list and form), log at the bottom, CLI command row, and Footer with mouse-clickable keys. In a narrow window (< 95 columns), one panel at a time.
  - `ansi-dark` theme (terminal colours), Ctrl+P toggles theme. CSS without hex colours, elements 1 row high (`compact=True`), no emojis or large buttons.
  - New `widgets.py`: `ChoiceRow`, `InputRow`, `ActionRow`, `ConfirmRow`, `FormPanel`, `FilterInput`, `SelectedList`, `ChannelTree`, `TextView`, `display_name()`. Dialogs in `modals.py` (Help, Settings, Login, Preview, TimeWindow) have the same look. New `tests/test_tui_modals.py`.
- **Behavior rules:** cursor navigation does not call Discord, one network operation runs at a time, Esc aborts pauses immediately (even during `L`), selection does not change cursor or expansion.
- **Additions outside the original table of fixes:**
  - `X` on selection list clears the entire selection (bulk deselect otherwise vanished along with buttons, added after review).
  - After changing login, selection is cleared. `e` and saving a window on an unselected channel also selects it.
  - Esc in tree with active filter clears the filter. With Target=preview, Attachments and Max MB are hidden.
  - On QR, form is replaced with code. Under 27 rows, border and Footer disappear so QR fits in 80×24.
  - `TextView` renders only visible lines: changing format on 5000 messages takes 0.1–0.4 s (`Static` 1.5–8.7 s). Cost: text selection with mouse does not work in Help and Preview.
  - Token from TUI is saved only after verification on UI thread; Esc during verification saves nothing.
- **Export name in TUI (P21):** `Path` row replaced by `Name` with default name `YYYY-MMDD-HHMM` (date and time). First version merged name and path into one field (bare name to exports folder, slash or absolute path as path) and without `export-dir` went to `exports` in current folder. The user changed this on the same day, see P23 below. Automatic name collision gets `-2`, `-3`. Details in `design.md` (4.8).
- **How the work was done:** per [ADR 0010](decisions/0010-work-through-agents.md) via agents, the main Claude reviewed results (diff, `uv run pytest`, SVG screenshots rendered to PNG). Commits (all on `main`, unpushed): `a7a5347` (decisions P18–P20, ADR 0014), `470c127` (preview jobs and typed events), `4e13acb` (main screen), `4dc5f8b` (dialogs).
- **Verified `[VERIFIED]`:** `uv run pytest`: 385 tests pass. Automated tests via Textual Pilot with fake data, visual appearance verified via screenshots. QR in `ansi-dark` has only black and white segments.
- **Unverified `[ASSUMPTION]`:** execution in a real terminal (Windows Terminal), real account, scanning QR with a phone.
- **Known limitations:**
  - Esc during a running HTTP request takes effect only after it finishes (20 s timeout).
  - Retrying attachment download pauses in `attachments.py` cannot be interrupted immediately.
  - In 80 column width, Footer does not fit completely.
  - CLI command line always shows `--delay` from config.

**Installation and public repo (P22, [ADR 0015](decisions/0015-public-repo-and-installation.md)):**
- The user wants command `discoop` without `uv run`, fast installation on Windows, Linux, and macOS from GitHub. The `filbam/Discoop` repo is public. Chosen `uv tool install git+https://github.com/filbam/Discoop`, instructions for each OS are in README.
- Git history checked: 34 commits, Discord token pattern not found, `Temp/` and `prototype/out/` were never in git.
- **Verified `[VERIFIED]`** (Windows, uv 0.13.7): installation from local clone via `git+file://` in isolated directories takes less than 6 s, `discoop --version` and `--help` work, `discoop.tcss` is installed, `uv tool upgrade discoop` picked up new commit, anonymous `git ls-remote` to GitHub works.
- **Unverified `[ASSUMPTION]`:** installation directly from GitHub, Linux, macOS, automatic download of Python by uv, running TUI from such installation.
- GitHub is at `75f0310`, locally there are 9 unpushed commits.

**Export folder and name in TUI, two fields (P23, [ADR 0016](decisions/0016-default-export-folder-in-tui.md)):**
- The user decided that `Name` should not be a path and export should not depend on the terminal launch directory. The form now has separate rows `Folder` and `Name`. Empty `Name` is `discord-export-<date and time>`, empty `Folder` is `discoop` in the user's Documents (`platformdirs.user_documents_dir()`, identically on Windows, Linux, and macOS). Config `export-dir` takes precedence; in Settings it changes permanently, and in the `Folder` field for a single export. CLI remained unchanged.
- Relative `Folder` resides inside the default folder; `~` and absolute paths are used as-is. Provided `Name` is cleaned via `safe_name` and never escapes the folder. Paths in `--out`/`--zip` are absolute and use slashes, so the CLI command row requires no quoting even on Windows. `export.py` also creates parent folders (both directory and zip), so the default folder is created on first export. A test verifies this.
- `Folder` placeholder shows the actual path. A long path (e.g. Documents in OneDrive) is truncated from the left (`TailInput`) so the end remains visible.
- Tests mock `paths.documents_dir()` in `conftest.py` to a folder in `tmp_path`, real Documents are untouched.
- **Fixed along the way:** `tests/test_attachments.py::test_retries_after_server_errors_and_network_errors` failed on 2026-11-04 after 07:00 UTC (08:00 local time). Three `Downloader` instances in it ran on real clock and fixed links from the test (`NOW + 20 h`) had expired. Added `now=NOW.timestamp`. Unrelated to P23.
- **Verified `[VERIFIED]`:** `uv run pytest`: 426 tests pass, without warnings (`-W error`). The actual directory `C:\Users\Filip\Documents\discoop` does not exist before or after the run.
- **Unverified `[ASSUMPTION]`:** Linux and macOS (path per `platformdirs` documentation), Documents redirected to OneDrive, execution in a real terminal.
- **Out of scope:** `Save` in Preview continues saving to `export-dir`, otherwise `exports` in current directory.

**Antigravity round 1 — logging, diagnostics, JSON outputs, utility modules, and thread probe (P24, P25, [ADR 0018](decisions/0018-logging.md)):**
- **Work breakdown per ADR 0010:** work proceeded in three phases across specialized agent packages (AG-A, AG-B, AG-C, AG-E1, AG-E2, AG-DOC).
- **Package A (`src/discoop/logs.py`, `api.py`, `scrape.py`, `attachments.py`, ADR 0018):**
  - Implemented diagnostic logging infrastructure (`setup_logging`, `teardown_logging`, `DiscoopFormatter`).
  - By default, logging is completely disabled (no handler); when enabled, it attaches exclusively to the `discoop` logger (`propagate=False`). Third-party libraries (`httpx`, `httpcore`, `websockets`) are silenced to `WARNING`.
  - Strict security filter: never logs `Authorization` token, signed attachment URLs (`?ex=&is=&hm=`), message texts, response bodies, usernames, or channel/server names (only numeric IDs).
  - Logging of API calls (`api.py`), pagination (`scrape.py`), and attachment downloads (`attachments.py`).
- **Package B (`src/discoop/progress.py`, `profiles.py`, `tokens.py`, `resolve.py`):**
  - `progress.py`: calculation of completion fraction (`fraction_done`), channel initial snowflake (`window_start_id`), and estimated time remaining (`eta_seconds`, `format_eta`).
  - `profiles.py`: management of named settings profiles in `<config_dir>/profiles.json` (`load`, `save`, `delete`, `names`) with atomic write via `.tmp` and `os.replace`.
  - `tokens.py`: rough estimation of text token count `estimate_tokens` (`len(text)/4`) and formatting `format_tokens`.
  - `resolve.py`: fuzzy search and automatic suggestions on typo in server or channel name (`Did you mean: ...?`) via `difflib.get_close_matches(..., cutoff=0.6)`.
- **Package C (`prototype/probe_threads.py`, `prototype/README.md`):**
  - Created new read-only probe script `prototype/probe_threads.py` to investigate Discord API behavior regarding threads and forums (`threads/search`, offsets, thread types, unindexed 202 responses, and `last_message_id` consistency). The script neither reads nor prints the token and is ready to be run by the user on his account.
- **Package E1 (`src/discoop/cli.py`):**
  - Global CLI flags `--debug` and `--log FILE` work both before and after the subcommand thanks to a hoisting mechanism (`_hoist_mode_flags`).
  - Support for environment variables `DISCOOP_DEBUG` and `DISCOOP_LOG` (CLI flag takes precedence).
  - Disabled Rich spinner under `--debug` to prevent terminal output corruption.
  - Rejection of `discoop ui --debug` with exit code `8` (`BAD_ARGS`) and guidance to use `--log FILE` (`discoop ui --log FILE` is allowed).
  - Cleaned dead code from `cli.py` (`_export_target`, `_export`, `_message_targets`, `_progress`, `_unreadable`, `_local_time`).
- **Package E2 (`src/discoop/cli.py`, `src/discoop/output.py`):**
  - Flag `--format text|json` for commands `servers`, `channels`, `status`, and `config list` via unified method `Output.json()`.
  - New command `discoop doctor` for diagnostics of 6 points: login status (`login`), Discord API reachability (`network`), export directory writability (`export_dir`), free disk space (`disk_space`), cache age (`cache`), and tool version (`version`). Plain mode prints tab-separated lines, human mode a table.
  - Flag `--progress-json` for `discoop messages`: emits structured JSONL events to stderr (`channel_start`, `page`, `pause`, `channel_done`, `skipped`, `warning`).
  - Display of percentages and estimated time remaining (ETA) in `messages` (in human spinner as well as verbose mode).
- **Verified `[VERIFIED]`:** `uv run pytest`: all 511 tests pass (85 new tests in `test_logs.py`, `test_api.py`, `test_progress.py`, `test_profiles.py`, `test_tokens.py`, `test_resolve.py`, `test_cli_logging.py`, `test_servers_channels.py`, `test_doctor.py`, `test_progress_json.py`). Data leak test confirmed that token, CDN signatures, and message texts do not leak into logs.
- **Unverified `[ASSUMPTION]`:** Running `probe_threads.py` on the user's real account.

**Next (superseded by the list above):**
1. The user will decide on pushing. GitHub is at `75f0310`, so installation from GitHub gives old version without new TUI and diagnostics.
2. The user will test `discoop ui` on a real account including QR login (in development `uv run discoop ui`, after push also installation from GitHub, including Linux and macOS if available).
3. The user runs `uv run python prototype/probe_threads.py` on his account (server with forums/threads) and checks output in `prototype/out/`.
4. Step 4: threads and forums (`threads`, `--threads/--no-threads`) based on probe script results.
5. Steps 5–6: `agent-guide` and help texts, `--since-last` with deduplication.
6. Decision 9 (channel access calculation) remains deferred (low priority).

---

## 2026-11-03

**Analysis of Discord web client** → [analyses/discord-analysis.md](analyses/discord-analysis.md)
- The analysis was performed by an agent in the user's Chrome (VUT FIT server) across three runs. The agent only monitored requests sent by the Discord client itself. Did not read the token.
- Main findings:
  - Messages, pins, threads, and search go through REST `/api/v9`. Channel list and active threads arrive via gateway.
  - Hidden channels appear in data as `___hidden___`.
  - Attachment links are valid for 12 to 24 h and do not require a token for download.
  - REST responses do not contain rate-limit headers.
- Open items for verification via prototype are in section 14 of the analysis.

**Incident 1: accidentally sent message.** The agent sent a message `cdn.discordapp.com` from the user's account into a thread in forum `#help-center`. This happened after closing the search panel: the next click hit the message input field and Enter intended for search sent the message.
- The user deleted the message.
- Thread remained followed (Following).
- Precaution: an agent on Discord must not type or press keys ([ADR 0003](decisions/0003-rules-for-agents-in-the-users-browser.md)).

**Incident 2: Chrome closed twice.** In both cases exactly at `tabs_close_mcp`. The agent's tab was the only one in the window the agent had created.
- Precaution: agent never closes tabs or windows (ADR 0003).

**Side effects of the analysis:**
- Several channels were marked as read (list is in the analysis, section "Side effects").
- 4 queries were added to Discord's search history.

**Tool design** → [design.md](design.md)
- Covers commands, outputs (console, folder, zip), human/agent modes, attachments, threads, help, and exit codes.
- Open decisions are in section 15. The name `discoop` is accepted (ADR 0004).

**Git**
- Repo created locally and connected to private `filbam/Discoop` ([ADR 0002](decisions/0002-private-repo-and-identity.md)).
- First commit `f1c6fac` (analysis + design) is pushed.
- Push required logging in as `filbam`, because the default account `FilipBambura` cannot see the private repo.

**Records:** documentation structure established according to requirement P12 ([ADR 0001](decisions/0001-record-everything-and-version-it.md)): `CLAUDE.md`, `CHANGELOG.md`, `requirements.md`, `journal.md`, `decisions/`, `analyses/`.

**New requirements:** P13 (Windows, Linux, macOS) and P14 (QR login in terminal).

**Login analysis** → [analyses/discord-login.md](analyses/discord-login.md)
- Performed by an agent in the Claude built-in browser, in logged-out state. Only observed traffic and read page source code. Sent nothing and did not scan QR.
- **Main finding:** QR login (remote auth gateway `v=2`) can be implemented without a browser. A WebSocket, RSA-OAEP-SHA256, and a single REST POST are sufficient.
- **Unverified** (to be verified by prototype): `Origin` check, captcha on `remote-auth/login`, real frames after scanning.
- **Design updated:** login via QR, Playwright dropped, paths and keyring for all OSs ([ADR 0005](decisions/0005-qr-login-without-a-browser.md)). Open decisions 7 (fallback login) and 8 (`login` in agent mode) added.

**Incident 3: passkey dialog.** The login page calls passkey autofill (`navigator.credentials.get`) on every form render. The built-in browser on Windows popped up a Windows Security system dialog ("Insert your security key"). The user was advised to cancel the window. No login occurred.
- Precaution: warn the user before opening `discord.com/login` in the built-in browser (CLAUDE.md, ADR 0003).
- Built-in browser tab was navigated away from the login page to avoid generating new QRs.

**First prototype.** Decisions from questions recorded as ADR 0006–0009:
- Python, English in the tool, `login --token`, reject login in agent mode.
- Commit rule: commit independently step by step, push only on instruction.
- uv installed via winget.

Code (`src/discoop/`, 42 tests):
- `login` (QR + `--token` + `--trace`), `status`, `logout`, human/agent modes, keyring, REST client.
- `prototype/probe.py` to verify REST endpoints.

**Verified on real Discord** (`login --handshake-only`): QR gateway accepted connection from terminal client (Python `websockets` with `Origin: https://discord.com`). Handshake completed up to `pending_remote_init`. No one logged into the account.

**Deviation from design:** unknown `op`s are ignored (as in the web client) and only logged to trace. Unknown close code ends with an error advising `--token`.

**Prototype run by the user (2026-11-03 afternoon):**
- **`discoop login` via QR works on real account.** First attempt passed without captcha.
  - Scan ~52 s, phone confirmation ~16 s.
  - Token is stored in Windows Credential Manager.
  - QR was scannable in terminal (PowerShell).
  - `timeout_ms` was ~5.7 min, so QR validity fluctuates more than expected.
- **`prototype/probe.py`** (13 API requests, no rate limits and no rate-limit headers), results in [analysis, section 15](analyses/discord-analysis.md#15-prototype-verification-2026-11-03):
  - list of servers and channels goes via REST, gateway won't be needed,
  - `limit` max 100,
  - `after` returns closest newer messages sorted from newest,
  - active threads via `threads/search?archived=false`. `guilds/{id}/threads/active` is for bots only,
  - CDN works without token,
  - `refresh-urls` works.
- **Design updated:** items [PROTOTYPE] are now [VERIFIED].
- **Still open:**
  - format of `429`,
  - pins pagination,
  - mismatch between `total_results` 15 and 13 returned threads in forum,
  - `refresh-urls` on expired URL.

**Step 1 of implementation (servers, channels, config, cache, name search):**
- Done, 71 tests, commits `1d31ba4` and `ce466c7`.
- Run against real Discord so far only by the user; per CLAUDE.md only the user calls the API.
- **Deviations from design:**
  - `--include-hidden` dropped because REST appeared not to return hidden channels. Later test proved otherwise.
  - `default-server` is stored as ID.
  - `export-dir` deferred to export step.
- **Cache** cleared on both login and logout to avoid stale servers after logging in with another account.

**User test** (log in `Temp/`, local, git-ignored):
- **Working:** `servers`, `channels` (tree, `--flat`, `--type`), `config set default-server`, `--agent channels`.
  - 8 servers, VUT FIT has 390 channels.
- **Finding:** REST `GET /guilds/{id}/channels` returns **also channels the user cannot see**, with real names.
  - For example, entire categories `moderation`, `logging`, `fillers`.
  - Even `#přípravné-kurzy` (`1549737445002584094`), which the client displayed as `___hidden___`.
  - Previous claim "REST does not return hidden channels" was incorrect. Analysis (sections 13–15) and design (4.3) are corrected.
  - Resolution is open decision 9: channel access calculation from permissions and roles.

**Change in way of working** ([ADR 0010](decisions/0010-work-through-agents.md)):
- Main conversation ran out of context during implementation and had to be summarized.
- The user determined: work is done by agents, the main Claude manages them, reviews results (diff, `uv run pytest`), and commits.
- Agents do not commit. Writing agents do not modify the same files, and only one writes the journal in a work block.
- `CLAUDE.md` has a new section "Working through agents" and current project status.

**Channel access investigation** → [analyses/channel-access.md](analyses/channel-access.md)
- Performed by an agent from documentation and third-party code, without Discord API calls.
- REST can return computed permissions via `GET /guilds/{id}/channels?permissions=true` (Userdoccers).
- Fallback route: roles from `GET /users/@me/guilds/{id}/member` and local calculation from `permission_overwrites`. `/guilds/{id}/roles` not needed.
- Everything is currently an **[ASSUMPTION]**. Verification on the user's account is deferred along with decision 9.
- `is_hidden` (`___hidden___`, flag `1<<17`) is gateway obfuscation. REST never sends it, so it filters nothing in `channels`.
- Discord announced (changelog 2026-08-12) that REST will stop returning inaccessible channels: for bots from 2026-11-16, for users later.
- Opt-in channels are purely a display preference.
- **Decision 9 (access calculation) is deferred with low priority.** The user stated it is not important if it causes issues. Work-in-progress `prototype/access_probe.py`, `src/discoop/permissions.py`, and `tests/test_permissions.py` were discarded.

**Decisions 4 to 6** ([ADR 0011](decisions/0011-default-behaviour-of-messages.md)): the user confirmed that threads are downloaded by default, default window is 24 h (full history only via `--from all`), and format in agent mode is `text`.

**Step 2 of implementation (`messages` to console):**
- Done, 161 tests (90 new). Discord is replaced in tests by `httpx.MockTransport` with anonymized messages.
- Not run against real Discord. Locally only `--help` and invalid inputs ending before API calls were run.
- **Content:**
  - channel selection by name, ID, or pattern, including multiple `-c` options,
  - time window converted to snowflake, pagination by 100 via `before`, `--last N`,
  - formats `text` and `json`, coloured text in human mode,
  - attachments only as name, size, and URL.
- **Errors per access investigation:**
  - `403` with code 50001/50013 → code 5,
  - other `403` (anti-abuse, Cloudflare) → code 1, because it is not a missing permission,
  - `404` → code 4,
  - empty first page → note about possible missing `READ_MESSAGE_HISTORY`.
- **Deviations from design** (in detail in design, section 4.5):
  - without `--from`, window is 24 h before `--to`,
  - `--last` can be combined with `--from`/`--to`,
  - messages of types 20 and 23 (bot command responses) are not system messages,
  - time zone in header is offset `UTC+01:00`, not name,
  - `--all-channels` awaits access calculation (decision 9, deferred),
  - `--max-messages` and `--include-system` also added from design.
- **Unverified on account:** `GET /channels/{id}` (channel ID not in cache), error codes `403`, and format of forwards.

**User test of step 2** (log in `Temp/`, local, git-ignored):
- **All 6 commands worked** (VUT FIT, channel `1282100102743330887`):
  - human mode with default 24 h window (including 24 h note at the end) and `--last 30`,
  - `--agent --from 7d`,
  - `--agent --format json --from 2026-11-01 --to 2026-11-02`: `--to` with bare date takes the full day, window ends 2026-11-03 00:00,
  - `--agent -v --from all --max-messages 300`: pagination by 100 with progress on stderr, `WARNING` and `truncated: yes`,
  - channel without access (`1549737445002584094`): `ERROR NO_ACCESS`, exit 5.
- **Verified on account:**
  - Channel without `VIEW_CHANNEL` returns `403` with code `50001` or `50013`. Which one, output does not show. Recorded in access analysis (sections 1 and 7) and design (section 9).
  - Forward was displayed with `(forwarded)` tag, text, and attachment. Tag requires `message_reference.type 1` and non-empty `message_snapshots`.
- **Output fixes** (agent, 3 new regression tests, total 164):
  - **Duplicate URL:** GIF sent as bare URL had `[image]` with the same URL below text. Embed now does not repeat URL that the message already displays: only tag with title remains (`[gif] "…"`), embed without title is omitted. JSON retains full embeds as it is a complete structured format for scripts and future export.
  - **Reactions:** two `[reactions]` rows on a single message were not found in the log. Code prints one row per message and Discord sends one item per emoji. Super reactions (`count_details.burst`) are now next to count, `🔥5 (2 super)`, in JSON array `reactions[].super`.
  - **Blank lines:** double blank lines in human mode were also not found in the log. As a safeguard, blank lines at the start and end of message text and rich embed description are stripped, and `\r\n` is converted to `\n`. Text ending in `\n` previously produced two blank lines after the message in human mode.
  - Rich embed without URL and title had an extra space after `[embed]`.
- **Considered, left unchanged:** reply to message with only attachment lacks quotation (`reply-to name` without text). Rich embed having only an image (no URL, title, or description) is not displayed in output at all.

**Step 3 of implementation (attachments, `--out`, `--zip`, manifest):**
- Done, 223 tests (59 new in `test_attachments.py` and `test_export.py`).
- **Attachment downloads:**
  - Separate client without token: token is sent exclusively to Discord API; CDN requests (`cdn.discordapp.com`, `media.discordapp.net`) go without `Authorization` header.
  - Refreshing expired signatures via `POST /attachments/refresh-urls` in batches of 50 before download (when expiring within 60 s) as well as after CDN rejection (403, 404, 410) at pacing configured in settings (`delay`).
  - Safe filenames for Windows, Linux, and macOS: truncation to 100 characters and 200 bytes, preservation of extension, trimming of dots and spaces, prefix `_` for Windows reserved names (`CON`, `NUL`, ...).
  - Channel folders truncated to 50 characters, suffix `_<id>` on channel name collisions.
  - Failed attachment (network error, redirect loop, invalid URL) does not stop export of the whole channel, recorded in manifest, and error summary goes to stderr.
- **Export to folder and zip:**
  - Structure: `manifest.json`, `messages.md`, `messages.jsonl`, `channels/<name>.md`, and `files/<channel>/<attachment_id>_<name>`.
  - Atomic writing: `.part` for downloaded files and staging folder for zip archive.
  - Protection of existing data: rejection of non-empty folder or file that is not a discoop export.
  - Repeated run reuses already downloaded files with matching ID and size (`present`), including from a previous `.zip` archive.
  - Compression in zip: `ZIP_DEFLATED` for texts and manifest, `ZIP_STORED` for files in `files/`.
- **Options and configuration:**
  - `--print` alongside export prints messages to stdout with relative paths, summary goes to stderr.
  - `--no-files` skips file downloads (`skipped`), `--max-file-size` skips files over specified size in MB.
  - Formats `md` and `jsonl` are also available for console.
  - `discoop config set export-dir <path>` saves default folder for relative export paths as an absolute path.
- **Confirmed defaults:** batching by 50 and 60 s margin for `refresh-urls`, sequential CDN download with 60 s timeout and 3 retries (1 s and 2 s pauses), name limits 100/50 characters and 200 bytes, target verification via `manifest.json`, `ZIP_STORED` for `files/`.

**User test of step 3** (log in `Temp/`, local, git-ignored):
- **All 4 commands worked** (VUT FIT, channel `1282100102743330887`, 84 messages over 7 days, 5 attachments):
  - `--out exports/fit-krok3`: successfully downloaded 4 attachments; one attachment (8.3 MB) failed with HTTP 504 Gateway Timeout from CDN – export correctly continued, did not crash, and recorded error in manifest as well as warning on stderr.
  - Repeated run into the same directory: immediately recognized 4 already downloaded files (`already present: 4`), did not re-download them, and attempted only the missing attachment.
  - `--zip exports/fit-krok3.zip --print`: created zip archive in agent mode (all 5 attachments downloaded including the one that previously got 504) and printed messages with local paths (`files/...`) to stdout.
  - `--out exports/fit-nofiles --no-files`: export without downloading attachments (`skipped: 5`), messages and manifest saved.
- **Verified on account:**
  - Resilience against CDN errors (504): export did not crash and continued correctly.
  - Detection and reuse of existing attachments works.
  - Zip archive and export without attachments (`--no-files`) work.

**Safe and fast download modes (safe browser simulation vs fast batch pace):**
- The user noticed that the tool downloads too fast and suggested two download modes:
  1. `safe`: downloads slowly and safely, mimics browser scrolling, includes random intervals and pauses. Default mode.
  2. `fast`: previous state with batch downloading by 100 messages and fixed `delay` pause.
- **Implementation and verification (231 tests, 8 new/updated):**
  - `config.py`: key `mode` (`safe` / `fast`), function `parse_mode`, configuration `discoop config set mode safe|fast`.
  - `api.py`: in `safe` mode, batch of 25 messages (`limit=25`), random jitter 2.0 to 4.5 s before each API call, reading pauses 8.0 to 15.0 s every 5 to 8 requests (reporting via `on_pause`), pause 3.0 to 6.0 s on channel switch (`between_channels()`), pause 1.0 to 3.0 s between CDN file downloads (`between_files()`), backoff on 429 with automatic interval doubling. In `fast` mode, batch of 100 messages, fixed `delay` (default 1.0 s), no reading pauses and no pauses between files/channels.
  - `scrape.py`: support for optional `page_size`, governed by `api.page_size` (25 for safe, 100 for fast).
  - `attachments.py`: wiring `between_files()` into attachment download loop for subsequent files (2..N).
  - `cli.py`: new options `--safe`, `--fast`, and `--delay` in `discoop messages`, mutual conflict check for `--safe` and `--fast`, passing mode to `DiscordAPI`, and wiring `on_pause` to Rich status / agent stderr notification.
  - `export.py` & `manifest.json`: manifest records used mode in object `query.mode` (`"safe"` / `"fast"`).

**Renaming "agent mode" to "plain mode" (`--plain`, P15, [ADR 0012](decisions/0012-rename-agent-mode-to-plain.md)):**
- The user suggested renaming the mode so it clearly expresses the absence of color rendering and graphical elements, while retaining information in help that it is suitable for AI agents and scripts.
- Approved solution:
  - Primary option is `--plain` (Plain mode), environment variable `DISCOOP_PLAIN=1`.
  - Original `--agent` and `DISCOOP_AGENT=1` remain fully functional as a hidden alias for backward compatibility.
  - In help and section `NOTE FOR AI AGENTS`, it is explained that plain mode removes colors and rich formatting, saving tokens and making output easily parseable.
- Verified by automated tests (232 tests).

**Interactive terminal user interface TUI (`discoop ui`, P16–P17, [ADR 0013](decisions/0013-tui-and-shared-service-layer.md)):**
- The user requested for `--human` mode a visual terminal environment in Discord/file-explorer style controlled by keyboard (arrows, `Space`, `Tab`, `Enter`, shortcuts), acting as an overlay on top of tool core, dynamically adjusting to window resizing, and containing built-in Help with instructions as well as `discoop --help` output.
- **Shared service layer (`src/discoop/service.py`):**
  - Orchestration of `list_servers`, `list_channels`, `load_all`, `resolve_targets`, `validate_export_target`, and `run_messages` extracted from `cli.py` into `service.py`.
  - CLI and TUI call the same functions; every job in TUI is translated to a `MessagesRequest` and displays the equivalent `discoop messages ...` command in the bottom bar.
- **TUI architecture and state (`src/discoop/tui/`):**
  - Built on `Textual` library (lazy import only on `discoop ui` / `--ui`, in `--plain` mode exits with code `8`).
  - `state.py`: channel selection management across servers (`SelectionState`), global and individual time windows (`WindowSpec`), grouping channels with the same window into jobs (`plan_jobs`, with subfolders `01-7d`, `02-...` for multiple jobs), channel search without diacritics and emojis (`filter_channels`).
  - `bridge.py`: interruptible sleep (`CancelToken`) for immediate stopping (`Esc`) even during reading pauses in `safe` mode, and bridging events from background worker thread to UI.
  - `app.py`, `modals.py`, `discoop.tcss`: 3-column Discord layout (*Servers* │ *Channels* │ *Export and Progress*) with automatic switch to tabs on narrow windows (< 95 columns), buttons for refreshing servers, channels of selected server, and loading everything at `safe` pace, modal dialogs for custom channel time window (`E`), built-in message viewer, settings, login, and Help screen (`F1`/`?`) with generated `discoop --help` output.

**Next (superseded by the list in section 2026-11-04):**
1. Step 4: threads and forums (`threads`, `--threads/--no-threads`).
2. Decision 9 (channel access calculation) remains deferred (low priority).

Completed from previous list: step 3, its test by the user, safe/fast download modes, and interactive terminal UI (discoop ui).

---

## 2026-11-02

**Brainstorming.** The user described requirements → [requirements.md](requirements.md) (P1–P11).
- Reviewed old script `discord-script.js` (FITSeeker):
  - ran from browser console and called `GET /api/v9/channels/{id}/messages`,
  - paginated via `before` and calculated time window via snowflake,
  - handled `429` and paused 800 ms between requests.
- Findings:
  - Discord API authenticates with a **token** in the `Authorization` header, not cookies. `login` therefore must obtain and store the token.
  - Name `scoop` collides with the Windows package manager Scoop.
