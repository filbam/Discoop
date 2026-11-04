# 0011: Default behaviour of `messages`: threads, time window, format

- **Status:** Accepted
- **Date:** 2026-11-03
- **Decided by:** the user

## Context

The design left three open decisions for the `messages` command (section 15, points 4 to 6). They need to be resolved
before implementing `messages` (design, section 14, step 2). Default values determine what an agent or
a human receives when options are omitted:
- whether threads are also downloaded,
- how old messages are downloaded,
- what format the output takes in agent mode.

## Options

1. **Threads:** download by default (`--no-threads` disables them), or not by default (`--threads` enables them).
   On the VUT FIT server, a lot of study information is in threads and forums.
2. **Time window:** short default window (24 h), longer (e.g. 7 days), or full history. Full history
   of a large channel means thousands of messages, many requests, and a massive output for an agent.
3. **Format in agent mode:** `text` (token-efficient) or `json` (for programs).

## Decision

- **Threads are downloaded by default.** They can be disabled via `--no-threads`, except for a forum, which contains only threads.
- **The default time window is 24 h** (`--from 24h --to now`). Full history is only downloaded via `--from all`.
- **The default format in agent mode is `text`.** JSON is enabled via `--format json`.

## Consequences

- An agent that forgets to specify a window receives a small output. It will not download the entire history by accident.
- Threads will be added in step 4 (design, section 14). Until implemented, `messages` does not download threads
  and the `--no-threads` flag does not yet exist.
- Programs that want structured data must specify `--format json`.
