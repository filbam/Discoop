# Thread probe: pagination, active threads, thread messages, and `last_message_id`

Date: 2026-11-04. Type: measurement on the user's account. Two runs of the script `prototype/probe_threads.py` (GET
requests only, rate 1 request per second): first at 12:14 UTC (53 requests), second at 12:58 UTC (59 requests, script
extended in the meantime, see section 10).

**Legend:** **[VERIFIED]** = observed in one of the reports `prototype/out/probe-threads-20261104-121417.json`
(run 1) and `prototype/out/probe-threads-20261104-125820.json` (run 2). Both are local and git-ignored.
**[ASSUMPTION]** = not observed in these reports: follows from documentation, from another record in the repository, or is an inference.
The source is indicated in parentheses.

**Methodology:**
- From the reports, I only read structure: status codes, counts, field names, and keys. This document contains no user,
  channel, or thread names, message texts, or user IDs. Of IDs, only the VUT FIT server ID appears here.
- I did not use the older run `probe-threads-20261104-121242.json`.
- Sections 2 through 6 primarily describe run 1; section 7 is run 2. Where run 2 concluded something, sections 2 through 6 reference it.
- Related records: [discord-analysis.md](discord-analysis.md) (section 6 Threads and forums, browser observation) and
  [design.md](../design.md) (section 8 Threads and forums).

---

## 1. Summary

State after both runs.

| # | Question | Short answer |
|---|---|---|
| 1 | Page size of `threads/search` | `limit=25` works, `limit=50` gave `400` (code `50035`, in both runs). Values 26 to 49 are untested |
| 2 | `offset` reach | `0`, `25`, `100`, `500`, and `1808` each returned 25 threads. 40 consecutive pages yielded 1000 unique threads, 0 duplicates (in both runs) |
| 3 | End of list | **An empty page marks it** (offset 1833 and 1858: `200`, 0 threads). **A short page is also the end** (12 threads, next page 0) |
| 4 | `has_more` and `total_results` | `has_more: true` on the last page was a false positive. `total_results` of the archived list matched (1833), for active threads it did not (14 vs 12 returned, reason unknown). The end must not be determined from them |
| 5 | `202` "not indexed" | Did not occur in 112 requests (both runs). This is not proof that it never occurs |
| 6 | Private threads | None visible. All 66 inspected threads had type 11 and were not locked |
| 7 | `GET /guilds/{id}/threads/active` | `403`, code `20002`, "Only bots can use this endpoint" |
| 8 | Threads in a text channel | **Works in one readable channel** (archived: 25, active: 4). Channel without access gave `403` (code `50001`). Other text and announcement channels are unverified |
| 9 | Thread messages | `GET /channels/{thread_id}/messages` gave `200` in all 3 calls; thread is read like a regular channel |
| 10 | Forum post starter message | It is the thread's first message and its ID equals the thread ID (25 of 25 in `first_messages`, as well as in the 2 read posts) |
| 11 | `last_message_id` in channel list | Present on 385 of 412 channels. In 2 of 2 readable samples it matched the newest message (both runs identically). Samples are few |

---

## 2. Run setup

**Run 1:**
- 53 requests in 64.0 s, start 2026-11-04 12:14:17 UTC **[VERIFIED]**.
- Server: VUT FIT, ID `461541385204400138` **[VERIFIED]**.
- Target forum: `help-center` (channel type 15), containing 1833 archived threads (`total_results` on both the first and
  last of 40 pages) **[VERIFIED]**.
- Rate-limit headers (`x-ratelimit-*`, `retry-after`) did not appear in any of the 53 responses **[VERIFIED]**.

**Run 2:** 59 requests in 73.0 s, start 2026-11-04 12:58:20 UTC, same server and forum **[VERIFIED]**.

**Common:**
- All requests were GET. Nothing was written or modified **[VERIFIED]** (the script sends GET only).
- Thread search parameters: `archived`, `sort_by=last_message_time`, `sort_order=desc`, `limit`, `offset`
  **[VERIFIED]**.
- Result ordering was not checked by the probe. That results are genuinely sorted newest-first is an **[ASSUMPTION]** (server
  accepted parameters; Discord client sends the same, see [discord-analysis.md](discord-analysis.md), section 6).

---

## 3. Forum thread search (`threads/search`)

### 3.1 Page size

| Request | Result |
|---|---|
| `archived=true&limit=25&offset=0` | `200`, 25 threads **[VERIFIED]** |
| `archived=true&limit=50&offset=0` | `400`, code `50035` "Invalid Form Body", body has keys `code`, `errors`, `message` **[VERIFIED]** |

- The only difference between these two requests was `limit`, so the reason for rejection is probably that parameter
  **[ASSUMPTION]**. Details in the `errors` array were not recorded in the report.
- Values 26 to 49 were not tested **[VERIFIED]**. That the maximum is exactly 25 is an **[ASSUMPTION]**.
- The result was repeated in run 2 **[VERIFIED]**.

### 3.2 Offsets and pagination

- Offsets `0`, `25`, `100`, `500`, and `1808` each returned `200` and 25 threads **[VERIFIED]** (both runs). Offset `1808` is
  `total_results − 25`, i.e. the last full page.
- Pagination from offset 0 with step 25 exhausted 40 pages: 1000 returned threads, 1000 unique, 0 duplicates
  **[VERIFIED]** (both runs). It was stopped by the 40-page ceiling in the probe (`stop_reason: max_pages_reached`), not the API.
- During pagination, `total_results` did not change (1833) **[VERIFIED]**. The list therefore did not shift between pages enough
  to produce duplicates.
- Page past the end: see section 7.6.
- Untested: pages between offsets 1000 and 1807 (uniqueness).

### 3.3 `has_more` and `total_results` are unreliable

| Observation | Values |
|---|---|
| Offset `1808`, `archived=true` | `has_more: true`, although `1808 + 25 = 1833 = total_results` **[VERIFIED]** |
| All 5 inspected offsets | `has_more: true`, including the last page **[VERIFIED]** |
| Active forum threads (`archived=false`) | 12 returned, `total_results: 14`, `has_more: false` **[VERIFIED]** |

- On the last page, two interpretations were possible: `has_more` is a false positive, or `total_results` is lower than
  the actual count. Run 2 settled this: offset 1833 returned 0 threads, so `has_more: true` at offset 1808 was
  a **false positive** (section 7.6) **[VERIFIED]**.
- For active threads, `total_results` exceeds the count of returned threads by 2, identically in both runs **[VERIFIED]**. A similar
  discrepancy (15 vs 13) is also recorded in [discord-analysis.md](discord-analysis.md), section 14. The next page (offset 25)
  was empty, so the missing 2 threads are not on it (section 7.5). Why `total_results` reports 14 remains
  unexplained.
- **Consequence:** the end of pagination must not be determined from `has_more` or `total_results`. They are best suited as a rough
  estimate for a progress indicator.

### 3.4 `202` response

- In 112 requests (53 + 59), not a single `202` was received **[VERIFIED]** (`count_202: 0` in both runs).
- This is not proof that it never occurs. For message search, a `202` with `retry_after` is expected
  **[ASSUMPTION]** ([discord-analysis.md](discord-analysis.md), section 8). For `threads/search`, no one has verified it.

### 3.5 Response shape

- Keys of a `200` response: `first_messages`, `has_more`, `members`, `threads`, `total_results` **[VERIFIED]**.
- The content of `first_messages` and `members` was only determined in run 2 (section 7.4).

---

## 4. Active threads

| Source | Result |
|---|---|
| `GET /guilds/{id}/threads/active` | `403`, code `20002`, "Only bots can use this endpoint.", body has keys `code`, `message` **[VERIFIED]** (both runs) |
| `threads/search?archived=false` in forum | `200`, 12 threads, `total_results: 14`, `has_more: false` **[VERIFIED]** (both runs) |
| `threads/search` (archived and active) in text channel, which was first in list (run 1) | `403`, code `50001` "Missing Access" **[VERIFIED]** |
| `threads/search?archived=false` in readable text channel (run 2) | `200`, 4 threads **[VERIFIED]** |

- Active forum threads can be read via `threads/search?archived=false` **[VERIFIED]**. Completeness (12 of 14) is
  questionable, see section 3.3.
- **Run 1** took the first text channel (type 0) from the list without checking whether the user can see into it. The first sample
  of the subsequent `last_message_id` check (first text channel with `last_message_id`) gave `403` when reading messages as well
  **[VERIFIED]**. That it was the same channel is not directly proved by the report (sample IDs are not stored); it follows from
  both selections proceeding in list order **[ASSUMPTION]**.
- **Run 2** selected candidates by newest `last_message_id`, and the first of them answered `200` (section 7.2).

---

## 5. Threads: types and fields

**Run 1:** 37 unique threads were inspected: the first 25 archived forum threads and 12 active forum threads
(the guild endpoint and the text channel returned nothing) **[VERIFIED]**. **Run 2:** 66 threads (section 7.7).

| Property | Observation |
|---|---|
| Type | all 37 (run 1) and all 66 (run 2) have type 11 (public thread) **[VERIFIED]** |
| Private threads (type 12) | 0 in both runs **[VERIFIED]** |
| `thread_metadata.locked` | `false` on all **[VERIFIED]** |
| `flags` | `0` on all **[VERIFIED]** |

**Thread fields in run 1** (union across 37 threads; not guaranteed that every thread has them) **[VERIFIED]**:
`applied_tags`, `bitrate`, `flags`, `guild_id`, `id`, `last_message_id`, `member_count`, `member_ids_preview`,
`message_count`, `name`, `owner`, `owner_id`, `parent_id`, `rate_limit_per_user`, `rtc_region`, `thread_metadata`,
`total_message_sent`, `type`, `user_limit`. In run 2, `last_pin_timestamp` was added (section 7.7).

**`thread_metadata` fields** **[VERIFIED]**: `archive_timestamp`, `archived`, `auto_archive_duration`,
`create_timestamp`, `locked` (identical in both runs). The `invitable` field, which appeared in the browser log
([discord-analysis.md](discord-analysis.md), section 6), was not present here.

- The absence of private threads is weak evidence. The sample is one forum (newest 25 archived and 12 active threads)
  and one text channel (25 archived and 4 active). Furthermore, a forum contains only public threads (type 11)
  **[ASSUMPTION]** (documentation). The user may also lack permission that reveals private threads **[ASSUMPTION]**.
- The `owner`, `owner_id`, and `member_ids_preview` fields carry personal data **[ASSUMPTION]** (from
  [discord-analysis.md](discord-analysis.md), section 6). They must be handled according to privacy rules.

---

## 6. `last_message_id` in the channel list

`GET /guilds/{id}/channels` returned 412 channels **[VERIFIED]** (identically in both runs):

| Channel type | With `last_message_id` | Total |
|---|---|---|
| 0 text | 354 | 358 |
| 5 announcement | 12 | 12 |
| 15 forum | 9 | 9 |
| 2 voice | 9 | 10 |
| 13 stage | 1 | 1 |
| 4 category | 0 | 22 |
| **Total** | **385** | **412** |

**Comparison with newest message:** the probe took the first 3 text channels with `last_message_id` in list order and fetched
`GET /channels/{id}/messages?limit=1` from each **[VERIFIED]**.
- Sample 1: `403`, messages unreadable.
- Samples 2 and 3: `200`, ID of the newest message **matched** the channel's `last_message_id`.
- Thus 2 of 2 readable samples matched. Neither forum, announcement channel, nor voice channel was sampled.
- Run 2 did not change this selection (same channels, same results), so it **brought nothing new** (section 7.8).

**Implications:**
- `last_message_id` is populated on most channels where it makes sense **[VERIFIED]**. On categories it is missing (or is
  `null`), as well as on 4 text and 1 voice channel **[VERIFIED]** (27 channels without value).
- That it is reliable is an **[ASSUMPTION]**: two samples are not enough.
- The value may point to a deleted message. In [discord-analysis.md](discord-analysis.md), section 14, there is a channel whose
  `last_message_id` was newer than the newest readable message. The official documentation states that it may not point to an
  existing message **[ASSUMPTION]**. Such an error is harmless: one unnecessary request is made.
- The dangerous error would be the opposite: `last_message_id` older than the genuinely newest message. We did not observe it,
  but two samples do not rule it out.
- For a forum, `last_message_id` points to the last created post, not the last message in any post
  **[ASSUMPTION]** (official documentation). Messages in threads are probably not reflected into the parent channel's
  `last_message_id` **[ASSUMPTION]** (inference from documentation, unobserved).

---

## 7. Second run (2026-11-04, 12:58 UTC)

Report `prototype/out/probe-threads-20261104-125820.json`. The script was extended (section 10) to answer the open
questions from run 1.

### 7.1 Repeatability

- 59 requests in 73.0 s **[VERIFIED]**.
- Results of run 1 repeated **[VERIFIED]**:
  - `limit=25` gave `200` and `total_results` 1833, `limit=50` gave `400` (code `50035`),
  - offsets 0, 25, 100, 500, and 1808 returned 25 threads each and `has_more: true`,
  - 40 pages yielded 1000 unique threads without duplicates,
  - active forum threads: 12 returned, `total_results` 14, `has_more: false`,
  - `GET /guilds/{id}/threads/active` gave `403` (code `20002`),
  - `last_message_id` statistics in channel list (385 of 412).
- Rate-limit headers did not appear, `202` did not occur **[VERIFIED]**. No recorded response had status `429`
  (all had `200`, `400`, or `403`). A possible client retry after `429` would not be captured by the report.

### 7.2 Threads in a text channel

- Candidates (text and announcement channels with `last_message_id`, sorted newest first) numbered 6; only the first had to be tried:
  it answered `200` **[VERIFIED]**.
- `archived=true` (limit 25, offset 0): `200`, **25 threads** (full page), key `threads` present **[VERIFIED]**.
- `archived=false`: `200`, **4 threads** **[VERIFIED]**.
- `threads/search` therefore works in a text channel as well **[VERIFIED for one channel]**. For other text channels the
  user can see, this is an **[ASSUMPTION]** (same API). Channels without access return `403` (section 4).
- The report did not record candidate type (0 or 5), nor `total_results` or `has_more` for the text channel. Announcement
  channels (type 5) are therefore not considered tested, and whether 25 archived threads is the full list is unknown. Pagination
  in a text channel was not attempted **[VERIFIED]**.

### 7.3 Thread messages

Three calls to `GET /channels/{thread_id}/messages`, all `200` **[VERIFIED]**:

| Thread | Call | Result |
|---|---|---|
| newest archived forum post | `limit=1&after=0` | 1 message of type 0, ID equals thread ID |
| newest active forum post | `limit=1&after=0` | 1 message of type 0, ID equals thread ID |
| newest archived forum post | `limit=100` | 6 messages, types 0 (5×) and 19 (1×), batch complete (6 < 100), oldest message has thread ID |

- A thread is read like a regular channel, both archived and active **[VERIFIED]**.
- The server accepted `after=0` and returned the oldest message of the thread **[VERIFIED]** (for both threads its ID equalled the thread
  ID, and in the batch of 100 it was the oldest in the batch).
- Type 19 is a reply **[ASSUMPTION]** (documentation). Fields `message_reference` and `referenced_message` appeared in the batch
  **[VERIFIED]**.
- Fields of messages in a thread (union across batch of 6 messages) **[VERIFIED]**: `attachments`, `author`, `channel_id`,
  `components`, `content`, `edited_timestamp`, `embeds`, `flags`, `id`, `mention_everyone`, `mention_roles`, `mentions`,
  `message_reference`, `pinned`, `position`, `reactions`, `referenced_message`, `timestamp`, `tts`, `type`.
- Untested: thread with more than 100 messages (`before`/`after` pagination within a thread). That it works the same as in a
  channel is an **[ASSUMPTION]**.

### 7.4 Forum post starter message and `first_messages`

- `first_messages` in the `threads/search` response (first page of archived forum threads) is an array of 25 messages for 25
  threads **[VERIFIED]**. All 25 messages have **ID equal to thread ID**, `channel_id` equal to thread ID, and type 0
  **[VERIFIED]**.
- The same holds for both read posts: the oldest message of the thread has thread ID (section 7.3) **[VERIFIED]**.
  The ID of a forum post's starter message thus equals the thread ID, and it is the first message of the thread.
- Fields of messages in `first_messages` **[VERIFIED]**: `attachments`, `author`, `channel_id`, `components`, `content`,
  `edited_timestamp`, `embeds`, `flags`, `id`, `mention_everyone`, `mention_roles`, `mentions`, `pinned`, `position`,
  `reactions`, `timestamp`, `tts`, `type`. They are thus full message objects including `attachments`. The content of the `attachments`
  array was not examined by the probe; whether attachments of the starter message already arrive with search is an **[ASSUMPTION]**.
- `members` is present, but empty (0 items) **[VERIFIED]**.
- For threads in text channels, this does not hold automatically and was not tested (in browser, `first_messages` was missing on a text
  channel, [discord-analysis.md](discord-analysis.md), section 6).

### 7.5 A short page is the end

- Active search in the forum returned 12 threads (fewer than 25), `total_results` 14, `has_more: false` **[VERIFIED]**.
- The next page of the same search (`offset=25`): `200`, **0 threads**, `has_more: false` **[VERIFIED]**.
- The discrepancy of 12 vs 14 is therefore not caused by threads on the next page **[VERIFIED]**. Why `total_results` reports 14
  remains unexplained.
- This is a single observation of a short page, and that in the list of active threads. In the archived list, a short page
  did not occur: the last page had 25 threads and only the subsequent page was empty **[VERIFIED]**.

### 7.6 Page past the end

- Archived search at `offset=1833` (`= total_results`) and `offset=1858` (`= total_results + 25`): both
  `200` and **0 threads** **[VERIFIED]**. The server did not return an error even on an offset past the end.
- An empty page therefore marks the end of the list **[VERIFIED]**.
- The page at offset 1808 had 25 threads and offset 1833 had 0, so the list had exactly 1833 threads and
  `total_results` for the archived forum list matched **[VERIFIED]** (with list unchanged between requests).
- `has_more: true` at offset 1808 was therefore a false positive **[VERIFIED]**. The interpretation that `total_results` is lower
  than the actual count is ruled out for the archived list.

### 7.7 Thread types and fields

- 66 unique threads: 25 archived and 12 active from forum, 25 archived and 4 active from text channel
  (sum of counts from report) **[VERIFIED]**.
- All 66 have type 11, none is locked (`locked: false`), `flags` is 0, and private threads (type 12) are 0
  **[VERIFIED]**.
- Thread fields: the same 19 as in run 1 plus **`last_pin_timestamp`** **[VERIFIED]**. That it comes from the text
  channel threads is an **[ASSUMPTION]** (the sample changed precisely by adding these threads; the report does not list fields
  per individual thread).
- The `thread_metadata` fields are the same 5 **[VERIFIED]**.

### 7.8 `last_message_id`

- Comparison with the newest message gave the same result as in run 1: sample 1 `403`, samples 2 and 3 `200` with match
  **[VERIFIED]**. The script selects channels in list order, so these are the same 3 channels.
- The question of `last_message_id` reliability is thus still answered only weakly (2 readable samples, section 6).

---

## 8. What remains unverified

**Concluded by run 2:**
- `threads/search` in a text channel (works in one readable channel, section 7.2),
- reading thread messages via `GET /channels/{thread_id}/messages` (section 7.3),
- ID of a forum post starter message equals thread ID (section 7.4),
- whether a short page means the end (section 7.5) and what a page past the end returns (section 7.6),
- whether `has_more: true` on the last page was a false positive (section 7.6).

**Still open:**
1. **Additional text channels.** Verified on one channel. Unknown: type 5 (announcement channels), `total_results` and
   `has_more` for a text channel, pagination via `offset` there, and whether `first_messages` is missing there.
2. **Private threads (type 12).** None were present among the 66 threads. Whether they are visible for this user at all is
   unknown.
3. **Response `202`** on `threads/search` (did not occur in 112 requests).
4. **Pagination edge cases:** limits 26 to 49, uniqueness of pages after offset 1000, result ordering, short page
   in archived list (observed only on active threads).
5. **Why `total_results` for active threads is 2 higher** than returned count (14 vs 12).
6. **Thread with more than 100 messages** and pagination within a thread. Also ID of a thread's first message in a text channel: a thread
   originating from a message has an ID equal to that message's ID in the parent channel **[ASSUMPTION]**
   ([design.md](../design.md), section 8, `thread.id == message.id`), unverified in the thread itself.
7. **Reliability of `last_message_id`:** only 2 readable samples, none from a forum, announcement channel, or voice channel.

---

## 9. Design consequences

1. **Page size:** always `limit=25`. Do not use higher values (50 gives `400`).
2. **End of pagination** for both archived and active threads to be determined by the first of these conditions, never by
   `has_more` or `total_results`:
   - empty page (confirmed: offset 1833 and 1858 gave `200` and 0 threads),
   - short page, i.e. fewer than 25 (confirmed: page with 12 threads, next had 0),
   - start of time window (thread with last activity older than `--from`, provided sorting is genuinely by last
     message, see section 2),
   - page count ceiling as a safeguard.

   The rule "finish on empty or short page" is confirmed by run 2. A short page was observed once, on active threads.
   If the last page is full (25), the end is signalled only by the next, empty page, costing one additional request.
3. **`total_results`** should be used at most as a rough estimate for a progress indicator. For the archived forum list it
   matched, for active it did not (14 vs 12).
4. **Active threads** should be read via `threads/search?archived=false` per channel. The guild endpoint is for bots only.
   Verified in a forum and in one text channel. The fallback source from [design.md](../design.md), section 8
   (messages with a `thread` object), can remain for channels where search fails.
5. **`403` (code `50001`) when searching threads in a single channel** should be treated as "no access" and that channel skipped,
   not aborting the entire run. Access does not need to be guessed prior to calling; handling the response is enough.
6. **`202`** should be handled (short wait and retry with an upper limit), even though it did not occur in 112 requests.
7. **Type 12** (private thread) must not crash on an unknown value. None was present in this data.
8. **Thread messages** should be downloaded via standard message pagination with thread ID as channel ID
   (`GET /channels/{thread_id}/messages`, `limit`, `before`/`after`). Verified: `limit=1&after=0` (oldest message) and
   `limit=100`, both archived and active thread. Pagination beyond 100 messages in a thread is an **[ASSUMPTION]**.
   The exporter must also handle type 19 messages (reply) with fields `message_reference` and `referenced_message`.
9. **Forum post starter message** is the thread's first message with ID equal to thread ID. No special case is needed:
   normal thread downloading from the start encompasses it. `first_messages` from search can save requests, but is not
   required and relying on it as sole source makes no sense. For threads in text channels, this was not verified.
10. **Skipping inactive channels (`--since-last`)** via `last_message_id` from the channel list (no additional request
    needed). A channel is skipped only when `last_message_id` is non-empty and not newer than the stored
    cursor. On `null`, the channel is not skipped. All of this remains an **[ASSUMPTION]**, because we have 2 readable samples. Safeguards:
    - always provide a way to disable skipping and fetch everything,
    - do not skip forums and channels where threads are downloaded based on `last_message_id` until determined otherwise whether they
      have new thread messages (new messages in old posts and threads probably do not alter it, see section 6),
    - treat the value only as a reason not to skip (a deleted message causes an unnecessary request; nothing is lost).

---

## 10. Extended script (basis for run 2)

The script `prototype/probe_threads.py` was extended between runs (instructions in [prototype/README.md](../../prototype/README.md),
section 4). Run 2 executed all new checks, about 59 to 64 requests. New checks:
- `threads_search_text_candidates` and `threads_search_text_active`: thread search in up to 6 text channels
  with the newest `last_message_id`, until one answers `200` (section 7.2),
- `thread_messages_readable`: reading messages in a thread via `GET /channels/{thread_id}/messages` (section 7.3). First
  call takes the oldest message (`limit=1&after=0`), because the newest (`limit=1` without anchor) would equal the thread ID
  only for a single-message thread. The server accepted `after=0` (section 7.3),
- `threads_search_first_messages`: counts and field names from `first_messages` and `members` without an additional request
  (section 7.4),
- `threads_search_after_short_page`: if active search in the forum returns fewer than 25 threads, the probe requests
  the next page (`offset=25`) and records status code, thread count, and `has_more` (section 7.5),
- `threads_search_past_end`: archived search in the forum at `offset = total_results` and `total_results + 25`;
  if `total_results` is not known, the check is skipped (section 7.6).

The report remains structural, without IDs and texts.
