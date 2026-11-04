# Prototype: QR login and API verification

One-off verification of open items from [docs/analyses/](../docs/analyses/). You run everything yourself because it runs
on your Discord account. Outputs go to `prototype/out/`, which git ignores.

## 1. Login

In a terminal (Windows Terminal or PowerShell) in the project root, run:

```
uv run discoop login --trace prototype/out/login-trace.jsonl
```

1. A QR code with a countdown will appear. In the Discord mobile app, scan it via **Settings → Scan QR Code**.
2. The terminal shows who is logging in. Confirm the login on your phone.
3. The tool outputs `Logged in as …`. The token is stored in Windows Credential Manager.

Check the login:

```
uv run discoop status
```

**If the QR code cannot be scanned,** for example due to unreadable rendering, let me know and zoom in
the terminal (`Ctrl` + `-`/`+`).

**If Discord asks for a captcha** or login fails otherwise, send me the output and `prototype/out/login-trace.jsonl`.
The fallback path is `uv run discoop login --token`.

## 2. Probe

```
uv run python prototype/probe.py
```

**What the probe does:**
- Sends approximately 20 requests, one per second, to VUT FIT and #2bit-general. It finds the `help-center` forum automatically.
- Writes nothing: no messages, `ack`s, or reactions. The only POST is `/attachments/refresh-urls`, which only returns a new link.
- Reads the first 1 KB of one attachment from the CDN to verify that no token is needed. Stores nothing.

**Output:**
- a summary table in the console,
- report `prototype/out/probe-<time>.json`. It contains only structure: no token, names, message texts, user IDs, or attachment URLs.

Targets can be changed via `--guild`, `--channel`, `--forum` and pacing via `--delay`.

## 3. Next

Let me know that it's done. I will read `prototype/out/*` and record the results into analyses and the journal.

To log out, use `uv run discoop logout`. The Discord session can be revoked in **Settings → Devices**.

## 4. Thread probe

```
uv run python prototype/probe_threads.py
```

Runs for approximately 1.5 minutes (about 59 to 64 requests, one per second).

**What the thread probe does:**
- Focuses on API behavior for threads and forums:
  - page sizes when searching threads (`limit` 25 vs 50),
  - availability of pagination via `offset` (0, 25, 100, 500, and end),
  - checking for a possible 202 Accepted ("not indexed") response,
  - presence and attributes of private threads (type 12),
  - comparison of `total_results` with the actual number of returned and unique threads across pages,
  - checking `last_message_id` across server channels.
- New compared to the first run (2026-11-04):
  - `threads_search_text_candidates`: searching threads in text channels. The probe takes at most 6 text
    and announcement channels (types 0 and 5) with a non-empty `last_message_id`, newest first, and tries them until one
    responds with 200. For each, it records only order, status code, error code, number of returned threads, and whether
    the `threads` key exists. If one responds with 200, `threads_search_text_active` (`archived=false`) follows on that same
    channel. The `--channel` option replaces the selection with exactly one channel.
  - `thread_messages_readable`: reading messages in a thread via `GET /channels/{thread_id}/messages`. The probe takes
    the newest archived forum thread and (if present) the newest active one, and from each fetches the oldest message
    (`limit=1&after=0`). On the first thread, it then adds a call with `limit=100`. It records only status code, message count,
    whether the oldest message ID equals the thread ID, message type, and whether more than one message was returned. No texts, names, or IDs.
  - `threads_search_first_messages`: counts and field names from the `first_messages` and `members` parts of the response from
    `threads_search_limit_25` (without an extra request).
  - `threads_search_after_short_page`: if active forum search (`archived=false`) returns fewer than 25
    threads, the probe requests the next page (`offset=25`) as well and records status code, thread count, and `has_more`. This
    verifies whether a short page really means the end.
  - `threads_search_past_end`: archived forum search at `offset = total_results` and at
    `offset = total_results + 25` (value from the first page; if unknown, the check is skipped). Records status code
    and thread count for both pages.
- Sends exclusively GET requests at a pace of 1 request per second (`--delay 1.0`). Writes or modifies nothing.
- Everything is run by the user on their account.

**Output:**
- a summary table in the console,
- report `prototype/out/probe-threads-<time>.json`. Contains only structure: types, counts, field names, and status codes. No token, channel or thread names, message texts, user IDs, or URLs.

Targets can be customized via the `--guild`, `--forum`, `--channel` options and pacing via `--delay`.
