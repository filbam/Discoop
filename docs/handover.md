# Project discoop Handover (Handoff)

This document serves as a complete and clear summary of the `discoop` project status for the next AI agent or developer taking over work on the repository.

---

## 1. Introduction and required reading

Before starting any work, the following documents **must be read**:

1. **[CLAUDE.md](../CLAUDE.md):**
   - **Work through subagents ([ADR 0010](decisions/0010-work-through-agents.md)):** The main Claude directs work, assigns specific bounded tasks to agents, and checks results (diff, tests) himself. Subagents do not commit or push on their own.
   - **Prohibition of live Discord API calls:** Automated tests run **exclusively offline** via MockTransport and anonymized fixtures in `tests/fixtures/`. Live API may only be run by the user on their account.
   - **Git rules:** Branch `main`, author `filbam <f.bambura@gmail.com>`. Committing after every verified step (done by the main Claude), **`git push` forbidden without explicit instruction from the user**.
   - **Record everything ([ADR 0001](decisions/0001-record-everything-and-version-it.md)):** Every change, decision, or requirement must be recorded in documentation within the same work step.
2. **[docs/requirements.md](requirements.md):**
   - List of all user requirements (P1–P33). Source of truth for what the tool should do.
3. **[docs/design.md](design.md):**
   - Architecture of the entire tool, package structure of `src/discoop/`, command list, exit codes, data flows, and open questions.
4. **[docs/journal.md](journal.md):**
   - Chronological journal of development so far, test records on the user's real account, and resolved incidents.
5. **[docs/decisions/README.md](decisions/README.md):**
   - Registry of all Architectural Decision Records ([ADR 0001](decisions/0001-record-everything-and-version-it.md) to [ADR 0022](decisions/0022-browser-login.md)).
6. **[docs/analyses/thread-probe-2026-11-04.md](analyses/thread-probe-2026-11-04.md):**
   - Results of probe measurements for threads, forums, and `last_message_id` on a real Discord account with strict distinction between `[VERIFIED]` and `[ASSUMPTION]`.
7. **[docs/analyses/real-account-check-2026-11-04.md](analyses/real-account-check-2026-11-04.md):**
   - Results of testing the `discoop` tool on a real account (2026-11-04, `safe` mode, small windows): what was verified, known limitation with attachments, open observations, and list of what remains unverified.
8. **[docs/analyses/browser-login.md](analyses/browser-login.md):**
   - CDP browser login analysis, local headless Chrome/Edge verification, and results of the first real-account check on Windows 10 (2026-11-10).

---

## 2. Current project status (as of 2026-11-10)

- **Test coverage:** All **1186 automated tests** pass (`uv run pytest`; 1 skipped on Windows without symlink privileges). All run offline against fake Discord (`httpx.MockTransport`) and fake CDP (`FakeCdpBrowser`, `FakeSpawn`). Round 2 features were partially verified on a real account on 2026-11-04 (details in [analysis](analyses/real-account-check-2026-11-04.md)), and CLI browser login (`discoop login --browser` with Chrome and Edge, `--timeout 30` exit code `2`) plus starting `discoop ui` were verified on a real account on Windows 10 on 2026-11-10 (details in [browser-login.md](analyses/browser-login.md), section 7). What remains unverified is in section 4.
- **Origin of round 2:** the implementation (P26–P30) was done by Antigravity according to `docs/briefs/antigravity-round-2.md`, then reviewed by the main Claude and findings were fixed. What was found and fixed is in [journal.md](journal.md), section 2026-11-04.
- **Installed environment:** Python 3.12+, project managed via `uv`. Development in the repo runs via `uv run discoop ...`, the user has the `discoop` command installed (`uv tool install git+https://github.com/filbam/Discoop`, instructions in [README.md](../README.md)).
- **The repo is public** (P22, [ADR 0015](decisions/0015-public-repo-and-installation.md)). No token, cookies, or other people's names and message texts may go into git. `[VERIFIED]`: installation from local clone on Windows. `[ASSUMPTION]`: installation from GitHub, Linux, macOS.

### Overview of implemented features

#### A. Authentication and identity (`login.py`, `remote_auth/`, `browser_login/`, `tokenstore.py`)
- **`discoop login`:**
  - Primary path: **QR login without a browser** in the terminal ([ADR 0005](decisions/0005-qr-login-without-a-browser.md), P14) via Discord remote auth gateway (WebSocket, RSA-OAEP-SHA256 key exchange, QR rendering via `segno`).
  - Support for test handshake without login (`--handshake-only`).
  - When Discord asks for a captcha during QR login, `CaptchaRequired` (exit code 1) recommends `login --browser` first and `login --token` as a last resort (`BROWSER_HINT`, P32).
  - **`login --browser`** (added 2026-11-10, [ADR 0022](decisions/0022-browser-login.md), P31 to P33, [analysis](analyses/browser-login.md)): opens the user's own Chrome, Edge, Chromium or Brave in a separate window with a temporary profile; the user logs in there (password, QR on the page, captcha, 2FA); Discoop reads the token over the DevTools Protocol (package `browser_login/`), closes the window, verifies the token and stores it like the other ways. Options `--browser-path`, `--timeout` (30 to 1800, default 300), `--format json`, `--progress-json`; config key `browser-path`. Exit code 2: window closed, time ran out or token not accepted; exit code 1: no usable browser or desktop session. **Partly verified on a real account on Windows 10 (2026-11-10, [analysis](analyses/browser-login.md) section 7):** Chrome `--debug` (`source=storage`, `profile_removed=true` in 0.41–0.50 s, `WinVaultKeyring`), Edge `--browser-path`, `--timeout 30` returning exit code `2`, clean folder/process removal, and starting `discoop ui` succeeded; remaining unchecked items are in section 4. The TUI login dialog (`b`) reuses `login.CaptchaRequired`, `login.find_login_browser` and the engine's `wait_for_browser_token` with its own listener.
  - Fallback login via `--token` from hidden interactive input or stdin ([ADR 0008](decisions/0008-fallback-login-token.md)). In plain mode, `login` without `--browser` and `login --token` are rejected with code `2` ([ADR 0009](decisions/0009-login-in-agent-mode.md)); `login --browser` is the one exception ([ADR 0022](decisions/0022-browser-login.md)), and the AI instructions (`discoop agent-guide`, the skill) make an agent tell the user and wait for their consent before running it.
- **`discoop status`:** Prints login status, user account information, and local cache age.
- **`discoop logout`:** Securely removes the token from the OS system keyring (Windows Credential Manager, macOS Keychain, Linux Secret Service).

#### B. Servers, channels, and configuration (`cache.py`, `config.py`, `resolve.py`)
- **`discoop servers` & `discoop channels`:**
  - Listing servers and channels, storing them in local SQLite database `cache.db` (located according to OS standards via `platformdirs`).
  - Searching and filtering channels by ID, exact name, or glob patterns (`resolve.py`). Searching is resilient to diacritics and letter case, and strips emoji.
- **`discoop config`:**
  - Managing configuration values: `browser-path`, `default-server`, `delay`, `export-dir`, `mode` (`safe` / `fast`).

#### C. Downloading messages (`cli.py`, `service.py`, `scrape.py`, `snowflake.py`)
- **`discoop messages`:**
  - Time windows: `--from`, `--to` (date, date and time, or relative `7d`, `48h`, `2w`, `now`, with `--from` also `all`), `--last N` returns N newest messages. Conversion to Discord snowflake ID.
  - Output formats for console: `text` (default plain text), `md` (Markdown), `json`, and `jsonl`.
  - Flag `--print` (concurrent printing of messages alongside export).

#### D. Resilient export and downloading attachments (`export.py`, `attachments.py`, [ADR 0017](decisions/0017-reliable-export-and-partial-success.md), P26)
- **Channel-by-channel writing and staging `<target>.partial`:**
  - `ExportWriter` writes messages and files progressively per individual channel into temporary location `<target>.partial` (for zip archive `<name>.zip.partial`), without holding the entire history in memory.
  - Atomic publication to the target folder or zip file occurs only upon successful completion of the entire run (`close(complete=True)`). A previous finished export is never overwritten by an interrupted run.
- **Automatic resume:**
  - If an in-progress `<target>.partial` exists when starting export and its fingerprint (`request_fingerprint`) matches the request, the run automatically skips completed channels and their downloaded attachments and continues downloading the remaining channels. The fingerprint also includes `threads` and `since_last`: an interrupted export with threads does not continue a run with `--no-threads`, and a normal run does not pick up from `--since-last` (and vice versa); it starts over. Download mode and `--max-tokens` do not alter the fingerprint.
  - Relative windows are calculated from the original run creation time (`Resume.created`).
  - The `--print` flag in combination with a resume where completed channels already exist is rejected (code 8) before downloading messages.
- **Partial result and return code `ExitCode.PARTIAL = 9`:**
  - Skipping an inaccessible channel due to missing permission (HTTP 403 `NO_ACCESS`), non-existence (HTTP 404 `NOT_FOUND`), attachment download error, or skipping a failing thread results in exit code `9`.
  - Intentional exclusion of files by the user via `--no-files` or `--max-file-size` does not trigger code 9 (returns code 0).
- **CDN client and security:**
  - Attachments are downloaded by a separate HTTP client **without token in headers** (protection against leaks on CDN redirects).
  - Refreshing expired signatures via read-only `POST /attachments/refresh-urls` in batches of 50 (60 s ahead of expiry or after 403, 404, 410 errors) progressively per individual channel.
  - Safe file names for Windows, Linux, and macOS (limit 100 characters / 200 bytes, trimming dots and spaces, prefix `_` for reserved Windows names like `CON`, `NUL`).
  - Atomic writing of individual files with `.part` extension.
  - Reuse of already downloaded files with matching ID and size (`present`); CDN failure does not stop export of remaining messages.

#### E. Download modes: `safe` vs `fast` (`api.py`)
The tool allows pacing selection via configuration (`discoop config set mode safe|fast`) or via flags `--safe` / `--fast`:
1. **`safe` (default mode):**
   - Mimics natural user behaviour in a browser with emphasis on minimizing risk of detection and account ban.
   - Batches of 25 messages (`limit=25`).
   - Random jitter of 2.0 to 4.5 s before every API call.
   - Reading pauses of 8.0 to 15.0 s every 5 to 8 pages (with notification via `on_pause` callback).
   - Pause of 3.0 to 6.0 s when switching channels (`between_channels()`).
   - Pause of 1.0 to 3.0 s between downloading individual files from CDN (`between_files()`).
   - Automatic exponential backoff with doubling interval on HTTP 429.
2. **`fast`:**
   - Batches of 100 messages (`limit=100`).
   - Fixed configurable `delay` (default 1.0 s).
   - No random reading pauses or delays between channels and files.

#### F. Plain mode (`--plain`, [ADR 0012](decisions/0012-rename-agent-mode-to-plain.md), P15)
- The mode originally named "agent mode" was renamed to **Plain mode**.
- Flag `--plain` or environment variable `DISCOOP_PLAIN=1`.
- Output is clean, unstyled text without ANSI codes, tables, or Rich elements (saves tokens for AI agents and is directly parseable).
- The original flag `--agent` and `DISCOOP_AGENT=1` are retained as fully functional hidden backward aliases.

#### G. Interactive terminal user interface TUI (`discoop ui`, [ADR 0013](decisions/0013-tui-and-shared-service-layer.md), P16–P17)
- **Shared service layer (`src/discoop/service.py`):**
  - Dedicated business logic for loading servers (`list_servers`), channels (`list_channels`), complete structure (`load_all`), resolving targets (`resolve_targets`), and downloading messages (`run_messages`).
  - Shared for both CLI and TUI. TUI actions map to `MessagesRequest`.
- **Textual application (`src/discoop/tui/`, layout and keys per [ADR 0014](decisions/0014-tui-keyboard-one-tree.md)):**
  - Main screen: single tree (servers → categories → channels, all collapsed by default), Export panel on the right (selection list and form), log at the bottom, row with CLI command (`c` to copy), and clickable Footer. In narrow window (< 95 columns) one panel at a time (`1`, `2`, `3`, Tab).
  - Primary keyboard control: arrows, Space/Enter, `/` filter, `e` custom channel window, `x`/Delete removes from selection, `X` clears entire selection, `r`/`R`/`L` load (`L` = channels of all servers), `F5` export, Esc cancels operation, `q` quit, `P` saves and `p` loads profile, `o` opens latest export folder. Table is in ADR 0014, new keys in its "2026-11-04 Addition" section.
  - Appearance: `ansi-dark` theme (terminal colours, Ctrl+P switches theme), controls `compact=True`, no emoji.
  - Rules: cursor movement does not call Discord, one network operation runs at a time, Esc also cancels safe mode pauses (`CancelToken` in `bridge.py`), selection changes neither cursor nor expanded state.
  - `widgets.py`: `ChoiceRow`, `InputRow`, `TailInput`, `ActionRow`, `ConfirmRow`, `FormPanel`, `FilterInput`, `SelectedList`, `ChannelTree`, `TextView`, `display_name()`.
  - **Export folder and name (P21, P23, [ADR 0016](decisions/0016-default-export-folder-in-tui.md)):** the form has separate `Folder` and `Name` rows (both empty by default). Empty `Name` is `discord-export-<date and time>` (`discord-export-2026-1104-0108`), entered `Name` is only a name and never a path. Empty `Folder` is `discoop` in the user's Documents (`paths.default_export_dir()` via `platformdirs`, Windows, Linux, and macOS), config `export-dir` takes precedence, relative `Folder` resides in the default folder. Changed in Settings (`Export folder`, permanent) or in `Folder` field (single export). CLI does not change. `[VERIFIED]` on Windows, `[ASSUMPTION]` on Linux and macOS.
  - Job planner (`plan_jobs` in `state.py`): channels with identical window into one job, subfolders for different windows (`01-7d`, `02-24h`...).
  - **Dialogs (`modals.py`):** Help (`F1`/`?`, live `discoop --help`), Settings (`F2`), Login (`F3`, QR, browser `b`, or token, with error hints and captcha redirection, token saved after verification), Preview, TimeWindow.
  - **Improvements from round 2 (P30):**
    - Persistent TUI state in `<config_dir>/tui-state.json` tied to account ID (`tuistate.py`): automatic restoration of channel selection across servers, time windows, `safe`/`fast` mode, `Folder`/`Name` fields, threads toggle, and channel last export dates. Restores against cached channels; IDs not in cache are dropped. State is saved only after saved account state was loaded (fixed startup race condition that could overwrite it with default values). Disk failure does not crash TUI (warning in log). Write is not debounced: runs on every change (`_save_tui_state`). Last export date is not written during preview.
    - Threads toggle in export form to enable/disable downloading threads.
    - Profile management via keyboard shortcuts: `P` (uppercase) saves current selection, time window, and mode as a profile, `p` (lowercase) loads saved profile. `L` is "load channels of all servers". Profiles are in `profiles.json` alongside CLI profiles. Hand-edited profile with invalid value types is tolerated by TUI.
    - Keyboard shortcut `o` opens the latest export folder (for zip, folder where zip resides) in system file explorer (`os.startfile` / `xdg-open` / `open`). Active after completed export, not during running job.
    - Channel row suffixes in tree: each channel has a dimmed right-aligned suffix with time since last activity (`now`, `5m`, `3h`, `2d`, `4mo`, `1y`, from `Channel.last_message_id`), and for channel exported from this account, date of last export (`exp 11-03`, local date, with year if from another year). In narrow row, export date drops first, then activity; channel name is never truncated. Refreshed after export, after state reload, and every 60 s (`format_activity` and `format_last_exported` in `tuistate.py`, rendering in `ChannelTree`).
    - Percentage and estimated time (ETA) display in progress bar per `progress.py`.
    - Pinning export name in `Name` field after interruption, so pressing `F5` in the next minute continues in existing `.partial`.
  - **Forums and media channels in TUI (2026-11-04):** selected like other channels (selection accepts `MESSAGE_TYPES` and `FORUM_TYPES`; category is not selectable, selecting it selects its channels). Their posts are threads, so with Threads = no and a forum selected, the form shows a warning and `F5` start is rejected with a message before the first Discord call (service would reject it with code 8). Verified only with fake Discord tests (`tests/test_tui_forums.py`).
  - **Known limitations:** TUI lacks `--since-last` and `--max-tokens`. Esc during running HTTP request only takes effect after it finishes (timeout 20 s), pauses during attachment download retries in `attachments.py` cannot be interrupted immediately, at 80 column width the Footer does not fit entirely, CLI command always has `--delay` from config, text selection with mouse does not work in Help and Preview.
  - **Verification:** originally only Pilot tests with fake data and screenshots. The user on 2026-11-04 confirmed that `discoop ui` works on a real account and that they logged in with QR ([analysis](analyses/real-account-check-2026-11-04.md)). Ctrl+C in TUI, forum selection, and Threads toggle on a real account remain unverified; shortcut `o`, profiles `P`/`p`, tree suffixes, and `tui-state.json` are also unconfirmed separately. Linux and macOS as well.

#### H. Optional diagnostic logging (`logs.py`, [ADR 0018](decisions/0018-logging.md), P24)
- **Module `src/discoop/logs.py`:** `setup_logging`, `teardown_logging`, `DiscoopFormatter`. Off by default (no handler); when enabled, attaches exclusively to logger `discoop` (`propagate=False`).
- **Activation:** global flags `--debug` (stderr) and `--log FILE` (file) or environment variables `DISCOOP_DEBUG=1` and `DISCOOP_LOG=path`. Hoisting mechanism allows use both before and after subcommand.
- **Security guarantees:** never logs authentication tokens, signatures in CDN URLs (`ex`, `is`, `hm`), message texts, response bodies, usernames, or channel/server names (only numeric snowflake IDs). Third-party loggers (`httpx`, `httpcore`, `websockets`) are quieted to `WARNING`.
- **UI integration:** with `--debug`, spinner is disabled. The command `discoop ui --debug` is rejected with code 8 (UI owns the screen), but `discoop ui --log FILE` is allowed.

#### I. Environment diagnostics (`discoop doctor`, P25)
- **New command `discoop doctor`:**
  - Checks 6 key runtime environment points:
    - `login`: login via `GET /users/@me` (`api.get_me()`),
    - `network`: Discord API availability (distinguishes network error from invalid token; `skipped` when not logged in),
    - `export_dir`: writeability of export folder (`export-dir` from config, otherwise current folder) via `os.access` on nearest existing parent (creates nothing),
    - `disk_space`: free space via `shutil.disk_usage` (FAIL under 100 MB, otherwise size in MB),
    - `cache`: server cache age,
    - `version`: tool version (`__version__`).
  - Output: in plain mode, tab-separated lines `check<TAB>OK|FAIL<TAB>detail`; in human mode, table (`check`, `status`, `detail`).
  - Exit code based on first failed check (`AUTH_REQUIRED` 2, `NETWORK` 7, otherwise `ERROR` 1); 0 on success.

#### J. Machine-readable outputs and JSONL progress (P25)
- **JSON format (`--format text|json`):**
  - Implemented on `servers`, `channels`, `status`, and `config list` commands via `Output.json()`.
  - `servers` returns list of objects `[{"id": "...", "name": "...", "member_count": ...}]`.
  - `channels` always returns flat list of objects `{id, name, type, type_name, category, position}`.
  - `status` and `config list` return structured JSON objects to stdout.
- **Download progress (`--progress-json`):**
  - For `discoop messages`: writes JSONL events to stderr (`channel_start`, `page`, `pause`, `channel_done`, `skipped`, `warning`).
  - Calculation of completion percentage (`~42%`) and time estimate (ETA, e.g. `about 3 min left`) by snowflake ID in spinner and verbose output.

#### K. Helper modules (`progress.py`, `profiles.py`, `tokens.py`, `resolve.py`, P25)
- **`src/discoop/progress.py`:** pure functions `fraction_done`, `window_start_id`, `eta_seconds`, `format_eta` for calculating percentage and estimated remaining time based on message snowflake IDs.
- **`src/discoop/profiles.py`:** profile management in `<config_dir>/profiles.json` (`load`, `save`, `delete`, `names`) with atomic saving.
- **`src/discoop/tokens.py`:** rough text token estimate `estimate_tokens` (`len(text)/4`) and formatting `format_tokens`.
- **`src/discoop/resolve.py`:** fuzzy suggestions for typos in server or channel name (`Did you mean: ...?`) via `difflib.get_close_matches`.

#### L. Threads and forum posts (`threads.py`, [ADR 0019](decisions/0019-threads.md), P27)
- **Analysis and probe:** verified on the user's account in [docs/analyses/thread-probe-2026-11-04.md](analyses/thread-probe-2026-11-04.md). Real account check of the tool itself (thread listing, forum export, `message_count` excluding post starter message): [docs/analyses/real-account-check-2026-11-04.md](analyses/real-account-check-2026-11-04.md).
- **Downloading threads in `messages`:**
  - Threads are enabled by default (`request.threads = True`), can be disabled via `--no-threads`.
  - Forums (type 15) and media channels (type 16) are first-class targets of `messages` (download their threads). Forum with `--no-threads` is rejected with code 8. In TUI they are selected like other channels; with Threads = no, starting is rejected right in the form.
  - Downloading both active and archived threads via `GET /channels/{id}/threads/search` with `limit=25`, offset pagination, and end detection by empty or incomplete page (< 25).
  - Nesting thread sections in `channels/<channel>.md`, flat format in `messages.jsonl` with `thread` attribute, thread attachments go into `files/<parent>/`.
  - Limits `--max-messages` and `--last N` apply independently per channel and per each thread.
  - HTTP 403/404 on an individual thread skips the thread with a warning, and the run continues with exit code 9 (`ExitCode.PARTIAL`).
- **Command `discoop threads`:**
  - Quick listing of channel threads and forum posts without downloading messages (`-s SERVER -c CHANNEL`).
  - Supports formats `human` (Rich table), `plain` (TSV), and `--format json`.

#### M. Incremental download and disk check (`syncstate.py`, [ADR 0020](decisions/0020-since-last.md), P28)
- **Flag `messages --since-last`:**
  - Downloads messages newer than last successful export of each channel and thread.
  - Persistent file `sync-state.json` in `paths.data_dir()` separate from SQLite cache (survives `clear_cache`), keyed by the user's account ID.
  - Exclusive lower bound `min_id = int(saved_id) + 1` protects against duplicates.
  - State progression occurs only upon successful and complete export of channel (not on error or `truncated`).
  - Skipping inactive channels: server channel list is refreshed on `--since-last`, and if a channel has saved state and `Channel.last_message_id <= saved_id`:
    - channel that cannot have threads, or any channel with `--no-threads`: skipped completely (0 requests, `_is_channel_unchanged` in `service.py`),
    - text or announcement channel with threads enabled: its own messages are not downloaded, but its thread list is loaded and threads are downloaded as usual (`_is_own_unchanged`),
    - forum and media channel are never skipped.
    - `[ASSUMPTION]` `last_message_id` of a text channel is reliable: from thread probe (2 samples) and real account check on 2026-11-04 (20 of 25 readable channels matched, in 4 pointed to newer message, in 1 message was newer than the field). If Discord delayed it, a new channel message could be missed until another arrives.
  - After interrupted and resumed run, channels saved by interrupted run keep old state and will be downloaded again next time (duplicates, nothing lost). Run warns with a note.
  - Free disk space check: before downloading attachments of each channel (`service._check_disk_space`), calculates what will actually be downloaded (`ExportWriter.bytes_to_download`: without files already in export, without `--no-files` and over `--max-file-size`), and compares with free space via `shutil.disk_usage`. If at least 50 MB safety margin does not remain, run fails with code 1 before sending requests to CDN.

#### N. Token splitting, token estimation, and profiles in CLI (`split.py`, `profiles.py`, P29)
- **Token splitting (`--max-tokens N`):**
  - Module `src/discoop/split.py` and function `split_markdown(text, max_tokens)` split `messages.md` into numbered parts `parts/part-NNN.md` with header `<!-- discoop part X of Y -->`. Splitting occurs only on actual message and channel/thread heading boundaries: a message containing a line `# Heading` remains intact. Limitation: a line in message body that looks exactly like `[2026-01-01 10:00] x` immediately after an empty line cannot be distinguished from a message header. A message larger than the limit goes into a part by itself with a warning.
  - `--max-tokens` works with `--out` and `--zip` (without them code 8 before API call). Parts are written to staging folder on `close(complete=True)` and published together with export, so crash before end leaves no `parts/` in destination. On repeated export to a folder, old `parts/part-*.md` are replaced with new ones. Parts are not in manifest.
  - Export summary displays line with estimated token count: `tokens: ~... (estimate, about 4 characters per token)`.
- **Named profiles in CLI:**
  - Flags `--profile NAME` (loading with override capability) and `--save-profile NAME` (saving settings before download).
  - Commands `discoop profiles` (profile list with `--format json` support) and `discoop profiles delete NAME`.

#### O. AI agent guide (`agent_guide.py`, P30)
- **Command `discoop agent-guide`:**
  - Clean unstyled text for AI agents with exact workflow `status` → `servers` → `channels` → `messages`.
  - Complete exit code table generated directly from `ExitCode`.
  - Dynamic alphabetical list of all registered commands from Typer app with their single-line descriptions.
  - Reference to the command in `NOTE FOR AI AGENTS` section in `discoop --help`.

---

## 3. Latest commits on branch `main`

GitHub (`origin/main`) is at `94bd862`, newer commits are only local (`git log --oneline origin/main..HEAD`). Push only on instruction from the user. Until pushed, installation from GitHub provides an older version without logging, threads, resilient export, and new TUI.

| Commit | Message | Meaning |
|---|---|---|
| `a236a71` | `Add safe and fast download modes to discoop` | Introducing `safe` modes (jitter, reading pauses, delay between files/channels) and `fast`. |
| `f346b1d` | `Rename agent mode to plain mode with --plain flag` | Renaming agent mode to plain mode ([ADR 0012](decisions/0012-rename-agent-mode-to-plain.md), P15), preserving `--agent` alias. |
| `1d3b38b` | `Extract messages orchestration into service layer and add ui command` | Creating `src/discoop/service.py` and registering `discoop ui` command. |
| `bf0d3f6` | `Add TUI state management, job planner and cancellation bridge` | TUI state logic (`state.py`), job planner (`plan_jobs`), and `CancelToken` (`bridge.py`). |
| `21e9e5c` | `Add Textual TUI screens, modals, styles and Pilot tests` | Complete Textual TUI implementation (`app.py`, `modals.py`, `discoop.tcss`) and pilot tests. |
| `75f0310` | `Document discoop ui TUI and ADR 0013` | Documenting TUI in requirements (P16, P17), tool design, journal, and record of [ADR 0013](decisions/0013-tui-and-shared-service-layer.md). |
| `bde52c6` | `Add live QR code login inside TUI LoginModal` | Integrating live QR code generation and scanning directly in TUI login dialog. |
| `a7a5347` | `Record keyboard-first TUI decisions` | Requirements P18–P20 and ADR 0014. |
| `470c127` | `Fix TUI preview jobs and typed event bridge` | Fixing preview jobs, typed events instead of `*args`. |
| `4e13acb` | `Redesign TUI main screen` | Single tree, Export panel, `widgets.py`, `ansi-dark` theme. |
| `4dc5f8b` | `Restyle TUI dialogs for keyboard use` | Help, Settings, Login, Preview, TimeWindow in unified style, `tests/test_tui_modals.py`. |
| `72eeef4` | `Document TUI redesign` | Documenting redesigned TUI. |
| `db16aef` | `Add export name row to the TUI` | Row `Name` in TUI (P21). |
| `94bd862` | `Split the TUI export path into Folder and Name` | Fields `Folder` and `Name` (P23, [ADR 0016](decisions/0016-default-export-folder-in-tui.md)). |
| `a162832` | `Add optional diagnostic logging with a leak test (ADR 0018)` | Round 1: logging `--debug`/`--log`. |
| `83bb692` | `Add a crash-safe ExportWriter with staging, resume and PARTIAL exit code` | Foundation of resilient export ([ADR 0017](decisions/0017-reliable-export-and-partial-success.md)). |
| `05ff654` | `Add resumable export, threads, --since-last, --max-tokens, profiles and agent-guide` | Round 2: export resume, threads and forums, `--since-last`, token splitting, profiles in CLI, `agent-guide`. |
| `bd3cacc` | `Add saved TUI state, profiles, threads toggle, open-folder key and tree suffixes` | Round 2: TUI improvements (P30). |

---

## 4. What follows next

All 6 steps of the original implementation plan plus browser login (round 4) are implemented and tested offline (1186 tests pass, 1 skipped on Windows without symlink privileges). Part of round 2 was verified on a real account on 2026-11-04 (details in [analysis](analyses/real-account-check-2026-11-04.md)), and CLI browser login plus starting `discoop ui` were partly verified on Windows 10 on 2026-11-10 (details in [browser-login.md](analyses/browser-login.md), section 7).

1. **Tests by the user on a real account that are still missing:**
   - **Browser login (`login --browser` and TUI `b`):** QR code on the web page, a real captcha, closing the window with X before logging in, Ctrl+C (exit code 130), `Esc` in the TUI during browser login, the Windows Security passkey dialog, Edge first-run/sign-in screens, `source=header`, the new entry under Discord Settings > Devices, `discoop status` the next day, hard kill (>24 h stale profile cleanup), and Linux and macOS (including snap/flatpak browsers).
   - **Resilient export and resume:** actual Ctrl+C from console while waiting for network and while downloading a file. Script interruption (code 130, `.partial`, resume) was verified on a real account.
   - **Threads and forums:** export of a forum with hundreds of posts from start to finish, private threads (type 12) and HTTP 202 (did not appear), export with many attachments (1 attachment seen).
   - **Incremental download `--since-last`:** a thread that receives a new reply between two runs. Skipping unchanged channels and continuing from previous run was verified.
   - **TUI in a real terminal:** Ctrl+C in TUI, `Esc` / `b` / captcha in the login dialog, forum selection and Threads toggle, saving (`P`) and loading (`p`) profiles, opening export folder (`o`), channel row suffixes in tree, and persistence of `tui-state.json`. The user confirmed running `discoop ui` and QR login on 2026-11-04, and starting `discoop ui` again on 2026-11-10.
2. **Git:**
   - The user decides on pushing commits to GitHub (GitHub is currently on an older commit).
3. **Decision 9 (Channel access calculation):**
   - Remains **deferred with low priority** (the user does not consider it important and Discord announced an API change where it stops returning inaccessible channels).
4. **Open minor items:**
   - Linux and macOS are unverified (installation from GitHub, TUI, paths via `platformdirs`).
   - An attachment described differently by the API than by the CDN (different size and content type) is downloaded again on repeated export: reuse by ID and size does not match it ([analysis](analyses/real-account-check-2026-11-04.md), section 4). Unfixed and harmless. Possible fix: relax size check or store actual size in manifest.
   - On code 130, the line "Interrupted." is not printed, although code has `out.error(...)`. Branch appears unreachable.
   - `--progress-json`: not determined whether thread message pages emit `page` event.
   - Save in preview (`PreviewScreen`, `s` key) goes to `export-dir` or `exports` in current folder, not to `Documents/discoop` like export from form. Whether it stays like this is an open question.
   - The repo does not have a `LICENSE` file.
   - `profiles.load()` on corrupted file still issues Python `UserWarning` (in TUI it would be printed to terminal). `split`, `syncstate`, and `tui/tuistate` now report only via log and `warning` event.
   - `_save_tui_state` is not debounced: writes `tui-state.json` on every change of selection or form.
