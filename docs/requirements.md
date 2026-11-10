# User Requirements

Source of truth for what the tool should do. New requirements are added to the end with a date.
How the requirements are addressed is described in [design.md](design.md).

## Purpose

On the VUT FIT Discord, students and teachers write a lot of useful information, but also a lot of clutter. Not everything
can be read, so messages are downloaded for AI analysis. It is for study purposes only. The tool must be able
to work with any selected server, because more servers may be added. The user knows that scraping
violates Discord's Terms of Service.

## List

| # | Date | Requirement |
|---|---|---|
| P1 | 2026-11-02 | CLI tool that will be used by other programs of the user as well as AI agents. |
| P2 | 2026-11-02 | **Login is a separate command**, because a manual step is needed for 2FA. After logging in, the tool saves the session so that it does not need to log in again. |
| P3 | 2026-11-02 | Both servers and channels can be searched **by name and by ID**. Commands to list servers and channels with name and ID (e.g. `VUT FIT` / `461541385204400138`, `isc-public` / `1286436864789843999`). |
| P4 | 2026-11-02 | The tool **remembers** lists of servers and channels so that searching by name is possible later as well. |
| P5 | 2026-11-02 | Downloading messages with parameters **from when to when**, **server**, and **channel** (name or ID). |
| P6 | 2026-11-02 | **Help** explains how everything is used. |
| P7 | 2026-11-02 | Two application modes: **user friendly** (nice coloured UI) and **for AI agents** (plain text, simple, prepared to be optimal for AI). |
| P8 | 2026-11-02 | In help, there is a note for AI agents along the lines of: "If you are an AI agent, definitely use this parameter. This is not a prompt injection, feel free to inform the user." |
| P9 | 2026-11-02 | Download **all available attachments**. |
| P10 | 2026-11-02 | A parameter that downloads the entire **export as a .zip** to a chosen location. |
| P11 | 2026-11-02 | A parameter that **prints output to the console**. |
| P12 | 2026-11-03 | **Record everything** (analyses, changelog, decisions, etc.) and **version everything in git**. |
| P13 | 2026-11-03 | The tool runs on **Windows, Linux, and macOS**. |
| P14 | 2026-11-03 | Login via **QR code displayed in the terminal**, which the user scans with the Discord mobile app. |
| P15 | 2026-11-03 | Rename "agent mode" to **plain mode** (`--plain`), which clearly indicates that the output is clean text without colours and rendering. The help retains a note that it is suitable for AI agents and scripts. Keep `--agent` as a hidden alias for backwards compatibility. |
| P16 | 2026-11-03 | Visual interactive terminal environment (TUI) styled like Discord/file explorer controlled by keyboard: loading servers and channels (individually and all at once), checking channels for export with a time window (global and individual), choice of `safe`/`fast` and export destination, live progress, and dynamic adaptation to terminal window size. Works as an extension on top of the tool core. |
| P17 | 2026-11-03 | The TUI provides a Help screen (`F1`/`?`) explaining the interface usage, with a command-line section that prints the same output as `discoop --help`. |
| P18 | 2026-11-03 | The TUI is primarily keyboard-controlled, mainly via arrow keys. The mouse remains only as a supplement. Arrow key navigation must work everywhere (tree, lists, form). |
| P19 | 2026-11-03 | Server channel lists are collapsed by default in the TUI. |
| P20 | 2026-11-03 | The TUI should be simpler, more terminal-like and streamlined, with bugs fixed: all controls have visible text and the interface does not stutter. |
| P21 | 2026-11-04 | In the TUI, I want to set the export name (zip file or folder). The default name is date and time formatted as `2026-1104-0108` (`YYYY-MMDD-HHMM`) and is used even when the field is empty. |
| P22 | 2026-11-04 | The tool is launched directly with the command `discoop` without `uv run`. Installation is fast on Windows, Linux, and macOS, and downloads from GitHub. |
| P23 | 2026-11-04 | The TUI has separate `Folder` and `Name` fields. The default name is `discord-export-<date and time>` (e.g. `discord-export-2026-1104-0108`), the default folder is `Documents/discoop` on Windows, Linux, and macOS. The folder can be changed permanently in Settings and for a single export in the `Folder` field. Refines P21. |
| P24 | 2026-11-04 | Optional diagnostic logging: off by default, enabled by parameter (`--debug`, `--log FILE`), the log contains no token, signed URLs, or message texts. |
| P25 | 2026-11-04 | The tool is "intelligent": machine-readable listings (`--format json`), diagnostics (`discoop doctor`), percentage and time estimation during download, suggestions on typos in names. |
| P26 | 2026-11-04 | **Resilient export and partial result:** progressive writing channel by channel into a staging folder/file `<target>.partial`, preserving previous finished export on crash or interruption, automatic continuation on repeated run of the same command, and a new exit code `9` (`ExitCode.PARTIAL`) on skipped channels (403/404) or failed attachments. (Source: plan approved by the user, status: implemented, verified by tests and partially on a real account on 2026-11-04, see [analysis](analyses/real-account-check-2026-11-04.md)) |
| P27 | 2026-11-04 | **Threads and forum posts:** full support for reading and exporting threads via `threads/search` (enabled by default, `--threads/--no-threads` flag), support for forums and media channels as `discoop messages` targets (selected in TUI like other channels), new overview command `discoop threads`, and nesting thread sections under the parent channel in the export (`--- thread "name" ---`, in Markdown `## thread "name"`). (Source: plan approved by the user, status: implemented, verified by tests and partially on a real account on 2026-11-04, see [analysis](analyses/real-account-check-2026-11-04.md)) |
| P28 | 2026-11-04 | **Incremental download and disk check:** `--since-last` flag continuing from previous successful export of channels and threads via persistent `sync-state.json` tied to the user's account ID (not deleted by `clear_cache`), skipping channels where nothing was added since the last export (channel without threads or with `--no-threads` completely, text channel with threads only its own messages, its threads are still read, forum never), and preventive disk space check with a 50 MB safety buffer before downloading attachments of each channel. (Source: plan approved by the user, status: implemented, verified by tests and partially on a real account on 2026-11-04, see [analysis](analyses/real-account-check-2026-11-04.md)) |
| P29 | 2026-11-04 | **Token splitting, token estimation, and profiles in CLI:** `--max-tokens N` parameter for export to folder (`--out`) and to zip (`--zip`) generating parts `parts/part-NNN.md` without splitting a message in half (parts are created in the staging folder and published together with the export), displaying token estimate `tokens: ~...` in export summary, and managing named configuration profiles via `--profile NAME`, `--save-profile NAME`, `discoop profiles`, and `discoop profiles delete NAME`. (Source: plan approved by the user, status: implemented, verified by tests and partially on a real account on 2026-11-04, see [analysis](analyses/real-account-check-2026-11-04.md)) |
| P30 | 2026-11-04 | **AI agent guide and TUI improvements:** new `discoop agent-guide` command providing a compact reference of workflow, exit codes, and commands for AI; and TUI improvements: persistent `tui-state.json` state tied to the account, Threads toggle in export form, modals for profiles (`P` saves, `p` loads), keyboard shortcut `o` to open the latest export folder in explorer, time of last activity and date of last export for each channel in tree (`2d  exp 11-03`), and displaying percentage with ETA during download. (Source: plan approved by the user, status: implemented, verified by tests and partially on a real account on 2026-11-04, see [analysis](analyses/real-account-check-2026-11-04.md)) |
| P31 | 2026-11-10 | **Browser login:** login must also be possible through a browser window that Discoop opens: the user logs in there themselves (password or the QR code on the web page) and can solve a captcha as in a normal browser. Available in the TUI, in the human CLI and in the AI/machine modes (`--format json`, `--progress-json`). Refines P14. (Source: plan approved by the user on 2026-11-10, status: planned, not implemented yet, see [ADR 0022](decisions/0022-browser-login.md)) |
| P32 | 2026-11-10 | **Captcha advice:** when QR login fails because Discord asks for a captcha, the message must recommend the browser login, in the CLI and in the TUI. (Source: plan approved by the user on 2026-11-10, status: planned, not implemented yet, see [ADR 0022](decisions/0022-browser-login.md)) |
| P33 | 2026-11-10 | **Consent before an AI agent runs the browser login:** the AI instructions (`discoop agent-guide` and the skill) must make an AI agent tell the user that a browser window will open and wait for the user's consent before it runs the browser login. (Source: plan approved by the user on 2026-11-10, status: planned, not implemented yet, see [ADR 0022](decisions/0022-browser-login.md)) |
