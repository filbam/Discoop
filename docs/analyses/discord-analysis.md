# Discord Web Client Data Analysis (VUT FIT Server)

Observation dates: 2026-11-02 – 2026-11-03 (Europe/Bratislava), three rounds (rounds 2 and 3 under strict rules). Client: discord.com in Chrome (logged in with the user's account), API `v9`.
Server: **VUT FIT** (`guild_id = 461541385204400138`).

> **INCIDENT during round 1 of the analysis:** while interacting with the search box, a message
> `cdn.discordapp.com` was accidentally **sent** from the user's account into the forum thread *"Question about automatic course credit"*
> (thread `1566814241946738698` in forum `#help-center`, 2026-11-03 00:07,
> `POST /api/v9/channels/1566814241946738698/messages` → `200`).
> **The user has deleted the message in the meantime.** However, sending the message appears to have made the user
> a member of the thread: in round 2 the thread was visible in the sidebar under `#help-center`, and in round 1 it showed
> "Following". If it should stay that way, it should perhaps be unfollowed manually.
> Rounds 2 and 3 (additions) were conducted under stricter rules: no keyboard input, no search,
> clicks only on channel names in the sidebar and on the Threads button in the header. Nothing unexpected occurred.

**Legend:** **[VERIFIED]** = observed in requests or in client state during this analysis.
**[ASSUMPTION]** = based on general knowledge of the Discord API, not verified during this analysis.

**Methodology:** URLs and status codes obtained from the network log of a Chrome extension. The extension cannot display response bodies
or headers, so in **my own tab** I installed a passive observer
(a wrapper around `XMLHttpRequest`/`fetch`). For `/api/v9/channels|guilds/...` it recorded the response body,
**only the names** of request headers, and selected response headers. I did not read or store the `Authorization` value or cookies.
I made no API requests of my own. I read the client state via React fiber
props in the DOM (the webpack store cache is hidden in the current client; from `__webpack_require__.c` only
~100 polyfill modules are accessible). JSON examples are anonymised.

---

## 1. Summary Table

| Data Type | Source in Client | Verified? | Note |
|---|---|---|---|
| Server list (guilds) | gateway `READY` → client state | partially (REST request not observed, guild object is in client state) | REST `GET /users/@me/guilds` exists, client did not call it on startup **[ASSUMPTION]** |
| Server info | gateway → client state (camelCase record) | [VERIFIED] list of fields | `name, description, icon, banner, features, rulesChannelId, ...` |
| Channels + categories | gateway → client state | [VERIFIED] | 392 channels + 22 categories. Hidden channels arrive **obfuscated** (`___hidden___`) |
| Channel messages (text, announcement, voice chat) | REST `GET /channels/{id}/messages` | [VERIFIED] | `limit` + `before`/`after`/`around`, response is an array **from newest to oldest**. Client: first open `limit=10`, subsequent pages `limit=20` |
| Messages in a thread / forum post | REST `GET /channels/{thread_id}/messages` | [VERIFIED] | thread = standalone channel, messages additionally have `position` |
| Pinned messages | REST `GET /channels/{id}/messages/pins?limit=25` | [VERIFIED] | `{items:[{pinned_at, message}], has_more}` |
| Active threads | gateway → client state | [VERIFIED] (without REST request) | thread record with `thread_metadata`, `message_count` |
| Archived threads / forum posts | REST `GET /channels/{id}/threads/search?archived=true...` | [VERIFIED] | pagination via `offset`, `total_results`, `has_more` |
| First message + author of forum post | REST `POST /channels/{forum_id}/post-data` | [VERIFIED] response, request body not observed | read-only POST |
| Search | REST `GET /guilds/{id}/messages/search` | [VERIFIED] | 25 results per page, `offset`, `min_id`, `channel_id`, `has`, `content` |
| Attachments | in message object (`attachments[]`) + CDN | [VERIFIED] | signed URLs with `ex/is/hm`, 24 h window, freshly fetched URL is valid for **≥ 12 h** |
| Embeds (links, GIF, YouTube, images, tweets) | in message object (`embeds[]`) | [VERIFIED] | types `link`, `gifv`, `video`, `image`, `rich`. GIF provider is now **Klipy** (not Tenor) |
| Custom emoji | message text `<:name:id>` + CDN | [VERIFIED] | `https://cdn.discordapp.com/emojis/{id}.webp?size=48`, unsigned |
| Thread created from a message | `message.thread` + `flags & 32` | [VERIFIED] | `thread.id == message.id` |
| Stickers, forwards, polls, system messages | in message object | **Unverified** | did not occur in ~410 inspected messages across 9 channels |
| Reactions | in message object (`reactions[]`) | [VERIFIED] | counts only, not who reacted |
| Members / nicknames | gateway (lazy member list) | [VERIFIED] indirectly (no REST members request) | REST messages **do not contain** `member` |
| Server roles, emojis, stickers | gateway → client state | [ASSUMPTION] | REST `GET /guilds/{id}/roles|emojis|stickers` |
| Rate-limit headers | – | [VERIFIED] **absent** | no `X-RateLimit-*` in ~40 API responses (all 200/204) |
| Read state (read receipts) | REST `POST /channels/{id}/messages/{id}/ack` | [VERIFIED] | client calls this automatically when opening a channel. The CLI **should not** call this |
| Server scheduled events | REST `GET /guilds/{id}/scheduled-events/{id}/users/counts` | [VERIFIED] URL | list of events arrives via gateway **[ASSUMPTION]** |

---

## 2. Server List

- When loading or reloading the tab, the client **did not call** `GET /api/v9/users/@me/guilds`. Captured requests were only
  `science`, `metrics/v2`, `quests/get-decisions`, and message requests **[VERIFIED]**. Caveat: network tracking resets
  on initial navigation, so the very first boot requests may have been missed.
- The guild object in client state (from gateway `READY`/`GUILD_CREATE`) has these fields (camelCase, client-side
  record) **[VERIFIED]**:
  `id, joinedAt, premiumSubscriberCount, name, description, icon, splash, banner, homeHeader, features,
  preferredLocale, ownerId, application_id, afkChannelId, afkTimeout, systemChannelId, verificationLevel,
  explicitContentFilter, defaultMessageNotifications, mfaLevel, vanityURLCode, premiumTier,
  systemChannelFlags, discoverySplash, rulesChannelId, safetyAlertsChannelId, publicUpdatesChannelId,
  maxMembers, nsfwLevel, hubType, profile, guildTheme, premiumFeatures, ...`
- REST alternative **[ASSUMPTION]**: `GET /api/v9/users/@me/guilds` (optionally `?with_counts=true`) returns an array of
  `{id, name, icon, banner, owner, permissions, features, approximate_member_count, approximate_presence_count}`.
  Raw JSON from gateway uses snake_case (`owner_id`, `system_channel_id`, `rules_channel_id`...).

## 3. Channels

**Source:** gateway (`READY` / `GUILD_CREATE`), in the client this is the sidebar model `guildChannels`. When switching
channels, no REST request for the channel list was sent **[VERIFIED]**.
REST alternative: `GET /api/v9/guilds/{guild_id}/channels` **[ASSUMPTION]**.

**Channel types on VUT FIT** **[VERIFIED]** (total 392 records + 22 categories):

| `type` | Meaning | Count | Examples |
|---|---|---|---|
| 0 | GUILD_TEXT | 358 | `#course-general`, `#course-deadlines`, `#team-private🔒`, `#readme-en` |
| 2 | GUILD_VOICE (also has text chat) | 10 | `general - open`, `games`, `lounge` |
| 4 | GUILD_CATEGORY | 22 (`categories` map) | `general`, `electives`, `static info`, `archive`, `1st semester` ... |
| 5 | GUILD_ANNOUNCEMENT | 12 | `course-info`, `campus-news`, `changelog`, `club-info` |
| 13 | GUILD_STAGE_VOICE | 1 | `general stage` |
| 15 | GUILD_FORUM | 9 | `help-center`, `marketplace`, `portal-bugfest`, `student-feedback` |
| 11 | PUBLIC_THREAD | (threads) | `"Secret thread"` in `#course-general`, forum posts |
| 16 | GUILD_MEDIA | 0 | does not occur |

**Channel fields** (client record, raw name in parentheses) **[VERIFIED]**:
`id, guild_id, name, type, parent_id` (category ID or `null`), `position_` (`position`), `topic_` (`topic`),
`nsfw_`, `flags_` (`flags`), `rateLimitPerUser_` (`rate_limit_per_user`), `lastMessageId` (`last_message_id`),
`lastPinTimestamp` (`last_pin_timestamp`), `permissionOverwrites_` (`permission_overwrites`), `iconEmoji`
(`{id, name}`), `themeColor`, `defaultAutoArchiveDuration`, `defaultThreadRateLimitPerUser`, `application_id`, `version`.

Forum channel (type 15) additionally has **[VERIFIED]**:
```json
{
  "available_tags": [{"id": "1065278887191384144", "name": "Unanswered", "emoji_id": "600435650227077120", "emoji_name": null, "moderated": false, "color": null}],
  "default_reaction_emoji": {"emoji_id": "960172090701524992", "emoji_name": null},
  "default_sort_order": null,
  "default_tag_setting": "match_some",
  "default_auto_archive_duration": 4320,
  "flags": 16
}
```
(`flags: 16` = REQUIRE_TAG. Tags `Academics`, `Offtopic`, `Answered`... In the client they are in camelCase.)

**Hierarchy and ordering:** `parent_id` points to a category (e.g. `#course-deadlines.parent_id = 591352457703981067` =
category `general`). Categories have their own `position` (e.g. `static info`=5, `electives`=240, `general`=254,
`archive`=325) **[VERIFIED]**. Ordering: categories by `position`, channels within a category by `position`, tie-breaker by `id`.
Voice channels appear below text channels **[ASSUMPTION]**.

**Locked and private channels:**
- The lock `🔒` in names such as `#team-private🔒` is **part of the channel name**, not a system state. Access is governed by
  `permission_overwrites` **[VERIFIED]**. Examples:
  - `#course-deadlines`: `@everyone` (`id = guild_id`, `type 0`) `deny = "103079218176"` (includes VIEW_CHANNEL `1024`),
    several roles `allow = "1024"`.
  - `#course-general`: `@everyone deny "1024"`, role `allow "3072"` (VIEW_CHANNEL + SEND_MESSAGES), plus
    **member overwrites** (`type 1`, `id = <user_id>`) `allow "1024"`.
  - `type 0` = role, `type 1` = member. `allow`/`deny` are **strings** containing permission bit fields.
- **Channels that the user cannot view ARE present in the data, but obfuscated** **[VERIFIED]**:
  ```json
  {"id": "1549737445002584094", "type": 0, "name": "___hidden___", "flags": 131072,
   "parent_id": null, "last_message_id": null, "topic": null, "position": 4,
   "permission_overwrites": [{"id": "461541385204400138", "type": 0, "allow": "0", "deny": "1024"}]}
  ```
  They have the name `___hidden___`, `flags` bit `1<<17` (131072), lost `parent_id` and `last_message_id`,
  and a synthetic overwrite "@everyone deny VIEW". For example, there were 4 whole categories named `___hidden___` and multiple channels
  (renderLevel 1 = unrendered: 74 records, some of which are hidden voice and "resource" channels).
- `#readme-docs`/`#readme-en` have `flags: 128` (likely a "Server Guide" resource channel) **[ASSUMPTION regarding meaning]**.

## 4. Messages

**Endpoint** **[VERIFIED]**:
```
GET /api/v9/channels/{channel_id}/messages?limit=10
GET /api/v9/channels/{channel_id}/messages?before={message_id}&limit=20
GET /api/v9/channels/{channel_id}/messages?after={message_id}&limit=20
GET /api/v9/channels/{channel_id}/messages?limit=10&around={message_id}
```
- The client used **always** `limit=10` on initial channel open and `limit=20` on each subsequent page
  (`before`/`after`) **[VERIFIED, 9 channels, ~20 requests]**. The maximum is **100** **[ASSUMPTION, verify via prototype]**.
- If fewer messages than `limit` are returned, it indicates the start of history. `#course-info` returned only 6 messages
  with `limit=10` and the client displayed "This is the start of the channel" **[VERIFIED]**.
- The response is a JSON **array ordered from newest to oldest**, even **when using `after=`** **[VERIFIED]**
  (`after=1566815961741262950` returned 5 messages in descending order).
- `around` returned 6 messages including the anchor with `limit=10`, because the thread had few messages **[VERIFIED]**.
- **Announcement channels** (type 5) are read identically (`GET /channels/{id}/messages`) **[VERIFIED]**
  (`#course-info`, `#campus-news`). The client additionally calls `GET /channels/{id}/follower-stats` (→ `204`) for them.
- Messages in the REST response **do not include `member`** (neither nickname nor roles of the author) **[VERIFIED]**: absent across all ~410 observed messages.

**Message fields** (observed in raw JSON) **[VERIFIED]**:

| Field | Meaning |
|---|---|
| `id` | message snowflake (contains timestamp) |
| `channel_id` | channel or thread ID |
| `type` | 0 = DEFAULT, 19 = REPLY (only these occurred in ~410 messages). System types (7 join, 6 pin, 18 thread created, 21 thread starter, 46 poll result...) **[ASSUMPTION]** |
| `content` | text (markdown, mentions such as `<@id>`, `<@&id>`, `<#id>`, custom emoji `<:name:id>`). `<@&id>` and `<:name:id>` **[VERIFIED]** |
| `author` | user object (see below). Bots additionally have `"bot": true` **[VERIFIED]** |
| `timestamp` | ISO 8601 with microseconds, `+00:00` |
| `edited_timestamp` | ISO string or `null` |
| `attachments[]` | attachments (Section 5) |
| `embeds[]` | link preview, GIF, video (Section 5) |
| `mentions[]` | **full user objects** of mentioned users |
| `mention_roles[]` | role IDs only |
| `mention_everyone` | bool |
| `reactions[]` | optional, only if any exist |
| `message_reference` | optional: `{type, channel_id, message_id, guild_id}`. `type 0` = reply, `1` = forward **[ASSUMPTION]** |
| `referenced_message` | optional: full object of original message (without its own `referenced_message`) |
| `pinned` | bool |
| `tts` | bool |
| `flags` | bitfield. Observed values **[VERIFIED]**: `0`; `1` (CROSSPOSTED, published message in announcement channel); `4` (SUPPRESS_EMBEDS, link without preview, `embeds: []`); `5` = 1+4; `32` (HAS_THREAD, a thread was created from this message). Bit names from documentation |
| `components[]` | buttons and menus (empty in all observed messages, even for bots) |
| `thread` | optional: full thread object if a thread was created from the message. **`thread.id == message.id`** **[VERIFIED]** |
| `position` | thread messages only, sequential number of the message within the thread |
| `hit` | search results only (`true`) |

**Thread created from a message** (`#advisor-questions`, "Automatic thread") **[VERIFIED]**:
```json
{"id": "1053252576004542494", "type": 0, "flags": 32, "content": "<text>",
 "thread": {"id": "1053252576004542494", "type": 11, "parent_id": "471211826571640842", "name": "Automatic thread",
            "owner_id": "<user_A_id>", "last_message_id": "…", "message_count": 3, "member_count": 3,
            "total_message_sent": 3, "member_ids_preview": ["<user_id>", "…"], "flags": 0,
            "bitrate": 64000, "user_limit": 0, "rtc_region": null, "rate_limit_per_user": 0,
            "thread_metadata": {"archived": true, "archive_timestamp": "…", "auto_archive_duration": 4320,
                                "locked": false, "create_timestamp": "…"}}}
```

Did not occur in ~410 messages from 9 channels, although present in the client Message record. Raw names and shapes are
**[ASSUMPTION, verify via prototype]**:
`sticker_items` (stickers), `message_snapshots` (forwards), `poll` (polls), system messages,
`interaction_metadata`, `application_id`, `webhook_id`, `mention_channels`, `call`, `activity`,
`role_subscription_data`, `nonce`. Inspected channels: `#course-general` (~200 messages back to 2026-10-19),
`#general` (~110), `#english-general` (30), `#vote-room` (30, bot voting via reactions, not polls),
`#quotes` (10, screenshots as attachments, not forwards), `#campus-news`, `#course-info`, `#advisor-questions`,
`#course-deadlines`, forum post in `#help-center`.

**`author`** **[VERIFIED]**:
```json
{
  "id": "<user_A_id>", "username": "<user_A>", "global_name": null,
  "avatar": "<avatar_hash>", "discriminator": "0",
  "public_flags": 128, "flags": 128, "banner": null, "accent_color": null, "banner_color": null,
  "avatar_decoration_data": null, "display_name_styles": null,
  "collectibles": {"nameplate": {"sku_id": "…", "asset": "<asset>", "label": "…", "palette": "cobalt"}},
  "clan": {"identity_guild_id": "<guild_id>", "identity_enabled": true, "tag": "<tag>", "badge": "<badge_hash>"},
  "primary_guild": {"identity_guild_id": "<guild_id>", "identity_enabled": true, "tag": "<tag>", "badge": "<badge_hash>"}
}
```
`username` is the unique handle, `global_name` is the display name (can be `null`), `discriminator` is currently `"0"`.

**Reply** **[VERIFIED]**:
```json
{
  "type": 19,
  "message_reference": {"type": 0, "channel_id": "1282100102743330887", "message_id": "1566536198581788806", "guild_id": "461541385204400138"},
  "referenced_message": {"type": 0, "id": "1566536198581788806", "content": "<text>", "author": {"…": "…"}, "…": "…"}
}
```
- 9 out of 10 replies had `referenced_message`. One **lacked the key entirely** (reference to an older, likely deleted message).
- **Pins and search results do not include `referenced_message`.** The client displays "Message could not be loaded" in that case **[VERIFIED]**.

**Reactions** **[VERIFIED]**:
```json
{"emoji": {"id": null, "name": "✅"}, "count": 1, "count_details": {"burst": 0, "normal": 1},
 "burst_colors": [], "me_burst": false, "burst_me": false, "me": false, "burst_count": 0}
```
Custom emoji has `emoji.id` + `name`, animated additionally `"animated": true` **[VERIFIED]**. Who reacted can be queried via
`GET /channels/{id}/messages/{id}/reactions/{emoji}` **[ASSUMPTION]**.

## 5. Attachments, Media, Embeds

**Fields `attachments[]`** **[VERIFIED]**:
```json
{
  "id": "1566570336231882913",
  "filename": "<file.png>",
  "size": 8328,
  "url": "https://cdn.discordapp.com/attachments/1282100102743330887/1566570336231882913/<file>?ex=…&is=…&hm=…&",
  "proxy_url": "https://media.discordapp.net/attachments/1282100102743330887/1566570336231882913/<file>?ex=…&is=…&hm=…&",
  "width": 1199, "height": 42,
  "content_type": "image/png", "original_content_type": "image/png",
  "content_scan_version": 4,
  "placeholder": "<thumbhash>", "placeholder_version": 1
}
```
Additional observed optional fields: `title` (original filename), `duration_secs` (video, e.g. `27.53`),
`flags` (`32` for animated GIF, IS_ANIMATED **[ASSUMPTION regarding meaning]**). Not observed: `description`
(alt text), `waveform` and `duration_secs` for voice messages, `ephemeral`. `width`/`height` are present only for images and videos.
Observed types: `image/png`, `image/jpeg`, `image/webp`, `image/gif`, `video/mp4`.

**CDN URLs and signatures** **[VERIFIED]**:
- Format: `https://cdn.discordapp.com/attachments/{channel_id}/{attachment_id}/{filename}?ex={hex}&is={hex}&hm={64 hex}&`
  (ends with `&`). Some have `backend=b2` as the first query parameter, e.g. `?backend=b2&ex=…&is=…&hm=…&`.
- `proxy_url` is the same file on `media.discordapp.net` with identical query parameters. The client appends
  `&format=webp&quality=lossless&width=…&height=…` for previews.
- `ex` = expiry, `is` = issue timestamp, both as **hex Unix timestamps in seconds**. **`ex − is = 24 h`** (all 22 + 26 attachments).
- `is` = **attachment creation time (from snowflake `attachment.id`) + k × 12 h**, where `k` is the largest integer such
  that `is ≤ fetch time`. In all 22 measured cases, `0 ≤ fetch − is < 12 h` held **[VERIFIED]**.
  Example: attachment from `2026-11-01T21:51:13Z` → `is=2026-11-02T21:51:13Z`, `ex=2026-11-03T21:51:13Z`.
  **A freshly fetched URL is therefore valid for at least 12 h and at most 24 h.** The URL is deterministic within
  a 12-hour window, which presumably enables caching.
- `POST /api/v9/attachments/refresh-urls` was **not triggered** during the analysis (found no message with an expired
  CDN link in text). Assumption: request body `{"attachment_urls": [...]}` → `{"refreshed_urls": [{"original", "refreshed"}]}` **[ASSUMPTION]**.
- **Authorization on CDN:** images and videos are fetched by the client as standard `<img>`/`<video>` resource requests
  (in the network log as GET to `media.discordapp.net/...`). No CDN request went through the API layer (XHR, which attaches `Authorization`)
  **[VERIFIED]**. The browser does not add custom headers to `<img>`, so the CDN
  **does not require a token**; the signature in the URL suffices (high confidence; I did not inspect CDN request headers directly).
- Role icons: `https://cdn.discordapp.com/role-icons/{role_id}/{hash}.webp?size=24&quality=lossless` **[VERIFIED]**.

**Embeds** **[VERIFIED]**:
- **GIF (`type: "gifv"`)**, provider **Klipy** (Discord switched from Tenor):
  ```json
  {"type": "gifv", "url": "https://klipy.com/gifs/<slug>", "title": "<text>",
   "provider": {"name": "Klipy", "url": "https://klipy.com"},
   "thumbnail": {"url": "https://static.klipy.com/…/x.webp", "proxy_url": "https://images-ext-1.discordapp.net/external/<sig>/https/static.klipy.com/…/x.webp", "width": 498, "height": 498, "placeholder": "…", "placeholder_version": 1, "flags": 0},
   "video": {"url": "https://static.klipy.com/…/x.mp4", "proxy_url": "https://images-ext-1.discordapp.net/external/<sig>/https/…", "width": 498, "height": 498, "placeholder": "…", "placeholder_version": 1, "flags": 0},
   "content_scan_version": 4}
  ```
- **Link preview (`type: "link"`)**: `url, title, description, color, provider{name}, thumbnail, content_scan_version, reference_id`.
- **YouTube (`type: "video"`)**: `url, title, description, color, author, provider{name: "YouTube"}, thumbnail, video, reference_id`.
- **Direct image link (`type: "image"`)** **[VERIFIED]**: `{type, url, thumbnail{url, proxy_url, width, height, …}, content_scan_version}`.
- **Rich (`type: "rich"`)**, e.g. tweet preview via vxtwitter/fixvx **[VERIFIED]**: `url, description, color, timestamp,
  author{name, url, icon_url, proxy_icon_url}, footer{text, icon_url, proxy_icon_url}, thumbnail,
  video{url, proxy_url, width, height, content_type, placeholder, placeholder_version, flags}, reference_id, content_scan_version`.
- External images go through proxy `images-ext-N.discordapp.net/external/{signature}/{scheme}/{host}/{path}`.

**Custom emoji** **[VERIFIED]**:
- in text: `<:name:id>`, e.g. `<:peepolove:827833315666558996>`. Animated `<a:name:id>` **[ASSUMPTION]**.
- CDN (fetched by client): `https://cdn.discordapp.com/emojis/{id}.webp?size=48` (also `size=56`), **without `ex/is/hm` signature**,
  therefore does not expire.

**Stickers** **[ASSUMPTION]** (none in observed data):
- `sticker_items: [{id, name, format_type}]`, CDN: `https://media.discordapp.net/stickers/{id}.webp`
  (format_type 1 PNG, 2 APNG, 3 Lottie JSON, 4 GIF).

## 6. Threads and Forums

- **Thread = standalone channel.** Messages are fetched via `GET /channels/{thread_id}/messages` **[VERIFIED]**.
- **Active threads** are received by the client via gateway. The "Threads" panel displayed the active thread without any REST request
  **[VERIFIED 2×]**. When opening the panel, **only one** API request is sent: `threads/search?archived=true…`
  (for archived threads). No REST request is sent for active threads.
  Thread record **[VERIFIED]**:
  ```json
  {"id": "1521315949171441765", "type": 11, "guild_id": "461541385204400138", "parent_id": "1282100102743330887",
   "name": "Secret thread", "owner_id": "<user_id>", "last_message_id": "…",
   "message_count": 240, "total_message_sent": 241, "member_count": 12, "member_ids_preview": ["<user_id>", "…"],
   "rate_limit_per_user": 0, "flags": 0, "applied_tags": [],
   "thread_metadata": {"archived": false, "auto_archive_duration": 4320, "archive_timestamp": "…",
                       "create_timestamp": "…", "locked": false, "invitable": true}}
  ```
- **Archived threads and forum posts** **[VERIFIED]**:
  ```
  GET /api/v9/channels/{parent_id}/threads/search?archived=true&sort_by=last_message_time&sort_order=desc&limit=25&tag_setting=match_some&offset=0
  ```
  Response: `{threads[], members[], has_more, total_results, first_messages[]}`. `first_messages` is present for forums;
  for text channels the key was absent. `#help-center` reported `total_results: 1831`, `has_more: true`. Paginated
  via `offset` (+25). Thread objects here additionally have `bitrate, user_limit, rtc_region`, and `owner`
  (guild member object: `nick, roles, joined_at, avatar, banner, flags, pending, premium_since,
  communication_disabled_until, mute, deaf, collectibles, user{…}`).
- **Forum post:** `first_message.id == thread.id`, i.e. the initial starter message has the same ID as the thread **[VERIFIED]**.
  Post tags are in `applied_tags[]` (IDs from forum `available_tags`).
- `POST /api/v9/channels/{forum_id}/post-data` (read-only POST when opening a forum) **[VERIFIED]**: response is
  `{"threads": {"<thread_id>": {"first_message": {…}, "owner": {member…}}}}` (10 threads). Request body
  was not captured, presumably `{"thread_ids": [...]}` **[ASSUMPTION]**.
- Standard alternatives from documentation **[ASSUMPTION]**:
  `GET /channels/{id}/threads/archived/public?before={ISO}&limit=100`,
  `GET /channels/{id}/users/@me/threads/archived/private`, `GET /guilds/{id}/threads/active`.
  For user accounts it is uncertain whether they work.
- `threads/search` in `#course-general` returned 0 archived threads; active "Secret thread" was not included in it.
  Active threads must be retrieved from another source (gateway, search, or `archived=false` **[ASSUMPTION]**).

## 7. Pinned Messages

**[VERIFIED]**
```
GET /api/v9/channels/{channel_id}/messages/pins?limit=25
→ {"items": [{"pinned_at": "2026-09-01T12:03:29.017000+00:00", "message": { …full message object, "pinned": true… }}], "has_more": false}
```
- `#course-general` had 4 pins. `message` does not include `referenced_message`.
- Pagination when `has_more: true` is likely `before={pinned_at ISO}` **[ASSUMPTION, verify via prototype]**.
  A channel with more than 25 pins was not found under the strict rules (without search). The old endpoint
  `GET /channels/{id}/pins` (plain array) is likely legacy **[ASSUMPTION]**.

## 8. Search

**[VERIFIED]** URLs based on what the client sent:
```
GET /api/v9/guilds/{guild_id}/messages/search?content=credit&sort_by=timestamp&sort_order=desc&offset=0
GET /api/v9/guilds/{guild_id}/messages/search?has=file&min_id=1555338520166400000&channel_id=1282100102743330887&sort_by=timestamp&sort_order=desc&offset=0
… &offset=25   (page 2)
```
- UI mapping to parameters: `has:file` → `has=file`, `in:#channel` → `channel_id=`, `after:2026-10-01` →
  `min_id=` snowflake for **the end of the day in local time zone** (`2026-10-01T22:00:00Z` = midnight Oct 2 CEST, "strictly after").
  Additional parameters **[ASSUMPTION]**: `author_id`, `mentions`, `max_id` (before:), `pinned`, `has=image|video|link|embed|sticker|poll|sound`, `author_type`, `include_nsfw`.
- Response **[VERIFIED]**:
  ```json
  {"analytics_id": "…", "total_results": 7901, "doing_deep_historical_index": false,
   "messages": [[{ …message…, "hit": true }], …],
   "threads": [ …thread objects containing hits… ], "members": []}
  ```
  `messages` is an **array of arrays**, each array containing **1 message** (context messages are no longer returned). There are **25**
  results per page; `offset` increments by 25. "credit" returned 7,901 results across 317 pages.
- The `channel_id` filter also returned messages from **threads belonging to that channel** (from "Secret thread") **[VERIFIED]**.
- Search also returns messages from private channels to which the user has access (`#team-private-a`, `#team-private-b`) **[VERIFIED]**.
- Limits **[ASSUMPTION]**: max `offset` around 9,975 (≈400 pages); for an unindexed channel `202`
  with `retry_after` may be returned; search has stricter rate limits.
- **Is search a useful alternative for time ranges?** Yes, for targeted queries: `min_id`/`max_id` + `channel_id`
  + `has=file` (e.g. "all files in a channel over the last week"). **Not for a complete archive**: 25 items
  per request, offset ceiling, missing `referenced_message`, index can lag. For completeness,
  `GET /channels/{id}/messages` with `before`/`after` is preferable.

## 9. Names: Mentions, Roles, Channels, Nicknames

- `<@id>`: user object is directly in `mentions[]` of the same message (`username`, `global_name`) **[VERIFIED]**.
- `<@&id>`: in `content` is token `<@&{role_id}>` and the same ID is in `mention_roles[]` **[VERIFIED]**.
  Role name is in the server's roles (gateway). REST
  `GET /guilds/{id}/roles` **[ASSUMPTION]**.
- `<#id>`: from the channel list (Section 3). A hidden channel remains `___hidden___`.
- **Nicknames:** REST messages **do not contain `member`/`nick`** **[VERIFIED]**. The client obtains `nick` and color (`colorString`)
  from the member store populated via gateway. When changing channels, no REST request for members was sent **[VERIFIED]**.
  Member list arrives via gateway (op 14 lazy guild / op 8 request members) **[ASSUMPTION regarding opcodes]**.
  Member objects with `nick` and `roles` also arrive in `threads/search` and `post-data` (`owner`) **[VERIFIED]**.
  REST `GET /guilds/{id}/members/{user_id}` **[ASSUMPTION]**. Listing all members via REST is presumably
  unavailable for a user account **[ASSUMPTION]**.
- **Display fallback order:** server `nick` → `global_name` → `username`.

## 10. Headers

- **Request headers** on API XHR (names only) **[VERIFIED]**: `Authorization`, `X-Super-Properties`,
  `X-Discord-Locale`, `X-Discord-Timezone`, `X-Debug-Options`. On POST also `Content-Type`, on one POST also
  `X-Context-Properties`. API calls use **XMLHttpRequest**, not `fetch`.
- **Response headers** (union) **[VERIFIED]**: `alt-svc, cf-cache-status, cf-ray, content-encoding,
  content-security-policy(-report-only), content-type, date, nel, priority, report-to, reporting-endpoints,
  server, server-timing, strict-transport-security, vary, via, x-content-type-options, x-discord-features,
  access-control-allow-*`.
  **No `X-RateLimit-*` or `Retry-After`** appeared in ~17 responses from round 1 or ~25 from round 2
  (all `200`/`204`). The budget cannot be determined from the response alone. Round 2 also confirmed the same
  set of request headers.
- On `429`, a JSON body `{"message", "retry_after", "global"}` is expected (the string `retry_after` is also present in client code)
  **[ASSUMPTION regarding shape]**.

## 11. Snowflake and Time, Pagination

- `timestamp_ms = (id >> 22) + 1420070400000` **[VERIFIED]**:
  `1566570336659439696` → `2026-11-01T21:51:13.729Z`, exactly matching message `timestamp`.
  `1555338520166400000` (lower 22 bits 0) → `2026-10-01T22:00:00Z`. The client generates synthetic
  snowflakes for `min_id` in search; `before`/`after` by time can be constructed identically.
- `before=X`: messages older than X, descending. `after=X`: messages newer than X, **also descending** (for the next page,
  take **max** ID). `around=X`: neighbourhood of X including X **[VERIFIED]**.

## 12. Other Available Data (Briefly)

- **Channel topic** `topic`, `icon_emoji`, forum tags: in the channel object **[VERIFIED]**.
- **Server info** (description, `rules_channel_id`, `features`...): in the guild object **[VERIFIED]**.
- **Announcement channels** (type 5: `#course-info`, `#campus-news`...) are read identically to text channels **[VERIFIED]**.
  Published messages have `flags & 1`. For study purposes they are probably the most valuable and contain few messages (`#course-info`
  has a total of 6 messages since 2021).
- **Scheduled events**: client called `GET /guilds/{id}/scheduled-events/{event_id}/users/counts` **[VERIFIED]**.
  List of events: `GET /guilds/{id}/scheduled-events` **[ASSUMPTION]**.
- **Roles, emojis, stickers**: gateway. REST `GET /guilds/{id}/roles|emojis|stickers` **[ASSUMPTION]**.
- Noise that the CLI does not need: `POST /science`, `POST /metrics/v2` (telemetry), `GET /quests/get-decisions`,
  `GET /applications/public?application_ids=…`.
- **`POST /channels/{id}/messages/{msg_id}/ack`** = mark as read. The client calls it automatically when
  viewing a channel or thread **[VERIFIED]**. Response contains ack `token` (not auth token).

---

## 13. Consequences for the CLI Tool

1. **Messages, pins, threads, and search are purely REST** (`/api/v9`). Gateway is not needed for downloading content,
   only for "convenience" metadata (channel list, roles, nicknames, active threads).
2. **Channel list:** REST `GET /guilds/{id}/channels` **[VERIFIED, Section 15]**. Gateway is not needed.
   **REST also returns channels that the user cannot view, with their real names** (Section 15). Access must be computed
   from `permission_overwrites` and the user's roles, or verified by attempt (`403` = Missing Access).
   Channels with `name == "___hidden___"` or `flags & (1<<17)` (obfuscated in the client) are skipped.
3. **Archive pagination:** from newest `before=<oldest_id>&limit=100` until an empty array is returned.
   **Incremental sync:** store `last_seen_id` for each channel and fetch `after=<last_seen_id>&limit=100`;
   note that results are descending, so the next `after` = **max(id)**. Create time windows using synthetic snowflake
   `((unix_ms − 1420070400000) << 22)`.
4. **Download attachments immediately** upon receiving the message. A freshly fetched URL is valid for another **12–24 h** (`ex`).
   Check `ex` (hex Unix seconds) and on expiry refetch the message (`around=<id>&limit=1`)
   or use `refresh-urls` **[VERIFIED, Section 15]**. CDN does not require `Authorization`. Emoji URLs are not signed.
   `proxy_url` + `?width=…` is suitable for smaller thumbnails for AI.
5. **Threads and forums:** for each text, announcement, and forum channel, traverse
   `threads/search?archived=true&offset=…` until `has_more=false`, plus active threads via
   `threads/search?archived=false` **[VERIFIED, Section 15]**.
   Each thread is then fetched as a standalone channel via `/messages`. For forums, the initial post is in
   `first_messages[]` (`id == thread_id`) and tags are in `applied_tags`.
6. **Replies:** `referenced_message` is typically present in `/messages` (not in pins or search). If missing,
   `message_reference.message_id` remains and can be looked up in the local DB or via `around`.
7. **Names:** build user cache from `author` and `mentions[]`. Nicknames come only from gateway or member objects
   (`threads/search`, `post-data`). For AI summaries, `global_name || username` is usually sufficient.
   Translate `<@&id>` and `<#id>` using the roles and channel lists.
8. **Rate limits:** headers are absent, hence **conservative throttling** (e.g. 1 request / ~1 s, search
   even slower) and handling `429` using `retry_after` from the JSON body. Search is expensive and limited; use it only for targeted queries.
9. **Do not call `ack`** or any POST endpoints other than read-only endpoints. GET on `/messages` does not mark anything as
   read on its own **[ASSUMPTION, ack is a separate request]**.
10. **Headers:** the client sends `X-Super-Properties`, `X-Discord-Locale`, `X-Discord-Timezone`,
    `X-Debug-Options`. Their absence is an easily identifiable sign of an unofficial client (ToS risk is on the user).
11. **Data model for AI:** from a message, the necessary fields are `id, channel_id, timestamp, edited_timestamp, author.username/global_name,
    content, attachments[{filename, content_type, size, url}], embeds[{type, url, title, description}],
    message_reference.message_id, type`. Filter out system types (≠ 0, 19) in most cases.

## 14. Unverified and Open Questions

**Verified via prototype 2026-11-03** (results in Section 15):
- REST `GET /users/@me/guilds` and `GET /guilds/{id}/channels` work with a user token.
- Maximum `limit` for `/messages` is 100.
- Response shape of `POST /attachments/refresh-urls`.
- Active threads via REST: `threads/search?archived=false` works; `guilds/{id}/threads/active` is for bots only.

**Still open:**
- Response shape of `429`. Did not occur across 13 requests with a 1 s pause. Rate-limit headers remain absent in normal responses.
- Pinned message pagination when `has_more: true` (`#course-general` has only 4 pins).
- ~~Whether REST returns channels without `VIEW_CHANNEL` permission~~. **Yes, it returns them with their real names**
  (added 2026-11-03, Section 15). How to determine a member's roles and compute access for a user token remains open.
- Forum `#help-center` reported `total_results` 15 during `threads/search?archived=false`, but returned 13 threads.
- `refresh-urls` on an already expired URL. The tested URL was still valid and returned unchanged.
- Shape of gateway `READY`. No longer needed for the CLI; REST suffices.

**Unverified due to absence in data** (~410 messages from 9 channels + 1 forum post):
- Raw shape of `sticker_items`, `message_snapshots` (forwards), `poll`, system messages (types ≠ 0/19),
  `components` with content, `webhook_id`, animated emoji in text (`<a:name:id>`), attachments with `description`, and
  voice messages (`waveform`).

**Other:**
- Search: additional parameters (`author_id`, `max_id`, `mentions`), max `offset`, behavior on unindexed channels (202).
  (Search was not used in round 2 under the rules.)
- Request body of `POST /channels/{forum_id}/post-data`.
- CDN request headers were not directly observed. The conclusion "without Authorization" is based on these being `<img>`/`<video>` resource loads.
- Meaning of `flags` bits: channel `1<<17` (obfuscated), `128` (resource), attachment `32` (animated). For messages,
  values 1/4/32 are verified; their names come from documentation.
- `#advisor-questions` has `last_message_id` from 2024-09-26 (the client acknowledged this ID), but REST returned a message
  from 2023-01-05 as newest. The newest message is thus likely deleted or inaccessible. The CLI should therefore not
  assume a channel's `last_message_id` corresponds to an existing message.

## 15. Prototype Verification (2026-11-03)

**Source:** `prototype/probe.py`, executed by the user. It consisted of 13 API requests with a 1 s pause and 1 CDN GET.
Report `prototype/out/probe-20261103-134510.json` is local and gitignored. Everything in this section is **[VERIFIED]** (prototype).

| Question | Result |
|---|---|
| `GET /users/@me/guilds` with a user token | `200`, 8 servers, fields `id, name, icon, banner, owner, permissions, features`. `?with_counts=true` adds `approximate_member_count` |
| `GET /guilds/{id}/channels` | `200`, 412 channels. Breakdown below |
| Max `limit` for `/messages` | `limit=100` returns 100 messages. `limit=101` returns `400`, `code 50035 Invalid Form Body` |
| `before` | 100 older messages, ordered from newest to oldest |
| `after` | returns **closest** messages after anchor (oldest among newer), but ordered **from newest to oldest**. Next page starts from `max(id)` |
| `member` in messages | absent in 0 out of 100 messages |
| Replies | 29 out of 100 messages are type 19, all had `referenced_message` |
| Pins | `limit=25` returns 4 items, `has_more: false` |
| Active threads | Two endpoints, breakdown below |
| CDN without token | `200`, `image/png`, file could be read without `Authorization` |
| URL validity | `ex − is` = 24 h. URL from freshly fetched message was valid for another 21.1 h |
| `POST /attachments/refresh-urls` | `200`, `{"refreshed_urls": [{"original", "refreshed"}]}`. For an already valid URL returned the same URL |
| Rate-limit headers | no `X-RateLimit-*` or `Retry-After` in 13 responses. Responses set `set-cookie` (cookie names were not recorded) |

**Channels from `GET /guilds/{id}/channels`:**
- **Counts by type:** 358 text, 22 categories, 12 announcement, 10 voice, 9 forum, 1 stage. Identical to visible
  channels in the client.
- **Hidden channels:** no `___hidden___` or flag `1<<17`. **REST does not hide them, returning them with their real names.**
  - Verified by `discoop channels` test (2026-11-03): the list contains whole categories that the user cannot see in Discord
    (`moderation`, `logging`, `fillers`), as well as channel `#prep-courses` (`1549737445002584094`).
  - That same channel was displayed by the client as `___hidden___` (Section 3).
  - Obfuscation is therefore performed by the client (or gateway), not REST.
  - The REST list thus contains all 390 channels of the server and access to them must be computed from
    `permission_overwrites` and the user's roles.
- **New fields** compared to the client: `template`, `voice_background_display`, `voice_hangout`, `default_forum_layout`.
- **Forum `#help-center`:** `1040350879783604234`.

**Active threads:**
- `GET /guilds/{id}/threads/active` returns `403`, `code 20002 "Only bots can use this endpoint."`.
- `GET /channels/{id}/threads/search?archived=false` works:
  - forum `#help-center`: `total_results` 15, returned 13,
  - `#course-general`: 1 active thread,
  - for forums, response also includes `first_messages`.

---

## Side Effects of the Analysis

### Round 1
- **Accidentally sent message** (see incident above): text `cdn.discordapp.com` in thread
  `Question about automatic course credit` (forum `#help-center`, thread `1566814241946738698`),
  2026-11-03 00:07. **The user deleted it.** The thread remained followed (in round 2 it was in the sidebar under
  `#help-center`). Root cause: after closing the search panel, the cursor and click landed in the thread composer and
  `Enter` sent the message.
- **Marked as read** (ack requests): `#course-deadlines`, forum `#help-center`, thread
  `Question about automatic course credit`. `#course-general` was also inspected (already opened by the user).
- **Discord search history** contains new queries: `credit`, `has:file after:2026-10-01 in:course-general`,
  `cdn.discordapp.com attachments`, `cdn.discordapp.com`.
- In my tab a passive XHR/fetch observer ran (in that tab's memory only).
- When calling `tabs_close_mcp` on my tab, the tool returned "The browser is shutting down" and Chrome disconnected.

### Rounds 2 and 3 (Strict Rules: No Keyboard, No Search)
- **Inspected channels** (clicks only on names in sidebar): `#course-info`, `#vote-room`, `#campus-news`, `#quotes`,
  `#advisor-questions`, `#english-general`, `#course-general` (scroll ~200 messages back) and `#general`
  (scroll ~110 messages back).
- **Ack (marked as read)** captured for `#course-info`, `#quotes` (had "NEW" badge, i.e. was
  unread), and `#advisor-questions`. For `#vote-room` and `#campus-news` no ack record exists because part of the
  network log was cleared. If they were unread, they are now marked as read. **`#general` was unread (bold) prior to opening**
  and is now almost certainly marked as read. `#english-general` and `#course-general`
  were already read.
- In `#course-general` I opened and closed the Threads panel once using the header button.
- I adjusted the sidebar several times via `scrollTop` in JS and once via a scroll action over the sidebar. This affects only
  rendering, not data.
- In my tabs a passive XHR observer was running (response bodies only; in round 2 also request header names, never values).
- Round 2: `tabs_close_mcp` again returned "The browser is shutting down" and Chrome disconnected.
- Round 3: tab (`#general`) **remained open** as instructed. The user will close it.
- No keyboard input, no clicks in message list, on reactions, composer, Follow, or Join.
  No POST requests except automated `ack`, `science`, and `metrics`.
