# 0020: Incremental download (`--since-last`)

- **Status:** Accepted
- **Date:** 2026-11-04
- **Decided by:** the user

## Context

During regular or repeated downloading of messages and exporting of servers (e.g. on a daily basis), it was previously necessary to manually specify a time window (e.g. `--from 24h` or `--from 7d`). This had two drawbacks:
1. If the user ran the tool after more than 24 hours, messages from the interim period were missed. Conversely, if too wide a window was specified, duplicate messages were downloaded, placing unnecessary load on the Discord API and local disk.
2. In exports with attachments, the user could fill up the local disk without prior warning in the middle of downloading a batch of files.

It was necessary to introduce an incremental downloading mechanism via the `--since-last` flag that picks up exactly where the last successful export of each channel and thread left off, and to add a preventive check of free disk space with a safe margin.

## Options

1. **Store sync state in SQLite cache (`cache.db`).**
   Rejected: By design, the cache is discardable (`cache.clear_cache()` on logout or schema changes) and serves only for fast lookup of server, channel, and thread names. Sync state must survive clearing the cache.
2. **Inclusive bound `lowest = saved_id`.**
   Rejected: Because `scrape.fetch_messages` filters `int(m["id"]) >= lowest`, an inclusive bound would re-download and duplicate the last already seen message. The exclusive bound `min_id = int(saved_id) + 1` guarantees that the message with the stored ID is not repeated.
3. **Continuous state advancement after each read message.**
   Rejected: If an export fails mid-run (e.g. network error, rate limit, user interruption, crash on subsequent channel), state would be advanced and unsaved messages would be skipped on the next run.
4. **Skip all channels with `Channel.last_message_id <= saved_id`, including their threads.**
   Rejected: According to the thread probe analysis (`docs/analyses/thread-probe-2026-11-04.md`, sections 6 and 11), `last_message_id` on forums points to the latest created post, and new thread replies in standard text channels likely do not propagate to the parent channel's `last_message_id` `[ASSUMPTION]`. Therefore, skipping a text channel with enabled threads or a forum would result in missing new replies in threads. A narrower version was adopted: a text or announcement channel skips only its own messages, while its threads continue to be read (Decision section).

## Decision

- **Dedicated JSON file `sync-state.json` keyed by account ID:**
  - The file is stored in `paths.data_dir() / "sync-state.json"`, separately from `cache.db`, so `clear_cache()` does not delete it.
  - Writing is atomic (via `.tmp` temporary file and `os.replace` following the pattern in `profiles.py`).
  - On file corruption (invalid JSON, invalid structure), the tool does not crash with an exception; instead, it returns empty state and emits a warning.
  - Exact format:
    ```json
    {
      "version": 1,
      "accounts": {
        "<user_id>": {
          "channels": {
            "<channel_id>": {
              "last_message_id": "...",
              "updated": "<ISO UTC>"
            }
          }
        }
      }
    }
    ```
  - `user_id` is determined with a single `GET /users/@me` call when `--since-last` is used.

- **`--since-last` behaviour and time windows:**
  - The `--since-last` flag is mutually exclusive with `--from`, `--to`, and `--last`. If specified together, `ExitCode.BAD_ARGS` (code 8) is raised before calling the API.
  - For a channel with recorded state, the window spans from `saved_id + 1` to now (`current_now`). `Window.min_id = int(saved_id) + 1` defines the exclusive lower bound, while `Window.start = to_time(int(saved_id))` provides a meaningful time for headers and thread activity checks.
  - For a channel without previous state, the default 24-hour window (`DEFAULT_SPAN`) is used and a note is emitted (`events.note`).
  - For threads: a thread's window begins from its own `thread_saved_id + 1` (if it has its own entry in `channels`), otherwise from the parent channel's `updated` timestamp (if the parent had state), otherwise from 24 hours.

- **Advancing state only after a complete and successful run:**
  - State is updated only after `writer.close(complete=True)` during export, or after successful completion of all channels during console output.
  - On any exception (interruption, error), state is not advanced.
  - State is updated only for channels that were not truncated by a limit (`not truncated`), not skipped (`not skipped`), had no problems with the thread list or a failed thread, and had no attachments in `failed` status.
  - If no new messages were added, the previous `last_message_id` is preserved (or `target.last_message_id` if larger) and `updated` is updated to `current_now`. State thus never moves backwards. For an empty channel on first run, a synthetic snowflake for `current_now` is saved.
  - **Known limitation after resuming an interrupted run:** if an interrupted `--since-last` export is resumed (the same command continuing in `<dest>.partial`, ADR 0017), sync state for channels saved by the interrupted run is not advanced. The resumed run does not re-download them, so it has nothing to record for them. The next `--since-last` will download them again from the old state: the subsequent export will contain messages already present in the previous export (duplicates), but no messages are lost. `run_messages` warns about this upon resumption with a note (`events.note`: "The channels saved by the interrupted run keep their old sync state, ...").
  - The request fingerprint used to resume an export (ADR 0017) also includes `since_last`: a `--since-last` run does not resume an interrupted standard run and vice versa.

- **Skipping inactive channels:**
  - The server channel list is refreshed (`refresh=True`) under `--since-last` to ensure it contains up-to-date `Channel.last_message_id`.
  - If a channel has saved state, its `Channel.last_message_id` is not empty, and `Channel.last_message_id <= saved_id`, no new messages have been added to the channel itself. What happens then depends on the channel type:
    - **A channel that cannot have threads (e.g. voice), or a run with `--no-threads`:** the channel is skipped completely without any network requests and counted in `outcome.unchanged` (note "is unchanged since last sync: skipping.").
    - **A text (type 0) or announcement (type 5) channel with threads enabled:** its own messages are not downloaded (no request to `/channels/{id}/messages`, `items = ()`), but its thread list is retrieved and threads are downloaded as in any other run (thread from its saved ID, otherwise from parent's `updated` time). `events.note` states that the channel's own messages are unchanged. The channel is not counted in `outcome.unchanged`; it is included in the result (only without its own messages). Its state is preserved (never moves backwards) and only `updated` and thread states are advanced.
    - **Forums (type 15) and media channels (type 16)** are never skipped, even in part: they have no messages of their own, and their `last_message_id` points to the latest post, telling nothing about new replies in a thread.
  - `[ASSUMPTION]` `last_message_id` of a text channel is reliable: it advances with every new message in the channel. The thread probe confirmed this on two readable samples (`docs/analyses/thread-probe-2026-11-04.md`). A check on a real account on 2026-11-04 ([analysis](../analyses/real-account-check-2026-11-04.md), read-only, 25 readable out of 28 sampled text and announcement channels): the field equalled the newest available message in 20 of 25 channels, pointed to a message newer than the newest available in 4 of 25 (likely deleted messages, safe direction for the skip rule), and in 1 of 25 (a channel active that day) the newest message was newer than the field (likely a message arriving during the ~2 minutes of sampling, unproven). This remains a sample, not a proof. If Discord were ever to delay updating it, a channel's new message could be missed in that run. Since the next run's window starts from the saved ID, it would appear on the next `--since-last` after another message is added to the channel and `last_message_id` advances.
  - `[ASSUMPTION]` New replies in threads do not update the parent's `last_message_id` (hence threads continue to be read and forums are not skipped). The 2026-11-04 check was inconclusive: 3 threads within the 7-day window of sampled channels had no message newer than the parent's `last_message_id` (inconclusive). Therefore the rule remains conservative: threads continue to be read and forums are not skipped.
  - `[VERIFIED]` On a real account (2026-11-04), a 2nd `--since-last` run on two study text channels reported that the channel's own messages were unchanged, downloaded 0 messages, called `threads/search` twice per channel (active + archived), and `/messages` of the channel not at all. On two forums, run 1 downloaded 1 thread with 1 message and saved 3 state records (2 forums + 1 thread); run 2 downloaded 0 messages. The state file was redirected to a temporary file. Not observed: a thread that receives a new reply between two runs.

- **Disk space check:**
  - Before each download of channel attachments (`writer.add_channel`), the actual size of files to download is calculated (`ExportWriter.bytes_to_download`): files omitted via `--no-files`, files over `--max-file-size`, files without a URL, attachments seen earlier in the export (an attachment appearing in both channel and its thread is counted once), and files that already exist in the staging folder, destination folder, or old zip (`present`) are excluded. The old zip is read at most once.
  - Required space is compared with available disk space (`shutil.disk_usage`).
  - If a safety margin of at least 50 MB is not maintained (`free_bytes - needed_bytes < 50 MB`), the operation is rejected with `ExitCode.ERROR` (code 1) before sending requests to the CDN.
