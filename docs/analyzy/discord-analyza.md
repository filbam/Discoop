# Analýza dát Discord web klienta (server VUT FIT)

Dátum pozorovania: 2. – 3. 11. 2026 (Europe/Bratislava), tri kolá (2. a 3. kolo s prísnymi pravidlami). Klient: discord.com v Chrome (prihlásený účet používateľa), API `v9`.
Server: **VUT FIT** (`guild_id = 461541385204400138`).

> **INCIDENT počas 1. kola analýzy:** pri práci so search boxom sa omylom **odoslala správa**
> `cdn.discordapp.com` z účtu používateľa do forum vlákna *„Dotaz ohledně Automaticky udělovaného zápočtu“*
> (thread `1566814241946738698` vo fóre `#help-center`, 3. 11. 2026 00:07,
> `POST /api/v9/channels/1566814241946738698/messages` → `200`).
> **Používateľ správu medzičasom sám zmazal.** Odoslanie správy však zrejme spravilo používateľa
> členom vlákna: v 2. kole bolo vlákno vidno v sidebari pod `#help-center` a v 1. kole ukazovalo
> „Following“. Ak to tak má zostať, treba ho prípadne ručne prestať sledovať.
> 2. a 3. kolo (doplnenie) prebehli s prísnejšími pravidlami: žiadny vstup z klávesnice, žiadny search,
> kliky len na názvy kanálov v sidebari a na tlačidlo Threads v hlavičke. Nič neočakávané sa nestalo.

**Legenda:** **[OVERENÉ]** = pozorované v requestoch alebo v stave klienta počas tejto analýzy.
**[PREDPOKLAD]** = zo všeobecných znalostí Discord API, v tejto analýze to overené nebolo.

**Metodika:** URL a stavové kódy z network logu Chrome rozšírenia. Rozšírenie nevie zobraziť telá
odpovedí ani hlavičky, preto som v **mojej vlastnej karte** nainštaloval pasívny observer
(obal nad `XMLHttpRequest`/`fetch`). Ten pre `/api/v9/channels|guilds/...` ukladal telo odpovede,
**iba mená** request hlavičiek a vybrané response hlavičky. Hodnotu `Authorization` ani cookies som
nečítal ani neukladal. Vlastné API requesty som nerobil. Stav klienta som čítal cez React fiber
props v DOM (webpack store cache je v aktuálnom klientovi skrytá, z `__webpack_require__.c` je
dostupných len ~100 polyfill modulov). Príklady JSON sú anonymizované.

---

## 1. Súhrnná tabuľka

| Dátový typ | Zdroj v klientovi | Overené? | Poznámka |
|---|---|---|---|
| Zoznam serverov (guilds) | gateway `READY` → stav klienta | čiastočne (REST request nevidno, guild objekt je v stave klienta) | REST `GET /users/@me/guilds` existuje, klient ho pri načítaní nevolal **[PREDPOKLAD]** |
| Info o serveri | gateway → stav klienta (camelCase record) | [OVERENÉ] zoznam polí | `name, description, icon, banner, features, rulesChannelId, ...` |
| Kanály + kategórie | gateway → stav klienta | [OVERENÉ] | 392 kanálov + 22 kategórií. Skryté kanály chodia **obfuskované** (`___hidden___`) |
| Správy kanála (text, announcement, voice chat) | REST `GET /channels/{id}/messages` | [OVERENÉ] | `limit` + `before`/`after`/`around`, odpoveď je pole **od najnovšej**. Klient: prvé otvorenie `limit=10`, ďalšie strany `limit=20` |
| Správy vo vlákne / fórum poste | REST `GET /channels/{thread_id}/messages` | [OVERENÉ] | thread = samostatný kanál, správy majú navyše `position` |
| Pripnuté správy | REST `GET /channels/{id}/messages/pins?limit=25` | [OVERENÉ] | `{items:[{pinned_at, message}], has_more}` |
| Aktívne vlákna | gateway → stav klienta | [OVERENÉ] (bez REST requestu) | thread record s `thread_metadata`, `message_count` |
| Archivované vlákna / fórum posty | REST `GET /channels/{id}/threads/search?archived=true...` | [OVERENÉ] | stránkovanie cez `offset`, `total_results`, `has_more` |
| Prvá správa + autor fórum postu | REST `POST /channels/{forum_id}/post-data` | [OVERENÉ] odpoveď, telo requestu nie | read-only POST |
| Vyhľadávanie | REST `GET /guilds/{id}/messages/search` | [OVERENÉ] | 25 výsledkov na stranu, `offset`, `min_id`, `channel_id`, `has`, `content` |
| Prílohy | v objekte správy (`attachments[]`) + CDN | [OVERENÉ] | podpísané URL `ex/is/hm`, okno 24 h, čerstvo získaná URL platí **≥ 12 h** |
| Embedy (linky, GIF, YouTube, obrázky, tweety) | v objekte správy (`embeds[]`) | [OVERENÉ] | typy `link`, `gifv`, `video`, `image`, `rich`. GIF provider je teraz **Klipy** (nie Tenor) |
| Custom emoji | text správy `<:name:id>` + CDN | [OVERENÉ] | `https://cdn.discordapp.com/emojis/{id}.webp?size=48`, bez podpisu |
| Vlákno založené zo správy | `message.thread` + `flags & 32` | [OVERENÉ] | `thread.id == message.id` |
| Nálepky, forwardy, ankety, systémové správy | v objekte správy | **neoverené** | v ~410 prezretých správach z 9 kanálov sa nevyskytli |
| Reakcie | v objekte správy (`reactions[]`) | [OVERENÉ] | iba počty, nie kto reagoval |
| Členovia / prezývky | gateway (lazy member list) | [OVERENÉ] nepriamo (žiadny REST members request) | REST správy **neobsahujú** `member` |
| Role, emoji, nálepky servera | gateway → stav klienta | [PREDPOKLAD] | REST `GET /guilds/{id}/roles|emojis|stickers` |
| Rate-limit hlavičky | – | [OVERENÉ] **chýbajú** | žiadne `X-RateLimit-*` v ~40 API odpovediach (všetky 200/204) |
| Read state (prečítané) | REST `POST /channels/{id}/messages/{id}/ack` | [OVERENÉ] | klient ho volá sám pri otvorení kanála. CLI ho volať **nemá** |
| Udalosti servera | REST `GET /guilds/{id}/scheduled-events/{id}/users/counts` | [OVERENÉ] URL | zoznam udalostí chodí cez gateway **[PREDPOKLAD]** |

---

## 2. Zoznam serverov

- Pri načítaní ani pri reloade karty klient **nevolal** `GET /api/v9/users/@me/guilds`. Zachytené boli len
  `science`, `metrics/v2`, `quests/get-decisions` a requesty na správy **[OVERENÉ]**. Výhrada: network tracking sa
  pri prvej navigácii resetuje, takže úplne prvé requesty bootu mohli uniknúť.
- Guild objekt v stave klienta (z gateway `READY`/`GUILD_CREATE`) má tieto polia (camelCase, klientsky
  record) **[OVERENÉ]**:
  `id, joinedAt, premiumSubscriberCount, name, description, icon, splash, banner, homeHeader, features,
  preferredLocale, ownerId, application_id, afkChannelId, afkTimeout, systemChannelId, verificationLevel,
  explicitContentFilter, defaultMessageNotifications, mfaLevel, vanityURLCode, premiumTier,
  systemChannelFlags, discoverySplash, rulesChannelId, safetyAlertsChannelId, publicUpdatesChannelId,
  maxMembers, nsfwLevel, hubType, profile, guildTheme, premiumFeatures, ...`
- REST alternatíva **[PREDPOKLAD]**: `GET /api/v9/users/@me/guilds` (voliteľne `?with_counts=true`) vracia pole
  `{id, name, icon, banner, owner, permissions, features, approximate_member_count, approximate_presence_count}`.
  Raw JSON z gateway má snake_case (`owner_id`, `system_channel_id`, `rules_channel_id`...).

## 3. Kanály

**Zdroj:** gateway (`READY` / `GUILD_CREATE`), v klientovi je to model sidebaru `guildChannels`. Pri prepínaní
kanálov nešiel žiadny REST request na zoznam kanálov **[OVERENÉ]**.
REST alternatíva: `GET /api/v9/guilds/{guild_id}/channels` **[PREDPOKLAD]**.

**Typy kanálov na VUT FIT** **[OVERENÉ]** (spolu 392 záznamov + 22 kategórií):

| `type` | Význam | Počet | Príklady |
|---|---|---|---|
| 0 | GUILD_TEXT | 358 | `2bit-general`, `2bit-terminy`, `aeu-private🔒`, `readme-cz` |
| 2 | GUILD_VOICE (má aj textový chat) | 10 | `general - open`, `games`, `hospoda` |
| 4 | GUILD_CATEGORY | 22 (mapa `categories`) | `general`, `volitelne`, `statické info`, `archiv`, `1. semestr` ... |
| 5 | GUILD_ANNOUNCEMENT | 12 | `2bit-info`, `skolni-info`, `changelog`, `kachna-info` |
| 13 | GUILD_STAGE_VOICE | 1 | `general stage` |
| 15 | GUILD_FORUM | 9 | `help-center`, `inzerce`, `isvut-bugfest`, `studentske-podnety` |
| 11 | PUBLIC_THREAD | (vlákna) | `Tajné vlákno` v `#2bit-general`, fórum posty |
| 16 | GUILD_MEDIA | 0 | nevyskytuje sa |

**Polia kanála** (klientsky record, raw meno v zátvorke) **[OVERENÉ]**:
`id, guild_id, name, type, parent_id` (ID kategórie alebo `null`), `position_` (`position`), `topic_` (`topic`),
`nsfw_`, `flags_` (`flags`), `rateLimitPerUser_` (`rate_limit_per_user`), `lastMessageId` (`last_message_id`),
`lastPinTimestamp` (`last_pin_timestamp`), `permissionOverwrites_` (`permission_overwrites`), `iconEmoji`
(`{id, name}`), `themeColor`, `defaultAutoArchiveDuration`, `defaultThreadRateLimitPerUser`, `application_id`, `version`.

Fórum kanál (type 15) má navyše **[OVERENÉ]**:
```json
{
  "available_tags": [{"id": "1065278887191384144", "name": "Nezodpovězeno", "emoji_id": "600435650227077120", "emoji_name": null, "moderated": false, "color": null}],
  "default_reaction_emoji": {"emoji_id": "960172090701524992", "emoji_name": null},
  "default_sort_order": null,
  "default_tag_setting": "match_some",
  "default_auto_archive_duration": 4320,
  "flags": 16
}
```
(`flags: 16` = REQUIRE_TAG. Tagy `Škola`, `Offtopic`, `Zodpovězeno`... V klientovi sú v camelCase.)

**Hierarchia a poradie:** `parent_id` ukazuje na kategóriu (napr. `#2bit-terminy.parent_id = 591352457703981067` =
kategória `general`). Kategórie majú vlastné `position` (napr. `statické info`=5, `volitelne`=240, `general`=254,
`archiv`=325) **[OVERENÉ]**. Poradie: kategórie podľa `position`, v kategórii kanály podľa `position`, pri zhode podľa `id`.
Hlasové kanály sú pod textovými **[PREDPOKLAD]**.

**Zamknuté a súkromné kanály:**
- Zámok `🔒` v názvoch ako `aeu-private🔒` je **súčasť mena** kanála, nie systémový stav. Prístup riadia
  `permission_overwrites` **[OVERENÉ]**. Príklady:
  - `#2bit-terminy`: `@everyone` (`id = guild_id`, `type 0`) `deny = "103079218176"` (obsahuje VIEW_CHANNEL `1024`),
    niekoľko rolí `allow = "1024"`.
  - `#2bit-general`: `@everyone deny "1024"`, rola `allow "3072"` (VIEW_CHANNEL + SEND_MESSAGES), plus
    **member overwrites** (`type 1`, `id = <user_id>`) `allow "1024"`.
  - `type 0` = rola, `type 1` = člen. `allow`/`deny` sú **stringy** s bitovým poľom oprávnení.
- **Kanály, ktoré používateľ nevidí, v dátach SÚ, ale obfuskované** **[OVERENÉ]**:
  ```json
  {"id": "1549737445002584094", "type": 0, "name": "___hidden___", "flags": 131072,
   "parent_id": null, "last_message_id": null, "topic": null, "position": 4,
   "permission_overwrites": [{"id": "461541385204400138", "type": 0, "allow": "0", "deny": "1024"}]}
  ```
  Majú meno `___hidden___`, `flags` bit `1<<17` (131072), stratený `parent_id` aj `last_message_id`
  a umelý overwrite „@everyone deny VIEW“. Takých bolo napr. 4 celé kategórie `___hidden___` a viacero kanálov
  (renderLevel 1 = nezobrazený: 74 záznamov, časť z nich sú skryté hlasové a „resource“ kanály).
- `readme-cz`/`readme-en` majú `flags: 128` (pravdepodobne resource kanál „Server Guide“) **[PREDPOKLAD k významu]**.

## 4. Správy

**Endpoint** **[OVERENÉ]**:
```
GET /api/v9/channels/{channel_id}/messages?limit=10
GET /api/v9/channels/{channel_id}/messages?before={message_id}&limit=20
GET /api/v9/channels/{channel_id}/messages?after={message_id}&limit=20
GET /api/v9/channels/{channel_id}/messages?limit=10&around={message_id}
```
- Klient používal **vždy** `limit=10` pri prvom otvorení kanála a `limit=20` pri každej ďalšej strane
  (`before`/`after`) **[OVERENÉ, 9 kanálov, ~20 requestov]**. Maximum je **100** **[PREDPOKLAD, overiť prototypom]**.
- Ak príde menej správ než `limit`, je to začiatok histórie. `#2bit-info` vrátil pri `limit=10` len 6 správ
  a klient zobrazil „This is the start of the channel“ **[OVERENÉ]**.
- Odpoveď je JSON **pole zoradené od najnovšej po najstaršiu**, a to **aj pri `after=`** **[OVERENÉ]**
  (`after=1566815961741262950` vrátilo 5 správ zostupne).
- `around` vrátil 6 správ vrátane kotvy pri `limit=10`, lebo vlákno malo málo správ **[OVERENÉ]**.
- **Announcement kanály** (type 5) sa čítajú rovnako (`GET /channels/{id}/messages`) **[OVERENÉ]**
  (`#2bit-info`, `#skolni-info`). Klient pri nich navyše volá `GET /channels/{id}/follower-stats` (→ `204`).
- Správy v REST odpovedi **nemajú `member`** (ani nick, ani roly autora) **[OVERENÉ]**: chýba vo všetkých ~410 pozorovaných správach.

**Polia správy** (pozorované v raw JSON) **[OVERENÉ]**:

| Pole | Význam |
|---|---|
| `id` | snowflake správy (obsahuje čas) |
| `channel_id` | kanál alebo vlákno |
| `type` | 0 = DEFAULT, 19 = REPLY (iba tieto v ~410 správach). Systémové typy (7 join, 6 pin, 18 thread created, 21 thread starter, 46 poll result...) **[PREDPOKLAD]** |
| `content` | text (markdown, mentions ako `<@id>`, `<@&id>`, `<#id>`, custom emoji `<:name:id>`). `<@&id>` a `<:name:id>` **[OVERENÉ]** |
| `author` | user objekt (pozri nižšie). Boti majú navyše `"bot": true` **[OVERENÉ]** |
| `timestamp` | ISO 8601 s mikrosekundami, `+00:00` |
| `edited_timestamp` | ISO alebo `null` |
| `attachments[]` | prílohy (sekcia 5) |
| `embeds[]` | link preview, GIF, video (sekcia 5) |
| `mentions[]` | **plné user objekty** spomenutých používateľov |
| `mention_roles[]` | iba ID rolí |
| `mention_everyone` | bool |
| `reactions[]` | voliteľné, iba ak existujú |
| `message_reference` | voliteľné: `{type, channel_id, message_id, guild_id}`. `type 0` = reply, `1` = forward **[PREDPOKLAD]** |
| `referenced_message` | voliteľné: plný objekt pôvodnej správy (bez vlastného `referenced_message`) |
| `pinned` | bool |
| `tts` | bool |
| `flags` | bitové pole. Pozorované hodnoty **[OVERENÉ]**: `0`; `1` (CROSSPOSTED, publikovaná správa v announcement kanáli); `4` (SUPPRESS_EMBEDS, link bez náhľadu, `embeds: []`); `5` = 1+4; `32` (HAS_THREAD, zo správy vzniklo vlákno). Mená bitov podľa dokumentácie |
| `components[]` | tlačidlá a menu (vo všetkých pozorovaných správach prázdne, aj pri botoch) |
| `thread` | voliteľné: plný thread objekt, ak zo správy vzniklo vlákno. **`thread.id == message.id`** **[OVERENÉ]** |
| `position` | iba vo vláknach, poradové číslo správy vo vlákne |
| `hit` | iba vo výsledkoch search (`true`) |

**Vlákno založené zo správy** (`#otazky-na-poradce`, „Automatické vlákno“) **[OVERENÉ]**:
```json
{"id": "1053252576004542494", "type": 0, "flags": 32, "content": "<text>",
 "thread": {"id": "1053252576004542494", "type": 11, "parent_id": "471211826571640842", "name": "<thread name>",
            "owner_id": "<user_A_id>", "last_message_id": "…", "message_count": 3, "member_count": 3,
            "total_message_sent": 3, "member_ids_preview": ["<user_id>", "…"], "flags": 0,
            "bitrate": 64000, "user_limit": 0, "rtc_region": null, "rate_limit_per_user": 0,
            "thread_metadata": {"archived": true, "archive_timestamp": "…", "auto_archive_duration": 4320,
                                "locked": false, "create_timestamp": "…"}}}
```

V ~410 správach z 9 kanálov sa **nevyskytli**, hoci ich klientsky Message record má. Raw mená a tvar sú
**[PREDPOKLAD, overiť prototypom]**:
`sticker_items` (nálepky), `message_snapshots` (forwardy), `poll` (ankety), systémové správy,
`interaction_metadata`, `application_id`, `webhook_id`, `mention_channels`, `call`, `activity`,
`role_subscription_data`, `nonce`. Prezreté kanály: `#2bit-general` (~200 správ dozadu po 19. 10. 2026),
`#general` (~110), `#english-general` (30), `#vote-room` (30, bot hlasovania cez reakcie, nie ankety),
`#hlasky` (10, screenshoty ako prílohy, nie forwardy), `#skolni-info`, `#2bit-info`, `#otazky-na-poradce`,
`#2bit-terminy`, forum post v `#help-center`.

**`author`** **[OVERENÉ]**:
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
`username` je unikátny handle, `global_name` je zobrazované meno (môže byť `null`), `discriminator` je dnes `"0"`.

**Odpoveď (reply)** **[OVERENÉ]**:
```json
{
  "type": 19,
  "message_reference": {"type": 0, "channel_id": "1282100102743330887", "message_id": "1566536198581788806", "guild_id": "461541385204400138"},
  "referenced_message": {"type": 0, "id": "1566536198581788806", "content": "<text>", "author": {"…": "…"}, "…": "…"}
}
```
- 9 z 10 replies malo `referenced_message`. Jednej **chýbal kľúč úplne** (odkaz na staršiu, asi zmazanú správu).
- **Pins ani search výsledky `referenced_message` nemajú.** Klient vtedy zobrazí „Message could not be loaded“ **[OVERENÉ]**.

**Reakcie** **[OVERENÉ]**:
```json
{"emoji": {"id": null, "name": "✅"}, "count": 1, "count_details": {"burst": 0, "normal": 1},
 "burst_colors": [], "me_burst": false, "burst_me": false, "me": false, "burst_count": 0}
```
Custom emoji má `emoji.id` + `name`, animované navyše `"animated": true` **[OVERENÉ]**. Kto reagoval, sa dá zistiť cez
`GET /channels/{id}/messages/{id}/reactions/{emoji}` **[PREDPOKLAD]**.

## 5. Prílohy, médiá, embedy

**Polia `attachments[]`** **[OVERENÉ]**:
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
Ďalšie pozorované voliteľné polia: `title` (pôvodný názov), `duration_secs` (video, napr. `27.53`),
`flags` (`32` pri animovanom GIF, IS_ANIMATED **[PREDPOKLAD k významu]**). Nepozorované: `description`
(alt text), `waveform` a `duration_secs` pri hlasovej správe, `ephemeral`. `width`/`height` sú len pri obrázkoch a videách.
Pozorované typy: `image/png`, `image/jpeg`, `image/webp`, `image/gif`, `video/mp4`.

**CDN URL a podpis** **[OVERENÉ]**:
- Formát: `https://cdn.discordapp.com/attachments/{channel_id}/{attachment_id}/{filename}?ex={hex}&is={hex}&hm={64 hex}&`
  (končí `&`). Niektoré majú ako prvý parameter `backend=b2`, napr. `?backend=b2&ex=…&is=…&hm=…&`.
- `proxy_url` je ten istý súbor na `media.discordapp.net` s rovnakým query. Klient si naň pridáva
  `&format=webp&quality=lossless&width=…&height=…` pre náhľady.
- `ex` = expirácia, `is` = vydanie, obe ako **hex unix sekundy**. **`ex − is = 24 h`** (všetkých 22 + 26 príloh).
- `is` = **čas vytvorenia prílohy (zo snowflake `attachment.id`) + k × 12 h**, pričom `k` je najväčšie také,
  že `is ≤ čas fetchu`. Vo všetkých 22 meraných prípadoch platilo `0 ≤ fetch − is < 12 h` **[OVERENÉ]**.
  Príklad: príloha z `2026-11-01T21:51:13Z` → `is=2026-11-02T21:51:13Z`, `ex=2026-11-03T21:51:13Z`.
  **Čerstvo načítaná URL teda platí ešte aspoň 12 h a najviac 24 h.** URL je deterministická v rámci
  12-hodinového okna, čo zrejme umožňuje cache.
- `POST /api/v9/attachments/refresh-urls` sa počas analýzy **nespustil** (nenašiel som správu s exspirovaným
  CDN linkom v texte). Predpoklad: body `{"attachment_urls": [...]}` → `{"refreshed_urls": [{"original", "refreshed"}]}` **[PREDPOKLAD]**.
- **Authorization na CDN:** obrázky a videá klient načítava ako bežné `<img>`/`<video>` resource requesty
  (v network logu ako GET na `media.discordapp.net/...`). Cez API vrstvu (XHR, ktorá pridáva `Authorization`)
  žiadny CDN request nešiel **[OVERENÉ]**. Prehliadač k `<img>` vlastné hlavičky nepridá, takže CDN
  **nepotrebuje token**, stačí podpis v URL (vysoká istota, hlavičky CDN requestov som priamo nevidel).
- Ikony rolí: `https://cdn.discordapp.com/role-icons/{role_id}/{hash}.webp?size=24&quality=lossless` **[OVERENÉ]**.

**Embedy** **[OVERENÉ]**:
- **GIF (`type: "gifv"`)**, provider **Klipy** (Discord prešiel z Tenoru):
  ```json
  {"type": "gifv", "url": "https://klipy.com/gifs/<slug>", "title": "<text>",
   "provider": {"name": "Klipy", "url": "https://klipy.com"},
   "thumbnail": {"url": "https://static.klipy.com/…/x.webp", "proxy_url": "https://images-ext-1.discordapp.net/external/<sig>/https/static.klipy.com/…/x.webp", "width": 498, "height": 498, "placeholder": "…", "placeholder_version": 1, "flags": 0},
   "video": {"url": "https://static.klipy.com/…/x.mp4", "proxy_url": "https://images-ext-1.discordapp.net/external/<sig>/https/…", "width": 498, "height": 498, "placeholder": "…", "placeholder_version": 1, "flags": 0},
   "content_scan_version": 4}
  ```
- **Link preview (`type: "link"`)**: `url, title, description, color, provider{name}, thumbnail, content_scan_version, reference_id`.
- **YouTube (`type: "video"`)**: `url, title, description, color, author, provider{name: "YouTube"}, thumbnail, video, reference_id`.
- **Priamy link na obrázok (`type: "image"`)** **[OVERENÉ]**: `{type, url, thumbnail{url, proxy_url, width, height, …}, content_scan_version}`.
- **Rich (`type: "rich"`)**, napr. náhľad tweetu cez vxtwitter/fixvx **[OVERENÉ]**: `url, description, color, timestamp,
  author{name, url, icon_url, proxy_icon_url}, footer{text, icon_url, proxy_icon_url}, thumbnail,
  video{url, proxy_url, width, height, content_type, placeholder, placeholder_version, flags}, reference_id, content_scan_version`.
- Externé obrázky idú cez proxy `images-ext-N.discordapp.net/external/{podpis}/{schéma}/{host}/{cesta}`.

**Custom emoji** **[OVERENÉ]**:
- v texte: `<:name:id>`, napr. `<:peepolove:827833315666558996>`. Animované `<a:name:id>` **[PREDPOKLAD]**.
- CDN (klient načítal): `https://cdn.discordapp.com/emojis/{id}.webp?size=48` (aj `size=56`), **bez podpisu `ex/is/hm`**,
  teda nevyprší.

**Nálepky** **[PREDPOKLAD]** (v pozorovaných dátach žiadne):
- `sticker_items: [{id, name, format_type}]`, CDN: `https://media.discordapp.net/stickers/{id}.webp`
  (format_type 1 PNG, 2 APNG, 3 Lottie JSON, 4 GIF).

## 6. Vlákna a fóra

- **Vlákno = samostatný kanál.** Správy sa čítajú cez `GET /channels/{thread_id}/messages` **[OVERENÉ]**.
- **Aktívne vlákna** klient dostáva cez gateway. Panel „Threads“ ukázal aktívne vlákno bez REST requestu
  **[OVERENÉ 2×]**. Pri otvorení panelu ide **jediný** API request, a to `threads/search?archived=true…`
  (pre archivované). Na aktívne vlákna nejde žiadny REST request.
  Thread record **[OVERENÉ]**:
  ```json
  {"id": "1521315949171441765", "type": 11, "guild_id": "461541385204400138", "parent_id": "1282100102743330887",
   "name": "Tajné vlákno", "owner_id": "<user_id>", "last_message_id": "…",
   "message_count": 240, "total_message_sent": 241, "member_count": 12, "member_ids_preview": ["<user_id>", "…"],
   "rate_limit_per_user": 0, "flags": 0, "applied_tags": [],
   "thread_metadata": {"archived": false, "auto_archive_duration": 4320, "archive_timestamp": "…",
                       "create_timestamp": "…", "locked": false, "invitable": true}}
  ```
- **Archivované vlákna aj fórum posty** **[OVERENÉ]**:
  ```
  GET /api/v9/channels/{parent_id}/threads/search?archived=true&sort_by=last_message_time&sort_order=desc&limit=25&tag_setting=match_some&offset=0
  ```
  Odpoveď: `{threads[], members[], has_more, total_results, first_messages[]}`. `first_messages` je pri fóre,
  pri textovom kanáli kľúč chýbal. `#help-center` hlásil `total_results: 1831`, `has_more: true`. Stránkuje sa
  cez `offset` (+25). Thread objekty tu majú navyše `bitrate, user_limit, rtc_region` a `owner`
  (guild member objekt: `nick, roles, joined_at, avatar, banner, flags, pending, premium_since,
  communication_disabled_until, mute, deaf, collectibles, user{…}`).
- **Fórum post:** `first_message.id == thread.id`, teda štartovacia správa má rovnaké ID ako vlákno **[OVERENÉ]**.
  Tagy postu sú v `applied_tags[]` (ID z `available_tags` fóra).
- `POST /api/v9/channels/{forum_id}/post-data` (read-only POST pri otvorení fóra) **[OVERENÉ]**: odpoveď je
  `{"threads": {"<thread_id>": {"first_message": {…}, "owner": {member…}}}}` (10 vlákien). Telo requestu
  som nezachytil, pravdepodobne `{"thread_ids": [...]}` **[PREDPOKLAD]**.
- Štandardné alternatívy z dokumentácie **[PREDPOKLAD]**:
  `GET /channels/{id}/threads/archived/public?before={ISO}&limit=100`,
  `GET /channels/{id}/users/@me/threads/archived/private`, `GET /guilds/{id}/threads/active`.
  Pre user účty nie je isté, či fungujú.
- `threads/search` v `#2bit-general` vrátil 0 archivovaných vlákien, aktívne „Tajné vlákno“ v ňom nebolo.
  Aktívne vlákna treba brať z iného zdroja (gateway, search, alebo `archived=false` **[PREDPOKLAD]**).

## 7. Pripnuté správy

**[OVERENÉ]**
```
GET /api/v9/channels/{channel_id}/messages/pins?limit=25
→ {"items": [{"pinned_at": "2026-09-01T12:03:29.017000+00:00", "message": { …plný objekt správy, "pinned": true… }}], "has_more": false}
```
- `#2bit-general` mal 4 piny. `message` nemá `referenced_message`.
- Stránkovanie pri `has_more: true` je asi `before={pinned_at ISO}` **[PREDPOKLAD, overiť prototypom]**.
  Kanál s viac ako 25 pinmi som pod prísnymi pravidlami (bez searchu) nenašiel. Starý endpoint
  `GET /channels/{id}/pins` (holé pole) je zrejme legacy **[PREDPOKLAD]**.

## 8. Vyhľadávanie

**[OVERENÉ]** URL podľa toho, čo klient poslal:
```
GET /api/v9/guilds/{guild_id}/messages/search?content=z%C3%A1po%C4%8Det&sort_by=timestamp&sort_order=desc&offset=0
GET /api/v9/guilds/{guild_id}/messages/search?has=file&min_id=1555338520166400000&channel_id=1282100102743330887&sort_by=timestamp&sort_order=desc&offset=0
… &offset=25   (strana 2)
```
- Mapovanie UI na parametre: `has:file` → `has=file`, `in:#kanál` → `channel_id=`, `after:2026-10-01` →
  `min_id=` snowflake **konca dňa v lokálnej zóne** (`2026-10-01T22:00:00Z` = polnoc 2. 10. CEST, „striktne po“).
  Ďalšie parametre **[PREDPOKLAD]**: `author_id`, `mentions`, `max_id` (before:), `pinned`, `has=image|video|link|embed|sticker|poll|sound`, `author_type`, `include_nsfw`.
- Odpoveď **[OVERENÉ]**:
  ```json
  {"analytics_id": "…", "total_results": 7901, "doing_deep_historical_index": false,
   "messages": [[{ …správa…, "hit": true }], …],
   "threads": [ …thread objekty, v ktorých sú hity… ], "members": []}
  ```
  `messages` je **pole polí**, každé pole s **1 správou** (kontextové správy už neprichádzajú). Na stranu je **25**
  výsledkov, `offset` rastie po 25. „zápočet“ našlo 7901 výsledkov na 317 stranách.
- Filter `channel_id` vrátil aj správy z **vlákien daného kanála** (z „Tajné vlákno“) **[OVERENÉ]**.
- Search vracia aj správy zo súkromných kanálov, kam má používateľ prístup (`isc-private`, `inp-private`) **[OVERENÉ]**.
- Limity **[PREDPOKLAD]**: max `offset` okolo 9 975 (≈400 strán), pri neindexovanom kanáli môže prísť `202`
  s `retry_after`, search má prísnejší rate limit.
- **Je to užitočná alternatíva pre časové rozsahy?** Áno, na cielené dotazy: `min_id`/`max_id` + `channel_id`
  + `has=file` (napr. „všetky súbory v kanáli za posledný týždeň“). Na **kompletný archív nie**: 25 položiek
  na request, strop offsetu, chýba `referenced_message`, index môže zaostávať. Na úplnosť je lepšie
  `GET /channels/{id}/messages` s `before`/`after`.

## 9. Mená: mentions, roly, kanály, prezývky

- `<@id>`: user objekt je priamo v `mentions[]` tej istej správy (`username`, `global_name`) **[OVERENÉ]**.
- `<@&id>`: v `content` je token `<@&{role_id}>` a to isté ID je v `mention_roles[]` **[OVERENÉ]**.
  Meno roly je v rolách servera (gateway). REST
  `GET /guilds/{id}/roles` **[PREDPOKLAD]**.
- `<#id>`: zo zoznamu kanálov (sekcia 3). Skrytý kanál ostane `___hidden___`.
- **Prezývky:** REST správy **nemajú `member`/`nick`** **[OVERENÉ]**. Klient berie `nick` a farbu (`colorString`)
  z member store naplneného cez gateway. Pri zmene kanála nešiel žiadny REST request na členov **[OVERENÉ]**.
  Member list ide cez gateway (op 14 lazy guild / op 8 request members) **[PREDPOKLAD k opkódom]**.
  Členské objekty s `nick` a `roles` prichádzajú aj v `threads/search` a `post-data` (`owner`) **[OVERENÉ]**.
  REST `GET /guilds/{id}/members/{user_id}` **[PREDPOKLAD]**. Zoznam všetkých členov cez REST je pre user účet
  zrejme nedostupný **[PREDPOKLAD]**.
- **Poradie zobrazenia:** server `nick` → `global_name` → `username`.

## 10. Hlavičky

- **Request hlavičky** na API XHR (iba mená) **[OVERENÉ]**: `Authorization`, `X-Super-Properties`,
  `X-Discord-Locale`, `X-Discord-Timezone`, `X-Debug-Options`. Pri POST aj `Content-Type`, pri jednom POST aj
  `X-Context-Properties`. API volania idú cez **XMLHttpRequest**, nie `fetch`.
- **Response hlavičky** (zjednotenie) **[OVERENÉ]**: `alt-svc, cf-cache-status, cf-ray, content-encoding,
  content-security-policy(-report-only), content-type, date, nel, priority, report-to, reporting-endpoints,
  server, server-timing, strict-transport-security, vary, via, x-content-type-options, x-discord-features,
  access-control-allow-*`.
  **Žiadne `X-RateLimit-*` ani `Retry-After`** sa neobjavili v ~17 odpovediach z 1. kola ani v ~25 z 2. kola
  (všetky `200`/`204`). Zo samotnej odpovede sa teda budget nedá zistiť. V 2. kole sa potvrdila aj rovnaká
  sada request hlavičiek.
- Pri `429` sa očakáva JSON `{"message", "retry_after", "global"}` (reťazec `retry_after` je aj v kóde klienta)
  **[PREDPOKLAD k tvaru]**.

## 11. Snowflake a čas, stránkovanie

- `timestamp_ms = (id >> 22) + 1420070400000` **[OVERENÉ]**:
  `1566570336659439696` → `2026-11-01T21:51:13.729Z`, presne ako `timestamp` správy.
  `1555338520166400000` (dolných 22 bitov 0) → `2026-10-01T22:00:00Z`. Klient si sám generuje „umelé“
  snowflake pre `min_id` v search, rovnako sa dá robiť `before`/`after` podľa času.
- `before=X`: staršie správy ako X, zostupne. `after=X`: novšie ako X, **tiež zostupne** (pre ďalšiu stranu
  treba zobrať **max** ID). `around=X`: okolie X vrátane X **[OVERENÉ]**.

## 12. Ďalšie dostupné dáta (stručne)

- **Téma kanála** `topic`, `icon_emoji`, fórum tagy: v objekte kanála **[OVERENÉ]**.
- **Info o serveri** (popis, `rules_channel_id`, `features`...): v guild objekte **[OVERENÉ]**.
- **Oznamovacie kanály** (type 5: `2bit-info`, `skolni-info`...) sa čítajú rovnako ako textové kanály **[OVERENÉ]**.
  Publikované správy majú `flags & 1`. Študijne sú asi najhodnotnejšie a majú málo správ (`#2bit-info`
  má celkovo 6 správ od 2021).
- **Scheduled events**: klient volal `GET /guilds/{id}/scheduled-events/{event_id}/users/counts` **[OVERENÉ]**.
  Zoznam udalostí: `GET /guilds/{id}/scheduled-events` **[PREDPOKLAD]**.
- **Roly, emoji, nálepky**: gateway. REST `GET /guilds/{id}/roles|emojis|stickers` **[PREDPOKLAD]**.
- Šum, ktorý CLI nepotrebuje: `POST /science`, `POST /metrics/v2` (telemetria), `GET /quests/get-decisions`,
  `GET /applications/public?application_ids=…`.
- **`POST /channels/{id}/messages/{msg_id}/ack`** = označenie ako prečítané. Klient ho volá automaticky pri
  zobrazení kanála alebo vlákna **[OVERENÉ]**. Odpoveď obsahuje ack-`token` (nie auth token).

---

## 13. Dôsledky pre CLI nástroj

1. **Správy, piny, vlákna aj search sú čisto REST** (`/api/v9`). Gateway netreba na sťahovanie obsahu,
   len na „pohodlné“ metadáta (zoznam kanálov, roly, prezývky, aktívne vlákna).
2. **Zoznam kanálov:** REST `GET /guilds/{id}/channels` **[OVERENÉ, sekcia 15]**. Gateway netreba.
   Kanály s `name == "___hidden___"` alebo `flags & (1<<17)` treba **preskočiť**, sú neprístupné.
   Prístup k ostatným stačí overiť pokusom (`403` = Missing Access) alebo výpočtom z `permission_overwrites` + rolí.
3. **Stránkovanie archívu:** od najnovšej `before=<najstaršie_id>&limit=100` až po prázdne pole.
   **Inkrementálny sync:** pre každý kanál uložiť `last_seen_id` a ťahať `after=<last_seen_id>&limit=100`,
   pozor, výsledok je zostupný, ďalšie `after` = **max(id)**. Časové okno vytvoriť syntetickým snowflake
   `((unix_ms − 1420070400000) << 22)`.
4. **Prílohy sťahovať hneď** po získaní správy. Čerstvo získaná URL platí ešte **12–24 h** (`ex`).
   Kontrolovať `ex` (hex unix sekundy) a pri expirácii správu znova načítať (`around=<id>&limit=1`)
   alebo použiť `refresh-urls` **[OVERENÉ, sekcia 15]**. Na CDN netreba `Authorization`. Emoji URL nie sú podpísané.
   `proxy_url` + `?width=…` sa hodí na menšie náhľady pre AI.
5. **Vlákna a fóra:** pre každý textový, announcement a forum kanál prejsť
   `threads/search?archived=true&offset=…` až do `has_more=false`, plus aktívne vlákna cez
   `threads/search?archived=false` **[OVERENÉ, sekcia 15]**.
   Každé vlákno potom ako samostatný kanál cez `/messages`. Pri fórach je prvá správa
   `first_messages[]` (`id == thread_id`) a tagy `applied_tags`.
6. **Odpovede (replies):** `referenced_message` býva v `/messages` (nie v pins ani search). Ak chýba, ostáva
   `message_reference.message_id`, dá sa dohľadať v lokálnej DB alebo cez `around`.
7. **Mená:** cache userov budovať z `author` a `mentions[]`. Nicky sú len z gateway alebo z member objektov
   (`threads/search`, `post-data`). Pre AI súhrn väčšinou stačí `global_name || username`.
   `<@&id>` a `<#id>` prekladať podľa zoznamu rolí a kanálov.
8. **Rate limity:** hlavičky chýbajú, preto **konzervatívny throttling** (napr. 1 request / ~1 s, search
   ešte pomalšie) a obsluha `429` cez `retry_after` z JSON tela. Search je drahý a obmedzený, používať ho len cielene.
9. **Nevolať `ack`** ani nič s POST okrem read-only endpointov. GET na `/messages` sám nič neoznačí ako
   prečítané **[PREDPOKLAD, ack je samostatný request]**.
10. **Hlavičky:** klient posiela `X-Super-Properties`, `X-Discord-Locale`, `X-Discord-Timezone`,
    `X-Debug-Options`. Ich absencia je ľahko rozpoznateľný znak neoficiálneho klienta (riziko ToS je na používateľovi).
11. **Dátový model pre AI:** zo správy stačí `id, channel_id, timestamp, edited_timestamp, author.username/global_name,
    content, attachments[{filename, content_type, size, url}], embeds[{type, url, title, description}],
    message_reference.message_id, type`. Systémové typy (≠ 0, 19) väčšinou filtrovať.

## 14. Neoverené a otvorené otázky

**Overené prototypom 2026-11-03** (výsledky v sekcii 15):
- REST `GET /users/@me/guilds` a `GET /guilds/{id}/channels` fungujú pre user token.
- Maximálny `limit` pre `/messages` je 100.
- Tvar odpovede `POST /attachments/refresh-urls`.
- Aktívne vlákna cez REST: `threads/search?archived=false` funguje, `guilds/{id}/threads/active` je len pre botov.

**Stále otvorené:**
- Tvar odpovede `429`. Pri 13 requestoch s pauzou 1 s nenastal. Rate-limit hlavičky v bežných odpovediach stále chýbajú.
- Stránkovanie pinov pri `has_more: true` (#2bit-general má len 4 piny).
- Či REST vracia aj kanály bez práva `VIEW_CHANNEL` (s reálnym menom). Obfuskované `___hidden___` v odpovedi nie sú.
- Fórum `#help-center` pri `threads/search?archived=false` hlásilo `total_results` 15, ale vrátilo 13 vlákien.
- `refresh-urls` pri už exspirovanej URL. Testovaná URL bola ešte platná a vrátila sa nezmenená.
- Tvar gateway `READY`. Pre CLI ho už netreba, REST stačí.

**Neoverené, lebo sa v dátach nevyskytli** (~410 správ z 9 kanálov + 1 fórum post):
- Raw tvar `sticker_items`, `message_snapshots` (forwardy), `poll`, systémových správ (typy ≠ 0/19),
  `components` s obsahom, `webhook_id`, animovaného emoji v texte (`<a:name:id>`), prílohy s `description` a
  hlasovej správy (`waveform`).

**Ostatné:**
- Search: ďalšie parametre (`author_id`, `max_id`, `mentions`), max `offset`, správanie pri neindexovanom kanáli (202).
  (Search sa v 2. kole podľa pravidiel nepoužíval.)
- Telo requestu `POST /channels/{forum_id}/post-data`.
- Hlavičky CDN requestov som priamo nevidel. Záver „bez Authorization“ vychádza z toho, že ide o `<img>`/`<video>` loady.
- Význam `flags` bitov: kanál `1<<17` (obfuskovaný), `128` (resource), príloha `32` (animated). Pri správach
  sú hodnoty 1/4/32 overené, ich mená pochádzajú z dokumentácie.
- `#otazky-na-poradce` má `last_message_id` z 2024-09-26 (to ID klient aj ackol), REST však ako najnovšiu
  vrátil správu z 2023-01-05. Najnovšia správa je teda asi zmazaná alebo nedostupná. CLI preto nemá
  `last_message_id` kanála považovať za ID existujúcej správy.

## 15. Overenie prototypom (2026-11-03)

**Zdroj:** `prototype/probe.py`, ktorý spustil používateľ. Bolo to 13 API requestov s pauzou 1 s a 1 CDN GET.
Report `prototype/out/probe-20261103-134510.json` je lokálny a git ho ignoruje. Všetko v tejto sekcii je **[OVERENÉ]** (prototyp).

| Otázka | Výsledok |
|---|---|
| `GET /users/@me/guilds` s user tokenom | `200`, 8 serverov, polia `id, name, icon, banner, owner, permissions, features`. `?with_counts=true` pridá `approximate_member_count` |
| `GET /guilds/{id}/channels` | `200`, 412 kanálov. Rozpis nižšie |
| Max `limit` pre `/messages` | `limit=100` vráti 100 správ. `limit=101` vráti `400`, `code 50035 Invalid Form Body` |
| `before` | 100 starších správ, zoradené od najnovšej |
| `after` | vracia **najbližšie** správy po kotve, teda najstaršie z novších, ale zoradené **od najnovšej**. Ďalšia strana ide od `max(id)` |
| `member` v správach | chýba v 0 zo 100 správ |
| Replies | 29 zo 100 správ je typ 19, všetky mali `referenced_message` |
| Piny | `limit=25` vráti 4 položky, `has_more: false` |
| Aktívne vlákna | Dva endpointy, rozpis nižšie |
| CDN bez tokenu | `200`, `image/png`, súbor sa dal čítať bez `Authorization` |
| Platnosť URL | `ex − is` = 24 h. URL z práve načítanej správy platila ešte 21,1 h |
| `POST /attachments/refresh-urls` | `200`, `{"refreshed_urls": [{"original", "refreshed"}]}`. Pri ešte platnej URL vrátil tú istú |
| Rate-limit hlavičky | žiadne `X-RateLimit-*` ani `Retry-After` v 13 odpovediach. Odpovede nastavujú `set-cookie` (mená cookies sa nezaznamenávali) |

**Kanály z `GET /guilds/{id}/channels`:**
- **Počty podľa typu:** 358 text, 22 kategórií, 12 announcement, 10 voice, 9 forum, 1 stage. Sú rovnaké ako viditeľné
  kanály v klientovi.
- **Skryté kanály:** žiadne `___hidden___` ani flag `1<<17`.
- **Nové polia** oproti klientovi: `template`, `voice_background_display`, `voice_hangout`, `default_forum_layout`.
- **Fórum `#help-center`:** `1040350879783604234`.

**Aktívne vlákna:**
- `GET /guilds/{id}/threads/active` vráti `403`, `code 20002 "Only bots can use this endpoint."`.
- `GET /channels/{id}/threads/search?archived=false` funguje:
  - fórum `#help-center`: `total_results` 15, vrátených 13,
  - `#2bit-general`: 1 aktívne vlákno,
  - pri fóre je v odpovedi aj `first_messages`.

---

## Vedľajšie účinky analýzy

### 1. kolo
- **Omylom odoslaná správa** (pozri incident hore): text `cdn.discordapp.com` vo vlákne
  `Dotaz ohledně Automaticky udělovaného zápočtu` (fórum `#help-center`, thread `1566814241946738698`),
  3. 11. 2026 00:07. **Používateľ ju zmazal.** Vlákno ostalo sledované (v 2. kole bolo v sidebari pod
  `#help-center`). Príčina: po zatvorení search panelu sa kurzor a klik dostali do composera vlákna a
  `Enter` správu odoslal.
- **Označené ako prečítané** (ack requesty): `#2bit-terminy`, fórum `#help-center`, vlákno
  `Dotaz ohledně Automaticky udělovaného zápočtu`. Prezeraný bol aj `#2bit-general` (už otvorený používateľom).
- **História vyhľadávania** v Discorde obsahuje nové dotazy: `zápočet`, `has:file after:2026-10-01 in:2bit-general`,
  `cdn.discordapp.com attachments`, `cdn.discordapp.com`.
- V mojej karte bežal pasívny XHR/fetch observer (iba v pamäti tej karty).
- Pri volaní `tabs_close_mcp` na moju kartu nástroj vrátil „The browser is shutting down“ a Chrome sa odpojil.

### 2. a 3. kolo (prísne pravidlá: bez klávesnice, bez searchu)
- **Prezreté kanály** (kliky iba na názvy v sidebari): `#2bit-info`, `#vote-room`, `#skolni-info`, `#hlasky`,
  `#otazky-na-poradce`, `#english-general`, `#2bit-general` (scroll ~200 správ dozadu) a `#general`
  (scroll ~110 správ dozadu).
- **Ack (označené ako prečítané)** zachytené pre `#2bit-info`, `#hlasky` (mal značku „NEW“, teda bol
  neprečítaný) a `#otazky-na-poradce`. Pre `#vote-room` a `#skolni-info` ack záznam nemám, lebo časť
  network logu som vymazal. Ak boli neprečítané, sú teraz prečítané. **`#general` bol pred otvorením
  neprečítaný (tučný)** a teraz je takmer určite označený ako prečítaný. `#english-general` a `#2bit-general`
  boli už prečítané.
- V `#2bit-general` som raz otvoril a tým istým tlačidlom v hlavičke zatvoril panel Threads.
- Sidebar som niekoľkokrát posunul cez `scrollTop` v JS a raz scroll akciou nad sidebarom. Mení to len
  zobrazenie, nie dáta.
- V mojich kartách bežal pasívny XHR observer (len telá odpovedí; v 2. kole aj mená request hlavičiek, nikdy hodnoty).
- 2. kolo: `tabs_close_mcp` znova vrátil „The browser is shutting down“ a Chrome sa odpojil.
- 3. kolo: karta (`#general`) **ostala otvorená** podľa pokynu. Používateľ ju zatvorí sám.
- Žiadny vstup z klávesnice, žiadne kliky do zoznamu správ, na reakcie, composer, Follow ani Join.
  Žiadne POST requesty okrem automatických `ack`, `science` a `metrics`.
