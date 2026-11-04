# 0019: Threads and forum posts

- **Status:** Accepted
- **Date:** 2026-11-04
- **Decided by:** the user

## Context

In Discord, there are two main types of channels containing discussions:
1. Standard channels (text type 0, announcement type 5), which contain their own linear stream of messages along with optional child threads.
2. Forum channels (type 15) and media channels (type 16), which have no message stream of their own – all their content is organized exclusively into posts (threads), where each post is an independent thread with a starter message and possible replies.

In the initial version, Discoop did not support reading threads; forums and media channels were rejected as unreadable (message "threads come in a later version"). On servers like VUT FIT, however, a large part of key study information, questions, and answers is concentrated precisely in forum posts and channel threads.

ADR 0011 established that threads should be downloaded by default. Measurements via a probe script (`docs/analyses/thread-probe-2026-11-04.md`) verified the behaviour of the Discord API for a user account:
- The bot endpoint `GET /guilds/{id}/threads/active` cannot be used by a user account (403, code 20002).
- The channel endpoint `GET /channels/{id}/threads/search` works for a user account on forums as well as in standard text channels with `limit=25`.
- Messages of individual threads are read via the standard route `GET /channels/{thread_id}/messages`.

It was necessary to implement full support for downloading threads in the service layer (`service.py`), in the `discoop messages` command, add a standalone overview command `discoop threads`, and resolve error handling when access to threads fails.

## Options

1. **Do not download threads at all or require them via an explicit `--threads` flag.**
   Rejected: According to ADR 0011, threads should be a natural part of exported history so that the user does not lose important context.
2. **Treat a forum as an ordinary channel and call `fetch_messages` on the forum ID.**
   Rejected: A forum has no messages of its own; calling its ID wastes HTTP requests unnecessarily and can fail. A forum exclusively downloads its threads.
3. **Stop the entire export on an error in a single thread (fail-fast).**
   Rejected: If one thread returns 403 (e.g. a private thread) or 404, there is no reason to discard messages of the entire channel or other threads. The solution is partial success (code 9) according to ADR 0017.

## Decision

- **Downloading threads in `messages` and the `--threads / --no-threads` flag:**
  - In accordance with ADR 0011, threads are enabled by default (`request.threads = True`).
  - The user and scripts can disable threads with the `--no-threads` flag. The command and flag descriptions include a warning that threads generate additional requests and with large forums (hundreds of posts) downloading takes longer in `safe` mode.
  - For standard channels (text type 0, announcement type 5), channel messages are downloaded first, followed by threads.
  - For forums (type 15) and media channels (type 16), exclusively threads are downloaded (`items = ()`, no call to `fetch_messages` on the channel itself).
  - If the user provides a forum or media channel together with `--no-threads`, Discoop rejects it with `ExitCode.BAD_ARGS` (code 8) and advice: *"A forum only has threads: drop --no-threads."*.

- **Time window and thread ordering:**
  - Both active and archived threads are downloaded (`threads.fetch_all_threads`) whose existence overlaps the specified time window (`threads.in_window`).
  - Threads are processed and stored sorted chronologically from oldest (by `thread.created` and numeric `thread.id`).
  - A thread that has no messages within the given time window is excluded from the result.

- **Message limits (`--max-messages`, `--last`):**
  - The `--max-messages` and `--last N` parameters apply independently to each channel and each individual thread (every thread gets the same limit).
  - When a thread is truncated by a limit, `truncated = True` is recorded and warning `events.warning(...)` is emitted.

- **Unit of storage and export:**
  - A channel and its threads form an indivisible unit: `ChannelMessages(..., threads=tuple(nested_threads))`.
  - They enter `writer.add_channel(...)` and `events.channel_done(...)` together.
  - Thread settings are part of the request fingerprint used to resume an interrupted export (ADR 0017): an export interrupted with threads does not continue a run with `--no-threads` (saved channels would lack threads) nor vice versa; such a run restarts from scratch.
  - In plain text and markdown export, each thread has its own section following the channel messages (`--- thread "name" ---` in plain text, `## thread "name"` in markdown). In JSON/JSONL export, thread messages are part of a flat list of messages with a populated `"thread"` attribute.

- **New command `discoop threads`:**
  - Provides a quick overview of a channel's threads without having to download messages.
  - Signature: `discoop threads -s SERVER -c CHANNEL [--from ...] [--to ...] [--refresh] [--format text|json]`.
  - The default time window for listing threads is 30 days (`--from 30d`). Full history is printed via `--from all`.
  - If the specified channel does not support threads (`not threads.is_thread_container(channel)`), the command exits with `ExitCode.BAD_ARGS` (code 8).
  - Supports `human` mode (Rich table: id, archived, messages, last_activity, tags, name), `plain` mode (TSV format with header), and `--format json` (machine-readable JSON with tag list).

- **Error handling and exit code `ExitCode.PARTIAL = 9`:**
  - An HTTP 403 (`NO_ACCESS`) or HTTP 404 (`NOT_FOUND`) error when downloading messages of a single thread skips the thread with a warning (`events.warning(...)`). The channel and remaining threads are saved, and the overall outcome is partial (`partial = True`, code 9).
  - An error when fetching the thread list of a channel (403/404) or an incomplete list (`FetchedThreads.problem` is not `None`, e.g. on HTTP 202 unindexed threads) emits a warning and yields a partial result (code 9). The messages of the channel itself are preserved.
  - Both `MessagesOutcome.partial` and `ExportWriter` account for thread errors (`thread_problems > 0`), and the CLI in final advice (`_partial_advice`) accurately informs the user of thread issues.

- **Privacy during progress (`Events.thread`):**
  - Under `--progress-json`, the `thread` event emits exclusively technical identifiers (`channel_id`, `thread_id`) and counts (`index`, `total`). No channel names, thread names, or message texts appear in machine JSON progress output.

## Relation to probe findings (`docs/analyses/thread-probe-2026-11-04.md`)

- **[VERIFIED]**
  - A user account cannot access `/guilds/{id}/threads/active` (403, code 20002). Active threads are therefore retrieved via the channel endpoint `/channels/{id}/threads/search?archived=false`.
  - Pagination of `threads/search` accepts `limit=25`; a limit of 50 is rejected by Discord with code 400 (`Invalid Form Body`).
  - Fields `has_more` and `total_results` on `threads/search` are unreliable (false `has_more: true` on the final page, inconsistencies in `total_results`). The end of pagination is therefore reliably determined only by an empty or incomplete page (< 25 items).
  - Thread messages are read via standard call `GET /channels/{thread_id}/messages`. The starter message of a forum post has an ID identical to the thread ID.
  - Channels and threads without permissions return HTTP 403 `Missing Access`. Discoop catches them and safely reports them as a partial result (code 9).
  - On a real account (2026-11-04, [analysis](../analyses/real-account-check-2026-11-04.md)): `discoop threads` on a forum returned 2 threads (5.9 s) with `--from 3d`, and 61 unique threads (50 archived) sorted by last activity descending over 4 `threads/search` pages (1 active + 3 archived at 25 each) in 17 s with `--from 90d --refresh --format json`. `has_more` was again `true` on the last archived page; the end was detected by window (`reached_start`), confirming the unreliability of `has_more`. A thread that is still active but older than the window was dropped by the window filter.
  - On a real account (2026-11-04): forum export (`messages -c <forum> --from 3d --no-files --out DIR`) yielded 2 posts and 22 messages in 11.6 s with a complete manifest (`messages 0, threads 2, thread_messages 22`). Markdown has `## thread "..."` sections with header lines (creation, last activity, messages, files, tags), and messages in `messages.jsonl` contain a `thread: {id, name, parent_id, tags}` field with forum tag names.
  - On a real account (2026-11-04): `message_count` in the thread list does not include the starter message of a forum post. The list showed 9 and 11, while downloading returned 10 and 12 messages (observed across 2 posts).

- **[ASSUMPTION]**
  - All standard text channels (type 0) and announcement channels (type 5) are assumed to support `threads/search` for a user account identically to the forum and sampled reference text channel.
  - Unindexed threads may return HTTP status code 202 (not encountered on real account 2026-11-04, nor were private threads of type 12). The implementation responds by recording the problem `Stop.NOT_INDEXED` and returning a partial result (code 9).

## Consequences

- Users and AI agents have full access to forum and thread content without manual intervention.
- Loss of access to a single thread does not ruin the entire export (code 9 guarantees transparency and safety for automation).
- The `discoop threads` command provides quick and clear navigation across channel contents without unnecessary message downloads.
