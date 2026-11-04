# Brief for Antigravity: round 1

Repository state at the time of the brief: branch `main`, base is commit `94bd862` (the following commit added only this brief), clean tree, `uv run pytest` = **426 passed** (takes about 2 minutes).
This brief is self-contained: you do not need the conversation it came from.

## 0. For the main agent: how to split the work

You are the coordinator. Split the work into packages from the table in section 3 and give each package to **one** Gemini Flash agent.
- **Phase 1:** AG-A, AG-B, and AG-C run concurrently, because their files are disjoint.
- **Phase 2:** after phase 1 is complete and `uv run pytest` is green, AG-E1 goes first, then AG-E2 (both modify `cli.py`, never at the same time).
- **Phase 3:** AG-DOC only after phases 1 and 2.
- No agent may modify a file that is not in its row in the table. If an agent needs to change one, it should state so in its report and leave it alone.
- You run the full `uv run pytest` at the end of each phase. Agents run only their own test files during their work.
- At the end, write a report according to section 5.

## 1. Project in a nutshell

`discoop` is a Python 3.12 CLI tool (Typer, Rich, Textual, httpx) that downloads messages and attachments from Discord servers where the user
is a member. Code is in `src/discoop/`, tests in `tests/`, documents in `docs/`. The tool is read-only, and its
robustness and controls are the focus here. Read `CLAUDE.md` in the repo root: it contains rules of work and documentation that apply to you as well.

Important files for your packages:
- `src/discoop/api.py`: `DiscordAPI` (`request`, `get_me`, `_pace`, `between_channels`, `between_files`), 429 and retries.
- `src/discoop/scrape.py`: message pagination. `src/discoop/attachments.py`: downloading attachments from CDN (`Downloader`, `_download`, `_fetch`).
- `src/discoop/cli.py`: Typer application. `_root` (global flags), `_MODE_FLAGS`, `_hoist_mode_flags`, `main()`, `_CliEvents`.
- `src/discoop/output.py`: `Output` (`note`, `warning`, `error`, `rows`, `fields`, `err_console`).
- `src/discoop/snowflake.py`: `Window` (`start: datetime | None`, `end: datetime`), `from_time`, `to_time`, `parse_window`.
- `src/discoop/resolve.py`: name lookup (`resolve_one`, `resolve_many`, `NotFoundError`, `normalize`).
- `src/discoop/paths.py`: `data_dir()`, `config_dir()` (call at runtime, not at import time).
- `src/discoop/errors.py`: `ExitCode` (0 to 8), `DiscoopError`.
- `prototype/probe.py` and `prototype/README.md`: template for probe script.
- Test patterns: `tests/test_api.py` (scripted clock), `tests/test_messages.py` and `tests/test_export.py` (calling `cli.main([...])`
  with `httpx.MockTransport`, fake Discord in `tests/fake_messages.py`), `tests/conftest.py` (directory isolation, **tests must never touch real Documents or data**).

`uv` might not be in PATH. In Git Bash: `export PATH="$PATH:/c/Users/Filip/AppData/Local/Microsoft/WinGet/Packages/astral-sh.uv_Microsoft.Winget.Source_8wekyb3d8bbwe"`.
Commands: `uv run pytest`, `uv run pytest tests/test_xyz.py`.

## 2. Hard rules

1. **No commits, pushes, or git changes.** Claude commits only after verification.
2. **Discord:** never call the Discord API or CDN and do not run commands that would call them (`discoop servers`, `channels`, `messages`, `login`, `status`,
   `doctor` against the real network and similar). Allowed: `uv run pytest` and `uv run discoop --help`. All tests run **offline** on `httpx.MockTransport`.
   Do nothing in a browser on Discord. Do not read `Temp/`. Never read or output token or cookies.
3. **Do not modify existing tests.** You may **only add** new tests to test files. Do not remove or weaken any assertion,
   do not add `skip` or `xfail`. If an existing test fails because of your change, fix your code, not the test. If that is not possible, stop the package and report it.
4. **Only your files.** Do not change anything outside the files in your package row. No refactors, renames, or "improvements" outside the brief.
5. **No new dependencies** in `pyproject.toml` or `uv.lock`. Use stdlib and what the repo already has.
6. **Style:** follow surrounding code (type hints, short docstrings, no unnecessary comments). User-facing texts, help, messages, code identifiers, and tests **in English**.
   Documents in `docs/` in Slovak. Absolute dates (`2026-11-04`).
7. **No sensitive data** in code, tests, or documents: no real token, cookies, names, or message texts of other people. Use fake values.
8. **When unsure, stop and write it into the report.** Do not guess. For facts about Discord API not verified in the repo, write `[ASSUMPTION]`.
9. Run tests after each package. At the end of the phase, run the full `uv run pytest`, and **426 + your new tests** must pass.

## 3. Packages and file ownership

| Package | Phase | Files it may modify |
|---|---|---|
| AG-A core logging | 1 | new `src/discoop/logs.py`, `src/discoop/api.py`, `src/discoop/scrape.py`, `src/discoop/attachments.py` (**only** logging lines in `_download` and `_fetch`), new `tests/test_logs.py`, `tests/test_api.py` (add only), new `docs/decisions/0018-logging.md`, one line in `docs/decisions/README.md` |
| AG-B helper modules | 1 | new `src/discoop/progress.py`, `profiles.py`, `tokens.py`, `src/discoop/resolve.py`, new `tests/test_progress.py`, `tests/test_profiles.py`, `tests/test_tokens.py`, `tests/test_resolve.py` (add only) |
| AG-C probe script | 1 | new `prototype/probe_threads.py`, `prototype/README.md` (add section only) |
| AG-E1 CLI logging and cleanup | 2 | `src/discoop/cli.py`, new `tests/test_cli_logging.py` |
| AG-E2 JSON lists, doctor, progress | 2, after E1 | `src/discoop/cli.py`, `src/discoop/output.py`, `tests/test_servers_channels.py` (add only), new `tests/test_doctor.py`, `tests/test_progress_json.py` |
| AG-DOC documentation | 3 | `CHANGELOG.md`, `docs/journal.md`, `docs/design.md`, `docs/requirements.md`, `README.md`, `docs/handover.md`, status line in `CLAUDE.md` |

## 4. Package specifications

### AG-A Core logging

Goal: optional diagnostics logging. **Disabled by default**, nothing is written or output until enabled.

`src/discoop/logs.py` (new):
- `setup_logging(debug: bool, log_file: Path | None) -> None` and `teardown_logging() -> None`.
- Handlers attach **only** to logger `discoop` with `propagate = False` and `DEBUG` level. Never `logging.basicConfig`, never root logger.
  `debug=True` adds `StreamHandler(sys.stderr)` (created on call), `log_file` adds `FileHandler` in append mode with UTF-8 encoding.
  Set `httpx`, `httpcore`, and `websockets` loggers to WARNING (otherwise they would log full URLs and headers).
- `teardown_logging()` removes and closes all handlers added by `setup_logging` and restores state before the call. It is idempotent.
- Log header (one block at the beginning): tool version (`discoop.__version__`), OS, Python version, and the line "IDs in this log identify private servers and channels. Do not publish it."
- Line format: ISO time, level, short logger name, then `key=value` pairs (e.g. `api request method=GET path=/channels/123/messages attempt=1 status=200 ms=412 items=25`).

`src/discoop/api.py` (logger `discoop.api`, add logging only, do not alter behavior):
- After each request attempt: `method`, `path` **without query string**, parameter names (`params=before,limit`), values only for `before`, `after`, `limit`, `archived`, `offset`, `with_counts`,
  `attempt`, `status`, duration in ms (`time.perf_counter()`, **not** `self._clock`, as tests replace it), response length.
- 429: `retry_after`, `global`, doubled `delay`. Pauses: seconds and reason (`reading pause`, `rate limited (429)`, `between channels`, `between files`, plain jitter).
  Silent retries (network error, 5xx) and their backoff in seconds. Error: JSON `code` (number) and top-level `message`; **not** the `errors` subobject.
- Log transport errors as `type(e).__name__`, **never** `str(e)`.

`src/discoop/scrape.py`: one line per page: channel ID, message count, oldest and newest message ID, whether it is the last page.

`src/discoop/attachments.py` (logger `discoop.attachments`, **only** `_download` and `_fetch`): attachment ID, size, status, attempt number, number of bytes written, only the **host** from URL.
Never filename, path, or query (`ex`, `is`, `hm`).

**Never log:** headers (neither `client.headers` nor `response.request.headers`), `kwargs` from `request()` (contain ticket and signed URLs), `response.text`, `response.json()`,
dataclass reprs (`FileJob`, `Attachment`, `Message`, `ChannelMessages`, `StoredToken`), message texts, channel and server names (IDs only), signed URLs.

Tests `tests/test_logs.py` (required):
1. **Leak test:** fake token `FAKE.TOKEN.VALUE`, attachment URL `https://cdn.example/f.png?ex=1&is=2&hm=SECRETSIG`, message text `SECRET MESSAGE TEXT`, and channel name `secret-channel-name`
   pass through an entire run (`DiscordAPI` with `MockTransport`, pagination, attachment download, 429, 5xx, 403 error) with `setup_logging(True, tmp_path / "x.log")`.
   Read the log file and verify that **none** of these strings are present in it. (Handlers attach to logger `discoop` with `propagate=False`, so `caplog` does not capture them; read the file).
2. Without `setup_logging`, nothing is written to stderr or to file.
3. After `teardown_logging()`, no handlers remain on logger `discoop`. Calling `setup_logging`/`teardown_logging` twice in succession leaves no duplicate lines.
4. API line has expected fields (`status`, `attempt`, `ms`) and path has no `?`.
5. `tests/test_api.py`: add at least one test verifying that with logging enabled, 429 and network retry are logged and `DiscordAPI` behavior (attempt count, waiting) is unchanged.

`docs/decisions/0018-logging.md`: ADR following the `0016-default-export-folder-in-tui.md` template (Status **Accepted**, date 2026-11-04, Context, Decision, Consequences).
Content: optional, disabled by default, `--debug` to stderr and `--log FILE`, field allowlist, what is never logged, log contains private server IDs so it must not be published.
Add one line to index `docs/decisions/README.md` in the same format as the others.

### AG-B Helper modules (pure functions, no network, no writes outside `tmp_path` in tests)

`src/discoop/progress.py`:
- `fraction_done(start_id: int | None, end_id: int, oldest_id: int) -> float | None`: pagination proceeds from newest message to oldest,
  so `fraction = (end_id - oldest_id) / (end_id - start_id)`, clamped to 0..1. `None` if `start_id` is `None` or `end_id <= start_id`.
- `window_start_id(window: Window, channel_id: str | int, last: int | None = None) -> int | None`: `None` if `last` is not `None`;
  otherwise `from_time(window.start)` if `window.start` is not `None`; otherwise `int(channel_id)` (the entire history starts with the creation of the channel, which is encoded in its ID).
- `eta_seconds(elapsed: float, fraction: float | None) -> float | None`: `elapsed * (1 - fraction) / fraction`; `None` if `fraction` is `None`, less than 0.02, or `elapsed <= 0`.
- `format_eta(seconds: float | None) -> str`: `""` for `None`, otherwise short English format (`45 s`, `3 min`, `1 h 05 min`).
- Use `from_time`/`to_time` from `snowflake.py`, do not reinvent conversions. Tests: boundary values (`None`, 0, 1, out of range, `last` specified, `all`).

`src/discoop/profiles.py`:
- File `profiles.json` in `paths.config_dir()` (call `paths.config_dir()` at call time). Functions `load() -> dict[str, dict]`, `save(name: str, profile: dict) -> None`,
  `delete(name: str) -> bool`, `names() -> list[str]`.
- Profile has keys `server`, `channels` (list), `from`, `to`, `last`, `mode` (all optional). Disallowed keys are dropped on `save`.
- Profile name: after sanitization only letters, digits, `-`, `_`, `.`; no slashes or `..`; empty or invalid name raises `ValueError`.
- Atomic write (write to `.tmp` in the same folder, then `os.replace`). Corrupted or missing file = empty dictionary (`warnings.warn` on corrupted), never an exception.
- Tests in `tmp_path` with monkeypatched `paths.config_dir` (see `tests/conftest.py`).

`src/discoop/tokens.py`: `estimate_tokens(text: str) -> int` (`ceil(len(text) / 4)`, in docstring **state that it is a rough estimate**) and `format_tokens(n: int) -> str` (`850`, `12.4k`, `1.2M`).

`src/discoop/resolve.py`: in `resolve_one` as well as `resolve_many` on `NotFoundError`, add to `hint` the sentence `Did you mean: A, B?` (at most 3 names, `difflib.get_close_matches` on `normalize(item.name)`, `cutoff=0.6`,
show original item names). If nothing is close, messages and `hint` remain **exactly** as before. Existing tests must pass unchanged. New tests: typo finds suggestion, completely different word has no suggestion, glob without match.

### AG-C Probe script (the agent only writes it, does not run it; the user runs it on their account)

New `prototype/probe_threads.py` patterned after `prototype/probe.py` (same access via `DiscordAPI` and `TokenStore`, anonymized report to `prototype/out/`,
pace of 1 s between requests, `argparse` with `--guild`, `--forum`, `--delay`). **GET only.** Token is never read or output anywhere. The report contains **structure only**:
types, counts, field names, status codes. No names, message texts, user IDs, or URLs. Verify `python -m py_compile prototype/probe_threads.py`, do not run the script.

The script determines and records:
1. Page size of `GET /channels/{forum}/threads/search?archived=true&sort_by=last_message_time&sort_order=desc&limit=N&offset=0` for `limit=25` and `limit=50`:
   how many threads were returned, value of `has_more`, `total_results`.
2. How far `offset` reaches: try 0, 25, 100, 500 (and if `total_results` is larger, near the end as well). Record status and count of returned threads.
3. Response 202 ("not indexed"): if any request returns it, record status and body key names.
4. Private threads: whether among threads in text channel or forum there is type 12 and how they are indicated (`type`, `thread_metadata.locked`, `flags`). Counts and field names only.
5. Difference between `total_results` and the sum of threads across all pages.
6. `GET /guilds/{id}/channels`: how many channels have a non-empty `last_message_id`. For 3 text channels, compare `last_message_id` with the ID of the latest message from `GET /channels/{id}/messages?limit=1`
   (record only `matches` / `is older` / `missing`, no contents).

`prototype/README.md`: add section "4. Thread probe" (command `uv run python prototype/probe_threads.py`, what it does, where the output goes, that the user runs it).

### AG-E1 CLI logging and cleanup (`src/discoop/cli.py`)

- Global flags `--debug` (bool) and `--log FILE` (`Path`, not directory) in `_root`. Add them to `_hoist_mode_flags` so they work after a subcommand as well
  (`discoop messages --debug ...`). `--debug` is like other boolean flags in `_MODE_FLAGS`. `--log` takes a value: both `--log FILE` and `--log=FILE` must be hoisted **along with the value**
  and search stops at `--`.
- Fallback environment variables `DISCOOP_DEBUG=1` and `DISCOOP_LOG=path`, processed in `main()` (similar to `PLAIN_ENV` in `output.py`). Command-line flags take precedence over environment variables.
- After processing flags, call `logs.setup_logging(...)`, in `finally` call `logs.teardown_logging()` (even on error and on `KeyboardInterrupt`).
- When `--debug` is enabled, the CLI **does not display a spinner** (behaves as in plain mode) so stderr log output does not corrupt the Rich animation.
- `discoop ui`: reject `--debug` with code `ExitCode.BAD_ARGS` (8) and hint `Use --log FILE: the terminal UI owns the screen.`; allow `--log FILE`.
- Remove dead code from `cli.py`: `_export_target`, `_export`, `_message_targets`, `_progress`, `_unreadable`. **First verify via `grep` that the function has no callers** (in `src/` or `tests/`);
  if it has any, keep the function and note it in the report. Note: `service.py` has its own active `_unreadable`, leave that one.
- **Do not modify** `messages()`, its return value, `_export_report`, or exit codes (Claude does that later).
- New tests `tests/test_cli_logging.py` via `cli.main([...])`: flags before and after subcommand, `--log=FILE` and `--log FILE`, environment variables and flag precedence,
  `ui --debug` exits with code 8, no handlers remain on logger `discoop` after run, no log file is created without flags.

### AG-E2 JSON lists, doctor, progress (`cli.py`, `output.py`)

1. **`--format text|json`** for `servers`, `channels`, `status`, and `config list` (default `text`, invalid value = code 8 with a hint). Add a helper method on `Output` (e.g. `json(data)`),
   which prints JSON identically in plain and human mode (`json.dumps(..., ensure_ascii=False, indent=2)` to stdout).
   - `servers`: array of `{id, name, member_count}`. `channels`: **always a flat** list of `{id, name, type, type_name, category, position}` (respects `--type`, not a tree). `status`: object, without `Path` objects (`str`). `config list`: object key -> value.
   - Cache notes go to stderr, stdout is clean JSON. Default TSV and Rich output must remain **byte-for-byte identical** (existing tests in `tests/test_servers_channels.py` must pass unchanged).
2. **`discoop doctor`** (new command): check points a) login via existing `get_me`, b) network (distinguish network error from invalid token), c) export directory (`export-dir` from config, otherwise current):
   writable via `os.access` on the closest existing parent, **create nothing**, d) free disk space via `shutil.disk_usage` (FAIL below 100 MB, otherwise informational only), e) cache age, f) tool version.
   Output in plain mode: lines `check<TAB>OK|FAIL<TAB>detail`; in human mode a table. Exit code: code of the first failed check (`AUTH_REQUIRED` 2, `NETWORK` 7, otherwise `ERROR` 1), otherwise 0.
   **No mutating calls to Discord** (only `GET /users/@me`). When not logged in, remaining checks still run.
3. **`--progress-json`** for `messages`: with this flag there is no spinner and no notes; stderr receives one JSON object per line for events `channel_start`, `page`, `pause`, `channel_done`, `skipped`, `warning`
   (via `_CliEvents`). Fields: `event`, indices `index`/`total`, `channel_id`, counts, `fraction`, `eta_seconds`, `seconds` and `reason` for pause. **No message texts or names.**
4. **Percentages and time estimate** in `_CliEvents.page`: in human spinner as well as plain `--verbose` notes add `~42%, about 3 min left` when calculable. Use `progress.py` from AG-B
   (`window_start_id`, `fraction_done`, `eta_seconds`, `format_eta`); for calculation you need window, channel ID, and start time. When incalculable, output remains as before.
5. Do not modify `messages()` return value or exit codes.

Tests: new `tests/test_doctor.py` and `tests/test_progress_json.py` (both via `cli.main([...])` and `MockTransport`, following `tests/test_messages.py`), add JSON lists to `tests/test_servers_channels.py`.

### AG-DOC Documentation (after phases 1 and 2, written in Slovak)

- `docs/requirements.md`: add to the end of the table
  `P24 | 2026-11-04 | Optional diagnostics logging: disabled by default, enabled by option (--debug, --log FILE), log does not contain token, signed URLs, or message texts.`
  and `P25 | 2026-11-04 | The tool is "smart": machine-readable lists (--format json), diagnostics (discoop doctor), percentages and time estimate during download, suggestions on name typos.`
- `CHANGELOG.md` (`[Unreleased]`): everything from packages A, B, E1, E2. `docs/journal.md`: new section for this block (date 2026-11-04), **do not delete** the existing "Next" block, only append.
- `docs/design.md`: commands and options (`doctor`, `--format json`, `--debug`, `--log`, `--progress-json`), section on logging with what is logged and what is never logged.
- `README.md`: short section on logging and diagnostics. `docs/handover.md`: current state. `CLAUDE.md`: status line only.
- Check that documents contain no token, cookies, or other people's names or texts. Texts are based on what is in the code; do not invent anything.

## 5. Report (mandatory)

Write it to `prototype/out/antigravity-kolo-1-sprava.md` (git ignores the folder, create it if missing). For each package:
- list of modified and new files,
- `uv run pytest` result (passed and failed count, after phase also full run),
- what was not accomplished or what you skipped and why,
- what you were unsure of or had to assume.

**Hide nothing.** If a package is not finished, state so. Claude does not take the report as proof, but uses it for verification.

## 6. What happens next

Claude (a different model) takes over the work: verifies that only allowed files were changed, reads the diff, runs the full `uv run pytest`, verifies that tests are not weakened and that the log leaks nothing,
and only then commits package by package. Meanwhile, the user runs `prototype/probe_threads.py` on their account.
