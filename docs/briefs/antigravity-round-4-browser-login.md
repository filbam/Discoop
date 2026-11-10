# Brief for Antigravity, round 4: finish the browser login (CLI wrap-up, TUI, records)

This brief is self-contained: you do not need the conversation it came from. Rounds 1 to 3 are done and committed
([round 1](antigravity-round-1.md), [round 2](antigravity-round-2.md), [round 3](antigravity-round-3-english.md)).
This round finishes one feature, **browser login** (`discoop login --browser`, decided in
[ADR 0022](../decisions/0022-browser-login.md)), which Claude's agents started and which was stopped half way on request.
Unlike round 3, this round **changes behaviour on purpose**. Better a simple and correct solution than an ambitious and broken one.

**The one thing the owner asked for above all: commit often.** After every finished chunk of work, not only at big
milestones. Section 6 says how.

## 0. For the coordinator: how to proceed

1. **First, yourself** (no delegation): read `AGENTS.md`, `CLAUDE.md`, ADR 0022 and sections 1 to 6 of this brief; run
   `git status`, `git log --oneline -6` and the full `uv run pytest` (about 3.5 minutes: run it in the background or with a long
   timeout). Expected: **1154 passed, 1 skipped** (the skip is a symlink test that needs special rights on Windows). Write the
   baseline into the report (section 8). If the numbers differ, find out why before you change anything.
2. Work through the chunks of section 5 **in order**. Each chunk is small enough to finish, test and commit on its own.
3. **After every chunk: check, test, commit** (section 6). Never start the next chunk with finished work uncommitted. If a chunk
   grows, split it and commit the parts.
4. You may give a chunk to a sub-agent, but never two agents on one file, and **sub-agents never run git** (only you do). An agent
   changes only the files of its chunk; if it needs a change elsewhere, it says so in its report and leaves it.
5. Write the report (section 8) **as you go**, after each commit, so that the owner can see how far you got if something stops you.
6. You have no one to ask. When unclear, take the simplest solution that satisfies this brief and write it under "Decisions" in
   the report. Stop a chunk only if continuing would break a hard rule (section 4).

## 1. The feature in a nutshell

QR login sometimes fails because Discord asks for a captcha, which a terminal cannot solve. The new mode `discoop login --browser`
opens the user's own Chromium-family browser (Chrome, Edge, Chromium, Brave) as a separate instance with a temporary profile. The
user logs in on Discord's page themselves (password, QR code on the page, captcha, 2FA). Discoop reads the token over the Chrome
DevTools Protocol (CDP), closes the window, verifies the token with `GET /users/@me` and stores it like the other modes.

It must work in the TUI, in the human CLI and in the AI/machine modes (plain mode, `--format json`, `--progress-json`). When QR
login fails because of a captcha, the message recommends the browser mode (CLI and TUI). AI agents must announce the window and
wait for the user's consent before running it.

Read [ADR 0022](../decisions/0022-browser-login.md) (it is binding) and the requirements P31 to P33 in `docs/requirements.md`.
The analysis [browser-login.md](../analyses/browser-login.md) explains the engine and has the owner's real-account checklist
(its section 6).

## 2. Where things stand at the start

### 2.1 Done and committed (do not redo)

- `48091b4`: ADR 0022, the index, the status lines of ADR 0005, 0008 and 0009, requirements P31 to P33 (status "planned").
- `e2b9d11`: the **engine** `src/discoop/browser_login/` with `tests/fake_cdp.py` and `tests/test_browser_login_*.py`.
  `a39e351`: its analysis and CHANGELOG entry. The engine is verified against local headless Chrome 157 and Edge 157.
  **It is frozen: do not edit `src/discoop/browser_login/**`.** If you find a bug in it, write it into the report and carry on with
  what does not depend on it.
- Engine interface: `find_browser(configured)`, `await wait_for_browser_token(listener, *, browser, timeout=300.0,
  poll_interval=1.0, session_factory=...) -> str` (the raw token) and `BrowserListener` with `on_launching(browser_name)`,
  `on_opened(deadline)` (a `time.monotonic()` value) and `on_captured()`. None of them receives the token. Errors are
  `DiscoopError`: exit code 2 when the window is closed or the time is up; exit code 1 when no browser is found, it cannot start,
  there is no desktop session on Linux, or it misbehaves. The engine prints nothing and neither verifies nor stores the token.

### 2.2 Written but NOT committed: the CLI side (step C)

An earlier agent wrote it and was stopped on request. Its last full test run was green (1154 passed, 1 skipped). `git status`
shows the files below. Read `git diff` for each; do not discard it and do not rewrite it from scratch.

| Files | What they contain |
|---|---|
| `src/discoop/config.py`, `tests/test_config.py` | config key `browser-path` (`parse_browser_path`: an absolute path of an existing file). `tests/test_tui_modals.py` has one added test that the Settings dialog keeps this value when it saves the other rows. |
| `src/discoop/login.py`, `src/discoop/remote_auth/protocol.py`, `src/discoop/errors.py` | `CaptchaRequired` (exit code 1), `BROWSER_HINT`, `find_login_browser`, `browser_login`, the listeners `BrowserScreen` and `BrowserProgressJson`, the constants `BROWSER_TIMEOUT` (300), `MIN_BROWSER_TIMEOUT` (30), `MAX_BROWSER_TIMEOUT` (1800); new `TOKEN_HINT` and `AUTH_HINT` texts. |
| `src/discoop/cli.py` | the `login` command with the new options, `_check_login_options`, `_login_with_browser`, `LOGIN_HELP`, new `GETTING_STARTED` and `AI_NOTE` text. |
| `tests/browser_rig.py` (new), `tests/test_login_browser.py` (new), `tests/test_login_browser_cli.py` (new), `tests/test_login.py`, `tests/test_cli.py`, `tests/test_remote_auth_flow.py`, `tests/test_service.py` | tests for all of the above. The rig runs the real engine against `tests/fake_cdp.py`. |
| `src/discoop/agent_guide.py`, `.claude/skills/discoop/SKILL.md`, `tests/test_agent_guide.py` | the AI rule (P33). A test checks that the same key phrases (`RULE_PHRASES`) appear in both the guide and the skill, so the two cannot drift apart. |
| `docs/design.md`, `README.md`, `docs/handover.md` | documentation of the CLI side. |
| `CHANGELOG.md` | Added and Changed entries (with two leftovers, section 2.3). |

Public names in `discoop.login` that the TUI may use: `CaptchaRequired()`, `BROWSER_HINT`, `find_login_browser(browser_path=None)
-> Browser`, `BROWSER_TIMEOUT`. `browser_login(...)` is synchronous and calls `asyncio.run`, so **the TUI must not call it**: the
TUI awaits `wait_for_browser_token` directly with its own listener.

### 2.3 Decisions already made about that work (keep them), and leftovers

- **Keep:** a token that Discord rejects after the capture gives exit code 2 with its own message (section 3.1); `config set
  browser-path` requires an existing file; an empty explicit browser path counts as "not given"; `login --format json` has no
  `data_dir` key; notices use `Output.note`, so in plain mode they show only with `-v`.
- **Change:** in the final JSON object the `browser` value becomes the lower-case id (`"chrome"`, `"edge"`, `"chromium"`,
  `"brave"`, `"browser"`), the same as in the progress events. Today it is the display name (`"Chrome"`). Display names stay in the
  human text. Change code, tests and docs together (chunk C3).
- **Leftovers:** `CHANGELOG.md` contains the literal placeholder `TESTS_PASSED` and the clumsy phrase "2 is window closed or time
  out" (make it "2 is window closed or time ran out"); the header of `docs/analyses/browser-login.md` still says the command and the
  config key "come in later steps". Fix them in chunk C6 (for the placeholder use the real number of the last full run).

### 2.4 Not started (step D)

The TUI, the journal entry, the status of P31 to P33 in `docs/requirements.md`, the status block of `CLAUDE.md`.

## 3. Specification (what "done" means)

### 3.1 CLI (already written: verify it against this list and fix what differs)

- Three ways to log in: QR code (no option), `--browser`, `--token`.
- New options, **only with `--browser`**: `--browser-path PATH`, `--timeout SECONDS` (30 to 1800, default 300), `--progress-json`,
  `--format json` (`--format text` is always fine). Misuse is exit code 8 (BAD_ARGS):
  - `--browser` together with `--token`, `--trace` or `--handshake-only` ("<a> cannot be used with <b>." and a hint);
  - `--browser-path`, `--timeout`, `--progress-json` or `--format json` without `--browser` ("<option> only works with --browser.");
  - `--timeout` outside 30 to 1800, or NaN ("--timeout must be between 30 and 1800 seconds.").
- Browser choice: `--browser-path`, then the config key `browser-path`, then auto-detection (Chrome, Edge, Chromium, Brave).
- **Plain mode** (also when stdout is not a terminal): `--browser` is **allowed**. `login` without `--browser` and `login --token`
  are refused with exit code 2. Message: "Login needs the human user: QR login shows a code to scan with their phone, and a token
  must not pass through an AI." Hint: "Tell the user that a browser window will open in which they log in themselves; after they
  agree, run `discoop login --browser`. Or ask them to run `discoop login` in their own terminal."
- **Text mode with `--browser`:** notices through `Output.note`: "Opening {name}. A browser window will open: log in to Discord
  there yourself (password or QR code) and solve a captcha if one appears." and "If your system asks for a passkey or security key,
  you can cancel that dialog and log in with the password or the QR code on the page.", then "Waiting up to M:SS for the login.
  Press Ctrl+C to cancel.", then "Login detected, closing the browser window...". After success: `clear_cache()`, "Logged in as
  {name}." and the note "Token stored in {location}.".
- **`--format json`:** stdout is only `{"logged_in": "yes", "user": <display name>, "user_id": <id>, "token_storage": <location>,
  "browser": <lower-case id>}`.
- **`--progress-json`:** one compact JSON line on stderr per event, no notices, ids and counts only (never names):
  `{"event": "browser_launch", "browser": "chrome"}`, `{"event": "browser_open", "timeout_seconds": 300}`,
  `{"event": "token_captured"}`, `{"event": "logged_in", "user_id": "<id>"}`. Errors stay text (`ERROR NAME:` and `HINT:` on stderr).
- **Exit codes:** the engine's errors pass through (2: window closed or time ran out; 1: no browser, cannot start, no desktop
  session, browser misbehaves). A token that Discord rejects: exit code 2, message "Discord did not accept the token read from the
  browser window.", hint "Run `discoop login --browser` again. If it keeps failing, use `discoop login --token`." Ctrl+C: exit
  code 130 (the engine closes the window and deletes the temporary profile first).
- **QR login and a captcha:** `CaptchaRequired` (exit code 1), message "Discord asked for a captcha, which cannot be solved in a
  terminal.", hint (`BROWSER_HINT`): "Log in through a browser window instead, where the captcha can be solved: `discoop login
  --browser`. As a last resort use `discoop login --token`."
- `TOKEN_HINT` (QR gateway failures): "If QR login keeps failing, use `discoop login --browser` (a browser window where you log in
  yourself) or, as a last resort, `discoop login --token`." `AUTH_HINT` (every command that needs a login): "Run `discoop login`
  (or `discoop login --browser`). AI agents: tell the user a browser window will open in which they log in themselves, wait for
  their consent, then run `discoop login --browser`; never run `discoop login` or `login --token` yourself."
- The token never appears in any output, log record or error text (tests exist for `--debug --log FILE`; keep them).

### 3.2 AI texts (`discoop agent-guide` and the skill; written, verify)

Rule (P33): on exit code 2 an AI agent must not run `discoop login` or `login --token` and never handles a token or a password.
It tells the user in plain words that `discoop login --browser` opens a browser window in which the user logs in themselves
(password or QR code, and any captcha), that the agent never sees the password or the token, and that a passkey dialog may appear
and can be cancelled. It **waits for the user's explicit consent in the chat**. Only then does it run `discoop --plain login
--browser` (optionally with `--format json --progress-json`). The command can take up to 5 minutes, so the agent gives its shell a
longer timeout or runs it in the background. It never types into or clicks in the window and never reads the token, cookies or the
browser profile. Results: exit 0 means logged in (check with `discoop --plain status`); exit 2 means the window was closed or the
time ran out (ask whether to try again); exit 1 means no usable browser (ask the user to run `discoop login` or `discoop login
--token` in their own terminal). Alternative: the user runs `discoop login` themselves.

### 3.3 TUI (step D, to write)

Where: `LoginModal` in `src/discoop/tui/modals.py` (QR, a pasted token and logout today); styles in `src/discoop/tui/discoop.tcss`
(look at the `-qr`, `-short` and `-tall` rules); tests in `tests/test_tui_modals.py` (the QR flow tests there are your pattern; the
modal is driven with fakes, see `_make_dummy_api_factory` in `tests/test_tui_app.py`).

1. A new row `[ Log in with browser (b) ]` (id `row-login-browser`) right below the QR row, and a binding `b`
   (`action_browser_login`, footer label "Browser"). It does nothing while a login is running (`_busy`).
2. A new display state `-browser`, like `-qr`: the form is hidden; the status label says what is going on ("Opening Chrome...",
   then "A browser window opened (Chrome). Log in to Discord there; solve a captcha if one appears.", then "Login detected, closing
   the browser window..."); the countdown label shows the time left (reuse the QR countdown: the engine's `on_opened(deadline)`
   gives the deadline); a short text block says that a passkey dialog can be cancelled and that Esc cancels and closes the window.
   It must fit in 80x24 and in 140x40: add the new state to the parametrized dialog layout test in `tests/test_tui_modals.py`
   (every visible row shows text, no emoji, focus is set).
3. Flow: `find_login_browser()` (config key or auto-detection), then `token = await wait_for_browser_token(listener, browser=...,
   timeout=BROWSER_TIMEOUT)` in a worker through `_guarded`, then the existing `_finish_login(lambda: token)` (verifies in a
   thread, stores, clears the cache, notifies, dismisses with True). The modal is already the listener of the QR flow
   (`on_connecting`, `on_qr`, ...): add `on_launching`, `on_opened` and `on_captured` the same way (or use a small listener object
   if a name clashes with Textual). Inject `find_browser_fn` and `wait_for_browser_token_fn` into the constructor (like
   `wait_for_ticket_fn`), so the tests never start a browser or touch the network.
4. **Esc** cancels the worker (`workers.cancel_node`); the engine's cleanup closes the window and deletes the profile; the dialog
   closes and stores nothing. A test with a fake engine checks that the cancellation reaches it.
5. **Failures** return to the form, like the QR failures, and show the message **and the hint** (today `_login_failed` shows only
   the message, so the TUI drops every hint). For `CaptchaRequired` show the message and "Press b to log in through a browser
   window instead." and put the focus on the browser row. If Discord rejects the token read from the browser, show the same text
   as the CLI (section 3.1).
6. The Help screen lists the key (`GUIDE_KEYS` in `modals.py`; `tests/test_tui_r4g.py` checks that keys appear in the help and in
   the footer).
7. All TUI texts are plain ASCII, no emoji, as everywhere in the TUI.

## 4. Hard rules

1. **Git:** only the coordinator runs git, and only `git status`, `git diff`, `git log`, `git add <explicit paths>` and
   `git commit`. Never `add -A` or `add .`, never `push`, `checkout`, `reset`, `stash`, `rebase` or `commit --amend`, never an
   interactive git command. **No push, ever:** pushing is the owner's decision. (`AGENTS.md` reserves git for the coordinator; this
   round the owner explicitly wants frequent commits.)
2. **Discord: never call the Discord API or CDN, and never run a `discoop` command that does.** Allowed manual commands:
   `uv run pytest ...`, `uv run discoop --help`, `uv run discoop <command> --help`, `uv run discoop agent-guide`. Do **not** run
   `status`, `servers`, `channels`, `threads`, `messages`, `doctor`, `ui`, `login` in any form, `logout`, `config set` or `config
   unset`: they use or change the owner's real stored token and settings. *An earlier agent ran `discoop --plain status` by mistake
   and it contacted Discord with the owner's real token. Do not repeat it.*
3. **No real browser**, not even headless: everything is tested with the fakes (`tests/fake_cdp.py`, `tests/browser_rig.py`). The
   real login is checked later by the owner on their own account.
4. **Existing tests:** do not remove or weaken an assertion, no `skip` or `xfail`. You may change an expected value only where this
   brief changes the behaviour (section 3), and you justify each such change in the report.
5. **No new dependencies.** Do not touch `pyproject.toml` or `uv.lock`; do not run `uvx`, `pip`, `npm` or anything that downloads.
   No linter is configured.
6. **The engine is frozen** (`src/discoop/browser_login/**`, section 2.1). The scope is this brief: do not "improve" anything else
   (for example a browser check in `discoop doctor` is out of scope).
7. **English only** everywhere (code, comments, docs, tests, tool texts, commit messages), absolute ISO dates, `.py` files with LF
   line endings. A fact that was not checked on a real account is an `[ASSUMPTION]`, never `[VERIFIED]`.
8. **No secrets and no real people:** fake tokens only (`FAKE-TOKEN-0000`), no real names, ids or message texts. Do not read or
   touch the owner's keyring, `%LOCALAPPDATA%\discoop`, `Temp/`, `exports/` or `prototype/out/` (the only exception is your report,
   section 8).
9. **Project rules stay as they are:** do not edit the rules in `CLAUDE.md` and `AGENTS.md`; chunk D4 edits only the Status block
   of `CLAUDE.md`.
10. Never delete lock files you did not create. If a test fails in a file that belongs to a chunk you have not reached yet, finish
    your chunk first and look again.

## 5. Chunks and commits

Order matters. "Targeted tests" are the test files named in the row (`uv run pytest tests/test_x.py -q`). Before each commit read
its diff against section 3: fix the bugs you find and add a test for each; do not commit what you do not understand. Run the **full**
suite after C3, after C6 and after D4.

### Part 1: check and commit the CLI side (step C)

| Chunk | Files | What | Commit subject (example) |
|---|---|---|---|
| **C1** | `src/discoop/config.py`, `tests/test_config.py`, `tests/test_tui_modals.py` | the `browser-path` config key | `Add the browser-path config key for browser login` |
| **C2** | `src/discoop/login.py`, `src/discoop/remote_auth/protocol.py`, `src/discoop/errors.py`, `tests/browser_rig.py`, `tests/test_login_browser.py`, `tests/test_remote_auth_flow.py` | `browser_login`, `CaptchaRequired`, the new hints | `Add browser_login and recommend it when QR login hits a captcha` |
| **C3** | `src/discoop/cli.py`, `tests/test_login.py`, `tests/test_cli.py`, `tests/test_login_browser_cli.py`, `tests/test_service.py` | the `login --browser` command, options, JSON and progress output, plain-mode rules; the lower-case browser id in the JSON (section 2.3) | `Add discoop login --browser with JSON and progress output` |
| **C4** | `src/discoop/agent_guide.py`, `.claude/skills/discoop/SKILL.md`, `tests/test_agent_guide.py` | the AI rule (P33) | `Tell AI agents to announce the browser window and wait for consent` |
| **C5** | `docs/design.md`, `README.md`, `docs/handover.md` | documentation of the CLI side; no statement may say the TUI part exists yet | `Document login --browser in the design, README and handover` |
| **C6** | `CHANGELOG.md`, `docs/analyses/browser-login.md` | fix the leftovers of section 2.3 | `Record login --browser in the CHANGELOG and update the analysis` |

### Part 2: the TUI and the records (step D)

| Chunk | Files | What | Commit subject (example) |
|---|---|---|---|
| **D1** | `src/discoop/tui/modals.py`, `src/discoop/tui/discoop.tcss`, `tests/test_tui_modals.py`, `tests/test_tui_r4g.py` (only if its key checks need the new key) | section 3.3 points 1 to 4, 6 and 7: row, key `b`, `-browser` state, flow, Esc, injection, help; tests: success stores the token and dismisses with True, a closed window and a timeout return to the form, Esc reaches the fake engine, the layout test covers the new state | `Add browser login to the TUI login dialog` |
| **D2** | the same files | section 3.3 point 5: hints in the login dialog, the captcha pointer to `b`, the rejected token; tests: QR login with a captcha shows the pointer and focuses the browser row, other errors show message and hint | `Show hints in the TUI login dialog and point captcha failures to browser login` |
| **D3** | `docs/design.md`, `README.md`, `CHANGELOG.md`, `docs/analyses/browser-login.md` | the TUI in the docs; a CHANGELOG entry (Added: browser login in the TUI; Changed: the login dialog shows hints); the analysis checklist item 7 no longer says "once the TUI step exists" | `Document browser login in the TUI` |
| **D4** | `docs/journal.md`, `docs/requirements.md`, `CLAUDE.md` | the records below | `Record browser login: journal, requirement status, project status` |

**D4 in detail** (you are the only one who writes the journal in this round):
- `docs/journal.md`: a new section `## 2026-11-10` at the top (newest first; copy the style of the latest section). What was
  done (ADR 0022, the engine, the CLI, the AI rule, the TUI), decisions, the test count, and these incidents, as facts without
  names or ids:
  1. Edge on Windows relaunches itself: the process Discoop starts exits with code 0 after about 0.05 s and the real browser
     carries on under another process id. The engine handles it (analysis, fact P1).
  2. During its local check the engine's author left five headless Edge process trees running against five temporary profile
     folders (its early probes took the relaunch for a failed start). It found them with a read-only process listing, stopped only
     those five main processes (identified by a unique marker in their command lines) and deleted the folders. The owner's own
     Chrome and Edge windows were not touched.
  3. A one-off safety-net script of that check once matched and ended its own shell; nothing else was affected.
  4. That agent ran two read-only `git log` commands at the start, although sub-agents never run git.
  5. The agent that wrote the CLI side ran `discoop --plain status` once by mistake: one read-only `GET /users/@me` request went to
     Discord with the owner's stored real token, and the account's display name and id were printed into that agent's tool output
     only (nothing was written to the repository). All its other runs of the real CLI were local.
  - **Next** block: the owner's real-account check (analysis section 6: Chrome and Edge, password login, QR code on the page, a real
    captcha if one shows, closing the window, Ctrl+C, a short `--timeout`, the TUI with F3 and `b` and Esc, a hard kill, the passkey
    dialog, `status` the next day, headed-window behaviour); still unverified: Linux and macOS, snap or flatpak browsers, the real
    captcha flow, the TUI with the real engine on Windows; possible follow-ups, not started: a browser check in `discoop doctor`,
    a `browser-path` row in the TUI Settings dialog; pushing is the owner's decision.
- `docs/requirements.md`: P31 to P33 change from "status: planned" to implemented, with the honest note that it is verified by tests
  with fakes (and the engine against local Chrome 157 and Edge 157), and that a real login with a real account is not verified yet.
- `CLAUDE.md`: only the Status paragraph: the date becomes 2026-11-10, browser login is added to the implemented list, the test
  count is the real one, and "not yet verified on a real account" gains the browser login (real browser, captcha). Keep its style
  and links.

## 6. Commits (often, by the coordinator)

- **Commit after every chunk of section 5 as soon as it is finished and checked.** If you are about to start something new and
  `git status` shows finished work, commit first. If a chunk turns out bigger than expected (a diff of several hundred lines, or two
  separate concerns), split it by file into two or more commits. Many small honest commits are what the owner wants; one huge
  commit at the end is the thing to avoid.
- Before each commit: `git status --short`, read `git diff -- <the chunk's files>` (no debug leftovers, no placeholders, no secrets),
  run the chunk's targeted tests, then `git add <explicit paths>`, check `git diff --cached --name-only` (only the chunk's files),
  `git commit`.
- Message: English, imperative, a subject of at most 72 characters, a short body of bullet points saying what and why (look at
  `git log` for the style), and a `Co-Authored-By:` line with your own name as `AGENTS.md` requires. **No push.**
- Intermediate commits only need to be coherent; the full suite must be green at the end of Part 1 and at the end of Part 2. Do not
  use `git stash` or interactive git to test an intermediate state. If a file spans two chunks, commit it with the chunk that needs it
  and say so in the report.
- Never rewrite history: no `--amend`, no `rebase`, no `reset`. A wrong commit is fixed by one more commit.
- If a commit fails because of `index.lock` from a running process, wait a moment and retry; never delete a lock file you did not
  create.
- After each commit add its hash and a line about the chunk to the report.

## 7. Final checks (coordinator, after D4)

1. The full `uv run pytest` is green: the count is at least 1154 plus the new TUI tests, with the same single skip as at the start.
   Put the real count into the report.
2. `git grep -n "TESTS_PASSED\|TODO\|FIXME\|XXX" -- . ':!uv.lock' ':!docs/briefs'` finds nothing new that you added.
3. **Links:** every relative markdown link resolves. Script (save it outside the repository, run it from the repository root):

```python
import re, subprocess
from pathlib import Path
files = subprocess.run(["git", "ls-files", "*.md"], capture_output=True, text=True, encoding="utf-8").stdout.split()
bad = []
for f in files:
    for m in re.finditer(r"\]\(([^)\s]+)\)", Path(f).read_text(encoding="utf-8")):
        t = m.group(1)
        if re.match(r"[a-z]+:", t) or t.startswith("#"):
            continue
        path = t.split("#")[0]
        if path and not (Path(f).parent / path).exists():
            bad.append((f, t))
print(len(bad), "broken links")
for f, t in bad:
    print(" ", f, "->", t)
```

4. **English only:** `git grep -nP "[áäčďéíĺľňóôŕšťúýžÁČĎÉÍĽŇÓŠŤÚÝŽ]" -- . ':!uv.lock' ':!docs/briefs'` shows only the documented Unicode fixtures in
   `tests/` (list any hit with the reason in the report).
5. `uv run discoop --help`, `uv run discoop login --help` and `uv run discoop agent-guide` run, and their texts agree with section 3.
6. Consistency: the same flag names and the same rule wording in the CLI help, `agent-guide`, the skill, the README, `docs/design.md`
   and the TUI texts. `git status` is clean. `git log --oneline` lists the commits of this round (one per chunk or more).
7. Nothing was pushed.

## 8. Report

Write `prototype/out/antigravity-round-4-report.md` (git ignores it) **as you go**, after each commit: the chunk, the files, the
commit hash, the test result (counts passed and failed), decisions you made, anything odd or unverified. At the end add the state of
the checks of section 7 and a list of everything that is still open. If something stops you in the middle (usage limit, error), the
report must tell the owner exactly where you got to.
