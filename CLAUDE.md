# Discoop

CLI tool for downloading messages and attachments from Discord servers the user is a member of. The output serves
for AI analysis of study materials (mainly the VUT FIT server). It is a personal project for study purposes. The user knows
that scraping violates Discord's Terms of Service.

Status (2026-11-12, first `1.x` release; see [CHANGELOG.md](CHANGELOG.md)): implemented are `login` (QR, browser login `--browser` over CDP via [ADR 0022](docs/decisions/0022-browser-login.md), and `--token`), `status`, `logout`, `servers`, `channels`, `threads`, and `config` (including `browser-path` and `update-check`) with SQLite cache, `messages` to console as well as resilient export of attachments to folder and zip (`--out`, `--zip`, manifest, automatic resume via `.partial`, exit code 9 `PARTIAL`), full support for threads and forums ([ADR 0019](docs/decisions/0019-threads.md)), incremental downloading `--since-last` with `sync-state.json` and disk check ([ADR 0020](docs/decisions/0020-since-last.md)), splitting by tokens `--max-tokens` with both `--out` and `--zip` and profiles in the CLI (`discoop profiles`), reference for AI `discoop agent-guide` (with the browser-login consent rule and the update-notice no-self-upgrade rule) plus skill `.claude/skills/discoop/SKILL.md`, download modes `safe` (default) and `fast`, interactive terminal user interface TUI (`discoop ui`, login dialog `F3` with QR, browser login `b`, pasted token, and error hints/captcha advice, persistent state `tui-state.json`, profiles: `P` saves and `p` loads, opening the folder of the last export `o`, in the tree by the channel the time of last activity and date of last export, top-bar `#update-indicator` and mount worker, keyboard-controlled, single tree, [ADR 0014](docs/decisions/0014-tui-keyboard-one-tree.md)), diagnostics `doctor` (7 checks including `update`), diagnostic logging `--debug`/`--log`, machine-readable outputs `--format json` and `--progress-json`, single-source package versioning ([ADR 0023](docs/decisions/0023-version-and-single-source.md)), release pipeline (`.github/workflows/release.yml`, `scripts/release_notes.py`, and `@stable` branch, P35, [ADR 0024](docs/decisions/0024-releases-tags-and-stable-branch.md) superseding [ADR 0015](docs/decisions/0015-public-repo-and-installation.md)), passive GitHub Releases update notifier across `update_check.py`, CLI stderr, TUI, `doctor`, `config`, `agent-guide`, and `SKILL.md` (P34, [ADR 0025](docs/decisions/0025-update-notifier.md)), parallel tests by default via `pytest-xdist` (P36, [ADR 0026](docs/decisions/0026-parallel-tests.md)), and utility modules. 1355 tests pass (1 skipped on Windows without symlink privileges). Verified by offline tests with fake Discord/CDP and `httpx.MockTransport` (plus engine against local Chrome 157 and Edge 157: [analysis](docs/analyses/browser-login.md)), isolated `%TEMP%` `uv tool` `@stable` install/upgrade/`--force` switch and bare-remote `stable` push checks ([release-process.md](docs/analyses/release-process.md)), parallel suite timings ([test-speed.md](docs/analyses/test-speed.md)), and partially on a real account on Windows 10: round 2 features (2026-11-04, `safe` mode, small windows: [analysis](docs/analyses/real-account-check-2026-11-04.md)) and browser login (`2026-11-10`: Chrome `--debug` `source=storage`, Edge `--browser-path`, `--timeout 30` exit code `2`, clean profile/process removal, and starting `discoop ui`: [analysis](docs/analyses/browser-login.md)). On a real account, not yet verified are QR on the web page, a real captcha, closing the browser window with X, `Esc` in TUI browser login, the Windows passkey dialog, Edge first-run screens, `source=header`, Discord Settings > Devices, `status` the next day, hard kill, real Ctrl+C from console, forum selection and Ctrl+C in TUI, exporting a large forum, and Linux or macOS. On live GitHub, not yet verified are the release workflow on GitHub (`.github/workflows/release.yml` execution across the `ubuntu-latest`/`windows-latest`/`macos-latest` runner matrix), remote `stable` fast-forward push, GitHub Release creation, live HTTPS `uv tool install git+https://github.com/filbam/Discoop@stable` / `uv tool upgrade discoop`, and live `releases/latest` detection once releases are published. Not yet verified in a real terminal are the CLI update notice and the TUI update label.
Current next steps are in the "Next" block of the latest section of the [journal](docs/journal.md). Start from [docs/requirements.md](docs/requirements.md) and
[docs/design.md](docs/design.md).

## Language: the repository is English only

Everything that is committed is English (docs, code, comments, identifiers, commit messages, tests and fixtures, file and folder names, tool texts). The conversation with the user may be in Slovak or any language, but nothing of it enters the repository. Quoted Discord content in tests and docs is made up and English, except small fixtures that test Unicode handling (accents, emoji, normalisation), which state so in a comment. See [ADR 0021](docs/decisions/0021-english-only-repository.md).

## Documentation: record everything

The user wants everything recorded in the repo and versioned in git ([ADR 0001](docs/decisions/0001-record-everything-and-version-it.md)).

| What | Where |
|---|---|
| The user's requirements | [docs/requirements.md](docs/requirements.md) |
| Tool design | [docs/design.md](docs/design.md) |
| Analyses, research, measurements | `docs/analyses/<topic>.md` |
| Decisions (ADR) | `docs/decisions/NNNN-name.md` + line in the [index](docs/decisions/README.md) |
| Project changes | [CHANGELOG.md](CHANGELOG.md), `[Unreleased]` section |
| Work progress, incidents, next steps | [docs/journal.md](docs/journal.md) |

Rules:
- **When to record:** update the record in the same step as the change itself, not retroactively.
  - New requirement from the user → `requirements.md`.
  - Decision → ADR.
  - Finished change → `CHANGELOG.md`.
  - At the end of a work block → entry in `journal.md`.
- **ADR status:**
  - `Accepted` = decided by or clearly agreed to by the user.
  - `Proposed` = your proposal without their agreement.
  - Do not delete a modified decision. A new ADR replaces it and the old one receives the status `Superseded by ADR NNNN`.
- **Analyses:** distinguish `[VERIFIED]` and `[ASSUMPTION]` for every fact.
- **Dates:** always absolute (`2026-11-03`).
- **Language:** English only (see section above and [ADR 0021](docs/decisions/0021-english-only-repository.md)).
- **No sensitive data:** no tokens, cookies, or other people's names or message texts. Anonymise examples.

## Working through agents

The main Claude does not do the work directly; he dispatches agents and manages them ([ADR 0010](docs/decisions/0010-work-through-agents.md)).
- **The main Claude:**
  - talks with the user, splits work into steps, and writes standalone briefs for agents
    (what is done, which files, what the expected result is, how to verify it),
  - inspects the result himself (diff, `uv run pytest`); an agent's report is not proof,
  - does not write code or documents himself; returns errors to the agent. Exception: trivial fix during inspection.
- **Agents:**
  - complete the entire step including tests and records according to this file,
  - never commit and never push,
  - at the end, return a concise report: what they changed, how they verified it, what remained open.
- **Concurrency:** read-only agents may run concurrently. Writing agents never modify the same files; otherwise they run sequentially.
  Only one agent writes the journal in a single work block.
- **External APIs and Discord:** rules prohibiting direct Discord API, Discord CDN, and GitHub API calls (Development section) and the Working with Discord section apply equally to agents.
  An agent in the user's browser only works according to ADR 0003 and only when requested by the user.

## Git

- Repo: `github.com/filbam/Discoop` (public); `main` branch for development, `stable` branch updated by `.github/workflows/release.yml` for user installations (created by the first workflow-driven release; not on GitHub yet as of 2026-11-12, so when the merged `main` with the `@stable` README is pushed, `stable` must exist at the same time: push the tag `v1.1.0` together with `main` or create `stable` by hand first, both only on the user's instruction) ([ADR 0002](docs/decisions/0002-private-repo-and-identity.md), [ADR 0024](docs/decisions/0024-releases-tags-and-stable-branch.md) superseding [ADR 0015](docs/decisions/0015-public-repo-and-installation.md)).
- **Author:** commits are written by `filbam <f.bambura@gmail.com>` (local `git config`).
- **GitHub login:** as `filbam` (`credential.https://github.com.username`). Push goes through this account,
  default is `FilipBambura`.
- **Commit messages:** in English, with a Co-Authored-By line.
- **Commit:** alone after each finished and tested step (agreed 2026-11-03). The main Claude commits
  after inspecting the agent's work ([ADR 0010](docs/decisions/0010-work-through-agents.md)).
- **Push:** only on the user's instruction.

## Development

- **Language and tools:** Python 3.12+, packages via uv ([ADR 0006](docs/decisions/0006-python.md)), code in `src/discoop/`, tests in `tests/`.
- **uv missing from PATH:** might be missing in Claude's shell. In that case:
  `export PATH="$PATH:/c/Users/Filip/AppData/Local/Microsoft/WinGet/Packages/astral-sh.uv_Microsoft.Winget.Source_8wekyb3d8bbwe"`.
- **Commands:** `uv sync`, `uv run pytest`, `uv run discoop …`.
  - `uv run pytest` runs in parallel by default (`-n auto --dist worksteal`, [ADR 0026](docs/decisions/0026-parallel-tests.md)).
  - `uv run pytest -n0 tests/test_x.py` runs serially: for one file or for debugging with `print`/`pdb`.
  - `uv run pytest --ignore-glob="tests/test_tui_*.py"` is a quick run without the TUI tests (about 18 s).
- **Version and release:** `pyproject.toml` (`project.version`) is the single source of truth ([ADR 0023](docs/decisions/0023-version-and-single-source.md)); `discoop.__version__` reads it from package metadata and ongoing docs do not repeat the current number. To release: update `project.version` in `pyproject.toml`, run `uv lock` and `uv sync`, rename `[Unreleased]` in [CHANGELOG.md](CHANGELOG.md) to `## [X.Y.Z] - YYYY-MM-DD` (with a fresh empty `## [Unreleased]` above it), add an entry in [docs/journal.md](docs/journal.md), verify `uv run pytest`, commit on `main`, and (only on explicit user instruction) create the annotated tag `git tag -a vX.Y.Z -m "discoop X.Y.Z"` and push `git push origin main vX.Y.Z`. A release is an annotated `vX.Y.Z` tag; pushing it (only on the user's explicit instruction) triggers `.github/workflows/release.yml`, which runs the tests on Ubuntu, Windows and macOS, builds the package, fast-forwards `stable` and creates the GitHub Release ([ADR 0024](docs/decisions/0024-releases-tags-and-stable-branch.md)).
- **Tool help and messages** are in English ([ADR 0007](docs/decisions/0007-english-in-the-tool.md)).
- **No direct Discord API, Discord CDN, or GitHub API calls by agents** (except `git push` and `gh release` commands the user explicitly asks for): the Discord API/CDN is called only by the prototype or the tool executed by the user (exception: `login --handshake-only` to verify connectivity), and the update notifier's GitHub Releases endpoint is called only by the tool at runtime. All tests run strictly offline using fake Discord/CDP servers and `httpx.MockTransport`.
- **Line endings:** `.py` files and workflow YAML files (`.github/workflows/release.yml`) must use LF (`\n`) line endings in git. On Windows with `core.autocrlf=true`, working-copy checkouts may write CRLF on disk while git stores LF, so tests reading tracked workflow files should normalize `\r\n` to `\n`.
- **Prototype outputs** (`prototype/out/`) are anonymised and ignored by git.

## Working with the user's Discord

Applies after incidents from 2026-11-03 ([ADR 0003](docs/decisions/0003-rules-for-agents-in-the-users-browser.md)):
- **No keyboard.** An agent in the user's browser on Discord must not type or press keys.
- **Clicking only for navigation:** channels in the sidebar, buttons in the channel header, closing panels.
  Never on the message list, reactions, composer, Follow, or Join.
- **Never close tabs or windows** (`tabs_close_mcp` crashed all of Chrome twice). Leave the tab open for the user.
- **Read-only.** Never read or use tokens or cookies.
- **Verifications via custom API calls** are performed by the prototype, which the user runs on their account.
- **Passkey dialog on the login page:** `discord.com/login` in the embedded browser on Windows automatically opens the
  Windows Security system window. Warn the user in advance to cancel it. After the analysis, navigate the tab away from the login page (e.g. `https://example.com`), otherwise it generates new QRs.
