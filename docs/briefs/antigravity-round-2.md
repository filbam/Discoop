# Brief for Antigravity: round 2 (completion of the whole plan)

This brief is self-contained: you do not need the conversation it came from. It is a continuation after round 1 (which is finished and committed).
This time you are finishing **the entire rest of the plan at once**. Claude will then inspect the result and fix any errors found.
So: better a simple and correct solution than an ambitious and broken one.

## 0. For the main agent (coordinator): how to proceed

You are the coordinator. Split the work into packages from the table in section 3 and give each package to **one** Gemini Flash agent.

1. **First, yourself** (no delegation): read `CLAUDE.md` and this section 0 to 3, run `git status`, `git log --oneline -5`, and full `uv run pytest`.
   Write into the report (section 5) the starting state: passed/failed count and list of failing tests.
2. Phases run **sequentially**. Within a single phase, only packages with disjoint files run in parallel (table in section 3). Do not proceed to the next phase
   until the full `uv run pytest` is green. Exception: a test fails in a file belonging to a package still running in that phase. In that case wait and rerun.
3. After **each phase**, append the block for that phase to the report (section 5). The report is written **continuously**, not at the very end:
   if something stops you in the middle (usage limit, error), Claude can see from the report how far you got.
4. An agent may only modify files from its row in the table. If it needs to modify another file, it writes that into its report and leaves it alone.
5. During work, an agent runs only its own test files. **You run the full `uv run pytest`** at the end of the phase (takes about 2 minutes).
6. You have no one to ask. When unclear, choose the **simplest solution that satisfies the text of the brief**, and write it into the report under "Decisions".
   Stop a package only if continuing would mean violating a hard rule from section 2.

## 1. Project in a nutshell and state at the brief

`discoop` is a Python 3.12 CLI tool (Typer, Rich, Textual, httpx) that downloads messages and attachments from Discord servers where the user
is a member (primarily VUT FIT), for analysis by AI. Code is in `src/discoop/`, tests in `tests/`, documents in `docs/` (in Slovak).
Read `CLAUDE.md` (rules of work and documentation) and then: `docs/design.md`, `docs/requirements.md`, `docs/decisions/README.md`,
and **`docs/analyses/thread-probe-2026-11-04.md`** (verified facts about Discord API for threads; where `[ASSUMPTION]` appears, do not rely on it).

`uv` might not be in PATH. In Git Bash: `export PATH="$PATH:/c/Users/Filip/AppData/Local/Microsoft/WinGet/Packages/astral-sh.uv_Microsoft.Winget.Source_8wekyb3d8bbwe"`.
Commands: `uv run pytest`, `uv run pytest tests/test_xyz.py`, `uv run discoop --help`.

**Finished and committed (base is commit `05255cd`):**
- Logging `--debug`/`--log` (`logs.py`), `doctor`, `--format json` for lists, `--progress-json`, `progress.py`, `profiles.py`, `tokens.py`, suggestions on typo in `resolve.py`.
- **Resilient export** (`src/discoop/export.py`, commit `83bb692`): `ExportWriter` writes channel by channel into `<target>.partial` (for zip `<name>.zip.partial`)
  and publishes to target only on `close(complete=True)`, so a finished export is never corrupted by an interrupted run. Manifest has fields
  `request`, `targets`, `skipped_channels`, `interrupted`, `partial`, `complete`. `ExitCode.PARTIAL = 9` (`errors.py`).
  Interface: `ExportWriter(target, as_zip, *, query, options, api, cdn, created, tz, now, sleep, progress)` with methods
  `open(targets, resume)`, `add_channel(result)`, `add_skipped(channel, reason)`, `close(complete)`, `fetch_files(results)`; functions
  `find_unfinished(target, fingerprint=None)`, `request_fingerprint(targets, query, options, tz)`, `skip_reason(code)`, `is_partial(...)`, `staging_path(target)`.
  On resume, a relative window ("last day") must be computed from `Resume.created`. Details are in docstrings in `export.py`.
- **Data for threads** (commit `275374f`): `models.Thread`, `ForumTag`, `Channel.last_message_id`/`available_tags`, `threads.py`
  (`fetch_threads`, `fetch_all_threads`, `FetchedThreads`, `Stop`, `is_thread_container`, `in_window`), `Directory.threads(channel, window, refresh=...)`,
  cache schema 2. Always `limit=25`; end of list is an empty or short page (`has_more` and `total_results` are not considered reliable).
- Verified (probe 2026-11-04): threads work on forum as well as in text channel; thread messages are read like channel messages (`/channels/{thread_ID}/messages`);
  on forum the first message has the same ID as the thread; messages can have type 19 (reply).

**In progress and UNCOMMITTED (two previous agents were interrupted in the middle of their work):**
`git status` will show modified `service.py`, `cli.py`, `tui/app.py`, `tui/bridge.py`, `export.py`, `attachments.py`, `models.py`, `render/text.py`,
`render/jsonout.py`, `tests/export_helpers.py`, `tests/test_export.py`, `tests/test_messages.py`, `tests/test_tui_app.py`, `tests/test_tui_modals.py`,
and new `tests/test_export_threads.py`, `tests/test_thread_render.py`. This belongs to packages **R2-A** and **R2-C** (phase 1). Build on what is there
(read `git diff`), do not discard any of it or rewrite from scratch. Mostly missing: ADR 0017, test fine-tuning, and part of the specification.
`tests/test_export.py` already has one justified modification (constant `SOON` due to real clock) and `tests/test_messages.py` has one (code 0 -> 9). Leave both in place.
**Known failing test at start:** `tests/test_export.py::test_url_refused_by_the_cdn_is_refreshed` (expects one batch `[4]`, after per-channel writes these are batches `[3, 1]`).
This is an intentional change in behavior: attachments are downloaded channel by channel, so URLs are refreshed channel by channel. Adjust that test to verify the same thing
(all 4 URLs were refreshed, channel by channel) and justify it in the report.

## 2. Hard rules

1. **No git write commands** (`add`, `commit`, `push`, `checkout`, `stash`, `reset`). Claude commits only after verification.
2. **Discord:** never call Discord API or CDN and do not run commands that would call them. Allowed: `uv run pytest` and `uv run discoop --help`.
   All tests run **offline** (`httpx.MockTransport`, fake objects in `tests/fake_messages.py`, `tests/fake_threads.py`, `tests/export_helpers.py`).
   Nothing from `Temp/`. Never read or output token or cookies.
3. **Do not modify existing tests.** You may **add** new tests to test files. Do not remove or weaken any assertion, no `skip` or `xfail`.
   The only permitted modifications to existing assertions are those explicitly stated in section 1 or in the package description. Justify every such modification in the report.
4. **Only your files** (table in section 3). No refactors, renames, or "improvements" outside the brief.
5. **No new dependencies** in `pyproject.toml` or `uv.lock`. **Do not run** `uvx`, `pip`, `npm`, or anything that downloads. Lint tools are not installed; do not use them.
6. **New fields** in existing dataclasses (`MessagesRequest`, `MessagesOutcome`, `Channel`, `ChannelMessages`, ...) only at the end and with a default value
   (tests and TUI instantiate them positionally). New methods in `Events` only as empty default implementations.
7. **Style:** follow surrounding code (type hints, short docstrings, few comments). User-facing texts, help, messages, code identifiers, and tests **in English**
   (ADR 0007). Documents in `docs/` in Slovak, absolute dates (`2026-11-04`).
8. **Line endings:** `.py` files have LF. Do not rely on `grep -c` with `\r` (it misreports in this shell); count bytes via Python. Markdown documents in this
   checkout mostly have CRLF (git normalizes this); on editing preserve what the file has, and do not mix.
9. **No sensitive data:** in code, tests, and documents no real token, cookies, names, or message texts of other people. Use fake values.
10. Facts about Discord API not verified in the repo must be written as `[ASSUMPTION]`, verified as `[VERIFIED]` (rule from `CLAUDE.md`).
11. If a test fails in a file you do not own due to work in progress from another package, wait a minute and rerun. Do not fix someone else's file.
12. Never delete `*.partial` folders or anything outside `tmp_path` in tests. Tests must not touch real Documents or data (isolated by `tests/conftest.py`).

## 3. Packages, phases, and file ownership

| Package | Phase | Files it may modify |
|---|---|---|
| **R2-A** complete resilient export in service, cli, TUI | 1 | `src/discoop/service.py`, `src/discoop/cli.py` (command `messages` and what it needs), `src/discoop/tui/bridge.py`, `src/discoop/tui/app.py`, `src/discoop/tui/modals.py`, `tests/test_messages.py`, `tests/test_service.py`, `tests/test_tui_app.py`, `tests/test_tui_modals.py`, new tests, new `docs/decisions/0017-reliable-export-and-partial-success.md`, one line in `docs/decisions/README.md` |
| **R2-C** complete threads in renderer and export | 1 | `src/discoop/models.py` (only `ChannelMessages` and thread metadata), `src/discoop/render/text.py`, `src/discoop/render/jsonout.py`, `src/discoop/export.py`, `src/discoop/attachments.py`, `tests/export_helpers.py`, `tests/test_export.py`, `tests/test_export_writer.py`, `tests/test_attachments.py`, `tests/test_thread_render.py`, `tests/test_export_threads.py`, new tests |
| **R3** threads in service and cli | 2 | `src/discoop/service.py`, `src/discoop/cli.py`, `tests/test_messages.py` (add only), `tests/test_service.py` (add only), new `tests/test_threads_cli.py`, new `docs/decisions/0019-threads.md`, one line in `docs/decisions/README.md` |
| **R4-D** `--since-last` and disk space check | 3 | `src/discoop/service.py`, `src/discoop/cli.py`, `src/discoop/snowflake.py`, new `src/discoop/syncstate.py`, new `tests/test_syncstate.py`, `tests/test_since_last.py`, new `docs/decisions/0020-since-last.md`, one line in `docs/decisions/README.md` |
| **R4-G** TUI: state, profiles, thread toggle, open folder, percentages | 3 | `src/discoop/tui/*`, `src/discoop/paths.py`, `src/discoop/config.py`, `tests/test_tui_*.py`, new TUI tests |
| **R5-H** `--max-tokens`, token estimate, `--profile` | 4 | `src/discoop/cli.py`, `src/discoop/service.py`, new `src/discoop/split.py`, new `tests/test_split.py`, `tests/test_profile_cli.py` |
| **R5-G** `agent-guide` module (without write to `cli.py`) | 4 | new `src/discoop/agent_guide.py`, new `tests/test_agent_guide.py` |
| **R5-R** register `agent-guide` command and link in help | 5 | `src/discoop/cli.py`, `tests/test_agent_guide.py` (add only) |
| **R6-DOC** documentation | 6 | `CHANGELOG.md`, `docs/journal.md`, `docs/design.md`, `docs/requirements.md`, `README.md`, `docs/handover.md`, status line in `CLAUDE.md`, ADR 0017/0019/0020 statuses |

Order: phase 1 (R2-A ‖ R2-C) -> phase 2 (R3) -> phase 3 (R4-D ‖ R4-G) -> phase 4 (R5-H ‖ R5-G) -> phase 5 (R5-R) -> phase 6 (R6-DOC) -> final full `uv run pytest`.
`service.py` and `cli.py` are never modified by two agents at the same time (which is why R3, R5-R are serial and in parallel phases they are owned by only one package).

## 4. Package specifications

### R2-A: resilient export in service, cli, TUI (phase 1)
Goal: a crash, Ctrl+C, or cancellation on the 30th channel out of 40 does not lose the 29 finished ones and running the same command continues automatically; a skipped channel or failed attachment
is honestly reported with code 9; the user sees what happened and what to do. Much of this is already in the tree; verify against these points:
1. `service.run_messages`: during export (`--out`/`--zip`) uses `ExportWriter` channel by channel (keep nothing fully in memory). Without export (console only) the in-memory path remains, but a skipped channel also counts as a partial result.
2. Automatic resume: if `find_unfinished` matches the request fingerprint, finished channels are skipped (neither downloaded nor their attachments fetched) and event
   `Events.resumed(done, total)` (empty by default) reports how many. CLI outputs a note ("Continuing an unfinished export: 29 of 40 channels are already saved."). No new flag.
3. Interruption (`Cancelled`, `KeyboardInterrupt`, unexpected error): writer closes with `complete=False` and the user receives a note "Saved N of M channels in <path>.partial. Run the same command again to continue."
   Ctrl+C must still result in code 130 in `main()`; it must not be swallowed.
4. `MessagesOutcome` has new fields with default values (skipped channels, resumed count, partial flag). TUI summary shows skipped channels and hint to resume (F5 runs the same export again).
   Fix docstring in `tui/bridge.py` if it still contradicts new behavior.
5. `cli.messages` returns `ExitCode.PARTIAL` (9) on partial result: channel skipped due to access or non-existence, or attachment in `failed` state.
   Skipping due to size (`--max-file-size`) and `--no-files` **does not count**. Summary after resume takes counts from `exported.manifest["counts"]` and `exported.jobs`, not from `Exported.results`.
   `--print` combined with resume where channels are already finished is rejected (BAD_ARGS + hint) before any API call.
6. ADR 0017 "Reliable export and partial success" (in Slovak, format like other ADRs; status **Accepted** for code 9 and automatic resume: the user approved the plan on 2026-11-04;
   describe the `<target>.partial` mechanism as implementation). One line into the `docs/decisions/README.md` index (check whether it is already there).
7. Tests: crash on 2nd channel of 3 and rerun finishes without redownloading channel 1 (verify request counts on fake), Ctrl+C/`Cancelled` leaves resumable `.partial`,
   code 9 on skipped channel (export and console) and failed attachment, but 0 on skipping due to size and `--no-files`, note on resume, rejection of `--print`, summary in TUI,
   finished export remains untouched after interrupted resume via CLI.

### R2-C: threads in renderer and export (phase 1)
Goal: rendering and export can carry **threads nested under parent channel** (nothing downloaded yet; structure is tested with hand-crafted objects). In progress in tree.
Design (already in `models.ChannelMessages`):
- `ChannelMessages.threads: tuple[ChannelMessages, ...] = ()` and `thread: Thread | None = None` (nested thread metadata). Nested item has `channel` = `Thread.as_channel(server_id)`, thread has no threads of its own.
  `file_count` of parent includes files of threads. Forum itself has no messages, everything is in `threads`.
- **Text** (`render/text.py`): channel section, then subsection for each thread (title, created, last activity, archived/locked, message count, forum tag names, thread messages in same format).
  Channel header shows `threads: N`. If there are no threads, output must remain **byte-for-byte identical** to current output (all existing tests pass unchanged).
- **JSON lines** (`render/jsonout.py`): thread messages have a field identifying the thread (id, name, parent_id); do not break existing `thread`/`has_thread` (message that started thread). `messages.jsonl` is flat.
- **Export**: `channels/<parent>.md` contains nested sections; `messages.md`/`messages.jsonl` are flat; thread attachments go to `files/<parent_folder>/` (names are unique thanks to attachment ID);
  `plan()` and `with_paths()` traverse nested results; manifest `channels[]` has thread count and `file_count` including thread files (no thread names in manifest).
  `ExportWriter.add_channel` treats parent with threads as **one unit**; output channel-by-channel must be byte-for-byte identical to one-shot `export()` including threads; resume after crash works.
- Tests: render with 0, 1, and multiple threads (text and jsonl), forum without its own messages, export to folder and zip with threads, equality of `ExportWriter` vs `export()` byte-for-byte, crash and resume, `plan()` with deduplication of attachment IDs between parent and thread.

### R3: threads in service and cli (phase 2)
Goal: `messages` downloads threads as well (forums and text channel threads) and a new command `discoop threads` lists them.
1. `MessagesRequest.threads: bool = True` (new field at the end); `to_argv` adds `--no-threads` when `False`. CLI: `messages --threads/--no-threads` (enabled by default).
   Help explains that threads add many requests and a large forum (hundreds of posts) is slow in `safe` mode.
2. `resolve_targets`: forum (type 15) and media channel (type 16) are valid targets (they have no messages of their own, content is threads). Remove the message "threads come in a later version".
   Categories remain rejected. Forum with `--no-threads` is rejected (BAD_ARGS, hint: "A forum only has threads: drop --no-threads").
3. In `run_messages` for channel of type text/announcement/forum (`threads.is_thread_container`), when `request.threads`: call `directory.threads(channel, window, refresh=True)`, sort threads from oldest,
   for each download messages via the same path as for channel (`scrape.fetch_messages` with thread ID, same normalization) and attach them as `ChannelMessages(server, thread.as_channel(server.id), messages, truncated, thread=thread)`
   into `threads=` of parent. Omit threads without messages in the window. `--max-messages` and `--last N` apply **separately per channel and separately per each thread** (record in ADR 0019).
   Parent with threads goes into `ExportWriter.add_channel` as one unit.
4. Errors: 403/404 on a single thread -> thread is skipped with warning (`events.warning`) and result is partial (code 9). Error on channel thread listing -> threads of that channel are skipped with warning,
   messages of the channel itself are saved, result is partial. Incomplete listing (`FetchedThreads.problem`) -> warning and partial result.
5. Progress: new empty `Events.thread(index, total, channel, thread)` (or equivalent); CLI displays in spinner/`--verbose` "thread i of n" and `--progress-json` receives event `thread` (ID and counts, **no names or texts**).
6. Command `discoop threads -s SERVER -c CHANNEL [--from ...] [--to ...] [--refresh] [--format text|json]`: lists channel threads (id, archived, messages, last activity in local time, tags, name).
   Default window `--from 30d` (longer via `--from all`). Same plain/human rule applies as with `channels` (plain = TSV without colours; `--format json` = list of objects). Channel that cannot have threads -> BAD_ARGS.
7. ADR 0019 "Threads and forum posts" (Accepted: the user wanted threads and approved the plan; describe window, per-thread limits, what is `[ASSUMPTION]`).
8. Tests: forum end-to-end (`tests/fake_threads.py` has `threads/search`; read thread as channel), text channel with threads, `--no-threads`, forum with `--no-threads` rejected, 403 on thread -> code 9 and others are saved,
   `to_argv`, `threads` command (both TSV and JSON), crash and resume with threads. If the fake cannot handle something, extend it **only** via a new helper file in `tests/` (do not modify `tests/fake_messages.py` or `tests/fake_threads.py`).

### R4-D: `--since-last` and disk space check (phase 3)
1. New `src/discoop/syncstate.py`: JSON file `sync-state.json` in `paths.data_dir()` (separate from cache so `clear_cache` does not delete it), keyed by account ID (one `api.get_me()` call when `--since-last` is used).
   Shape: `{"version": 1, "accounts": {"<user_id>": {"channels": {"<channel_id>": {"last_message_id": "...", "updated": "<ISO UTC>"}}}}}`. Atomic write, corrupted file = empty state with warning (pattern: `profiles.py`).
2. `messages --since-last`: mutually exclusive with `--from`, `--to`, `--last` (BAD_ARGS). For channel with state, the window is "messages with ID **greater** than saved ID" (note: `Window.after_id` is **inclusive**, needs +1) up to now.
   Channel without state is treated as default window (last 24 hours) and a note is printed about it. Threads: window of each thread starts from saved thread ID if present, otherwise from parent's `updated` time.
3. State advances **only after fully completed run** (export `close(complete=True)` or successful console output) and only for channels that were downloaded completely (not `truncated`, not skipped, not failed). Saves ID of newest seen message.
4. Skipping inactive channels: if `Channel.last_message_id` is non-empty and is `<=` saved ID, the channel is not downloaded (0 requests, counted as "unchanged"). Channel list is refreshed (`--since-last` forces refresh).
   **Only for channels that are not thread containers, or when `--no-threads` is set** (new replies in threads likely do not change parent's `last_message_id`, `[ASSUMPTION]`); forums are never skipped.
5. Space check: before downloading channel attachments, calculate size of attachments that will actually be downloaded (excluding `present`, `--no-files`, larger than `--max-file-size`), and compare with `shutil.disk_usage` of target's parent.
   If less than 50 MB margin remains, `DiscoopError(ExitCode.ERROR, "Not enough free space: need about X MB, Y MB free.", hint)` **before** downloading that batch.
6. ADR 0020 "Incremental download (`--since-last`)" (Accepted).
7. Tests: first run without state = default window, second run takes only newer messages (verify `after` parameters on fake), boundary is exclusive (message with saved ID is not duplicated), mutual exclusivity with `--from/--to/--last`,
   state does not advance after error or `truncated`, state survives `clear_cache`, corrupted file, skipping inactive channel (0 requests), forum is not skipped, disk space error before downloading.

### R4-G: TUI (phase 3)
Read `tui/state.py`, `tui/app.py` (keyboard shortcuts: `F5, F1, F2, F3, /, Esc, R, L, c, q, 1-3, Tab` are taken; choose new shortcuts so they do not conflict and add them to Help screen) and existing tests (`tests/test_tui_*.py`, Pilot).
1. **TUI state** `tui-state.json` in `paths.config_dir()`, tied to account ID: saves and restores on startup channel selection (per server), global and individual windows, safe/fast mode, Folder/Name, thread toggle.
   On loading, discard IDs that no longer exist. No tokens. Atomic write, corrupted file = default values. Tests via `tmp_path`.
2. **Threads toggle** (corresponds to `MessagesRequest.threads` from phase 2) in export settings; `plan_jobs` carries it into request and into command copy (`to_argv`).
3. **Profiles** via `profiles.py`: one shortcut saves current selection as profile (modal with name), second loads profile (modal with list). Profile format: `{"server", "channels", "from", "to", "last", "mode"}`.
4. **Opening export folder** on completion (shortcut on summary screen): `os.startfile` (Windows), `open` (macOS), `xdg-open` (Linux) via **swappable function** so tests can replace it (tests never launch anything).
5. **Percentages and time estimate** in progress via `progress.py` (same as `_CliEvents.page` in `cli.py`); `bridge.py` sends `fraction` and `eta_seconds` in event `page`.
6. In tree next to channels, dimmed indicator of last activity (from `Channel.last_message_id` via snowflake time, e.g. "2d ago") and next to exported channels date of last export from state. If it harms readability in 80x24, omit and note in report.
7. Tests via Pilot: state restoration, discarding invalid IDs, thread toggle in command, profiles (save/load), opening folder with stubbed function, percentages in progress. 80x24 and wider terminal.

### R5-H: tokens and profiles in CLI (phase 4)
1. New `src/discoop/split.py` (pure functions): `split_markdown(text: str, max_tokens: int) -> list[str]` splits `messages.md` into parts with token estimate (`tokens.estimate_tokens`) of at most `max_tokens`.
   **Never split a message across two parts** (determine from `render/text.py` what a message boundary looks like; multiline messages and messages with blank lines in text must be handled). Message larger than limit goes into a single part alone (warning).
   Each part begins with a single-line header `<!-- discoop part 2 of 5 -->`.
2. `messages --max-tokens N` (only with `--out`; with `--zip` BAD_ARGS before any API call): after completed export, writes `parts/part-001.md`, ... into export folder (deletes old parts only within `parts/` first). Parts are not in manifest.
3. Token estimate in export summary: line e.g. `tokens: ~12.4k (estimate, about 4 characters per token)` from `messages.md` (`tokens.format_tokens`); for `--format json` summary field `tokens_estimate` if such output exists.
4. `messages --profile NAME` loads saved profile (`server`, `channels`, `from`, `to`, `last`, `mode`) as default values; explicit flags override them. Unknown profile -> BAD_ARGS with suggestion (`difflib`) and list of profiles.
   `messages --save-profile NAME` saves effective arguments after validation, **before** downloading. New command `discoop profiles` lists names (`--format json`) and `discoop profiles delete NAME` deletes profile.
5. Tests: splitting (message boundaries, huge message, multiline messages, empty input), `--max-tokens` with `--zip` rejected before API, creation of `parts/` with expected part count, token line in summary, `--profile` (loading, overriding, unknown), `--save-profile`, `profiles` and `profiles delete`.

### R5-G and R5-R: `agent-guide` (phases 4 and 5)
- **R5-G**: module `src/discoop/agent_guide.py` with `build_guide(app: typer.Typer) -> str` (pure function, does not import `cli.py`). Text for AI agents (English, plain text without colours): fixed sequence `status` -> `servers` -> `channels` -> `messages`
  (with `--plain`, `--format json`, `--progress-json`, `--out`), exit code table **composed from `ExitCode`** (so it does not get outdated), rules (login is performed by user with `discoop login`; do not send token; large downloads in `safe` mode),
  and **list of all commands from Typer application with one-line description** (new command appears automatically). Tests: each registered command is in text, all codes from `ExitCode` are in text, output contains no ANSI.
- **R5-R** (only after R5-H): register command `discoop agent-guide` in `cli.py` (calls `agent_guide.build_guide(app)`), add link to it in `--help` (section for AI agents) and a test that command runs and outputs text.

### R6-DOC: documentation (phase 6)
All in Slovak, with `[VERIFIED]`/`[ASSUMPTION]`, without tokens or other people's data. Read real code and package reports from `prototype/out/antigravity-kolo-2-sprava.md`, do not write anything that was not done.
- `docs/requirements.md`: P26 resilient export and honest result (code 9, resume), P27 threads and forum posts, P28 incremental download `--since-last`, P29 token splitting/estimate/profiles, P30 `agent-guide` and TUI state. All dated 2026-11-04, source: plan approved by the user.
- `CHANGELOG.md` (`[Unreleased]`), `docs/journal.md` (new section for this round, preserve "Next" block and update what remains: test on real account), `docs/design.md` (exit codes including 9, atomic write and `.partial`, threads, `--since-last`, tokens, profiles, `agent-guide`, `threads`),
  `README.md` (concise examples), `docs/handover.md`, status line in `CLAUDE.md` (test count from last full run), statuses of ADR 0017/0019/0020 in index.
- Link to `docs/analyses/thread-probe-2026-11-04.md` wherever threads are discussed.

## 5. Report (mandatory, written continuously)

File `prototype/out/antigravity-kolo-2-sprava.md` (git ignores it). After each phase add a block:
- **Phase N, packages:** list of modified/new files for each package.
- **Full `uv run pytest`:** passed/failed count, duration, list of failing tests (if any remain).
- **Modified existing assertions:** file, test, what and why (otherwise "none").
- **Decisions:** where you picked a simpler solution and why; what is `[ASSUMPTION]`.
- **What was not accomplished / what remained open:** hide nothing.
At the end add a final summary: result of full `uv run pytest`, what is not finished, what to watch out for during verification.

## 6. What Claude will check after you

`git status` against the ownership table, `git diff -- tests/` (no removed or weakened assertion, no skip/xfail), full `uv run pytest`, `pyproject.toml` without new dependencies,
default command output byte-for-byte identical (where the brief specifies), actual crash and export resume behavior (resilience of finished export), logs without token leak, documents without other people's data and without claims that code does not satisfy.
Then commits package by package. What is uncertain, flag in the report: a trustworthy report with a missing item is better than a complete report containing falsehoods.
