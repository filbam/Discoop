# Design: `discoop`, CLI for downloading messages from Discord

Status: **discussion draft** (2026-11-03). Based on [analyses/discord-analysis.md](analyses/discord-analysis.md).
Accepted decisions are in [decisions/](decisions/README.md).
Items marked **[PROTOTYPE]** depend on things that still need to be verified with own API calls (analysis, section 14).
The 2026-11-03 prototype verified most of them (analysis, section 15). Verified items are marked **[VERIFIED]**.

---

## 1. Goals and boundaries

**Goal:** download messages and attachments from selected servers and channels for a chosen time period. Output comes in three forms:
- for AI agents as plain text,
- for programs as JSON,
- for humans as coloured output in the terminal.

**The tool is read-only.** It calls only `GET` endpoints. The only exception is the read-only `POST /attachments/refresh-urls` **[VERIFIED]**.
It never sends messages, never marks channels as read (`ack`), never reacts, and never tracks threads.

**Out of scope for v1:** DMs, real-time tracking (gateway), local archive of all messages with search (candidate for v2).

## 2. Name

`scoop` conflicts with the Windows package manager Scoop. Proposal: **`discoop`** (Discord + scoop). The local folder is `Discoop`, renamed from `Scoop` on 2026-11-04. Below in the text, the working name is `discoop`.

## 3. Technologies

The tool runs on **Windows, Linux, and macOS** (P13). No part may depend on a single OS.

| Purpose | Choice | Why |
|---|---|---|
| Language | Python 3.12+ | fast development, best libraries for nice CLIs |
| CLI | Typer | commands, parameters, and help from type hints |
| Human UI | Rich | tables, trees, progress bars, colours |
| HTTP | httpx | timeouts, retries, streamed file downloads |
| Login | QR via remote auth gateway: `websockets` + `cryptography` + `segno` (QR in terminal). Fallback: the user's own Chromium-family browser, driven over the Chrome DevTools Protocol with the same `websockets` (no new dependency) | QR login is browserless on all OSes ([ADR 0005](decisions/0005-qr-login-without-a-browser.md)); a browser window solves the captcha that QR login cannot ([ADR 0022](decisions/0022-browser-login.md)) |
| Token storage | keyring (Windows Credential Manager, macOS Keychain, Linux Secret Service) | token is not stored in a plain-text file. On Linux without Secret Service fallback, section 10 |
| Data paths | platformdirs | correct directory on every OS |
| Cache and state | SQLite (stdlib `sqlite3`) | single file, fast name lookup |
| Installation | `uv tool install git+https://github.com/filbam/Discoop` | `discoop` command available globally on Windows, Linux, and macOS ([ADR 0015](decisions/0015-public-repo-and-installation.md)) |

## 4. Commands

```
discoop login                 login by scanning terminal QR code with a phone (or --browser, --token), saves token
discoop logout                deletes the stored token
discoop status                login status, account, cache age
discoop servers               list of servers
discoop channels              list of server channels
discoop threads               list of channel threads/forum posts
discoop messages              download messages (+ attachments)
discoop config                default settings (e.g. default server)
discoop agent-guide           compact reference for AI agents
discoop ui                    interactive terminal user interface (TUI)
discoop doctor                diagnostics of environment, token, and exports folder
discoop profiles              management of named settings profiles
```

**Global options:** `--plain` (alias `--agent`), `--human`, `--quiet`, `--verbose`, `--debug`, `--log FILE`.

The `--debug` and `--log FILE` options (or environment variables `DISCOOP_DEBUG=1` and `DISCOOP_LOG=path`) enable optional structured diagnostic logging to stderr or a file ([ADR 0018](decisions/0018-logging.md)). Thanks to option hoisting, they work both before and after subcommands (e.g. `discoop messages --debug ...`). With `--debug`, the Rich animated spinner is automatically disabled so logs do not corrupt the terminal. The command `discoop ui --debug` is rejected with exit code 8 (the UI fully controls the screen), but `discoop ui --log FILE` is allowed.

Server and channel are specified via **named parameters** `-s/--server` and `-c/--channel`, not positionally.
This is clearer for agents. The value can be an ID or a name (see section 5).
`-s` can be omitted if:
- the channel is specified by ID (channel ID is globally unique), or
- `default-server` is configured (`discoop config set default-server "VUT FIT"`).

### 4.1 `login`, `logout`, `status`

```
discoop login                      QR code in the terminal (default)
discoop login --browser [--browser-path PATH] [--timeout SECONDS] [--format text|json] [--progress-json]
discoop login --token              paste a token (hidden prompt or stdin)
```

There are three ways to log in. The primary path is **browserless QR login** (P14, [ADR 0005](decisions/0005-qr-login-without-a-browser.md)).
When Discord asks for a captcha during it, which a terminal cannot solve, the error recommends **`login --browser`**
(P31, P32, [ADR 0022](decisions/0022-browser-login.md)). **`login --token`** ([ADR 0008](decisions/0008-fallback-login-token.md))
is the last resort. Email and password typed into the terminal are not offered (captcha, handling of the password).

**QR login (default).** The protocol is described in [analyses/discord-login.md](analyses/discord-login.md).

1. `login` connects to `wss://remote-auth-gateway.discord.gg/?v=2` (with `Origin: https://discord.com`),
   generates an RSA-2048 key, and completes the handshake (`hello` → `init` → `nonce_proof` → `pending_remote_init`).
2. It renders a QR code `https://discord.com/ra/<fingerprint>` in the terminal with an expiration countdown (`timeout_ms`, observed ~4 – 5.7 min).
   You scan it in the Discord mobile app (Settings → Scan QR Code).
3. After scanning, it prints "Logging in as <name>, confirm on your phone" (`pending_ticket`).
4. After confirmation (`pending_login`), it calls `POST /users/@me/remote-auth/login`, decrypts the token, verifies it via
   `GET /users/@me`, saves it to the keyring, and prints `Logged in as <name>`.
5. When the QR expires (`4003`) or you cancel the login on your phone (`cancel`), it generates a new QR. It exits after 3 attempts.

Other properties:
- **No need to handle 2FA** in the terminal. The login is confirmed on your already logged-in mobile device.
- **Separate device:** Discord sees the tool as a new session; your regular login remains unchanged.
- **Invalid token** (logged out device, password change): every command exits with code `2` with a message that
   `discoop login` needs to be run.
- **Security:** Neither the QR nor the token is ever logged.
- **Captcha:** if Discord answers the ticket exchange with a captcha, the error (exit code 1, `CaptchaRequired` in `login.py`) says "Discord asked for a captcha, which cannot be solved in a terminal." and the hint recommends `discoop login --browser` first and `discoop login --token` as a last resort (P32). The same pair is the hint of the other QR failures (`TOKEN_HINT`).
- **Fallback paths and `login` in plain mode** are decided: `--token` in [ADR 0008](decisions/0008-fallback-login-token.md), `--browser` in [ADR 0022](decisions/0022-browser-login.md), the plain-mode refusal in [ADR 0009](decisions/0009-login-in-agent-mode.md) as amended by ADR 0022 (see below and section 15, items 7 and 8).
- **Machine-readable output:** `discoop status [--format text|json]` allows obtaining the login status as a structured JSON object on stdout.

**Browser login: `discoop login --browser`** (P31, P32, P33, [ADR 0022](decisions/0022-browser-login.md); the facts and the engine are described in [analyses/browser-login.md](analyses/browser-login.md)):
- **Flow:** Discoop starts the user's installed Chrome, Edge, Chromium or Brave (tried in this order; Firefox has no DevTools Protocol) as a separate instance with a fresh temporary profile, on `https://discord.com/login`. The user logs in in that window themselves: password, the QR code on the web page, 2FA, captcha. Discoop reads the token over the Chrome DevTools Protocol (the localStorage key `token`, or the `Authorization` header of the page's requests to `https://discord.com/api/`; the first hit wins), closes the window, deletes the profile, verifies the token with `GET /users/@me`, stores it exactly like after a QR login, clears the cache and prints `Logged in as <name>.`
- **Which browser:** `--browser-path PATH`, else the config key `browser-path` (section 4.6), else auto-detection. On Linux a desktop session is needed (`DISPLAY` or `WAYLAND_DISPLAY`).
- **Notices** (`Output.note`: dim on stderr for humans, in plain mode only with `--verbose`): before the window opens, what will open and that a Windows passkey dialog may appear, which can be cancelled; then how long Discoop waits and that Ctrl+C cancels; then "Login detected, closing the browser window...". After the login `Token stored in <where>.` as for the other ways.
- **Waiting and exit codes:** `--timeout SECONDS` (30 to 1800, default 300). The user closing the window or the time running out is exit code 2; a missing browser, a browser that cannot start, no desktop session or a protocol failure is exit code 1; a token that Discord does not accept is exit code 2 (nothing is stored); Ctrl+C is 130, and the window is closed and the profile deleted before the command ends.
- **Options:** `--browser-path`, `--timeout`, `--format json` and `--progress-json` without `--browser` are exit code 8, and so are `--browser` together with `--token`, `--trace` or `--handshake-only`, and `--timeout` outside 30 to 1800.
- **Plain mode ([ADR 0009](decisions/0009-login-in-agent-mode.md) amended by ADR 0022):** `login --browser` is allowed: the human logs in in the window and the AI agent never sees the password or the token. `login` without `--browser` and `login --token` stay refused with exit code 2: "Login needs the human user: QR login shows a code to scan with their phone, and a token must not pass through an AI." with the hint to tell the user that a browser window will open, to run `discoop login --browser` after they agree, or to ask them to run `discoop login` in their own terminal.
- **Machine-readable output:** `--format json` prints only one JSON object on stdout: `{"logged_in": "yes", "user": "<display name>", "user_id": "<id>", "token_storage": "<where>", "browser": "<id>"}` (the keys of `status --format json` without `data_dir`, plus the lower-case browser id, for example `"chrome"`). `--progress-json` writes one JSON object per line on stderr, IDs and numbers only and never a name: `{"event": "browser_launch", "browser": "chrome"}`, `{"event": "browser_open", "timeout_seconds": 300}`, `{"event": "token_captured"}`, `{"event": "logged_in", "user_id": "<id>"}`. Errors stay text (`ERROR <NAME>:` and `HINT:` on stderr).
- **Rule for AI agents (P33):** `discoop agent-guide`, the skill and the hint of exit code 2 tell an agent not to run `discoop login` or `login --token` itself, to say that a browser window will open, to wait for the user's explicit consent, to give its shell a timeout longer than the 5 minutes the command may take (or to run it in the background), never to type into or click in the window and never to read the token, cookies or profile. After the command, exit code 2 means the window was closed or the time ran out (ask whether to try again) and exit code 1 means no usable browser (ask the user to run `discoop login` or `discoop login --token`).
- **Status (2026-11-10):** the engine, the CLI command, and the TUI login dialog (`F3` -> `b`) are tested against a fake DevTools server and a fake Discord. On 2026-11-10 (Windows 10, [analysis](analyses/browser-login.md) section 7), the owner checked CLI `discoop login --browser` on Chrome (`--debug`, `source=storage`, `profile_removed=true` in 0.41–0.50 s, `WinVaultKeyring`), Edge (`--browser-path`), `--timeout 30` (exit code `2`), absence of leftover folders/processes, and starting `discoop ui`. Remaining open items (QR on page, captcha, X-button window close, Ctrl+C, `Esc` in TUI, passkey dialog, Edge first-run screens, `source=header`, Discord Settings > Devices, `status` next day, hard kill, Linux/macOS) are listed in section 7 of the analysis.

### 4.2 `servers`

```
discoop servers [--refresh] [--format text|json]
```
Reads from cache. `--refresh` refreshes it, or it refreshes automatically if the cache is empty.
Source: `GET /users/@me/guilds?with_counts=true` **[VERIFIED]**. Columns: name, ID, member count (`approximate_member_count`).

**Implemented on 2026-11-03:**
- Human mode prints a table. Agent mode prints a header `id members name` and rows with tab-separated columns,
  sorted by name.
- The `--format text|json` option: format `json` returns a machine-readable array of objects `[{"id": "...", "name": "...", "member_count": ...}]` on stdout. Cache notes go to stderr.
- If cache was used, a note with its age is written to stderr (the agent sees it only with `--verbose`).

### 4.3 `channels`

```
discoop channels [-s SERVER] [--refresh] [--type text,forum,...] [--flat] [--format text|json]
```
- **Order** matches Discord's sidebar: first channels without a category, then categories by `position`.
  Inside a category, text channels precede voice channels, then by `position`, and finally by ID.
- **Human mode:** tree grouped by category. `--flat` gives a table.
- **Agent mode:** always lines with tab-separated columns `id type category name`.
- **JSON format (`--format json`):** always a flat list of objects `{id, name, type, type_name, category, position}` on stdout (respects the `--type` filter, not a tree). Cache notes go to stderr.
- **`--type` filter** (comma-separated): `text, voice, announcement, stage, directory, forum, media`.
- **Hidden channels** (`___hidden___`, flag `1<<17`) are not listed.
- **Attention, observed during testing on 2026-11-03:** REST also returns **channels that the user cannot see**, with their real names
  (e.g. categories `moderation`, `logging`). `channels` lists them as well for now.
  - The solution is decision 9 (section 15): calculate access from `permission_overwrites` and user roles.
    As of 2026-11-03, this is **deferred** with low priority.
  - The `--include-hidden` option can return as "show inaccessible too".
- **Source:** `GET /guilds/{id}/channels` **[VERIFIED]**.
- **No access:** `403`/`404` on the server exits with code `5`.
- **Server** is specified via `-s` (name or ID); otherwise, `default-server` is used. If neither is present,
  the tool exits with code `8` and a hint.

### 4.4 `threads`

```
discoop threads -s SERVER -c CHANNEL [--from WHEN] [--to WHEN] [--refresh] [--format text|json]
```
Command for a clear listing of channel threads and forum posts without downloading messages ([ADR 0019](decisions/0019-threads.md)):
- **Supported channels:** forum (type 15), media channel (type 16), text channel (type 0), and announcement channel (type 5). If the specified channel does not support threads, the command exits with code 8 (`BAD_ARGS`).
- **Time window:** default window is 30 days (`--from 30d`), the entire history is displayed via `--from all`.
- **Formats:**
  - *Human mode:* Rich table with columns `ID`, `Archived`, `Messages`, `Last activity` (in local time), `Tags` (forum tag names), and `Name`.
  - *Plain mode:* tab-separated lines (TSV) with a header.
  - *JSON format (`--format json`):* array of JSON objects `{id, name, parent_id, type, archived, locked, message_count, created, last_activity, tags}`.
- **Message count (`Messages`, `message_count`):** for a forum post, does not include the starter message. `[VERIFIED]` on a real account on 2026-11-04 on 2 posts: the list showed 9 and 11, the download returned 10 and 12 messages ([analysis](analyses/real-account-check-2026-11-04.md)).

### 4.5 `messages`

```
discoop messages -c CHANNEL [-c CHANNEL ...] [-s SERVER]
                 [--from WHEN] [--to WHEN] | [--last N] | [--since-last]
                 [--threads/--no-threads] [--include-system]
                 [--format text|md|json|jsonl] [--raw]
                 [--print] [--out DIR] [--zip FILE] [--no-files]
                 [--max-messages N] [--delay SEC]
                 [--safe | --fast] [--progress-json]
                 [--max-tokens N] [--profile NAME] [--save-profile NAME]
```

**Channel selection:**
- `-c` can be repeated and supports glob patterns (`-c "isc-*"`, `-c "*-deadlines"`).
- `--all-channels` takes the entire server.

**Time window:**
- `WHEN` can be a date `2026-10-01`, date and time `2026-10-01T14:00`, relative time `48h`, `7d`, `2w`
  or `all` (entire history).
- Time is interpreted in the local timezone. `--to` with a bare date means **including the entire day**.
- Default window is `--from 24h --to now`. The entire history is not downloaded by accident, only via `--from all`.
- `--last N` returns the last N messages.
- `--since-last` returns only messages since the last successful run for the given channel (section 9).

**Output:**
- Without `--out`/`--zip`, output goes to the console. With `--out`/`--zip`, only a summary is printed to the console;
  `--print` prints the messages themselves too.
- `--max-messages` (default 5000 per channel) protects the agent from huge output.
  When reaching the limit, the tool prints a warning and exits with code `0`. The output contains `truncated: true`.

Examples:
```
discoop messages -s "VUT FIT" -c isc-public --from 7d
discoop messages -c 1286436864789843999 --from 2026-10-01 --to 2026-10-31 --zip D:\exports\isc-october.zip
discoop messages -c "isc-*" --since-last --agent
```

**Implemented (steps 2–6, status as of 2026-11-04):**
- **Options:** `-c` (repeatable), `-s`, `--from`, `--to`, `--last`, `--since-last`, `--threads/--no-threads`,
  `--format text|md|json|jsonl`, `--include-system`, `--max-messages`, `--out DIR`, `--zip FILE`, `--print`,
  `--no-files`, `--max-file-size MB`, `--safe`, `--fast`, `--delay SEC`, `--progress-json`,
  `--max-tokens N`, `--profile NAME`, `--save-profile NAME`.
- **Resilient export channel by channel, staging `.partial` and code 9 ([ADR 0017](decisions/0017-reliable-export-and-partial-success.md)):**
  - The `ExportWriter` class (`src/discoop/export.py`) writes continuously channel by channel to a staging folder `<target>.partial` (for zip, `<name>.zip.partial`), without holding the whole export in memory.
  - A finished export is published only upon `close(complete=True)`. A previous finished export is never overwritten by an interrupted run.
  - Automatic resume: running the same command again automatically continues the work-in-progress run and skips already finished channels and their attachments. Relative time windows are calculated from the original `created` time.
  - The combination of `--print` with resume where finished channels already exist is rejected with code 8 before downloading messages.
  - New exit code `9` (`ExitCode.PARTIAL`) when skipping an inaccessible channel (403/404), a failed attachment, or a thread error. Files skipped via `--no-files` or `--max-file-size` do not trigger code 9.
- **Full thread and forum support ([ADR 0019](decisions/0019-threads.md)):**
  - Enabled by default (`request.threads = True`), disabled via `--no-threads`.
  - Forums (type 15) and media channels (type 16) are full targets for `messages` (downloading their threads). A forum with `--no-threads` is rejected with code 8. In the TUI they are selected like other channels; with Threads = no, starting is rejected right in the form (without calling Discord).
  - Downloading active and archived threads via `threads/search` with `limit=25`, pagination by offset, and end detection by an empty or incomplete page (per [docs/analyses/thread-probe-2026-11-04.md](analyses/thread-probe-2026-11-04.md)).
  - The `--max-messages` and `--last N` limits apply independently per channel and per each thread.
- **Incremental download `--since-last` ([ADR 0020](decisions/0020-since-last.md)):**
  - Downloads only messages newer than the last successful export. State is stored in `sync-state.json` tied to the user account ID in `paths.data_dir()` independently of `cache.db` (survives `clear_cache`).
  - Exclusive lower snowflake bound `saved_id + 1` protects against duplicates. State advances only after successful completion of a channel export.
  - Skipping inactive channels: the server channel list is refreshed on `--since-last`, and if a channel has saved state and `Channel.last_message_id <= saved_id`, nothing was added to the channel itself:
    - a channel that cannot have threads, or any channel under `--no-threads`: skipped completely (0 requests),
    - a text or announcement channel with threads enabled: its own messages are not downloaded, but its thread list is fetched and threads are downloaded as usual,
    - forums and media channels are never skipped.
    - `[ASSUMPTION]` `last_message_id` of a text channel is reliable (advances with every new message): confirmed on two samples from thread probe and verified on a real account on 2026-11-04 (20 out of 25 readable channels matched, in 4 it pointed to a newer message, in 1 the message was newer than the field; [analysis](analyses/real-account-check-2026-11-04.md)).
  - After an interrupted and resumed run, channels saved by the interrupted run keep their old state and will be downloaded again on the next `--since-last` (duplicates, nothing lost). The run alerts to this with a note.
  - Preventive free disk space check before downloading attachments for each channel: calculates only what will actually be downloaded (`ExportWriter.bytes_to_download`), and rejects with exit code 1 if less than a 50 MB safety margin remains (`service._check_disk_space`).
- **Token splitting and token estimation:**
  - The `--max-tokens N` option (with `--out` and `--zip`; without them code 8 before calling API) splits `messages.md` into numbered parts `parts/part-NNN.md` with a header `<!-- discoop part X of Y -->`. Splitting occurs only at boundaries of messages and channel/thread headings: a message with a line `# Heading` stays intact. Limitation: a line in the message body that exactly looks like `[2026-01-01 10:00] x` right after an empty line cannot be distinguished from a message header. A message larger than the limit goes into a part by itself with a warning.
  - Parts are created only upon completing the export in the staging folder and published together with other files (both into folder and zip), so a crash before the end leaves no `parts/` at the destination. On repeated export into a folder, old `parts/part-*.md` are replaced with new ones (or deleted if there are none). Parts are not in the manifest, and `--max-tokens` is not part of the resume fingerprint.
  - The export summary displays a line with estimated tokens `tokens: ~... (estimate, about 4 characters per token)`.
- **Named profiles in CLI:**
  - Options `--profile NAME` (loading with override capability) and `--save-profile NAME` (saving settings before execution), commands `discoop profiles` and `discoop profiles delete NAME`.
- **Progress and time estimation (`--progress-json`, percentage, ETA):**
  - The `--progress-json` option suppresses spinner and text notes, and writes one JSON object per line (JSONL) to stderr for events `channel_start`, `page`, `pause`, `channel_done`, `skipped`, `warning`. Contains fields `event`, `index`, `total`, `channel_id`, `fraction`, `eta_seconds`, `seconds`, `reason` (without message texts and names).
  - In regular runs (both in human spinner and in plain mode with `-v`), completion percentage and remaining time estimate (e.g. `~42%, about 3 min left`) are continuously displayed based on snowflake IDs.
- **Download modes (`--safe` vs `--fast`):**
  - `--safe` (default): safe mode mimicking a regular user in a browser. Pagination in batches of 25 messages, random jitter of 2.0 to 4.5 s between API requests, reading pauses of 8.0 to 15.0 s every 5 to 8 requests, a pause of 3.0 to 6.0 s on channel switch, and 1.0 to 3.0 s between downloading attachments from CDN.
  - `--fast`: fast batch mode suitable for exports with a limit of 100 messages per request, fixed pause per `--delay` (or from configuration, default 1.0 s), without additional reading pauses and without pauses between files/channels.
  - `--safe` and `--fast` are mutually exclusive. They can also be permanently set via `discoop config set mode safe|fast`.
- **Channel selection:**
  - `-c` takes a name, ID, or glob pattern. Names and patterns are looked up in server channels from `-s` or `default-server` and **skip categories**, so category `general` and channel `general` do not collide.
  - **Bare ID without `-s`** is looked up in the cache of all servers. If not found, the tool calls `GET /channels/{id}`
    **[ASSUMPTION]**, determines the server from `guild_id`, and fetches its channel list. `default-server` is not used for an ID.
  - Text, voice, and stage channels, announcements, and threads specified by ID are read. Forum (type 15) and media channels (type 16) are also valid targets, downloading only their threads ([ADR 0019](decisions/0019-threads.md)). A category exits with code `8`. A pattern finding only non-readable channels (e.g. categories) exits with code `4`.
  - **`--all-channels` is not implemented yet.** REST also returns inaccessible channels, and without access calculation (decision 9, deferred) it would end up with hundreds of `403`s.
- **Time window:**
  - Formats per design, plus `now`, time with timezone (`2026-10-01T14:00+02:00`, `…Z`), and space instead of `T`.
  - Relative time supports only units `h`, `d`, `w`. `1m` is an error because it could mean minute or month.
  - **Without `--from`, the window is 24 h before `--to`.** With default `--to now`, this is the last 24 h ([ADR 0011](decisions/0011-default-behaviour-of-messages.md)).
  - `--from` is inclusive, `--to` is exclusive.
  - **`--last N`** can be combined with `--from`/`--to`: returns N newest messages in the window. Without `--from`, it takes the entire history, not 24 h.
  - An invalid value, `--to all`, or `--from` after `--to` exits with code `8` before calling API.
- **Limits:**
  - `--max-messages` (default 5000 per channel) is per design. When reaching the limit, the tool prints a warning to stderr, header has `truncated: yes`, JSON has `"truncated": true`, and exit code is `0`.
  - `--last N` is not considered truncation; it is exactly what was asked for.
- **System messages:** besides types 0 and 19, types 20 and 23 (bot replies to slash and context commands) are also treated as regular messages. The initial design had only 0 and 19. `--include-system` displays the others as well.
- **Format `text`** follows 6.2 with these differences and additions:
  - An attachment is `[file] filename size URL` (or local path on export with `--print`).
  - Header has `threads: N (M messages)` only when the channel has threads ([ADR 0019](decisions/0019-threads.md)). Timezone is an offset `UTC+01:00`, not a name (IANA name cannot be reliably determined on Windows without an extra library).
  - Author line may have tags `[bot]`, `(edited)`, `(pinned)`, `(forwarded)`, `(system message, type N)`.
  - `[thread] "name" N messages` next to the message that started a thread.
  - Embeds by type: `[link]`, `[gif]`, `[image]`, `[video]`, `[embed]`. Rich embed (bots) also has description and fields, indented by 4 spaces. Also `[sticker]`.
  - **An embed does not repeat a URL already shown in the message** (in text or in a preceding embed). Only the tag with title remains, e.g. `[link] "Studies"` below the URL in text. An embed without title and description is omitted entirely, e.g. a GIF sent as a bare URL. JSON includes embeds in full.
  - **`[reactions]` is a single line** with all reactions of the message. The notation `🔥5 (2 super)` means 5 reactions, of which 2 are super reactions.
  - **Empty lines at the beginning and end of message text** and rich embed description are trimmed; `\r\n` is normalised to `\n`.
  - `<t:unix>` is converted to local time and `</command:id>` to `/command`. `<@&id>` is always `@role:<id>`.
  - Reply without `referenced_message` is `reply-to (message not available)`. Quote has at most 80 characters.
  - No empty line between messages (fewer tokens). Message starts with a line `[YYYY-MM-DD HH:MM]`.
- **Format `md`:** Markdown with header `# server / #channel`, list of details (`- `), and messages separated by an empty line. Images (`image/*`) are embedded directly as `![name]`(`path`) `size`, other files as links `[name]`(`path`) `size`. In `channels/<channel>.md`, paths have prefix `../files/...`.
- **Format `json`:** a single object `{from, to, last, truncated, channels: [...], messages: [...]}`.
- **Format `jsonl`:** one line of JSON message according to the schema in section 6.2 (without header, which is in manifest).
- **Export (`--out`, `--zip`):**
  - Creates structure: `manifest.json`, `messages.md`, `messages.jsonl`, `channels/<name>.md`, and `files/<channel>/<attachment_id>_<name>`. With `--max-tokens N`, also `parts/part-NNN.md`.
  - By default prints summary to console. `--print` prints messages to stdout with relative paths to local files, and summary goes to stderr.
  - `--no-files` skips downloading attachments (in manifest as `skipped`).
  - `--max-file-size` (default 50 MB, `0` = unlimited) skips larger files.

### 4.6 `config`

```
discoop config set default-server "VUT FIT"
discoop config set delay 1.0
discoop config set export-dir "exports"
discoop config set mode safe
discoop config set browser-path "C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe"
discoop config get delay
discoop config unset delay
discoop config list [--format text|json]
```
Stored in `config.toml` in the configuration directory (section 10).

**Implemented on 2026-11-03:**
- **Keys:** `browser-path`, `default-server`, `delay` (default 1.0 s), `export-dir`, and `mode` (values `safe` or `fast`, default `safe`).
- **`mode`** (added for safe scraping): determines default download mode (`safe` or `fast`).
- **`default-server`** on `set` is looked up as a server (name or ID) and its **ID** is stored, so
  renaming the server does not break the setting.
- **`export-dir`** (added in step 3): directory for relative `--out`/`--zip` paths. Stored as an absolute path.
  In the TUI, it is the default export folder, falling back to `Documents/discoop` ([ADR 0016](decisions/0016-default-export-folder-in-tui.md)).
  CLI without it keeps defaulting to the current directory.
- **`browser-path`** (added 2026-11-10, P31): the browser program that `login --browser` starts. Stored as an absolute path and checked on `set`: it must be an existing file (a folder is rejected; on macOS that means the program inside the `.app` bundle). Without it the browser is found automatically (Chrome, Edge, Chromium, Brave). `--browser-path` on the command wins over it. No default: `config list` shows it empty.
- **Machine-readable output:** `discoop config list --format json` returns configuration as a JSON object on stdout.
- **Unknown key** or invalid value exits with code `8`.

### 4.7 `agent-guide`

```
discoop agent-guide
```

Prints a compact reference for AI on ~1 screen in plain text without ANSI escape sequences:
- recommended workflow (`status` → `servers` → `channels` → `messages`),
- the rules for AI agents, including the section **LOGGING IN** (P33, [ADR 0022](decisions/0022-browser-login.md)): never run `discoop login` or `login --token` and never handle a token or a password; tell the user that a browser window will open in which they log in themselves, wait for their explicit consent, then run `discoop --plain login --browser` (it can take up to 5 minutes: give the shell a longer timeout or run it in the background); never type into the window; what exit codes 0, 1 and 2 mean afterwards. The skill `.claude/skills/discoop/SKILL.md` carries the same rule, and a test keeps the two in step,
- complete exit codes table generated directly from the `ExitCode` enum,
- dynamic list of all registered commands and subcommands from the Typer application with their one-line descriptions.
A link to `discoop agent-guide` is given directly in the `NOTE FOR AI AGENTS` section in `discoop --help`.

### 4.8 `ui`

```
discoop ui
discoop --ui
```

Interactive terminal user interface (TUI) built on the Textual library (P16, P17, [ADR 0013](decisions/0013-tui-and-shared-service-layer.md)). Serves as a visual layer for `--human` mode. In `--plain` mode or when not run in a terminal (`not sys.stdout.isatty()`), it exits with code `8`.

**Layout ([ADR 0014](decisions/0014-tui-keyboard-one-tree.md), replaces the three columns from ADR 0013):**
- **Single tree** servers → categories → channels, all collapsed by default. On the right, the *Export* panel (selection list and form: time window, `safe`/`fast` mode, destination `folder`/`zip`/`preview`, format, attachments, Max MB, Start).
- At the bottom, the log (always visible), below it a line with the equivalent CLI command `discoop messages ...` and a Footer with key bindings (clickable with mouse). In narrow windows (< 95 columns), one panel is shown at a time.
- **Appearance:** Textual theme `ansi-dark` (terminal colors, Ctrl+P changes theme), CSS without hex colors, controls one line tall (`compact=True`), without emojis and large buttons. With Target=preview, Attachments and Max MB are hidden. For QR, the form is replaced by the code (below 27 lines the border and Footer disappear so the QR fits in 80×24).
- **Keys:** primarily keyboard, mouse is supplementary. Complete table (arrows, Space, Enter, Tab, `/`, `e`, `x`/`X`, `a`, `r`, `R`, `L`, `F5`, Esc, `c`, F1–F3, `q`) is in ADR 0014. Keys `P`, `p`, and `o` (profiles and opening export folder) and channel row suffixes in the tree are in its section "Addition 2026-11-04".

**Export folder and name (P21, P23, [ADR 0016](decisions/0016-default-export-folder-in-tui.md)):**
- For Target=folder and zip, the form has two separate rows in this order: `Folder` and `Name` (both empty by default, hidden for preview). `Name` is never a path.
- **`Folder`:** empty = default folder. That is `export-dir` from config, otherwise `discoop` in the user's Documents (`platformdirs.user_documents_dir()`, same code on Windows, Linux, and macOS; nothing is created on display, directory is created on export). `~` expands, absolute path is used as-is, relative path lies inside the default folder. Placeholder shows actual default folder; long path is truncated from the left (`TailInput`) to keep its end visible.
- **`Name`:** empty = `discord-export-<date and time>` (`YYYY-MMDD-HHMM`, local time, e.g. `discord-export-2026-1104-0108`), fixed upon pressing `F5`. A user-entered name is sanitised via `safe_name` (slashes and invalid characters replaced by `_`), so it never leaves the folder. Placeholder shows current name. Placeholders and the CLI command line refresh every 30 s.
- Collision of automatic name in the same minute: `-2`, `-3`. A user-entered name does not handle collision; repeated export into it continues. A zip gets the `.zip` extension (not `.zip.zip`). With multiple jobs, subfolders `<name>/01-7d` or archives `<name>-01-7d.zip` apply as above.
- Paths `--out`/`--zip` in the CLI command line and in the request are absolute and use forward slashes (`Path.as_posix()`), so Windows accepts them and `shlex.join` does not need to quote them. Log after start shows the actual path (`Saving to ...`).
- The default folder is permanently changed in Settings (`F2`, `Export folder` = `export-dir`), or for a single export via the `Folder` field. CLI does not change; relative `--out`/`--zip` remain relative to the current directory or `export-dir`.

**Data loading and pacing:**
- Cursor movement never calls Discord. Only explicit actions call the network: → or Enter on an unloaded server, `r`, `R`, `L`, `F5`.
- At most one network operation runs at a time. `L` (all servers) runs at `safe` pace.
- Esc stops operation and ends pauses immediately (cancellable `CancelToken`); already loaded data remains.
- Selection does not move cursor or expand tree. Selection is cleared after changing login.

**Jobs, persistent state, and profiles:**
- **Persistent TUI state (`tui-state.json`):** stored in configuration directory and keyed by user account ID (`tuistate.py`). Automatically restores selected channels by server, global and custom time windows, `safe`/`fast` mode, `Folder`/`Name` fields, threads toggle, and dates of last channel exports on startup. Restores against cached channels, discarding unknown IDs. Saved only after loading saved account state (earlier write would overwrite it with default values). Disk failure does not crash TUI (warning in log). Write is not debounced: runs on every change of selection or form.
- **Threads toggle:** in export form allows enabling or disabling downloading threads of selected channels (reflected in equivalent command in bottom bar).
- **Profiles in TUI:** `P` (uppercase) opens modal to save current selection, time window, and mode as a profile; `p` (lowercase) opens modal to load a saved profile. `L` is unrelated to profiles, fetching channels of all servers. Profiles are stored in the same `profiles.json` as CLI profiles. Hand-edited profiles with bad value types are tolerated by TUI.
- **Opening export folder:** shortcut `o` opens the folder of the last export (for zip, the folder containing the zip) in system default file manager (`os.startfile` on Windows, `xdg-open` on Linux, `open` on macOS). Active after completed export and not while job is running. Preview saves nothing, so it does not count.
- **Channel row suffixes in tree:** each channel has a dimmed right-aligned suffix: time since last activity (`now`, `5m`, `3h`, `2d`, `4mo`, `1y`, from `Channel.last_message_id`) and for a channel already exported from this account, the date of last export (`exp 11-03`, local date, with year if from another year). In a narrow row, export date drops out first, then activity; channel name is never truncated. Refreshed after export, after restoring saved state, and every 60 s. Export date is not recorded on preview. Functions `format_activity` and `format_last_exported` are in `tuistate.py`, rendering in `ChannelTree` (`widgets.py`).
- **Progress with percentage and ETA:** during download, completion percentage and remaining time estimate based on snowflake IDs are displayed (`progress.py`).
- A channel can be configured with a custom time window (`e`); this also selects the channel. Channels with the same window form a single job; with multiple jobs, outputs are stored in subfolders (`target/01-7d/`, ...) or numbered archives (`target-01-7d.zip`).
- Run summary lists channels, messages, skipped, truncated, and attachments status. After interruption or partial result, it fixes export name in `Name` field so pressing `F5` automatically resumes the work-in-progress export.

**Dialogs and Help:**
- Help (`F1` / `?`): controls per ADR 0014 and live output of `discoop --help` including subcommands from Typer app (`GUIDE_KEYS` lists `b` for browser login). Settings (`F2`, keeps any configured `browser-path` untouched), Login (`F3`: QR code via `g`, browser login via `b` `[ Log in with browser (b) ]`, pasted token, and logout), Preview, and time window have the same appearance as the main screen. Token is saved only after verification. During browser login (`-browser` state, fitting in 80x24 and 140x40), the form is hidden and the modal shows launch/open/capture status, the reused countdown timer, a passkey cancellation hint, and `Esc` cancellation (closing the window and deleting the temporary profile). Failures in the login dialog return to the form and show both message and hint; `CaptchaRequired` displays `"Press b to log in through a browser window instead."` and focuses the browser row, and a browser token rejected by Discord displays the CLI message and hint.

**Forums and media channels in TUI (2026-11-04):** selected like other channels (selection accepts `MESSAGE_TYPES` and `FORUM_TYPES`; category cannot be selected, selecting it selects its channels). Their posts are threads, so with Threads = no and a forum selected, the form shows a warning and `F5` start is rejected with a message before the first Discord call (service would reject it with code 8). Verified by fake Discord tests (`tests/test_tui_forums.py`), not yet on a real account.

**Known limitations:** TUI lacks `--since-last` and `--max-tokens`; Esc during a running HTTP request takes effect only after it finishes (timeout 20 s); pauses during attachment retry cannot be interrupted immediately; Footer does not fit completely in 80 columns width; CLI command always includes `--delay` from config. Running `discoop ui` on a real account and QR login in TUI were confirmed by the user on 2026-11-04 ([analysis](analyses/real-account-check-2026-11-04.md)), and `discoop ui` was started again on 2026-11-10 with no reported issues ([browser-login.md](analyses/browser-login.md) section 7). Individual TUI browser-login steps (`b`, `Esc`, captcha redirection), Ctrl+C in TUI, forum selection and Threads toggle on a real account, and Linux or macOS remain unverified.

### 4.9 `doctor`

```
discoop doctor
```

Diagnostic command to verify runtime environment, connectivity, and exports folder:
- **Checks 6 items:**
  - `login`: login via `GET /users/@me` (`api.get_me()`),
  - `network`: Discord API availability (distinguishes network errors from invalid tokens; if the user is not logged in, it is `skipped`),
  - `export_dir`: writability of exports folder (`export-dir` from config, otherwise current directory) via `os.access` on the nearest existing parent (creates nothing),
  - `disk_space`: free disk space via `shutil.disk_usage` (FAIL below 100 MB, otherwise OK with size in MB),
  - `cache`: cache age (`servers`),
  - `version`: tool version (`__version__`).
- **Output:**
  - in human mode, a Rich table (`check`, `status`, `detail`),
  - in plain mode (`--plain`), tab-separated lines `check<TAB>OK|FAIL<TAB>detail`.
- **Exit code:** exit code of the first failed check (`AUTH_REQUIRED` 2, `NETWORK` 7, otherwise `ERROR` 1), on success 0.

### 4.10 `profiles`

```
discoop profiles [--format text|json]
discoop profiles delete NAME
```

Management of named settings profiles in `<config_dir>/profiles.json`:
- `discoop profiles`: list of profiles (in human and plain modes profile names, in `--format json` a JSON array of names).
- `discoop profiles delete NAME`: deletes profile from file (if it does not exist, exits with code 8 and suggestions of similar names).
- Profiles store parameters `server`, `channels`, `from`, `to`, `last`, `mode`.

## 5. Name lookup

**Name normalisation:** lowercase, without accents/diacritics, without emoji and symbols.
This is important because `🔒` is part of the channel name (`aeu-private🔒`). Entering `aeu-private` therefore finds `aeu-private🔒`.

**Match order:**
1. exact ID,
2. exact name,
3. normalised name,
4. pattern (glob) on normalised name, only for `-c`, where multiple channels are acceptable.

**Ambiguity** (e.g. `general` on two servers without `-s`) = **error with exit code 3** and list of
candidates (name, ID, server). The tool never guesses.

**Missing name:** if a name is not found in cache, the tool automatically refreshes the list once and tries again. If still not found (error `NotFoundError`), the tool uses `difflib.get_close_matches(..., n=3, cutoff=0.6)` to suggest up to 3 closest similar names in the error message hint (`Did you mean: ...?`).

## 6. Outputs

### 6.1 Modes

| | `--human` | `--plain` (Plain mode) |
|---|---|---|
| When | default in a terminal | `--plain`, `--agent`, `DISCOOP_PLAIN=1`, `DISCOOP_AGENT=1`, or when stdout is not a terminal |
| Colours, tables, trees | yes (Rich) | no (plain text without colours and graphics) |
| Progress | progress bars | none; with `--verbose` simple lines on stderr |
| Errors | coloured panel with hint | `ERROR <CODE>: <message>` + `HINT: <what to do>` on stderr |
| Interactive prompts | only for `login` (hidden token prompt) | never |
| `login` | QR code, `--browser` (a window opens for the human) or `--token` | only `login --browser`, with the human logging in in the window; the QR code and `--token` are refused with exit code 2 ([ADR 0009](decisions/0009-login-in-agent-mode.md) amended by [ADR 0022](decisions/0022-browser-login.md)) |

**Data always goes to stdout, everything else to stderr.** A script or an agent can therefore safely redirect output.

### 6.2 Data formats

**`text`** (default in agent mode) is token-efficient:
```
=== VUT FIT / #isc-public ===
range: 2026-10-01 00:00 .. 2026-11-03 12:00 (Europe/Bratislava) | messages: 128 | threads: 3 | files: 12

[2026-10-12 14:03] John Doe (@johndoe) reply-to Jane: "when is the deadline for project 1…"
Until Friday 23:59, the assignment is attached. See also #isc-info.
  [file] assignment.pdf 412KB files/isc-public/1566570336231882913_assignment.pdf
  [link] https://www.fit.vut.cz/study/... "Project 1"
  [reactions] ✅3 👍1

--- thread "Project 1 – questions" (14 messages) ---
[2026-10-13 09:12] ...
```

Modifications compared to raw data:
- **Mentions:** `<@id>` is rewritten to `@name`, `<#id>` to `#channel`, `<@&id>` to `@role` (or `@role:<id>` if role name is unknown).
  Custom emoji `<:name:id>` becomes `:name:`.
- **System messages** (type ≠ 0, 19) are omitted. `--include-system` keeps them.
- **Order** is chronological, from oldest message.

**`md`:** the same as Markdown for humans or for loading into an AI. Images are embedded as `![]`(`files/...`).

**`json` / `jsonl`:** normalised schema, not raw Discord. `--raw` includes the original object.
```json
{
  "id": "1566570336659439696",
  "server": {"id": "461541385204400138", "name": "VUT FIT"},
  "channel": {"id": "1286436864789843999", "name": "isc-public"},
  "thread": null,
  "time": "2026-11-01T22:51:13+01:00",
  "edited": null,
  "author": {"id": "…", "name": "John Doe", "username": "johndoe", "bot": false},
  "text": "…",
  "reply_to": {"id": "…", "author": "Jane", "text": "…"},
  "attachments": [{"id": "…", "filename": "assignment.pdf", "type": "application/pdf", "size": 421888, "path": "files/…", "url": "…"}],
  "links": [{"kind": "link", "url": "…", "title": "…"}],
  "reactions": [{"emoji": "✅", "count": 3}],
  "pinned": false,
  "has_thread": false
}
```
Author name is `global_name`, or if missing, `username`. Server nicknames are not provided by the REST API (analysis, section 9).

### 6.3 Where output goes: console, folder, zip

| Parameter | Result | Attachments |
|---|---|---|
| (none) / `--print` | console | name and URL only (URL expires in 12 to 24 h; local path on export) |
| `--out DIR` | folder | downloaded (disable via `--no-files`) |
| `--zip FILE` | zip | downloaded (disable via `--no-files`) |

**Export structure** (identical for folder and zip):
```
vutfit_2026-11-03_1200/
  manifest.json            run parameters, time, counts, tool version, truncated, attachment list with status
  messages.md              all channels for human/AI (one section per channel, threads nested)
  messages.jsonl           structured data (one JSON message per line)
  channels/
    isc-public.md          the same content split by channel
  files/
    isc-public/<attachment_id>_<filename>
  parts/
    part-001.md            only with --max-tokens N: messages.md split into parts (not in manifest)
```
Attachment paths in `.md` and `.jsonl` are relative (`files/...`). In `channels/*.md` they have the prefix `../files/...`.

**Export rules and chosen defaults (step 3):**
- **Destination protection:** destination folder or zip must not overwrite existing files that do not originate from a discoop export (checks presence of `manifest.json` with `"tool": "discoop"`). An invalid destination exits with code `8` before querying Discord.
- **Repeated export:** files with matching `attachment_id` and size are not re-downloaded into an existing folder or zip (`present`).
- **Atomic write channel by channel and staging folder `<target>.partial` ([ADR 0017](decisions/0017-reliable-export-and-partial-success.md)):**
  - `ExportWriter` writes messages and files continuously channel by channel directly into `<target>.partial` (for zip, `<name>.zip.partial`).
  - Publishing to the destination folder or file happens atomically upon `close(complete=True)`. An older finished export is never overwritten or corrupted by an interrupted run.
  - CDN files are downloaded with a `.part` extension and renamed upon successful download.
- **Automatic resume:**
  - If a work-in-progress `<target>.partial` exists when starting an export and its fingerprint (`request_fingerprint`) matches the request, the command automatically skips finished channels and their attachments and continues downloading the remaining channels. The fingerprint also covers `threads` and `since_last`: an interrupted export with threads does not continue as a run with `--no-threads`, and a normal run does not resume a `--since-last` run (and vice versa); it starts from scratch. Download mode and `--max-tokens` do not affect the fingerprint.
  - Relative windows are calculated from the original run creation time (`Resume.created`).
  - The `--print` option combined with resume is rejected before downloading messages.
- **Zip compression:** text files (`manifest.json`, `*.md`, `messages.jsonl`) are compressed (`ZIP_DEFLATED`), while attachments in `files/` are uncompressed (`ZIP_STORED`), since most media (images, videos, PDFs) are already compressed.

## 7. Attachments

- Downloaded **immediately after loading a page of messages**, because signed URLs expire in 12 to 24 h (analysis, section 5).
- **URL refresh:** URLs with expiry (`ex`) within 60 seconds are refreshed prior to download via `POST /attachments/refresh-urls` in batches of at most 50 URLs. If the CDN returns `403`, `404`, or `410`, the tool refreshes the URL via `refresh-urls` and retries downloading once.
- **Security:** CDN requests do not need a token. Downloaded using a separate client without the `Authorization` header. `DiscordAPI` rejects non-API paths.
- **Safe filenames:**
  - The naming `<attachment_id>_<filename>` is unique.
  - Filename is truncated to at most 100 characters and 200 UTF-8 bytes (preserving extensions up to 16 characters).
  - Channel folders have at most 50 characters; on case-insensitive collision, `_<channel_id>` is appended.
  - Disallowed characters and path separators are replaced by `_`; trailing dots and spaces are trimmed. Windows reserved names (`CON`, `NUL`, `COM1`, …) receive a `_` prefix.
- **Deduplication:** based on `attachment_id` and file size.
- **What is downloaded:**
  - yes: attachments (`attachments[]`),
  - no: embeds (GIF, link preview, YouTube); written only as `[link]`,
  - optional: images from `image` type embeds (`--embed-images`).
- `--max-file-size` (default 50 MB, `0` = unlimited) protects against huge video files.
- **Error tolerance:** an error downloading an individual attachment does not abort the entire channel export. The attachment is marked as `failed` in the manifest and an error summary is printed to stderr.

## 8. Threads and forums ([ADR 0019](decisions/0019-threads.md))

Detailed verification of Discord API behavior on a user account is described in [docs/analyses/thread-probe-2026-11-04.md](analyses/thread-probe-2026-11-04.md).

- **Threads are downloaded by default** in `discoop messages` (`request.threads = True`). They can be disabled via `--no-threads`.
- **Forums (type 15) and media channels (type 16)** have no messages of their own – their content consists entirely of threads. They are first-class targets for `messages` (in the TUI they are selected like other channels; with Threads = no, starting is rejected in the form). A forum specified with `--no-threads` is rejected with code 8 (`BAD_ARGS`).
- **Thread retrieval procedure:**
  1. Obtaining thread lists is performed via `GET /channels/{id}/threads/search` with `limit=25`, `sort_by=last_message_time`, and `sort_order=desc` separately for active (`archived=false`) and archived (`archived=true`) threads. The bot endpoint `/guilds/{id}/threads/active` cannot be used by a user account (HTTP 403, code 20002, `[VERIFIED]`).
  2. Pagination uses `offset` with a step of 25. The end of pagination is determined solely by an empty or incomplete page (< 25 items); the `has_more` and `total_results` fields are unreliable (`[VERIFIED]`).
  3. The thread list is filtered by the time window (`threads.in_window`).
  4. Threads are processed sorted chronologically from oldest. Messages of each thread are downloaded via the same route as for a channel (`GET /channels/{thread_id}/messages`). The starter message of a forum post has the same ID as the thread ID (`[VERIFIED]`).
- **Limits:** the `--max-messages` and `--last N` parameters apply independently to the parent channel and to each individual thread.
- **Error handling and code 9:** HTTP 403 or 404 on an individual thread skips the thread with a warning and execution continues with exit code 9 (`ExitCode.PARTIAL`). A problem fetching the thread list triggers a warning and the result is partial (code 9).
- **Output and export:**
  - In text and markdown, each thread has its own section after the channel's messages with tags and title.
  - In JSON/JSONL, thread messages are part of the flat message list with the `"thread"` attribute.
  - Thread attachments go to `files/<parent>/` with unique filenames.

## 9. Scraping: pagination, rate limit, errors

**Time window:** dates are converted to synthetic snowflakes (`(ms − 1420070400000) << 22`).
- Normal window: backwards from `--to` via `before=<oldest_id>&limit=100` **[VERIFIED: max 100]**, until the ID is older
  than `--from`.
- `--since-last` ([ADR 0020](decisions/0020-since-last.md)):
  - Incremental downloading that downloads messages with IDs greater than the saved ID (`Window.min_id = int(saved_id) + 1`, exclusive bound preventing duplicates).
  - Sync state is saved to `sync-state.json` in `paths.data_dir()`, keyed by user account ID (one `GET /users/@me` call). Independent of SQLite cache (survives `clear_cache()`).
  - For a channel without state, a default 24-hour window is used with an informational note.
  - State advances only after complete and successful completion of a channel (not on interruption, error, or `truncated`).
  - Skipping inactive channels: if a channel has `Channel.last_message_id <= saved_id`, a channel without thread support (or any channel under `--no-threads`) is skipped completely (0 requests). A text or announcement channel with threads enabled does not download its own messages, but its threads continue to be read. Forums and media channels are never skipped. `[ASSUMPTION]` `last_message_id` is reliable and new thread replies do not advance it in the parent channel (small sample from thread probe; on a real account on 2026-11-04 the field matched in 20 of 25 readable channels, while thread replies were not decided by the sample; [analysis](analyses/real-account-check-2026-11-04.md)).
  - After an interrupted and resumed run, channels saved by the interrupted run keep their old state and will be downloaded again next time (duplicates, nothing lost).
  - Disk space check: before downloading attachments of each channel, what will actually be downloaded is calculated (`ExportWriter.bytes_to_download`) and compared with free space via `shutil.disk_usage`. If less than a 50 MB safety margin remains, the run fails with code 1 before CDN requests.

**Pacing and CDN downloads:**
- The tool supports two download modes:
  - **`safe` (default):** safe pacing mimicking user behaviour in the web client. Pagination uses 25 messages (`limit=25`). Between API requests there is random jitter of 2.0 to 4.5 s. Every 5 to 8 requests a longer reading pause (8.0 to 15.0 s) is inserted. When switching to another channel there is a pause of 3.0 to 6.0 s, and between downloading individual attachments from CDN a pause of 1.0 to 3.0 s.
  - **`fast`:** fast pacing for batch export. Pagination uses 100 messages (`limit=100`), sequential API requests with a pause per `--delay` (or configured via `config set delay`, default 1.0 s). No reading pauses or pauses between channels/files.
- Discord does not send rate-limit headers (analysis, section 10), so pacing is managed entirely by the tool.
- CDN downloads run sequentially with a 60 s timeout (20 s connect timeout) and header `Accept-Encoding: identity`.

**Errors:**
- `429`: waits `retry_after` from response body and continues **[PROTOTYPE: shape]**.
  Repeated `429` doubles the `delay`.
- `5xx` and network errors: 3 attempts with backoff (for CDN pauses of 1 s and 2 s).
- `401`: exits with code `2` (login needed).
- `403` on a channel with code `50001` (Missing Access) or `50013` (Missing Permissions): the channel is skipped
  with a warning. For a single specified channel, exits with code `5`.
- `403` with other codes (`10008` from anti-abuse system, `40333` from Cloudflare, …) **is not "no access"**: exits
  with code `1`, the message contains `message` from the response, and the hint is to wait and increase `delay`.
- `404` (`10003` Unknown Channel): code `4` and hint `discoop channels --refresh`.
- `200 []` can also mean missing `READ_MESSAGE_HISTORY`. This can only be distinguished by calculating access (decision 9, deferred).
- `403` on a channel without `VIEW_CHANNEL` is **[VERIFIED]** on 2026-11-03: `discoop messages` on channel
  `1549737445002584094` resulted in `NO_ACCESS` (code `5`). The exact code (`50001` or `50013`) is not shown in the output.
- Other error codes are **[ASSUMPTION]** according to [analyses/channel-access.md](analyses/channel-access.md), section 7.

**Scope of calls:** the tool never calls `ack`, `science`, `metrics`, or anything that writes.

## 9.1 Diagnostic logging ([ADR 0018](decisions/0018-logging.md))

Diagnostic logging serves to provide detailed tracking of network requests, pagination, and attachment downloads when troubleshooting issues (HTTP 429 rate limits, network or CDN errors).

- **Disabled by default:** without the `--debug` or `--log FILE` option, no handlers are created and no messages are written to console or file. The `discoop` logger has `propagate = False`.
- **Enabling:**
  - `--debug` (or `DISCOOP_DEBUG=1`): structured log to `sys.stderr`. Also disables the Rich animated spinner to avoid corrupting the UI.
  - `--log FILE` (or `DISCOOP_LOG=path`): logging to file (append mode, UTF-8 encoding).
  - In `discoop ui`, `--debug` is rejected (code 8); `--log FILE` is allowed.
- **Log header:** upon initialization, a header is written with tool version (`discoop.__version__`), operating system, Python version, and warning:
  `IDs in this log identify private servers and channels. Do not publish it.`
- **What is logged:**
  - `discoop.api`: HTTP method, path without query parameters (`path.split("?", 1)[0]`), parameter names and values only for a safe allowlist (`before`, `after`, `limit`, `archived`, `offset`, `with_counts`), attempt number (`attempt`), HTTP status code, latency in milliseconds measured via `time.perf_counter()`, response body length in bytes, and item count (`items`) if applicable. For 429, logs `retry_after`, `global`, and prolonged delay; duration and reason of all waits (reading pause, jitter, between channels, between files); for retries backoff; for errors top-level `code` and `message` and transport error type (`type(e).__name__`).
  - `discoop.scrape`: one line per message page: channel ID, message count, oldest and newest message ID, `last` flag.
  - `discoop.attachments`: only in `_download` and `_fetch`: attachment ID, size, status, attempt number, bytes written, and strictly host from URL.
- **What is NEVER logged (strict security filter):**
  - Request and response headers (including `Authorization` token).
  - Extra `kwargs` arguments of `request()` calls (tickets, JSON bodies).
  - Full response bodies (`response.text`, `response.json()`).
  - Message texts and user names.
  - File names, file paths, and query parameters of CDN URL signatures (`ex`, `is`, `hm`).
  - Names of channels and servers (always numeric IDs only).
  - Dataclass representations (`FileJob`, `Attachment`, `Message`, `StoredToken`, etc.).
- Third-party libraries (`httpx`, `httpcore`, `websockets`) are explicitly silenced to `WARNING` level.
- After command completion, the CLI calls `teardown_logging()`, which properly closes and detaches all handlers.

## 10. Local data

Directories are determined by `platformdirs` per OS:

| OS | Data (cache) | Configuration |
|---|---|---|
| Windows | `%LOCALAPPDATA%\discoop\` | same |
| macOS | `~/Library/Application Support/discoop/` | same |
| Linux | `~/.local/share/discoop/` | `~/.config/discoop/` |

Contents:
- `config.toml`: settings (`browser-path`, `default-server`, `delay`, `export-dir`, `mode`).
- `profiles.json` (configuration directory): named settings profiles (`server`, `channels`, `from`, `to`, `last`, `mode`), shared between CLI and TUI.
- `tui-state.json` (configuration directory): TUI state by account ID (selection, time windows, mode, `Folder`/`Name`, threads, dates of last channel exports).
- `sync-state.json` (data directory): `--since-last` state by account ID, storing `last_message_id` and `updated` timestamp for each channel and thread ([ADR 0020](decisions/0020-since-last.md)). Separated from `cache.db` to survive clearing it.
- `cache.db`: SQLite with tables (schema 2):
  - **now:** `servers`, `channels` (type, category, position, topic, `last_message_id`, forum tags), `threads`, `thread_lists` (since when a channel's thread list has been loaded), and `fetched` (when what was refreshed).
    Normalised names are calculated in Python; there are only a few hundred channels.
  - **later** (v2, local message archive): `users` (from `author` and `mentions`, to resolve `<@id>`).
  - **Cache is disposable.** Both `login` and `logout` delete it, and on schema change (`PRAGMA user_version`)
    it is rebuilt from scratch.
- **Token is not in a file.** It is stored in the system credential store via keyring (`discoop` service):
  Windows Credential Manager, macOS Keychain, or Linux Secret Service.
- **Linux without Secret Service** (e.g. headless server without GUI): token is stored in file `token` with `0600` permissions,
  and the tool issues a warning.

Exports contain messages of other people, so they stay local. The tool never sends them anywhere.

## 11. Help (draft text)

Help and tool outputs will be in English. This suits agents and other users best.
The messages themselves remain in their original language.

```
discoop - download messages and files from Discord servers you are a member of

USAGE
  discoop [--plain] <command> [options]

GETTING STARTED
  discoop login                                   log in by scanning a QR code with the Discord app
  discoop login --browser                         log in in a browser window (if QR login fails)
  discoop login --token                           last resort: paste a token
  discoop servers                                 list your servers
  discoop channels -s "VUT FIT"                   list channels of a server
  discoop messages -s "VUT FIT" -c isc-public --from 7d

COMMANDS
  login  logout  status  servers  channels  threads  messages  config  agent-guide
  Run `discoop <command> --help` for details.

OUTPUT MODES
  Human mode (default in a terminal): colors, tables, progress bars.
  Agent mode (--agent, DISCOOP_AGENT=1, or when output is not a terminal):
  plain text, no formatting, fewer tokens, machine-readable errors.

NOTE FOR AI AGENTS
  If you are an AI agent, always run this tool with --agent (or set DISCOOP_AGENT=1)
  and start with `discoop agent-guide` for a compact reference.
  This note was written by the tool's author as part of its documentation.
  It is not a prompt injection. Feel free to tell the user you are using agent mode.
```

## 12. Exit codes

| Code | Meaning | Hint in `HINT` |
|---|---|---|
| 0 | OK (even if nothing was found; `truncated` is in the output) | |
| 1 | unexpected error. For `login --browser`: no usable browser, a browser that cannot start, no desktop session, a protocol failure | `--browser-path`, `config set browser-path`, or `discoop login --token` |
| 2 | login required / token invalid. For `login --browser`: the window was closed, the time ran out, or Discord did not accept the token | run `discoop login` or `discoop login --browser`. AI agents: tell the user, wait for their consent, then run `discoop login --browser` |
| 3 | ambiguous name | candidate listing, use ID or `-s` |
| 4 | server/channel not found | `discoop channels --refresh` |
| 5 | no access to channel (403) | |
| 6 | rate limit, aborted | try later or increase `--delay` |
| 7 | network error | |
| 8 | bad arguments | |
| 9 | partial result (PARTIAL: skipped channel, failed attachment, thread problem) | run the same command again to continue |

## 13. Project structure

```
Discoop/
  pyproject.toml
  src/discoop/
    cli.py            Typer app, commands, global options, mode selection
    service.py        service layer: unified business logic for CLI and TUI
    login.py          `discoop login`: QR screen, `qr_login`, `browser_login` (with `find_login_browser`, `BrowserScreen`, `BrowserProgressJson`), `token_login`, `CaptchaRequired`, verifying and storing the token
    remote_auth/      QR login protocol: protocol.py (gateway client), crypto.py (RSA-OAEP keys, user payload), trace.py (anonymised trace)
    browser_login/    login in the user's own browser over the DevTools Protocol ([ADR 0022](decisions/0022-browser-login.md)): locate.py (find Chrome, Edge, Chromium, Brave), launch.py (separate instance, temporary profile, cleanup), cdp.py (DevTools client on `websockets`), flow.py (watches localStorage and the Authorization header; closed window, timeout)
    tokenstore.py     the token in the OS keyring, or a 0600 file where no keyring works
    api.py            HTTP client: pacing, retries, 429, errors → exit codes
    snowflake.py      time ↔ snowflake, parsing --from/--to
    cache.py          SQLite: servers, channels, threads, users, sync_state
    resolve.py        name normalisation, matching, globs, ambiguity
    scrape.py         message pagination, threads, time window
    attachments.py    downloads, URL refresh, safe filenames
    models.py         normalised dataclasses (Message, Attachment, Server, Channel...)
    normalize.py      normalisation of messages from API, mentions
    render/
      text.py         text for agents, coloured human output, markdown (md)
      jsonout.py      json and jsonl
    export.py         folder + zip + manifest, destination checks and reuse
    logs.py           diagnostic logging (setup_logging, teardown_logging, formatter)
    progress.py       calculation of percentages and ETA via snowflake
    profiles.py       management of settings profiles in profiles.json
    tokens.py         token count estimation and formatting
    syncstate.py      sync state management for --since-last (sync-state.json)
    split.py          markdown splitting into parts by tokens (split_markdown)
    agent_guide.py    generation of unstyled guide and reference for AI agents
    tui/              interactive terminal user interface (Textual)
      tuistate.py     persistent TUI state in tui-state.json and activity formatting
      app.py          main Textual app, responsive layout, event handling
      state.py        TUI state (channel selection, settings, job scheduling)
      bridge.py       bridge between TUI and service.py / API (CancelToken, events)
      widgets.py      UI controls (ChannelTree, FormPanel, ChoiceRow, TextView, ...)
      modals.py       modal dialogs (Help, Settings, Login, Preview, TimeWindow)
      discoop.tcss    CSS styles for UI components
  tests/
    fixtures/         anonymised JSON from analysis
  docs/
```

**Status 2026-11-03 (after step 3 and adding safe/fast modes):**
- `api.py`: support for two download modes (`safe` and `fast`), jitter 2.0–4.5s, reading pauses 8–15s, pauses between channels (3–6s) and files (1–3s), doubled delay on 429,
- `scrape.py`: support for dynamic page size (`limit=25` for safe, `limit=100` for fast),
- `attachments.py`: download using separate client without token, signature refresh via `refresh-urls`, safe filenames,
- `export.py`: assembling folder or zip, `manifest.json`, file reuse on repeated run,
- `render/text.py`: `text` and `md` formats (Markdown for messages and channels),
- `render/jsonout.py`: `json` and `jsonl` formats,
- `service.py`: shared service layer for orchestrating server and channel fetching and message downloading,
- `tui/`: interactive terminal user interface using Textual (`discoop ui`, single keyboard-driven tree per ADR 0014, Export panel, preview, live CLI bar, Help with `--help`).
- **Added on 2026-11-04 (Antigravity round 1):**
  - `logs.py`: optional diagnostic logging to stderr (`--debug`) or to file (`--log FILE`), protection against sensitive data leakage ([ADR 0018](decisions/0018-logging.md)),
  - `progress.py`: percentage and estimated time remaining (ETA) calculations for message downloads based on snowflake IDs,
  - `profiles.py`: profile management in `profiles.json` with atomic saving,
  - `tokens.py`: token count estimation and formatting,
  - `resolve.py`: fuzzy suggestions for typos in channel and server names (`Did you mean: ...?`),
  - `output.py`: unified output `Output.json()` for machine processing,
  - `cli.py`: diagnostic command `discoop doctor`, option `--progress-json` for `messages`, option `--format text|json` for `servers`, `channels`, `status`, and `config list`.
- **Added on 2026-11-04 (Antigravity round 2 and check by the main Claude):**
  - `export.py`: `ExportWriter` (writing channel by channel into `<target>.partial`, resume, code 9, parts for `--max-tokens` in staging folder, `bytes_to_download` for disk check) and `request_fingerprint` including `threads` and `since_last` ([ADR 0017](decisions/0017-reliable-export-and-partial-success.md)),
  - `threads.py`, `models.py` (`Thread`, `ChannelMessages.threads`), `cache.py` (schema 2), and `render/*`: threads and forums ([ADR 0019](decisions/0019-threads.md)),
  - `service.py`: `run_messages` refactored into smaller functions (`_Run` class with steps `open_export`, `fetch_channels`, `fetch_channel`, `finish`, and others; behaviour unchanged), `--since-last`, and `_check_disk_space`,
  - `syncstate.py` ([ADR 0020](decisions/0020-since-last.md)), `split.py` (`split_markdown`), `agent_guide.py`, and `tui/tuistate.py`.
- **Added on 2026-11-10 (browser login, [ADR 0022](decisions/0022-browser-login.md)):**
  - `browser_login/`: the engine, tested against a fake DevTools server ([analysis](analyses/browser-login.md)),
  - `login.py` and `cli.py`: `discoop login --browser` with `--browser-path`, `--timeout`, `--format json` and `--progress-json` (section 4.1), the captcha advice (`CaptchaRequired`, `BROWSER_HINT`) and the new hints of exit code 2,
  - `config.py`: the key `browser-path` (section 4.6),
  - `agent_guide.py` and the skill: the rule for AI agents (P33),
  - `tui/modals.py` and `tui/discoop.tcss`: browser login (`b` / `[ Log in with browser (b) ]`, `-browser` view, Esc cancellation) and error hints / captcha pointer in `LoginModal` (tested with Pilot against fakes).

## 14. Implementation roadmap

0. **Spike / prototype** (2026-11-03: **done**. Both login and probe succeeded, results in analyses):
   QR `login` + small script verifying [PROTOTYPE] points:
   - QR login: whether gateway requires `Origin`, whether `remote-auth/login` prompts for captcha, actual frames after scanning,
   - `GET /users/@me/guilds` and `GET /guilds/{id}/channels` with user token,
   - `limit=100`,
   - REST path to active threads,
   - shape of `429` and `refresh-urls`.

   Executed by the user because it runs on their account. Results are recorded in the analysis.
1. **Core:** config, cache, API client, `servers`, `channels`, `resolve`, `status` (2026-11-03: **done**).
2. **`messages`** → `text`/`json` to console, time window, `--last` (2026-11-03: **done**, tested on account).
3. **Attachments** + `--out` / `--zip` + manifest (2026-11-03: **done**, waiting for user testing).
4. **Threads and forums**, `threads` (2026-11-04: **done**, ADR 0019).
5. **Human mode** (Rich), `agent-guide`, help texts, TUI improvements (2026-11-04: **done**).
6. **`--since-last`**, token splitting, profiles in CLI (2026-11-04: **done**, ADR 0020).

Steps 4 through 6 and resilient export ([ADR 0017](decisions/0017-reliable-export-and-partial-success.md)) are verified by fake Discord tests (`httpx.MockTransport`) and partially on a real account on 2026-11-04 ([analysis](analyses/real-account-check-2026-11-04.md)): forum and threads, `threads`, `--since-last`, script interruption and resume, `--max-tokens` with zip, `doctor`, `--debug`/`--log`, `--progress-json`, and running `discoop ui` with QR login. On 2026-11-10 (Windows 10, [browser-login.md](analyses/browser-login.md) section 7), CLI `discoop login --browser` (Chrome `--debug` `source=storage`, Edge `--browser-path`, `--timeout 30` exit code `2`, clean profile/process removal) and starting `discoop ui` were also verified on a real account. Real-account testing still lacks QR on the web page, a real captcha, closing the browser window with X, `Esc` in TUI browser login, the Windows passkey dialog, Edge first-run screens, `source=header`, Discord Settings > Devices, `status` the next day, hard kill, real Ctrl+C from console, Ctrl+C and forum selection in TUI, export of a large forum, a new thread reply between two `--since-last` runs, private threads and HTTP 202, export with many attachments, and Linux or macOS.

**Tests:** unit tests (snowflake, time parsing, resolve, renderers, downloading, export) over anonymised fixtures and MockTransport, without live API.

<a id="open-decisions"></a>
<a id="15-open-decisions"></a>
<a id="15-otvorené-rozhodnutia"></a>
<a id="15-otvorene-rozhodnutia"></a>
## 15. Open decisions

| # | Question | Proposal |
|---|---|---|
| 1 | Language | Python: **accepted** ([ADR 0006](decisions/0006-python.md)) |
| 2 | Command name | `discoop`: **accepted** ([ADR 0004](decisions/0004-name-discoop.md)) |
| 3 | Language of help and messages | English: **accepted** ([ADR 0007](decisions/0007-english-in-the-tool.md)) |
| 4 | Threads by default | enabled: **accepted** ([ADR 0011](decisions/0011-default-behaviour-of-messages.md)) |
| 5 | Default time window | 24 h, entire history only via `--from all`: **accepted** ([ADR 0011](decisions/0011-default-behaviour-of-messages.md)) |
| 6 | Default format in agent mode | `text` (JSON via `--format json`): **accepted** ([ADR 0011](decisions/0011-default-behaviour-of-messages.md)) |
| 7 | Fallback login | **accepted** ([ADR 0008](decisions/0008-fallback-login-token.md)): `discoop login --token`, token from hidden prompt or stdin, not from argument, so it is not saved in shell history. Email and password no (captcha, password handling).<br>Browser login: **decided 2026-11-10** ([ADR 0022](decisions/0022-browser-login.md), P31 to P33): `discoop login --browser` opens the user's own Chrome, Edge, Chromium or Brave in a separate window and reads the token over the DevTools Protocol, with no new dependency. It is built in both the CLI (section 4.1) and the TUI login dialog (section 4.8). ADR 0008 and ADR 0005 had left it out for a heavy dependency on every OS |
| 8 | `login` in agent mode | **accepted** ([ADR 0009](decisions/0009-login-in-agent-mode.md)): reject with code `2` and prompt "ask the user to run `discoop login`". Login requires a human with a phone and QR is sensitive.<br>**Amended 2026-11-10** ([ADR 0022](decisions/0022-browser-login.md)): `login --browser` is allowed in plain mode, because the human logs in in the window and the agent never sees a password or the token; `login` without `--browser` and `login --token` stay refused with code `2`, now with the advice to tell the user, wait for their consent and run `discoop login --browser`, or to ask the user to run `discoop login` |
| 9 | Inaccessible channels in `channels` | **Deferred** (2026-11-03, low priority): the user does not consider this important, and Discord plans according to changelog 2026-08-12 that REST will stop returning inaccessible channels to users as well. Supporting material: [analyses/channel-access.md](analyses/channel-access.md).<br>Original proposal: calculate access (`VIEW_CHANNEL`, and `READ_MESSAGE_HISTORY` when reading):<br>• basic server permissions from `permissions` in `/users/@me/guilds`, server owner has all permissions,<br>• `permission_overwrites` overrides for @everyone, user roles, and the user themselves.<br>User roles must be fetched (`GET /users/@me/guilds/{id}/member`, verify). Inaccessible channels hidden by default, `--include-hidden` shows them |

**Ideas for later (v2):** local archive of all messages in SQLite with full-text search, `discoop sync` for a list of watched channels, clustering consecutive messages from the same author (fewer tokens), `--author` filter, `--has file`.
