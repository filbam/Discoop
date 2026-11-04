# Channel access: how to determine via REST which channels the user can see

Date: 2026-11-03. Type: documentation and library source code research. **No Discord API calls**,
no browser with Discord.

**Legend:** **[VERIFIED]** = observed on the user's account (prototype, `discoop channels` test, analysis
[discord-analysis.md](discord-analysis.md)) or directly in the code of this repository.
**[ASSUMPTION]** = from documentation or third-party code, not yet verified on the user's account. The source is indicated
in parentheses and in the [Sources](#sources) section.

**Methodology:**
- Official documentation: `github.com/discord/discord-api-docs` (`main` state as of 2026-11-03), pages
  `docs.discord.com/developers/...`.
- Unofficial user API documentation: docs.discord.food (Discord Userdoccers), read from the repository
  `discord-userdoccers/discord-userdoccers`. For key points, I searched via `git log -S` when they were added.
- Additional evidence: `discord.py-self` (permission calculation, HTTP routes) and `DiscordChatExporter` (how it handles
  inaccessible channels).
- From the anonymised report `prototype/out/probe-20261103-134510.json`, I only read field lists.

---

## 1. Summary

| # | Question | Short answer |
|---|---|---|
| 1 | Logged-in user roles | `GET /users/@me/guilds/{guild_id}/member` (recommended), backup `GET /guilds/{guild_id}/members/{user_id}`. Both **[ASSUMPTION]** |
| 2 | `permissions` field in `/users/@me/guilds` | Server-level permissions (@everyone + all roles), **without** overwrites and implicit rules. The owner must be handled via `owner`, admin via the `ADMINISTRATOR` bit. `/guilds/{id}/roles` is not needed **[ASSUMPTION]** |
| 3 | Algorithm | base → owner/ADMINISTRATOR → @everyone overwrite → united role overwrites → member overwrite → implicit rules. Categories are not inherited in the API, threads inherit from their parent **[ASSUMPTION]** |
| 4 | `___hidden___` and `is_hidden` | Obfuscation of channels without `VIEW_CHANNEL`, performed **only by the gateway**. REST never sets the `1<<17` flag, so `is_hidden` does not filter anything in the REST path. Unrelated to opt-in channels |
| 5 | `/messages` without access | Without `VIEW_CHANNEL`: `403` **[VERIFIED]** (section 7), code `50001` Missing Access **[ASSUMPTION]**. With `VIEW_CHANNEL`, but without `READ_MESSAGE_HISTORY`: `200` and an empty array **[ASSUMPTION]** |

**Two new findings change the recommendation:**
1. **`GET /guilds/{id}/channels?permissions=true`** according to Userdoccers returns a `permissions` field for every channel.
   These are the logged-in user's permissions in the channel **including overwrites**, calculated by the server. If this holds,
   neither roles nor calculation are needed and not a single request is added **[ASSUMPTION]**.
2. **Discord announced that REST will stop returning channels without `VIEW_CHANNEL`** (changelog 2026-08-12). For bots,
   this is mandatory starting **2026-11-16**, for users "soon" without a date **[ASSUMPTION]**. The issue from the test may
   therefore resolve itself over time. Permission calculation is still needed afterwards: `READ_MESSAGE_HISTORY` and `CONNECT`
   are not filtered by REST.

## 2. Baseline

- `GET /guilds/{id}/channels` with a user token returns channels that the user cannot see as well, with their real name
  (e.g. categories `moderation`, `logging`, `fillers` and channel `1549737445002584094`) **[VERIFIED]**
  ([discord-analysis.md, section 15](discord-analysis.md#15-prototype-verification-2026-11-03)).
- Channels from REST have `permission_overwrites` and `flags` fields. The `permissions` field is not present in them
  because the prototype did not send `?permissions=true` **[VERIFIED]** (field list in the probe report).
- An overwrite has the shape `{id, type, allow, deny}`. `type 0` is a role, `type 1` is a member, `allow`/`deny` are bitfield
  strings. @everyone has `id = guild_id` **[VERIFIED]** (analysis, section 3).
- `GET /users/@me/guilds` returns fields `id, name, icon, banner, owner, permissions, features` **[VERIFIED]**.
  The tool does not store `owner` or `permissions` today **[VERIFIED]** (`server_from_api` in `models.py`).
- An error body has the shape `{"message", "code"}`. Example: `guilds/{id}/threads/active` returned `403`
  with code `20002` **[VERIFIED]**.
- `#2bit-deadlines` has @everyone `deny` with the `VIEW_CHANNEL` bit and roles with `allow 1024` **[VERIFIED]**. It is a typical
  private channel pattern on VUT FIT.

**Bits needed by the tool** (permissions topic, **[ASSUMPTION]**, values are stable):

| Bit | Value | Name |
|---|---|---|
| `1 << 3` | 8 | `ADMINISTRATOR` |
| `1 << 10` | 1024 | `VIEW_CHANNEL` |
| `1 << 11` | 2048 | `SEND_MESSAGES` |
| `1 << 16` | 65536 | `READ_MESSAGE_HISTORY` |
| `1 << 20` | 1048576 | `CONNECT` |
| `1 << 34` | 17179869184 | `MANAGE_THREADS` |

Bitfields are strings in API v9 and can exceed 32 bits. In Python, `int(...)` is sufficient; in SQLite they must be
stored as `TEXT` **[ASSUMPTION]** (official permissions topic).

## 3. Question 1: logged-in user roles

| Endpoint | User token | Requirements | What it returns | Note |
|---|---|---|---|---|
| `GET /users/@me/guilds/{guild_id}/member` | yes **[ASSUMPTION]** (Userdoccers: route for user and OAuth2, without bot badge) | be a guild member. The `guilds.members.read` scope only applies to OAuth2 applications; user tokens have no scopes | **private** guild member object: `user`, `nick`, `roles[]`, `joined_at`, `pending`, `communication_disabled_until`, `flags` and additionally `permissions` (total permissions in the guild) | a single request provides both roles and base permissions from the same point in time. Bots do not have this endpoint |
| `GET /guilds/{guild_id}/members/{user_id}` | yes **[ASSUMPTION]** (Userdoccers, `discord.py-self` `fetch_member`, `DiscordChatExporter` `TryGetGuildMemberAsync`) | be a member, know own user ID (`GET /users/@me` or stored after `login`) | public member object: `roles[]`, `pending`, `communication_disabled_until`, `flags`. **Without** `permissions` | backup |
| `GET /guilds/{guild_id}/channels?permissions=true` | yes **[ASSUMPTION]** (Userdoccers since 2024-06-02) | be a member (otherwise `permissions` is not returned) | channels + `permissions` for the caller in each channel, including overwrites | **roles are not needed at all**. It is the same request as today |
| `GET /guilds/{guild_id}/permissions/member/{user_id}` | unknown, endpoint is new (changelog 2026-10-30) | not stated | `{permissions}` only at the guild level | does not provide roles, insufficient for overwrites |
| `GET /channels/{id}/permissions/member/{user_id}` | unknown (2026-10-30) | requires `VIEW_CHANNEL`, for voice channels also `CONNECT` | `{permissions}` in the channel, by default with implicit masking (`implicit=false` disables it) | 1 request per channel (~390) and `403` on inaccessible channels. Unsuitable |
| `GET /users/{user_id}/profile?guild_id=…` | yes **[ASSUMPTION]** (Userdoccers) | – | profile + private `guild_member` | heavy request for a different purpose, do not use |
| `GET /guilds/{guild_id}/members` | **no** for user accounts **[ASSUMPTION]** (Userdoccers) | – | – | unusable |

**Rate limits** **[ASSUMPTION]**:
- Discord does not publish individual route limits; they are dynamic by bucket. The global limit is 50 requests per second
  (Userdoccers, rate limits).
- For a user token, rate-limit headers are only sent on `429` (Userdoccers). The prototype did not observe them in regular responses
  **[VERIFIED]**.
- **Invalid requests** (`401`, `403`, `429`) have their own limit: 10,000 per 10 minutes, otherwise an IP ban for 24 h
  (Userdoccers, rate limits). This is another reason **not to probe access by testing every channel**.
- The tool issues 1 request per second sequentially. With one additional request per guild, hitting the limit is not a concern.

**Recommendation:**
- **Primary:** `GET /users/@me/guilds/{guild_id}/member`. Provides both roles and `permissions` at once and does not require the user ID.
- **Backup:** `GET /guilds/{guild_id}/members/{user_id}`. Base permissions must then be taken from `/users/@me/guilds`.
- **Even better**, if confirmed: `?permissions=true` on the existing channel list. Roles are then only needed
  as a fallback (section 9.1).

## 4. Question 2: the `permissions` field in `GET /users/@me/guilds`

- **Content:** total user permissions in the guild, i.e. @everyone OR all of their roles. **Does not contain channel overwrites**
  or implicit rules **[ASSUMPTION]** (official Guild object, footnote to `owner`/`permissions`;
  Userdoccers, User Guild Object).
- **Owner:** the response contains a separate `owner` field. The official example shows `owner: true` with incomplete
  `permissions` (`"36953089"`). Therefore, do not rely on `permissions` for an owner, and treat `owner == true` as having
  all permissions **[ASSUMPTION]**.
- **Admin:** if any role has `ADMINISTRATOR`, bit 8 is present in `permissions`. Whether the server populates the other bits is
  undocumented. It is sufficient to check bit 8 and then ignore overwrites **[ASSUMPTION]**.
- **Timeout** is not mentioned by the documentation for this field. For reading, this does not matter; timeout does not strip
  `VIEW_CHANNEL` or `READ_MESSAGE_HISTORY` (section 5).
- **`GET /guilds/{id}/roles` is not needed.** Role permissions are already combined in `permissions`. For overwrites, member role
  **IDs** are sufficient. Guild roles will only be needed for `messages` to resolve `<@&id>` to names, or as an emergency base
  permission calculation (`@everyone.permissions | member_role_permissions`) should `permissions` be missing.
- **Timing caveat:** `permissions` from `/users/@me/guilds` and roles from the member endpoint come from two requests
  at different times. The private member object has its own `permissions`, making it a preferable source (section 3).

## 5. Question 3: channel permission calculation algorithm

Order according to the official permissions topic (Permission Overwrites section) and `discord.py-self`
(`GuildChannel.permissions_for`) **[ASSUMPTION]**:

```python
VIEW_CHANNEL, READ_MESSAGE_HISTORY, CONNECT, ADMINISTRATOR = 1 << 10, 1 << 16, 1 << 20, 1 << 3
ALL = (1 << 64) - 1  # current bits are below 1 << 64; owner and admin have everything


def base_permissions(owner: bool, guild_permissions: int) -> int:
    if owner or guild_permissions & ADMINISTRATOR:
        return ALL
    return guild_permissions                      # @everyone | roles (already combined from API)


def channel_permissions(base: int, overwrites: list[dict], guild_id: str,
                        role_ids: set[str], user_id: str) -> int:
    if base == ALL:                               # ADMINISTRATOR bypasses all overwrites
        return ALL
    by_key = {(int(o["type"]), o["id"]): o for o in overwrites}
    perms = base
    if everyone := by_key.get((0, guild_id)):     # 1. @everyone overwrite
        perms = (perms & ~int(everyone["deny"])) | int(everyone["allow"])
    allow = deny = 0                              # 2. roles: unite first, then apply at once
    for role_id in role_ids - {guild_id}:
        if o := by_key.get((0, role_id)):
            allow |= int(o["allow"])
            deny |= int(o["deny"])
    perms = (perms & ~deny) | allow               # allow of any role overrides deny of another role
    if member := by_key.get((1, user_id)):        # 3. overwrite for the member themself
        perms = (perms & ~int(member["deny"])) | int(member["allow"])
    return perms
```

Notes on calculation:
- Role order in the hierarchy **does not matter**. The allow of one role overrides the deny of another role in the same channel
  **[ASSUMPTION]** (permissions topic, Permission Hierarchy).
- `member.roles` does not contain @everyone. The @everyone overwrite is applied separately and must not be
  repeated in the role loop **[ASSUMPTION]**. The official pseudocode has a bug: `overwrites` is used before assignment.
  `discord.py-self` does the same in the correct order.

**Resulting access** for CLI:

```python
def access(perms: int | None, channel_type: int, flags: int) -> str:
    if perms is None:
        return "unknown"
    if flags & (1 << 17) or not perms & VIEW_CHANNEL:
        return "none"                             # cannot see channel, other bits are irrelevant
    if channel_type in (2, 13) and not perms & CONNECT:
        return "view"                             # visible in sidebar, cannot read text in voice channel
    if not perms & READ_MESSAGE_HISTORY:
        return "view"                             # visible, but /messages returns empty array
    return "read"
```

**Special cases:**

| Case | Rule | Source |
|---|---|---|
| Guild owner | all permissions, overwrites are ignored | official pseudocode `compute_base_permissions` **[ASSUMPTION]** |
| `ADMINISTRATOR` | all permissions, bypasses overwrites | permissions topic, bit table **[ASSUMPTION]** |
| Without `VIEW_CHANNEL` | implicitly no further permissions in channel | Implicit Permissions; `discord.py-self` `_apply_implicit_permissions` **[ASSUMPTION]** |
| Without `READ_MESSAGE_HISTORY` | `GET /messages` returns no messages | official Get Channel Messages, Userdoccers List Messages **[ASSUMPTION]** |
| Voice and stage channel (type 2, 13) | reading messages additionally requires `CONNECT`. Without `CONNECT`, voice permissions and channel management are implicitly stripped | Get Channel Messages; `discord.py-self` `VoiceChannel.permissions_for` **[ASSUMPTION]** |
| Connected in voice | channel is "visible" even without `VIEW_CHANNEL` if the user is connected in it | Obfuscated Channels **[ASSUMPTION]**. Irrelevant for the CLI, it does not connect anywhere |
| **Categories** | **nothing is inherited in the API.** Every channel has its own `permission_overwrites`. A "synced" channel only has a copy of the category's overwrites. A category is "visible" if at least one of its channels is visible | Permission Syncing; Obfuscated Channels **[ASSUMPTION]**. Channel's own overwrites **[VERIFIED]** (`#2bit-deadlines`) |
| Public threads (type 10, 11) | inherit permissions from parent channel. Exception: writing requires `SEND_MESSAGES_IN_THREADS` instead of `SEND_MESSAGES`. `VIEW_CHANNEL` on parent is always required, even if the user is mentioned or added to the thread | Inherited Permissions (Threads); `discord.py-self` `Thread.permissions_for` **[ASSUMPTION]** |
| Private threads (type 12) | additionally requires being a member of the thread or having `MANAGE_THREADS` | Userdoccers Threads **[ASSUMPTION]** |
| Forum and media (type 15, 16) | the forum itself has no messages. Posts are public threads and inherit forum permissions (`VIEW_CHANNEL` + `READ_MESSAGE_HISTORY` on the forum) | from thread rules **[ASSUMPTION]** |
| `threads/search`, archives | returns only threads the user has access to. Public archived threads require `READ_MESSAGE_HISTORY`, private archived also `MANAGE_THREADS` | Userdoccers Threads; official Channel resource **[ASSUMPTION]** |
| Timeout (`communication_disabled_until` in the future) | only `VIEW_CHANNEL` and `READ_MESSAGE_HISTORY` remain. Owner and admin are exempt. Mask is applied **at the very end** of calculation | permissions topic; `discord.py-self` `_timeout_mask` **[ASSUMPTION]**. **No effect on reading** |
| AutoMod quarantine (member `flags` `1<<7`, `1<<10`) | like timeout, additionally retains `CHANGE_NICKNAME` | Userdoccers permissions **[ASSUMPTION]**. No effect on reading |
| Membership screening (`pending: true`) | until member passes screening, they cannot send messages. Reading follows permissions. With "preview" disabled, `pending` is always `false` | official Add Guild Member; Userdoccers Guild Member **[ASSUMPTION]**. No effect on reading calculation, a notice is sufficient |
| Obfuscated channel (flag `1<<17`) | means the user does not have `VIEW_CHANNEL` | official Channel resource **[ASSUMPTION]**. Does not occur in REST (section 6) |

## 6. Question 4: `___hidden___`, the `1<<17` flag, `is_hidden`, and opt-in channels

**What `___hidden___` is:**
- It is **channel obfuscation**: a channel for which the user lacks `VIEW_CHANNEL` arrives over the **gateway**
  with the name `___hidden___` (as well as topic), the `CHANNEL_OBFUSCATED` flag (`1 << 17`), and a single overwrite
  "@everyone deny `VIEW_CHANNEL`". Other sensitive fields are zeroed out **[ASSUMPTION]** (official Channel resource,
  Obfuscated Channels; Userdoccers flag `OBFUSCATED` since 2024-12-15).
- Exactly such a record was present in the web client state **[VERIFIED]** (analysis, section 3).
  It also had `parent_id: null`. The official documentation for bots promises that `id`, `type`, `position`, and `parent_id`
  remain preserved. However, the user's client lost `parent_id` **[VERIFIED]** (difference compared to documentation).
- According to documentation, **the HTTP API will never set the `1<<17` flag**. Instead, inaccessible channels will be
  omitted from `GET /guilds/{id}/channels` **[ASSUMPTION]**. For users, this does not hold yet: REST returns them
  with their real name and without the flag **[VERIFIED]**.
- Detection should rely on the flag. According to documentation, `name` should not be relied upon **[ASSUMPTION]**.

**The `is_hidden` check in `src/discoop/models.py`** (`name == "___hidden___"` or `flags & (1 << 17)`) **[VERIFIED, code]**:
- Checks **gateway obfuscation**, which REST does not send. In the REST path, it therefore never filters anything.
  The prototype found 0 such channels **[VERIFIED]**.
- It is not harmful, but it is **misleading**: it looks like hiding inaccessible channels, but does not do so.
  The test `tests/test_servers_channels.py` has a fixture `___hidden___` of a kind that REST does not send.
- Furthermore, checking the name goes against documentation recommendations. A channel can legally be named `___hidden___`.
- **Proposal:** replace `is_hidden` with access calculation (section 9). Retain flag `1<<17` solely as a defensive
  "`access = none`" condition, drop the name check.

**Opt-in channels (Browse Channels, Channels & Roles, onboarding) are unrelated:**
- Opt-in is a **user display preference**, not access. It resides in user guild settings: server flag
  `OPT_IN_CHANNELS_ON` (`1 << 14`) and on the channel `channel_overrides[].flags & OPT_IN_ENABLED` (`1 << 12`,
  "channel is shown in UI") **[ASSUMPTION]** (Userdoccers, User Settings).
- A channel the user has not opted into still has `VIEW_CHANNEL`. The gateway does not obfuscate it, and REST returns
  it normally. The CLI should list it as accessible.
- Onboarding can **add roles** (`role_ids`) upon selecting an answer. That is real access, and role calculation captures it.
  `default_channel_ids` and `channel_ids` in onboarding signify only opt-in display **[ASSUMPTION]**
  (Userdoccers, Onboarding).
- User guild settings arrive via gateway (`READY`). Userdoccers lists no REST endpoint for reading them, only `PATCH`
  **[ASSUMPTION]**. The CLI does not need them.
- **Related case:** `readme-local`/`readme-en` have `flags: 128` **[VERIFIED]**. It is `IS_GUILD_RESOURCE_CHANNEL`
  (`1 << 7`): a resource channel from onboarding / Server Guide that is not displayed in the channel list
  **[ASSUMPTION]** (Userdoccers, Channel Flags). If the user has `VIEW_CHANNEL`, it is readable. The CLI may
  list it, optionally marked as `resource`.
- The data point "renderLevel 1 = not displayed: 74 records" from the analysis (section 3) probably mixes obfuscated channels,
  resource channels, and non-opted-in channels. Without the gateway, these cannot be distinguished, and the CLI does not need to **[ASSUMPTION]**.

## 7. Question 5: what `GET /channels/{id}/messages` returns without access

Officially: the endpoint requires `VIEW_CHANNEL`, for voice channels also `CONNECT`. Without `READ_MESSAGE_HISTORY`, it returns
an empty result **[ASSUMPTION]** (Get Channel Messages; Userdoccers List Messages).

| Situation | Expected response | Certainty |
|---|---|---|
| Server member, channel without `VIEW_CHANNEL` | `403`, `{"message": "Missing Access", "code": 50001}` | `403` **[VERIFIED]** 2026-11-03: `discoop messages` on channel `1549737445002584094` (client showed it as `___hidden___`) ended in `NO_ACCESS`, exit `5`. That occurs only on `403` with code `50001` or `50013`; which one it was is not shown in the output. Code `50001` remains **[ASSUMPTION]** (official error table; reports from `discord.js-selfbot-v13` and `discord-server-copy`) |
| Voice/stage channel without `CONNECT` | `403`, probably `50001` | **[ASSUMPTION]** |
| `VIEW_CHANNEL` without `READ_MESSAGE_HISTORY` | `200` and `[]` | **[ASSUMPTION]**. Indistinguishable from an empty channel; only permission calculation can distinguish it |
| Private thread the user is not in (and lacks `MANAGE_THREADS`) | `403`, `50001` | **[ASSUMPTION]** |
| Channel in a guild the user is not in | `403`, `50001` | **[ASSUMPTION]** |
| Non-existent or deleted channel, invalid ID | `404`, `10003` Unknown Channel | **[ASSUMPTION]** |
| Action requiring permission (e.g. posting) | `403`, `50013` "You lack permissions…" | **[ASSUMPTION]**. Not expected on GET messages, but should be mapped identically to `50001` |
| Block by anti-abuse system | `403` with code `10008` "Unknown Message", or another nonsensical code | **[ASSUMPTION]** (Userdoccers, Errors) |
| Cloudflare block | code `40333` | **[ASSUMPTION]** (Userdoccers, Errors) |

`DiscordChatExporter` does not calculate permissions in advance. It tries every channel, records `403` as a channel error ("forbidden"),
and continues. The entire export fails only when all channels fail **[ASSUMPTION]** (`ExportCommandBase.cs`,
`DiscordClient.cs`). For `discoop`, it is better to skip inaccessible channels in advance (section 3, invalid request limit).

**Mapping for future `messages`:**
- `403` + `50001` or `50013` → channel is skipped with a warning. When a single channel was specified, exit `5` (`NO_ACCESS`).
  `access = none` is cached.
- `404` + `10003` → exit `4` (`NOT_FOUND`) and advice `discoop channels --refresh`.
- `403` with other code (`10008`, `40333`, …) → exit `1` with a differentiated message. It is not "no access".
- `200 []` on a channel with `access = view` → warning "no READ_MESSAGE_HISTORY", exit `0`.

## 8. Planned change on Discord's side

- **Changelog 2026-08-12, "Channel Obfuscation for Users and Bots"** **[ASSUMPTION]**:
  - Users will soon stop receiving full data on channels they cannot see. The gateway will obfuscate them
    and `GET /guilds/{id}/channels` will omit them.
  - For bots, this is mandatory starting **2026-11-16**. No date is given for users.
  - Gateway obfuscation for the user is already active **[VERIFIED]** (`___hidden___` in the client). REST for the user
    does not filter yet as of 2026-11-03 **[VERIFIED]**.
- **Changelog 2026-10-30:** four new endpoints for computed permissions (section 3). Whether they work with a user token
  is unknown **[ASSUMPTION]**.
- **Consequences for `discoop`:**
  - After the REST change, inaccessible channels will disappear from the response and `--include-hidden` will not show anything extra.
    This must be accounted for in help text and tests.
  - A category with at least one visible channel will remain in the response even if the category itself lacks `VIEW_CHANNEL`. The display
    rule "a category is shown if it has a displayed channel" is therefore correct in both regimes.
  - `READ_MESSAGE_HISTORY` and `CONNECT` will not be filtered by REST. Permission calculation is needed even afterwards.

## 9. Implementation recommendations

### 9.1 Requests

Order when refreshing guild channels (`Directory._fetch_channels`):

1. `GET /guilds/{id}/channels?permissions=true` instead of today's request.
   If all channels (except categories) have a `permissions` field, it is used (source `server`).
   **0 requests added.**
2. **Fallback**, if `permissions` is missing: `GET /users/@me/guilds/{id}/member` → `roles`, `user.id`,
   and `permissions`. If `permissions` is not in the response, base is taken from `owner`/`permissions` from `/users/@me/guilds`
   (cache `servers`, refresh on missing value). Calculation according to section 5 (source `computed`).
   **1 request per guild added.**
3. **Backup**, if member endpoint returns `403`/`404`: `GET /guilds/{id}/members/{user_id}`. User ID is from
   `/users/@me`, ideally stored already during `login` or in cache. **1 to 2 requests added.**
4. If that fails as well: `permissions = NULL` → access `unknown` (section 9.5).

`GET /guilds/{id}/roles` is not needed. It will only be added with `messages` for role names.

### 9.2 Cache (`src/discoop/cache.py`)

`SCHEMA_VERSION` bumped by 1 (as of 2026-11-03 it is `1`, so to `2`, unless bumped by work on `messages` in the meantime).
`_migrate` drops and rebuilds the cache **[VERIFIED, code]**, so the migration is safe. The new `Cache.channel()` method
from work on `messages` will need the same new columns.

| Table | New column | Type | Purpose |
|---|---|---|---|
| `servers` | `owner` | `INTEGER NOT NULL DEFAULT 0` | from `/users/@me/guilds`, for fallback |
| `servers` | `permissions` | `TEXT` | base permissions in guild from `/users/@me/guilds`, for fallback |
| `channels` | `flags` | `INTEGER NOT NULL DEFAULT 0` | `1<<17` (defensively), `1<<7` (resource channel) |
| `channels` | `permissions` | `TEXT` (NULL = unknown) | effective permissions of the logged-in user in the channel |
| `channels` | `overwrites` | `TEXT` (JSON), optional | recalculation without a new request, debugging |

- Access (`read`/`view`/`none`/`unknown`) is **not stored**. It is calculated in Python from `permissions`, `type`, and `flags`.
- Roles do not need to be stored. They are evaluated during channel refresh and the result is in `channels.permissions`.
- Bitfields as `TEXT`, because SQLite `INTEGER` is signed 64-bit.
- Role changes on the guild take effect only after `--refresh`. The existing cache-age warning covers this.

### 9.3 New module `src/discoop/permissions.py`

Pure functions without I/O, easily testable on anonymised fixtures:
- bit constants (`VIEW_CHANNEL`, `READ_MESSAGE_HISTORY`, `CONNECT`, `ADMINISTRATOR`, `MANAGE_THREADS`, `ALL`),
- `parse_bits(value: str | int | None) -> int | None`,
- `base_permissions(owner, guild_permissions) -> int`,
- `channel_permissions(base, overwrites, guild_id, role_ids, user_id) -> int`,
- optionally `apply_timeout(perms, timed_out_until, now)`, with mask at the end and exemption for owner/admin,
- `access(perms, channel_type, flags) -> Access` (`StrEnum`: `read`, `view`, `none`, `unknown`).

Other changes:
- `models.Channel` gets `permissions: int | None` and `flags: int` and an `access` property. `models.Server` gets
  `owner` and `permissions`.
- `is_hidden` disappears (section 6).

**Tests:**
- @everyone deny `VIEW` + allow for a role the member has / does not have,
- allow of one role overrides deny of another role,
- member overwrite overrides role,
- owner, admin,
- voice channel without `CONNECT`,
- channel without `READ_MESSAGE_HISTORY`,
- flag `1<<17`,
- missing `permissions` → `unknown`.

### 9.4 Behaviour of `channels`

- **By default**, channels with access `read`, `view`, and `unknown` are listed. Channels with `none` are hidden.
- **Categories** follow their content: a category with at least one displayed channel is displayed. The category's own permissions
  are not evaluated. This matches Discord's rule (section 8) as well as the current `group_by_category`, which
  drops empty groups.
- **`--include-hidden`** also shows `none`. In human mode they are dimmed with a `[no access]` label; for entirely
  hidden categories, the category is marked as well.
- **`view`** (visible, but cannot read history, or voice channel without `CONNECT`) is displayed with a
  `(no history)` tag.
- **Agent mode:** adds an `access` column at the end: `id type category name access`. Values are
  `read|view|none|unknown`. The format change must be recorded in the design (4.3) and in `agent-guide`.
- **Summary** (stderr): `N channels (M without access hidden, use --include-hidden)`.
- **Name lookup:**
  - Exact ID or name will find even a `none` channel. `messages` will then terminate with code `5` without an API call,
    which is better advice than "not found".
  - Globs (`-c "isc-*"`) and `--all-channels` include only `read` channels.

### 9.5 When access cannot be determined

- All channels have `access = unknown`, nothing is hidden, and exit code remains `0`.
- Stderr receives a **warning visible to the agent as well** (not only with `--verbose`), e.g.
  `WARNING: Channel access could not be determined; all channels are listed, some may be unreadable.`
  `Output.warning()` serves this purpose, added in parallel by work on `messages`. The `WARNING: …` output goes to stderr
  even without `--verbose`. An agent without `--verbose` does not see `note()` **[VERIFIED, code as of 2026-11-03]**.
- Under `--verbose`, the reason is added (e.g. `member endpoint returned 403 (code 50001)`).
- On the next `--refresh`, calculation will be re-attempted.

### 9.6 Verification plan (run by the user)

A small new script, e.g. `prototype/access_probe.py`, in the style of `probe.py`: 1 request per second, GET only,
report to `prototype/out/` with structure only. Without role names, user IDs, or message texts. Channel IDs and guild
category names are fine; the analysis already contains them.

| # | Request | What to record | Expectation |
|---|---|---|---|
| 1 | `GET /users/@me/guilds` | `owner`, whether `permissions` contains `VIEW_CHANNEL`/`ADMINISTRATOR` (bool) | `owner: false`, without admin |
| 2 | `GET /users/@me/guilds/{VUT}/member` | status, field list, role count, whether `permissions` is present, `pending`, whether timed out (bool), `flags` | `200`, `roles` and `permissions` present |
| 3 | `GET /guilds/{VUT}/members/{me}` | status, field list, whether role set matches (2) | `200`, match |
| 4 | `GET /guilds/{VUT}/channels?permissions=true` | status, how many channels have `permissions` (by type, including categories) | `permissions` on all channels |
| – | (local) calculation from (1)/(2) + overwrites from (4) | match count with `permissions` from (4): `VIEW` bit, `RMH` bit, integer. IDs of channels with mismatch | 100% match on `VIEW` and `RMH` bits |
| – | (local) control channels | `1549737445002584094` and categories `moderation`, `logging`, `fillers` → `VIEW` in both sources | `false` |
| 5 | optional `GET /guilds/{VUT}/permissions/member/{me}` | status, error code, match with (1) | unknown |
| 6 | optional `GET /channels/1549737445002584094/messages?limit=1` | status and `code` | `403`, `50001` |
| 7 | optional, if (4) shows a channel with `VIEW` without `RMH`: `GET /channels/{id}/messages?limit=1` | status and array length | `200`, `0` |

In total 4 to 7 requests. Request 6 is one intentionally invalid request (`403`). Invalid requests have
a limit of 10,000 per 10 minutes, so one does not matter.

**Manual check:** compare count of `read`+`view` channels with the Discord sidebar. When comparing, keep in mind
opt-in hidden channels and resource channels (`readme-*`). Discord does not show those in the list, even though access to them exists.

### 9.7 Recommended workflow

1. The user runs verification (9.6). Results are written here into the "Verification" section and points are relabelled to
   **[VERIFIED]**.
2. Decision 9 is written as an ADR (status `Proposed`, until approved by the user). Primary source will be
   `?permissions=true` or the member endpoint, depending on results.
3. Implementation:
   - `permissions.py` + tests,
   - `models`/`cache` (schema 2),
   - `directory` (request with `permissions=true`, fallback, `unknown`),
   - `channels` (`--include-hidden`, `access` column, warning via `warning()`),
   - update design 4.3 and 15/9.
4. For `messages`: error mapping from section 7 and skipping `none` channels without a request.

## 10. Open questions

- Does `?permissions=true` work with a user token today? Does a category also have the field? Does the server apply implicit masking
  (without `VIEW` → `0`)?
- Does the private member object from `/users/@me/guilds/{id}/member` really contain `permissions`?
- Do the new endpoints from 2026-10-30 (`/permissions/member/...`) work with a user token?
- When will REST start omitting inaccessible channels for users as well?
- Exact `403` code on a voice channel without `CONNECT`.
- Does `permissions` in `/users/@me/guilds` include all bits for the owner? With `owner: true` it does not matter.

## Sources

Official documentation (`github.com/discord/discord-api-docs`, `developers/` directory, state as of 2026-11-03):
- [Permissions](https://docs.discord.com/developers/topics/permissions): bits, Permission Overwrites (pseudocode),
  Implicit Permissions, Inherited Permissions (Threads), Permission Syncing, timeout.
- [Guild: Get Guild Channels](https://docs.discord.com/developers/resources/guild#get-guild-channels) (warning
  as of 2026-11-16), Guild object (`owner`, `permissions`), Guild Member object (`pending`,
  `communication_disabled_until`), Get Guild Member, Get Guild Member Permissions, Add Guild Member (`pending`).
- [User: Get Current User Guilds, Get Current User Guild Member](https://docs.discord.com/developers/resources/user#get-current-user-guild-member).
- [Channel: Obfuscated Channels, Channel Flags, Get Channel Member Permissions, archived threads](https://docs.discord.com/developers/resources/channel#channel-object-obfuscated-channels).
- [Message: Get Channel Messages](https://docs.discord.com/developers/resources/message#get-channel-messages).
- [Change Log](https://docs.discord.com/developers/change-log): "Channel Obfuscation for Users and Bots" (2026-08-12),
  "New Endpoints for getting member and role permissions…" (2026-10-30).
- [Opcodes and Status Codes](https://docs.discord.com/developers/topics/opcodes-and-status-codes): JSON codes
  `10003`, `10008`, `20002`, `40333`, `50001`, `50013`.

Discord Userdoccers (docs.discord.food, repository `discord-userdoccers/discord-userdoccers`):
- [Channels: List Guild Channels](https://docs.discord.food/resources/channel#list-guild-channels): `permissions` parameter
  (commit `76992e2`, 2024-06-02), `OBFUSCATED` flag (commit `ceb928b`, 2024-12-15), note
  on future filtering and channel obfuscation in gateway (commit `20dd753`, 2026-06-24).
- [Guilds](https://docs.discord.food/resources/guild): List User Guilds, Get Current Guild Member (private member
  object with `permissions`), Get Guild Member, List Guild Members (not for user accounts), roles, Guild Member Flags.
- [Permissions](https://docs.discord.food/topics/permissions): quarantine, discoverable guilds.
- [Threads](https://docs.discord.food/topics/threads): private threads, enumeration.
- [User Settings](https://docs.discord.food/resources/user-settings): `OPT_IN_ENABLED`, `OPT_IN_CHANNELS_ON`.
- [Errors](https://docs.discord.food/topics/errors) and [Rate Limits](https://docs.discord.food/topics/rate-limits).

Libraries (`master` branch as of 2026-11-03):
- `dolfies/discord.py-self`:
  - `discord/abc.py` (`GuildChannel.permissions_for`, `_apply_implicit_permissions`),
  - `discord/channel.py` (voice channel and `CONNECT`),
  - `discord/threads.py` (`Thread.permissions_for`),
  - `discord/permissions.py` (`_timeout_mask`),
  - `discord/http.py` (`get_member` → `GET /guilds/{id}/members/{id}`).
- `Tyrrrz/DiscordChatExporter`:
  - `DiscordChatExporter.Core/Discord/DiscordClient.cs` (`TryGetGuildMemberAsync`, mapping `403` to "forbidden"),
  - `DiscordChatExporter.Cli/Commands/Base/ExportCommandBase.cs` (channel-by-channel errors, without preliminary permission check).

Community reports of `403 / 50001 Missing Access` when reading messages:
- [discord.js-selfbot-v13 #203](https://github.com/aiko-chan-ai/discord.js-selfbot-v13/issues/203),
- [discord-server-copy #37](https://github.com/itskekoff/discord-server-copy/issues/37).
