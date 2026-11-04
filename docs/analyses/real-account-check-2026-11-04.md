# Real account verification: test results from 2026-11-04

Date: 2026-11-04. Type: testing the `discoop` tool on the user's real account (VUT FIT server). Initiated by the main
Claude at the user's explicit request, in `safe` mode and with small time windows. Exports went to a temporary
directory that was deleted after the run; nothing from the content of the exports was retained.

**Legend:** **[VERIFIED]** = observed in the runs of 2026-11-04 on a real account (command outputs, summaries, manifests,
and verification scripts of the main Claude). **[ASSUMPTION]** = extrapolation or interpretation not confirmed by the run.

**Methodology and privacy:**
- The document contains no user IDs, people's names, message texts, or thread titles. The forum is referred to here as "forum (general
  category)", other channels as "study text channels".
- Only counts, times, exit codes, and field names entered this document.
- Related measurement: [thread-probe-2026-11-04.md](thread-probe-2026-11-04.md) (read-only GET calls of the
  prototype). Here, the `discoop` tool itself was executed.

---

## 1. Summary

| # | Area | Short result |
|---|---|---|
| 1 | Diagnostics and basic commands | `doctor`: all 6 checks OK. `status`, `servers`, and `channels` work |
| 2 | TUI | The user independently confirmed that `discoop ui` works and that they logged in through it (QR login in TUI works) |
| 3 | `discoop threads` on forum | `--from 3d`: 2 threads in 5.9 s. `--from 90d --refresh --format json`: 61 unique threads (50 archived) in 17 s, 4 `threads/search` pages. `has_more` was `true` again on the last archived page; `reached_start` found the end |
| 4 | Forum export | 2 posts, 22 messages, 11.6 s, manifest complete. New finding: `message_count` in the thread list does not include the post starter message |
| 5 | Interruption and resume | Code 130, `.partial` with `interrupted: true`, rerun fetched only the missing channel. Interruption by console signal was not tested |
| 6 | `--since-last` | Second run: unchanged channels did not fetch their own messages (0 requests to `/messages`), threads continued to be read |
| 7 | `last_message_id` | Matched the newest message in 20 of 25 readable channels, pointed to a newer message in 4 of 25, newest message was newer than the field in 1 of 25 |
| 8 | Zip with `--max-tokens` | Valid zip (`testzip` clean), 3 parts, part 1 header `<!-- discoop part 1 of 3 -->` |
| 9 | Attachment from CDN | Downloaded, but on repeated export downloaded again (known limitation, section 4) |
| 10 | `--debug --log` logs | Two real logs inspected: no token, signed URLs, names, or words from messages |
| 11 | `--progress-json` | 4 events, each line valid JSON, without names |
| 12 | Speed | `safe` mode pauses dominate: about 4 to 6 s per thread |

---

## 2. What was run and how

- **Account and scope:** the user's real account, VUT FIT server. Forum from the general category and study text channels.
  Windows were small (24 hours, 3, 7, and 14 days; widest was 90 days, and only for thread listing).
- **Mode:** `safe` (default). No `fast`.
- **Commands in brief:**
  - `discoop doctor`, `status`, `servers`, `channels`,
  - `discoop threads -c <forum> --from 3d` and `--from 90d --refresh --format json`,
  - `discoop messages -c <forum> --from 3d --no-files --out DIR`,
  - `discoop messages` with `--out` and with `--zip --max-tokens 300 --max-file-size 1`,
  - `discoop messages --since-last` twice in succession (state file redirected to a temporary file, so the user's real
    `sync-state.json` remained unchanged),
  - export with `--debug --log` and with `--progress-json`,
  - reading probe on `last_message_id` (read only).
- **Export interruption:** a script raised `KeyboardInterrupt` from CLI events during actual network downloading.
  It was not a console signal (real Ctrl+C).
- **What was retained:** nothing. Exports were in a temporary folder deleted after the run.

---

## 3. Results

### 3.1 Diagnostics, basic commands, and TUI

- **[VERIFIED]** `discoop doctor`: all 6 checks are OK.
- **[VERIFIED]** `status`, `servers`, and `channels` work.
- **[VERIFIED]** (the user's confirmation, not the main Claude's measurement) `discoop ui` works and the user logged in
  through it. QR login in TUI therefore works.

### 3.2 `discoop threads` on forum (general category)

| Command | Result |
|---|---|
| `--from 3d` | 2 threads in 5.9 s **[VERIFIED]** |
| `--from 90d --refresh --format json` | 61 unique threads, 50 of which archived, sorted by last activity descending, 17 s **[VERIFIED]** |

- **[VERIFIED]** The second command made 4 requests to `threads/search`: 1 page of active threads and 3 pages of
  archived threads (25 each).
- **[VERIFIED]** `has_more` was `true` again on the last archived page. Only the window found the end (`reached_start`).
  This confirms that `has_more` is not reliable (same as in [thread-probe-2026-11-04.md](thread-probe-2026-11-04.md),
  section 7.6).
- **[VERIFIED]** One thread that is still active, but older than the window, was dropped by the window filter.

### 3.3 Forum export: `messages -c <forum> --from 3d --no-files --out DIR`

- **[VERIFIED]** 2 posts, 22 messages, 11.6 s, manifest is complete (`complete`).
- **[VERIFIED]** `messages.md` contains sections `## thread "..."` with header lines: creation, last activity,
  message count, file count, and tags.
- **[VERIFIED]** Messages in `messages.jsonl` have field `thread: {id, name, parent_id, tags}`. Tags are forum tag names.
- **[VERIFIED]** Counts in manifest: `messages` 0, `threads` 2, `thread_messages` 22. The forum has no messages of its own,
  which matches [ADR 0019](../decisions/0019-threads.md).
- **[VERIFIED]** **New finding:** `message_count` shown by the thread list (`discoop threads` output)
  does not include the forum post starter message. The list showed 9 and 11, the download returned 10 and 12 messages. Observed on these
  two posts (22 messages in total).

### 3.4 Interrupted export and resume (real network, script interruption)

Interruption was raised by a script via `KeyboardInterrupt` from CLI events. A console signal was not used.

- **(a) After channel 2 of 3:**
  - **[VERIFIED]** Exit code 130. Created `<target>.partial` with manifest `complete: false, interrupted: true`
    and 2 channels. Target did not exist.
  - **[VERIFIED]** Message: "Saved 2 of 3 channels in ....partial. Run the same command again to continue."
  - **[VERIFIED]** The same command re-downloaded only channel 3, published target (`complete: true`), deleted `.partial`,
    and finished with exit code 0.
- **(b) In the middle of the first channel of a single-forum export (during its 2nd thread):**
  - **[VERIFIED]** Exit code 130, no `.partial`, no target, no `.part` files. Rerun completed normally.
  - In accordance with [ADR 0019](../decisions/0019-threads.md): a channel and its threads are an indivisible unit and
    saved together, so there was nothing to save into `.partial`.
- **Observation:** in both cases, `main()` did not output the line "Interrupted.", although code has `out.error(...)` for it.
  Exit code 130 was returned anyway. See section 5.
- **Untested:** real Ctrl+C from the console while waiting on network or during file download.

### 3.5 `--since-last` (state file redirected to temporary file)

- **Two study text channels:**
  - **[VERIFIED]** Run 1 (without state): fetched the last 24 hours with note "No previous sync state ...".
  - **[VERIFIED]** Run 2: both channels reported "its own messages are unchanged since last sync, fetching only its
    threads". 0 messages. `threads/search` was called twice per channel (active + archived), `/messages` of the channel not at all.
- **Two forums:**
  - **[VERIFIED]** Run 1: fetched 1 thread with 1 message (last 24 hours) and saved 3 state entries
    (2 forums + 1 thread).
  - **[VERIFIED]** Run 2: 0 messages.
- **Not observed:** a thread receiving a new reply between two runs.

### 3.6 Reliability of `last_message_id` (read only, two runs)

Sample: 28 text and announcement channels in total (most active and random older ones). 25 were readable, 3 returned
403.

| Result | Count out of 25 readable |
|---|---|
| Field matched newest available message | 20 |
| Field pointed to a message newer than newest available | 4 |
| Newest message was newer than field | 1 |

- **[VERIFIED]** Numbers from the table.
- **[ASSUMPTION]** Four cases of "field newer" are likely a deleted message. This is a safe direction for the
  `--since-last` skip rule.
- **[ASSUMPTION]** One case of "message newer than field" (a channel active that day) is likely a message that
  arrived during the ~2 minutes of sampling. Unproven.
- **Threads:** 3 threads in the 7-day window of sampled channels had no message newer than the parent's `last_message_id`. This is
  inconclusive for whether thread replies advance the parent's `last_message_id`. It remains an **[ASSUMPTION]** and the code
  remains cautious: threads continue to be read.

### 3.7 Zip with token splitting

`--zip --max-tokens 300 --max-file-size 1` on 3 study text channels over 7 days:

- **[VERIFIED]** 16 messages, 43.5 s.
- **[VERIFIED]** Zip is valid (`testzip` without errors). Entries: `channels/`, `manifest.json`, `messages.jsonl`,
  `messages.md`, `parts/part-001.md` through `parts/part-003.md`.
- **[VERIFIED]** Parts are not in manifest (matches [ADR 0017](../decisions/0017-reliable-export-and-partial-success.md)).
- **[VERIFIED]** First line of part 1 is `<!-- discoop part 1 of 3 -->`. Summary showed `tokens: ~742`.

### 3.8 Attachment from CDN

- **[VERIFIED]** In the forum export, 1 file was downloaded (PNG, 36731 B); after the run, no `.part` file remained.
- Repeated export to the same folder downloaded the file again. See section 4.
- Across 14 days of two forums, only one attachment was found, so this is a single sample.

### 3.9 `--debug --log` logs

- **[VERIFIED]** Two real logs were inspected (13 and 30 lines). They contain no token, `Authorization` or `Bearer`,
  signed URL parameters (`ex`, `is`, `hm`), server or channel names, or any of 102 distinct words sampled
  from exported messages.
- **[VERIFIED]** Logs contain channel and thread IDs (the log header warns about this).

### 3.10 `--progress-json` on forum export

- **[VERIFIED]** 4 events: `channel_start`, 2x `thread`, `channel_done`. Each line is valid JSON, without names.
- **[VERIFIED]** Keys: `event, index, total, channel_id, thread_id, messages, files, truncated`.
- The `page` event did not appear in this run (a forum has no messages of its own). Whether thread message pages emit
  a `page` event was not investigated. See section 5.

### 3.11 Speed

- **[VERIFIED]** `safe` mode pauses dominate: in the runs above, about 4 to 6 s per thread including share of thread listing.
- **[ASSUMPTION]** Extrapolation: full download of a forum with about 1800 posts takes roughly 2 to 3
  hours in `safe` mode. Unmeasured.

---

## 4. Known limitation: attachment described differently by API is re-downloaded on every run

**Status: open, unfixed.**

- **[VERIFIED]** Exporting the forum to the same folder a second time downloaded the same attachment again
  (`downloaded: 1, already_present: 0`).
- **[VERIFIED]** Cause in observed data: the API reported `size` 25238 and `content_type` `image/webp`
  for the attachment (filename ended in `.png`), but CDN returned a valid PNG with identical pixel dimensions (375x468) and size
  36731 B.
- **[ASSUMPTION]** Therefore, reuse by attachment ID and size (`attachments.reuse_stored`, similarly reuse
  in zip and `bytes_to_download`) does not recognise such an attachment. Only behaviour was observed (it downloads again);
  that size comparison is the reason is an interpretation from the code.
- **Impact:** harmless. The converted image is re-downloaded on every run. Observed on a single attachment (one
  sample).
- **Possible future fix (unscheduled, not being done):** relax size check or store actual size in manifest.

---

## 5. Open observations

- **Missing "Interrupted." line:** code in `main()` has `out.error(... "Interrupted.")`, yet on both
  interruptions (3.4) the line was not printed and code 130 was returned anyway. The branch appears unreachable. **[ASSUMPTION]**
  `click`/`typer` exits with code 130 earlier. Harmless, to be reviewed later.
- **`page` event with threads:** not determined whether thread message pages emit a `page` event in `--progress-json`
  (none appeared in run 3.10).

---

## 6. What remains unverified

- Real Ctrl+C signal from console (while waiting on network as well as during file download).
- Ctrl+C in TUI.
- Forum selection and Threads toggle in TUI on a real account.
- Export of a forum with hundreds of posts from start to finish.
- Thread receiving a new reply between two `--since-last` runs.
- Private threads (type 12) and HTTP 202 (did not appear).
- Export with many attachments (only 1 attachment seen).
- Linux and macOS.

---

## 7. Documentation impact

Records claiming that nothing from round 2 was verified on a real account were corrected: `CLAUDE.md`,
[journal](../journal.md), [handover](../handover.md), [requirements P26 to P30](../requirements.md),
[design](../design.md), [ADR 0017](../decisions/0017-reliable-export-and-partial-success.md),
[ADR 0019](../decisions/0019-threads.md), [ADR 0020](../decisions/0020-since-last.md), and
[CHANGELOG](../../CHANGELOG.md).
