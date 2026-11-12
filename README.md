# Discoop

CLI tool for downloading messages and attachments from Discord servers the user is a member of. Used for AI analysis
of study information. Personal project for study purposes.

**Warning:** scraping violates Discord's Terms of Service. You use the tool at your own risk; account suspension is possible.

**Status:** first `1.x` release (run `discoop --version` or see [CHANGELOG.md](CHANGELOG.md)); partly verified on a real account on Windows 10 (see the login and [analysis](docs/analyses/) notes; Linux and macOS untested; live GitHub Actions release runs and GitHub Release update checks await the first workflow-driven release). Working features include `login` (QR code in terminal, `--browser` window, or `--token`), `status`, `logout`,
`servers`, `channels`, `threads`, `config`, `messages` (printing messages to console, downloading attachments and resilient export to folder
or zip with manifest and automatic resume, download modes `safe` and `fast`, incremental download `--since-last`, token splitting `--max-tokens`), interactive terminal user interface `discoop ui` (TUI), passive GitHub release update notifications (CLI, TUI, and `doctor`), diagnostics `doctor`, diagnostic logging, profile management, and reference `discoop agent-guide`. Threads and forums are fully supported.

## Installation

No need to install Python separately: [uv](https://docs.astral.sh/uv/) uses Python 3.12+ and will download it automatically if missing.

**1. Install uv** (once only), then open a new terminal.

Windows:

```
winget install --id astral-sh.uv -e
```

Linux and macOS:

```
curl -LsSf https://astral.sh/uv/install.sh | sh
```

macOS via Homebrew (alternative):

```
brew install uv
```

**2. Install discoop** (same on all operating systems; installs from the `stable` release branch):

```
uv tool install git+https://github.com/filbam/Discoop@stable
```

**Note:** the `stable` branch is created by the first workflow-driven release. Until that release exists, the `@stable` command fails ("ref not found"). For now install from `main` (`uv tool install git+https://github.com/filbam/Discoop`) and switch later with the `--force` command under **Upgrade** below.

```
uv tool update-shell
```

Open a new terminal and verify the installation:

```
discoop --version
```

**Upgrade:**

```
uv tool upgrade discoop
```

If you previously installed Discoop from `main` (without `@stable`), switch once so future `uv tool upgrade discoop` runs track tested releases (works only once the `stable` branch exists, see the note above):

```
uv tool install --force git+https://github.com/filbam/Discoop@stable
```

Release notes for every version are on the [Releases page](https://github.com/filbam/Discoop/releases).

**Uninstall:** first `discoop logout` (removes the stored token), then:

```
uv tool uninstall discoop
```

Revoke the Discord session in Settings → Devices.

On Linux without keyring (Secret Service), the token is stored in a file with `0600` permissions.

## Usage

```
discoop --help
discoop login         # scan QR code in Discord app: Settings → Scan QR Code
discoop login --browser   # log in in a browser window instead (if QR login fails because of a captcha)
discoop login --token     # last resort: paste a token
discoop status
discoop ui            # interactive terminal user interface (TUI)
discoop servers
discoop channels -s "VUT FIT"
discoop threads -s "VUT FIT" -c help-center       # list of threads and forum posts
discoop agent-guide   # compact text reference for AI agents
discoop profiles      # list of saved configuration profiles
discoop config set default-server "VUT FIT"
discoop config set export-dir ~/discord-exports   # export folder (TUI: default, CLI: for relative paths)
discoop config set mode safe               # mode: safe (default) or fast
discoop config set browser-path <file>     # browser program for `login --browser` (default: found automatically)
discoop config set update-check off        # turn off the passive GitHub release check (on by default)
```

**Logging in:** `discoop login` shows a QR code in the terminal; scan it in the Discord app (Settings → Scan QR Code).
Sometimes Discord asks for a captcha during this, and a terminal cannot solve one. Then log in through a browser window:

```
discoop login --browser                       # a browser window opens: log in there yourself
discoop login --browser --timeout 600         # wait up to 10 minutes (default 300 seconds, allowed 30 to 1800)
discoop login --browser --browser-path "C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe"
discoop login --token                         # last resort: paste a token (hidden prompt or stdin)
```

- Discoop opens your installed Chrome, Edge, Chromium or Brave (in this order; not Firefox) in a **separate window with a
  temporary profile** on Discord's login page. You log in there yourself: password, the QR code shown on the web page,
  2FA, captcha. Discoop never sees your password. It reads the login token from that window over the Chrome DevTools
  Protocol, closes the window, deletes the temporary profile, verifies the token and stores it exactly like after a QR
  login. Your own browser and its profile are not used. No new dependency.
- `--browser-path <file>` or `discoop config set browser-path <file>` chooses another browser program. The option wins.
- On Windows a Windows Security (passkey) dialog may appear when the login page opens. You can cancel it and log in with
  the password or the QR code on the page.
- Closing the window or running out of time is exit code `2`. No usable browser (or, on Linux, no desktop session) is exit
  code `1`. Ctrl+C cancels and cleans up.
- `--format json` prints the result as one JSON object. `--progress-json` writes progress events (JSON lines) to stderr:
  `browser_launch`, `browser_open`, `token_captured`, `logged_in`.
- **AI agents never log in on their own.** In plain mode `discoop login` and `discoop login --token` are refused (exit
  code `2`). Only `discoop login --browser` is allowed, because the human logs in in the window. The agent has to tell you
  that a browser window will open, wait for your consent, and then run `discoop --plain login --browser` (it may take up to
  5 minutes). See `discoop agent-guide`.
- **Verified and still open:** CLI browser login (`discoop login --browser` with Chrome and Edge, `--timeout 30` exit code `2`, clean profile and process removal) and starting `discoop ui` were checked on a real account on Windows 10 (2026-11-10, [docs/analyses/browser-login.md](docs/analyses/browser-login.md)). Still unverified: QR code on the web page, a real captcha, closing the window with X, Ctrl+C, `Esc` in the TUI, the Windows passkey dialog, `source=header`, `discoop status` the next day, hard kill, Linux, and macOS.

Interactive terminal user interface (keyboard-controlled TUI: single tree of servers, categories, and channels, arrow keys for navigation,
Space/Enter to select, Tab to switch panels, `F3` to log in via QR, browser `b`, or token, `F5` starts export, `P` saves selection as a profile and `p` loads it, `o` opens the folder of the last export, Help via `F1`; colours according to terminal):

```
discoop ui
```

TUI export goes by default into the `discoop` folder in Documents (Windows `C:\Users\<username>\Documents\discoop`, Linux
and macOS `~/Documents/discoop`) under the name `discord-export-<date and time>`. The `Folder` field changes the folder for a single export,
the `Name` field changes the name (never a path). You can permanently change the default folder in Settings (`F2`, `Export folder`) or via
`discoop config set export-dir <folder>`. The `discoop messages --out/--zip` command is unaffected; its relative paths
apply from the current working directory (or from `export-dir`, if configured).

Messages to console (last 24 hours by default, from oldest):

```
discoop messages -s "VUT FIT" -c isc-public              # last 24 h (safe mode, including threads)
discoop messages -s "VUT FIT" -c isc-public --no-threads  # disable downloading threads
discoop messages -s "VUT FIT" -c isc-public --since-last  # only new messages since last export
discoop messages -s "VUT FIT" -c isc-public --fast       # fast mode (100 messages/batch)
discoop messages -s "VUT FIT" -c isc-public --from 7d
discoop messages -c 1286436864789843999 --from 2026-10-01 --to 2026-10-31
discoop messages -s "VUT FIT" -c "isc-*" --last 20       # 20 newest from each channel
discoop messages -s "VUT FIT" -c isc-public --format json
discoop messages -s "VUT FIT" -c isc-public --format md   # Markdown
discoop --plain messages -s "VUT FIT" -c isc-public      # plain mode (no colours), token-efficient (for AI agents and scripts)
```

Exporting messages and downloading attachments:

```
discoop messages -s "VUT FIT" -c isc-public --from 30d --out exports/isc
discoop messages -c 1286436864789843999 --from all --zip exports/isc.zip
discoop messages -s "VUT FIT" -c isc-public --out exports/isc --print    # save and print messages
discoop messages -s "VUT FIT" -c isc-public --out exports/isc --no-files # text and manifest only
discoop messages -s "VUT FIT" -c isc-public --out exports/isc --max-file-size 10 # skip files > 10 MB
discoop messages -s "VUT FIT" -c isc-public --out exports/isc --max-tokens 50000 # split into parts/part-NNN.md
discoop messages --save-profile fit-study -s "VUT FIT" -c "isc-*" --from 7d      # save profile
discoop messages --profile fit-study                                             # load profile
```

- `--safe` (default): mimics human scrolling – smaller batches (25 messages), randomised pauses of 2–4.5 s between requests, reading pauses of 8–15 s every 5–8 pages, spacing between channel switches (3–6 s) and between downloading files from CDN (1–3 s).
- `--fast`: fast batch downloading (100 messages per request, fixed interval).
- `--plain`: plain mode (no colours) without Rich tables or effects (token-efficient, machine-readable; ideal for AI agents and scripts; `--agent` works as a backward-compatible alias).
- `--delay SEC`: request interval configuration (default 1.0 s; scales randomised intervals in safe mode).
- `--from`/`--to`: date (`2026-10-01`), datetime (`2026-10-01T14:00`), relative time (`48h`, `7d`, `2w`),
  `now`, and for `--from` also `all` (entire history). Time is local; a bare date in `--to` covers the entire day.
- `--last N`: N newest messages, from entire history when `--from` is omitted.
- `--max-messages N` (default 5000 per channel): protects against huge outputs.
- `--out DIR` / `--zip FILE`: creates a folder or zip containing `manifest.json`, `messages.md`, `messages.jsonl`, `channels/*.md`, and attachments in `files/<channel>/`. Repeated export into an existing destination reuses already downloaded files. Without `--out`/`--zip`, attachments are only Discord CDN links, which expire after 12 to 24 h.
- `--threads` / `--no-threads`: downloading threads and forum posts (enabled by default). Forums require threads enabled.
- `--since-last`: incremental downloading – resumes from the last successful export of each channel (state stored in `sync-state.json`). Mutually exclusive with `--from`, `--to`, and `--last`. A channel with no new messages since the last run is skipped without requests (a channel with threads skips only its own messages, its threads continue to be read; forums are never skipped).
- `--max-tokens N`: with both `--out` and `--zip`, adds `parts/part-NNN.md` files to the export, splitting `messages.md` into parts of at most N estimated tokens (splits only between messages; individual messages stay intact). Fails with an error without `--out`/`--zip`.
- `--profile NAME` / `--save-profile NAME`: load and save a named parameter profile.
- **Resilient export and exit code `9` (`PARTIAL`):**
  - The export is written channel by channel into a temporary staging folder `<destination>.partial`. The finished export is published only upon successful completion of the entire run, so a previous finished export is never damaged.
  - If the export was interrupted (Ctrl+C, network outage), rerunning the same command automatically resumes from unsaved channels without re-downloading finished ones.
  - If some channels are inaccessible (HTTP 403 `NO_ACCESS` / 404 `NOT_FOUND`), a thread is skipped, or an attachment download fails, Discoop faithfully returns exit code `9` (`ExitCode.PARTIAL`) and prints recommendations for the user/agent.

API verification via prototype is described in [prototype/README.md](prototype/README.md).

## Logging and diagnostics

The tool includes diagnostic commands for checking status and optional safe logging:

```
discoop doctor                         # diagnostics for login, network, export folder, disk space, cache, version, updates
discoop servers --format json          # machine-readable JSON output (also for channels, status, config list)
discoop messages ... --progress-json   # JSONL progress events on stderr for scripts
discoop --debug messages ...           # detailed diagnostic log on stderr (disables spinner)
discoop --log discoop.log messages ... # write diagnostic log to file
```

- `--debug` and `--log FILE`: optional logging (disabled by default). Can also be activated via environment variables `DISCOOP_DEBUG=1` and `DISCOOP_LOG=path`. The log **never contains** authentication tokens, CDN URL signatures, message texts, or usernames (numeric IDs only).
- `discoop doctor`: checks 7 items: login (`login`), Discord API availability (`network`), export folder writability (`export_dir`), available disk space (`disk_space`, FAIL below 100 MB), cache age (`cache`), tool version (`version`), and available release (`update`, always `OK` so it never alters the exit code). Plain mode outputs tab-separated lines; human mode outputs a table.
- `--format json`: machine-readable JSON output for `servers`, `channels`, `status`, `config list`, and `login --browser`.
- `--progress-json`: structured JSONL messages about download progress on `stderr` with percentages and estimated time of arrival (ETA); `login --browser` has its own four events.

## Update notifications

Discoop passively checks GitHub Releases (`releases/latest`) to let you know when a newer release is published. The check is unauthenticated (sends `Accept` and `User-Agent: discoop/<version>` only, never tokens, cookies, or user data even if `GITHUB_TOKEN`/`GH_TOKEN` is set), uses a 2 s timeout, stays silent on network errors or when no release is published yet, and caches results in `update-check.json` inside Discoop's data folder (24 h check interval, 1 h backoff after errors).

- **CLI notice:** on interactive TTY terminals (`stderr`), prints a 3-line notice after command output at most once every 24 h without changing the exit code (waits at most 1 s for a background check at command end). Suppressed automatically for non-TTY runs, `CI`, `ui`/`--ui`, `config` commands, `--version`, `--help`/bare `discoop`, usage errors, `--format json`/`jsonl`, `--progress-json`, and Ctrl+C (`130`).
- **TUI (`discoop ui`):** checks in the background on startup (using the same 24 h cache and 1 h retry delay after a failure) without affecting the CLI's 24 h notice timer, displays `↑ <latest>` in the top bar when a newer release exists, and writes one reminder line with the upgrade command and release notes URL to the Log pane.
- **`discoop doctor`:** the `update` row (7th check) always performs a fresh check (even in `CI`) and reports `up to date (latest <version>)`, `<version> available: uv tool upgrade discoop`, `no release published yet`, `skipped (update-check is off)`, or `could not check: <reason>` while always keeping status `OK`.
- **Disabling update checks:**
  - `discoop config set update-check off` (`on` by default; visible in `discoop config list` in text and JSON) disables all update checks across CLI, TUI, and `doctor` (no network requests). Re-enable with `discoop config set update-check on`.
  - `DISCOOP_NO_UPDATE_NOTIFIER=1` (or `true`/`yes`/`on`) disables all update checks across CLI, TUI, and `doctor`.
  - `CI=1` (or any truthy `CI`) suppresses the automatic CLI check and notice (`doctor` still checks when run explicitly).
- **AI agents:** Discoop never upgrades itself automatically; `discoop agent-guide` instructs AI agents to inform you when they see an update notice or `doctor`'s `update` row and never run `uv tool upgrade` or `uv tool install`.

## Development

Development in the repo uses `uv run` (the `discoop` command is then `uv run discoop`):

```
git clone https://github.com/filbam/Discoop
cd Discoop
uv sync                      # dependencies into .venv
uv run discoop --help
uv run pytest                # tests
```

## Documentation

| Document | Content |
|---|---|
| [docs/requirements.md](docs/requirements.md) | what the tool should do |
| [docs/design.md](docs/design.md) | commands, outputs, architecture, implementation roadmap |
| [docs/analyses/](docs/analyses/) | analyses (e.g. Discord web client data) |
| [docs/decisions/](docs/decisions/README.md) | decisions (ADR) |
| [docs/journal.md](docs/journal.md) | work progress, incidents, next steps |
| [CHANGELOG.md](CHANGELOG.md) | project changes |
