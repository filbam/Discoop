# Prístup ku kanálom: ako cez REST zistiť, ktoré kanály používateľ vidí

Dátum: 2026-11-03. Typ: prieskum dokumentácie a zdrojového kódu knižníc. **Žiadne volanie Discord API**,
žiadny prehliadač s Discordom.

**Legenda:** **[OVERENÉ]** = pozorované na účte používateľa (prototyp, test `discoop channels`, analýza
[discord-analyza.md](discord-analyza.md)) alebo priamo v kóde tohto repa.
**[PREDPOKLAD]** = z dokumentácie alebo cudzieho kódu, na účte používateľa zatiaľ neoverené. Zdroj je uvedený
v zátvorke a v sekcii [Zdroje](#zdroje).

**Metodika:**
- Oficiálna dokumentácia: `github.com/discord/discord-api-docs` (stav `main` k 2026-11-03), stránky
  `docs.discord.com/developers/...`.
- Neoficiálna dokumentácia user API: docs.discord.food (Discord Userdoccers), čítaná z repa
  `discord-userdoccers/discord-userdoccers`. Pri kľúčových bodoch som cez `git log -S` dohľadal, kedy pribudli.
- Doplnkový dôkaz: `discord.py-self` (výpočet práv, HTTP routy) a `DiscordChatExporter` (ako zaobchádza
  s nedostupnými kanálmi).
- Z anonymizovaného reportu `prototype/out/probe-20261103-134510.json` som čítal iba zoznamy polí.

---

## 1. Zhrnutie

| # | Otázka | Odpoveď v skratke |
|---|---|---|
| 1 | Roly prihláseného používateľa | `GET /users/@me/guilds/{guild_id}/member` (odporúčané), záloha `GET /guilds/{guild_id}/members/{user_id}`. Oba **[PREDPOKLAD]** |
| 2 | Pole `permissions` v `/users/@me/guilds` | Práva na úrovni servera (@everyone + všetky roly), **bez** overwrites a implicitných pravidiel. Ownera treba riešiť cez `owner`, admina cez bit `ADMINISTRATOR`. `/guilds/{id}/roles` netreba **[PREDPOKLAD]** |
| 3 | Algoritmus | base → owner/ADMINISTRATOR → @everyone overwrite → zjednotené role overwrites → member overwrite → implicitné pravidlá. Kategórie sa v API nededia, vlákna dedia z rodiča **[PREDPOKLAD]** |
| 4 | `___hidden___` a `is_hidden` | Obfuskácia kanálov bez `VIEW_CHANNEL`, ktorú robí **iba gateway**. REST flag `1<<17` nikdy nenastaví, takže `is_hidden` v REST ceste nič nefiltruje. S opt-in kanálmi to nesúvisí |
| 5 | `/messages` bez prístupu | Bez `VIEW_CHANNEL`: `403` s kódom `50001` Missing Access. S `VIEW_CHANNEL`, ale bez `READ_MESSAGE_HISTORY`: `200` a prázdne pole **[PREDPOKLAD]** |

**Dve nové zistenia menia odporúčanie:**
1. **`GET /guilds/{id}/channels?permissions=true`** podľa Userdoccers vráti pri každom kanáli pole `permissions`.
   Sú to práva prihláseného používateľa v kanáli **vrátane overwrites**, vypočítané serverom. Ak to platí,
   roly ani výpočet netreba a nepribudne ani jeden request **[PREDPOKLAD]**.
2. **Discord oznámil, že REST prestane vracať kanály bez `VIEW_CHANNEL`** (changelog 2026-08-12). Pre botov
   to platí povinne od **2026-11-16**, pre používateľov „čoskoro“ bez dátumu **[PREDPOKLAD]**. Problém z testu sa
   teda môže časom vyriešiť sám. Výpočet prístupu však treba aj potom: `READ_MESSAGE_HISTORY` a `CONNECT`
   REST nefiltruje.

## 2. Východisko

- `GET /guilds/{id}/channels` s user tokenom vracia aj kanály, ktoré používateľ nevidí, s reálnym menom
  (napr. kategórie `moderation`, `logging`, `fillers` a kanál `1549737445002584094`) **[OVERENÉ]**
  ([discord-analyza.md, sekcia 15](discord-analyza.md#15-overenie-prototypom-2026-11-03)).
- Kanály z REST majú polia `permission_overwrites` a `flags`. Pole `permissions` v nich nie je,
  lebo prototyp `?permissions=true` neposlal **[OVERENÉ]** (zoznam polí v reporte probe).
- Overwrite má tvar `{id, type, allow, deny}`. `type 0` je rola, `type 1` je člen, `allow`/`deny` sú stringy
  s bitovým poľom. @everyone má `id = guild_id` **[OVERENÉ]** (analýza, sekcia 3).
- `GET /users/@me/guilds` vracia polia `id, name, icon, banner, owner, permissions, features` **[OVERENÉ]**.
  Nástroj dnes `owner` ani `permissions` neukladá **[OVERENÉ]** (`server_from_api` v `models.py`).
- Chybové telo má tvar `{"message", "code"}`. Príklad: `guilds/{id}/threads/active` vrátil `403`
  s kódom `20002` **[OVERENÉ]**.
- `#2bit-terminy` má @everyone `deny` s bitom `VIEW_CHANNEL` a roly s `allow 1024` **[OVERENÉ]**. Je to typický
  vzor súkromného kanála na VUT FIT.

**Bity, ktoré nástroj potrebuje** (permissions topic, **[PREDPOKLAD]**, hodnoty sú stabilné):

| Bit | Hodnota | Meno |
|---|---|---|
| `1 << 3` | 8 | `ADMINISTRATOR` |
| `1 << 10` | 1024 | `VIEW_CHANNEL` |
| `1 << 11` | 2048 | `SEND_MESSAGES` |
| `1 << 16` | 65536 | `READ_MESSAGE_HISTORY` |
| `1 << 20` | 1048576 | `CONNECT` |
| `1 << 34` | 17179869184 | `MANAGE_THREADS` |

Bitové polia sú v API v9 stringy a môžu presiahnuť 32 bitov. V Pythone stačí `int(...)`, v SQLite ich treba
ukladať ako `TEXT` **[PREDPOKLAD]** (oficiálny permissions topic).

## 3. Otázka 1: roly prihláseného používateľa

| Endpoint | User token | Požiadavky | Čo vráti | Poznámka |
|---|---|---|---|---|
| `GET /users/@me/guilds/{guild_id}/member` | áno **[PREDPOKLAD]** (Userdoccers: route pre usera a OAuth2, bez bot značky) | byť členom servera. Scope `guilds.members.read` platí len pre OAuth2 aplikácie, user token scopes nemá | **private** guild member objekt: `user`, `nick`, `roles[]`, `joined_at`, `pending`, `communication_disabled_until`, `flags` a navyše `permissions` (celkové práva na serveri) | jediný request dá roly aj base práva z toho istého okamihu. Boti tento endpoint nemajú |
| `GET /guilds/{guild_id}/members/{user_id}` | áno **[PREDPOKLAD]** (Userdoccers, `discord.py-self` `fetch_member`, `DiscordChatExporter` `TryGetGuildMemberAsync`) | byť členom, poznať vlastné user ID (`GET /users/@me` alebo uložené po `login`) | verejný member objekt: `roles[]`, `pending`, `communication_disabled_until`, `flags`. **Bez** `permissions` | záloha |
| `GET /guilds/{guild_id}/channels?permissions=true` | áno **[PREDPOKLAD]** (Userdoccers od 2024-06-02) | byť členom (inak sa `permissions` nevráti) | kanály + `permissions` pre volajúceho v každom kanáli, vrátane overwrites | **roly vôbec netreba**. Je to ten istý request ako dnes |
| `GET /guilds/{guild_id}/permissions/member/{user_id}` | neznáme, endpoint je nový (changelog 2026-10-30) | neuvedené | `{permissions}` len na úrovni servera | rolí nedá, na overwrites nestačí |
| `GET /channels/{id}/permissions/member/{user_id}` | neznáme (2026-10-30) | vyžaduje `VIEW_CHANNEL`, pri hlasových aj `CONNECT` | `{permissions}` v kanáli, predvolene s implicitným maskovaním (`implicit=false` ho vypne) | 1 request na kanál (~390) a pri nedostupnom kanáli `403`. Nevhodné |
| `GET /users/{user_id}/profile?guild_id=…` | áno **[PREDPOKLAD]** (Userdoccers) | – | profil + private `guild_member` | ťažký request na iný účel, nepoužívať |
| `GET /guilds/{guild_id}/members` | **nie** pre user účty **[PREDPOKLAD]** (Userdoccers) | – | – | nepoužiteľné |

**Rate limity** **[PREDPOKLAD]**:
- Discord limity jednotlivých routes nezverejňuje, sú dynamické podľa bucketu. Globálny limit je 50 requestov za sekundu
  (Userdoccers, rate limits).
- Pre user token chodia rate-limit hlavičky len pri `429` (Userdoccers). Prototyp ich v bežných odpovediach
  nevidel **[OVERENÉ]**.
- **Neplatné requesty** (`401`, `403`, `429`) majú vlastný limit: 10 000 za 10 minút, inak IP ban na 24 h
  (Userdoccers, rate limits). Je to ďalší dôvod, prečo prístup **nezisťovať skúšaním každého kanála**.
- Nástroj volá 1 request za sekundu sekvenčne. Pri jednom requeste navyše na server limit nehrozí.

**Odporúčanie:**
- **Hlavný:** `GET /users/@me/guilds/{guild_id}/member`. Dá roly aj `permissions` naraz a nepotrebuje user ID.
- **Záloha:** `GET /guilds/{guild_id}/members/{user_id}`. Base práva potom treba vziať z `/users/@me/guilds`.
- **Ešte lepšie**, ak sa potvrdí: `?permissions=true` na existujúcom zozname kanálov. Roly sú potom potrebné len
  ako fallback (sekcia 9.1).

## 4. Otázka 2: pole `permissions` v `GET /users/@me/guilds`

- **Obsah:** celkové práva používateľa na serveri, teda @everyone OR všetky jeho roly. **Neobsahuje overwrites**
  kanálov ani implicitné pravidlá **[PREDPOKLAD]** (oficiálny Guild object, footnote k `owner`/`permissions`;
  Userdoccers, User Guild Object).
- **Owner:** odpoveď má samostatné pole `owner`. Oficiálny príklad pritom ukazuje `owner: true` s neúplnými
  `permissions` (`"36953089"`). Na `permissions` sa preto pri ownerovi nespoliehať a `owner == true` brať ako
  všetky práva **[PREDPOKLAD]**.
- **Admin:** ak niektorá rola má `ADMINISTRATOR`, bit 8 je v `permissions`. Či server doplní aj ostatné bity, nie je
  zdokumentované. Stačí kontrolovať bit 8 a potom ignorovať overwrites **[PREDPOKLAD]**.
- **Timeout** dokumentácia pri tomto poli nespomína. Na čítanie to nevadí, timeout `VIEW_CHANNEL` ani
  `READ_MESSAGE_HISTORY` neberie (sekcia 5).
- **`GET /guilds/{id}/roles` netreba.** Práva rolí sú už zložené v `permissions`. Na overwrites stačia **ID**
  rolí člena. Roly servera budú treba až pri `messages` na preklad `<@&id>` na meno, alebo ako núdzový výpočet base
  práv (`@everyone.permissions | práva rolí člena`), keby `permissions` chýbalo.
- **Pozor na čas:** `permissions` z `/users/@me/guilds` a roly z member endpointu pochádzajú z dvoch requestov
  v rôznom čase. Private member objekt má vlastné `permissions`, preto je výhodnejší zdroj (sekcia 3).

## 5. Otázka 3: algoritmus výpočtu práv kanála

Poradie podľa oficiálneho permissions topicu (sekcia Permission Overwrites) a `discord.py-self`
(`GuildChannel.permissions_for`) **[PREDPOKLAD]**:

```python
VIEW_CHANNEL, READ_MESSAGE_HISTORY, CONNECT, ADMINISTRATOR = 1 << 10, 1 << 16, 1 << 20, 1 << 3
ALL = (1 << 64) - 1  # dnešné bity sú pod 1 << 64; owner a admin majú všetko


def base_permissions(owner: bool, guild_permissions: int) -> int:
    if owner or guild_permissions & ADMINISTRATOR:
        return ALL
    return guild_permissions                      # @everyone | roly (z API už zložené)


def channel_permissions(base: int, overwrites: list[dict], guild_id: str,
                        role_ids: set[str], user_id: str) -> int:
    if base == ALL:                               # ADMINISTRATOR obchádza všetky overwrites
        return ALL
    by_key = {(int(o["type"]), o["id"]): o for o in overwrites}
    perms = base
    if everyone := by_key.get((0, guild_id)):     # 1. @everyone overwrite
        perms = (perms & ~int(everyone["deny"])) | int(everyone["allow"])
    allow = deny = 0                              # 2. roly: najprv zjednotiť, potom naraz
    for role_id in role_ids - {guild_id}:
        if o := by_key.get((0, role_id)):
            allow |= int(o["allow"])
            deny |= int(o["deny"])
    perms = (perms & ~deny) | allow               # allow ktorejkoľvek roly prebije deny inej roly
    if member := by_key.get((1, user_id)):        # 3. overwrite pre samotného člena
        perms = (perms & ~int(member["deny"])) | int(member["allow"])
    return perms
```

Poznámky k výpočtu:
- Poradie rolí v hierarchii **nehrá rolu**. Allow jednej roly prebije deny inej roly v tom istom kanáli
  **[PREDPOKLAD]** (permissions topic, Permission Hierarchy).
- `member.roles` @everyone neobsahuje. Overwrite @everyone sa aplikuje zvlášť a v cykle rolí sa nesmie
  zopakovať **[PREDPOKLAD]**. Oficiálny pseudokód má chybu: `overwrites` používa pred priradením.
  `discord.py-self` robí to isté v správnom poradí.

**Výsledný prístup** pre CLI:

```python
def access(perms: int | None, channel_type: int, flags: int) -> str:
    if perms is None:
        return "unknown"
    if flags & (1 << 17) or not perms & VIEW_CHANNEL:
        return "none"                             # nevidí kanál, ostatné bity sú irelevantné
    if channel_type in (2, 13) and not perms & CONNECT:
        return "view"                             # vidí v sidebare, text v hlasovom kanáli nečíta
    if not perms & READ_MESSAGE_HISTORY:
        return "view"                             # vidí, ale /messages vráti prázdne pole
    return "read"
```

**Špeciálne prípady:**

| Prípad | Pravidlo | Zdroj |
|---|---|---|
| Owner servera | všetky práva, overwrites sa ignorujú | oficiálny pseudokód `compute_base_permissions` **[PREDPOKLAD]** |
| `ADMINISTRATOR` | všetky práva, obchádza overwrites | permissions topic, bit table **[PREDPOKLAD]** |
| Bez `VIEW_CHANNEL` | implicitne žiadne ďalšie práva v kanáli | Implicit Permissions; `discord.py-self` `_apply_implicit_permissions` **[PREDPOKLAD]** |
| Bez `READ_MESSAGE_HISTORY` | `GET /messages` nevráti žiadne správy | oficiálny Get Channel Messages, Userdoccers List Messages **[PREDPOKLAD]** |
| Hlasový a stage kanál (typ 2, 13) | čítanie správ potrebuje navyše `CONNECT`. Bez `CONNECT` sú implicitne odobraté hlasové práva aj správa kanála | Get Channel Messages; `discord.py-self` `VoiceChannel.permissions_for` **[PREDPOKLAD]** |
| Pripojenie v hlase | kanál je „viditeľný“ aj bez `VIEW_CHANNEL`, ak je používateľ v ňom pripojený | Obfuscated Channels **[PREDPOKLAD]**. Pre CLI irelevantné, nikam sa nepripája |
| **Kategórie** | **v API sa nič nededí.** Každý kanál má vlastné `permission_overwrites`. „Synced“ kanál má len kópiu overwrites kategórie. Kategória je „viditeľná“, ak je viditeľný aspoň jeden jej kanál | Permission Syncing; Obfuscated Channels **[PREDPOKLAD]**. Vlastné overwrites kanála **[OVERENÉ]** (`#2bit-terminy`) |
| Verejné vlákna (typ 10, 11) | dedia práva z rodičovského kanála. Výnimka: písanie potrebuje `SEND_MESSAGES_IN_THREADS` namiesto `SEND_MESSAGES`. `VIEW_CHANNEL` na rodičovi treba vždy, aj keď je používateľ vo vlákne spomenutý alebo pridaný | Inherited Permissions (Threads); `discord.py-self` `Thread.permissions_for` **[PREDPOKLAD]** |
| Súkromné vlákna (typ 12) | navyše treba byť členom vlákna alebo mať `MANAGE_THREADS` | Userdoccers Threads **[PREDPOKLAD]** |
| Fórum a media (typ 15, 16) | samo fórum správy nemá. Posty sú verejné vlákna a dedia práva fóra (`VIEW_CHANNEL` + `READ_MESSAGE_HISTORY` na fóre) | z pravidla pre vlákna **[PREDPOKLAD]** |
| `threads/search`, archívy | vracia len vlákna, ku ktorým má používateľ prístup. Verejné archivované vlákna vyžadujú `READ_MESSAGE_HISTORY`, súkromné archivované aj `MANAGE_THREADS` | Userdoccers Threads; oficiálny Channel resource **[PREDPOKLAD]** |
| Timeout (`communication_disabled_until` v budúcnosti) | ostanú len `VIEW_CHANNEL` a `READ_MESSAGE_HISTORY`. Owner a admin majú výnimku. Maska ide **úplne na koniec** výpočtu | permissions topic; `discord.py-self` `_timeout_mask` **[PREDPOKLAD]**. **Na čítanie bez vplyvu** |
| Karanténa AutoMod (`flags` člena `1<<7`, `1<<10`) | ako timeout, navyše ostáva `CHANGE_NICKNAME` | Userdoccers permissions **[PREDPOKLAD]**. Na čítanie bez vplyvu |
| Membership screening (`pending: true`) | kým člen neprejde screeningom, nemôže písať. Čítanie sa riadi právami. Pri vypnutom „preview“ je `pending` vždy `false` | oficiálny Add Guild Member; Userdoccers Guild Member **[PREDPOKLAD]**. Pre výpočet čítania bez vplyvu, stačí upozornenie |
| Obfuskovaný kanál (flag `1<<17`) | znamená, že používateľ nemá `VIEW_CHANNEL` | oficiálny Channel resource **[PREDPOKLAD]**. V REST sa nevyskytuje (sekcia 6) |

## 6. Otázka 4: `___hidden___`, flag `1<<17`, `is_hidden` a opt-in kanály

**Čo je `___hidden___`:**
- Je to **channel obfuscation**: kanál, na ktorý používateľ nemá `VIEW_CHANNEL`, príde cez **gateway**
  s menom `___hidden___` (aj topic), flagom `CHANNEL_OBFUSCATED` (`1 << 17`) a jediným overwrite
  „@everyone deny `VIEW_CHANNEL`“. Ostatné citlivé polia sú vynulované **[PREDPOKLAD]** (oficiálny Channel resource,
  Obfuscated Channels; Userdoccers flag `OBFUSCATED` od 2024-12-15).
- Presne takýto záznam bol v stave webového klienta **[OVERENÉ]** (analýza, sekcia 3).
  Mal aj `parent_id: null`. Oficiálna dokumentácia pre botov sľubuje, že `id`, `type`, `position` a `parent_id`
  ostanú zachované. Klient používateľa však `parent_id` stratil **[OVERENÉ]** (rozdiel oproti dokumentácii).
- Podľa dokumentácie **HTTP API flag `1<<17` nikdy nenastaví**. Namiesto toho budú nedostupné kanály z
  `GET /guilds/{id}/channels` vynechané **[PREDPOKLAD]**. Pre používateľov to zatiaľ neplatí: REST ich vracia
  s reálnym menom a bez flagu **[OVERENÉ]**.
- Na detekciu má slúžiť flag. Na `name` sa podľa dokumentácie spoliehať nemá **[PREDPOKLAD]**.

**Kontrola `is_hidden` v `src/discoop/models.py`** (`name == "___hidden___"` alebo `flags & (1 << 17)`) **[OVERENÉ, kód]**:
- Kontroluje **gateway obfuskáciu**, ktorú REST neposiela. V REST ceste preto nikdy nič nevyfiltruje.
  Prototyp našiel 0 takých kanálov **[OVERENÉ]**.
- Nie je škodlivá, ale je **zavádzajúca**: vyzerá ako skrývanie nedostupných kanálov, no to nerobí.
  Test `tests/test_servers_channels.py` má fixture `___hidden___`, aký REST neposiela.
- Kontrola mena je navyše proti odporúčaniu dokumentácie. Kanál sa môže legálne volať `___hidden___`.
- **Návrh:** `is_hidden` nahradiť výpočtom prístupu (sekcia 9). Flag `1<<17` ponechať len ako obrannú
  podmienku „`access = none`“, kontrolu mena zrušiť.

**Opt-in kanály (Browse Channels, Channels & Roles, onboarding)** s tým **nesúvisia**:
- Opt-in je **zobrazovacia preferencia používateľa**, nie prístup. Je v user guild settings: flag servera
  `OPT_IN_CHANNELS_ON` (`1 << 14`) a pri kanáli `channel_overrides[].flags & OPT_IN_ENABLED` (`1 << 12`,
  „kanál sa zobrazuje v UI“) **[PREDPOKLAD]** (Userdoccers, User Settings).
- Kanál, ktorý si používateľ nezobrazil, má stále `VIEW_CHANNEL`. Gateway ho neobfuskuje a REST ho vracia
  normálne. CLI ho má vypisovať ako dostupný.
- Onboarding môže pri výbere odpovede **pridať roly** (`role_ids`). To je skutočný prístup a výpočet z rolí ho
  zachytí. `default_channel_ids` a `channel_ids` v onboardingu znamenajú len opt-in zobrazenie **[PREDPOKLAD]**
  (Userdoccers, Onboarding).
- User guild settings chodia cez gateway (`READY`). REST na ich čítanie Userdoccers neuvádza, uvádza len `PATCH`
  **[PREDPOKLAD]**. CLI ich nepotrebuje.
- **Súvisiaci prípad:** `readme-cz`/`readme-en` majú `flags: 128` **[OVERENÉ]**. Je to `IS_GUILD_RESOURCE_CHANNEL`
  (`1 << 7`): resource kanál z onboardingu / Server Guide, ktorý sa nezobrazuje v zozname kanálov
  **[PREDPOKLAD]** (Userdoccers, Channel Flags). Ak má používateľ `VIEW_CHANNEL`, je čitateľný. CLI ho môže
  vypísať, prípadne s označením `resource`.
- Údaj „renderLevel 1 = nezobrazený: 74 záznamov“ z analýzy (sekcia 3) asi mieša obfuskované kanály,
  resource kanály a neoptované kanály. Bez gateway sa to nedá rozlíšiť a pre CLI to netreba **[PREDPOKLAD]**.

## 7. Otázka 5: čo vráti `GET /channels/{id}/messages` bez prístupu

Oficiálne: endpoint vyžaduje `VIEW_CHANNEL`, pri hlasovom kanáli aj `CONNECT`. Bez `READ_MESSAGE_HISTORY` vráti
prázdny výsledok **[PREDPOKLAD]** (Get Channel Messages; Userdoccers List Messages).

| Situácia | Očakávaná odpoveď | Istota |
|---|---|---|
| Člen servera, kanál bez `VIEW_CHANNEL` | `403`, `{"message": "Missing Access", "code": 50001}` | **[PREDPOKLAD]** (kód 50001 v oficiálnej tabuľke chýb; hlásenia z `discord.js-selfbot-v13` a `discord-server-copy`) |
| Hlasový/stage kanál bez `CONNECT` | `403`, pravdepodobne `50001` | **[PREDPOKLAD]** |
| `VIEW_CHANNEL` bez `READ_MESSAGE_HISTORY` | `200` a `[]` | **[PREDPOKLAD]**. Nedá sa odlíšiť od prázdneho kanála, rozlíši to len výpočet práv |
| Súkromné vlákno, v ktorom používateľ nie je (a nemá `MANAGE_THREADS`) | `403`, `50001` | **[PREDPOKLAD]** |
| Kanál na serveri, kde používateľ nie je | `403`, `50001` | **[PREDPOKLAD]** |
| Neexistujúci alebo zmazaný kanál, zlé ID | `404`, `10003` Unknown Channel | **[PREDPOKLAD]** |
| Akcia vyžadujúca právo (napr. písanie) | `403`, `50013` „You lack permissions…“ | **[PREDPOKLAD]**. Pri GET správ sa neočakáva, ale treba ho mapovať rovnako ako `50001` |
| Blok anti-abuse systémom | `403` s kódom `10008` „Unknown Message“, prípadne iný nezmyselný kód | **[PREDPOKLAD]** (Userdoccers, Errors) |
| Blok Cloudflare | kód `40333` | **[PREDPOKLAD]** (Userdoccers, Errors) |

`DiscordChatExporter` žiadne práva vopred nepočíta. Každý kanál skúsi, `403` zapíše ako chybu kanála („forbidden“)
a pokračuje. Celý export zlyhá, až keď zlyhajú všetky kanály **[PREDPOKLAD]** (`ExportCommandBase.cs`,
`DiscordClient.cs`). Pre `discoop` je lepšie nedostupné kanály vynechať vopred (sekcia 3, limit neplatných requestov).

**Mapovanie pre budúci `messages`:**
- `403` + `50001` alebo `50013` → kanál sa preskočí s varovaním. Pri jedinom zadanom kanáli exit `5` (`NO_ACCESS`).
  Do cache sa zapíše `access = none`.
- `404` + `10003` → exit `4` (`NOT_FOUND`) a rada `discoop channels --refresh`.
- `403` s iným kódom (`10008`, `40333`, …) → exit `1` s rozlíšenou hláškou. Nie je to „nemáš prístup“.
- `200 []` pri kanáli s `access = view` → varovanie „no READ_MESSAGE_HISTORY“, exit `0`.

## 8. Plánovaná zmena na strane Discordu

- **Changelog 2026-08-12, „Channel Obfuscation for Users and Bots“** **[PREDPOKLAD]**:
  - Používatelia čoskoro prestanú dostávať plné údaje o kanáloch, ktoré nevidia. Gateway ich obfuskuje
    a `GET /guilds/{id}/channels` ich vynechá.
  - Pre botov je to povinné od **2026-11-16**. Dátum pre používateľov nie je uvedený.
  - Gateway obfuskácia pre používateľa už beží **[OVERENÉ]** (`___hidden___` v klientovi). REST pre používateľa
    k 2026-11-03 ešte nefiltruje **[OVERENÉ]**.
- **Changelog 2026-10-30:** štyri nové endpointy na vypočítané práva (sekcia 3). Či fungujú s user tokenom,
  nie je známe **[PREDPOKLAD]**.
- **Dôsledky pre `discoop`:**
  - Po zmene REST zmiznú nedostupné kanály z odpovede a `--include-hidden` neukáže nič navyše. Treba s tým
    počítať v helpe aj v testoch.
  - Kategória s aspoň jedným viditeľným kanálom ostane v odpovedi, aj keď sama `VIEW_CHANNEL` nemá. Zobrazenie
    „kategória sa ukáže, ak má zobrazený kanál“ je preto správne v oboch režimoch.
  - `READ_MESSAGE_HISTORY` a `CONNECT` REST filtrovať nebude. Výpočet prístupu treba aj potom.

## 9. Odporúčanie pre implementáciu

### 9.1 Requesty

Poradie pri obnove kanálov servera (`Directory._fetch_channels`):

1. `GET /guilds/{id}/channels?permissions=true` namiesto dnešného requestu.
   Ak majú všetky kanály (okrem kategórií) pole `permissions`, použije sa (zdroj `server`).
   **Pribudne 0 requestov.**
2. **Fallback**, ak `permissions` chýba: `GET /users/@me/guilds/{id}/member` → `roles`, `user.id`
   a `permissions`. Ak `permissions` v odpovedi nie je, base sa vezme z `owner`/`permissions` z `/users/@me/guilds`
   (cache `servers`, pri chýbajúcej hodnote obnoviť). Výpočet podľa sekcie 5 (zdroj `computed`).
   **Pribudne 1 request na server.**
3. **Záloha**, ak member endpoint vráti `403`/`404`: `GET /guilds/{id}/members/{user_id}`. User ID je z
   `/users/@me`, ideálne uložené už pri `login` alebo v cache. **Pribudne 1 až 2 requesty.**
4. Ak zlyhá aj to: `permissions = NULL` → prístup `unknown` (sekcia 9.5).

`GET /guilds/{id}/roles` netreba. Pribudne až s `messages` kvôli menám rolí.

### 9.2 Cache (`src/discoop/cache.py`)

`SCHEMA_VERSION` zvýšiť o 1 (k 2026-11-03 je `1`, takže na `2`, ak ho medzitým nezvýši práca na `messages`).
`_migrate` cache zahodí a postaví znova **[OVERENÉ, kód]**, prechod je teda bez rizika. Nová metóda `Cache.channel()`
z práce na `messages` bude potrebovať tie isté nové stĺpce.

| Tabuľka | Nový stĺpec | Typ | Účel |
|---|---|---|---|
| `servers` | `owner` | `INTEGER NOT NULL DEFAULT 0` | z `/users/@me/guilds`, pre fallback |
| `servers` | `permissions` | `TEXT` | base práva na serveri z `/users/@me/guilds`, pre fallback |
| `channels` | `flags` | `INTEGER NOT NULL DEFAULT 0` | `1<<17` (obranne), `1<<7` (resource kanál) |
| `channels` | `permissions` | `TEXT` (NULL = neznáme) | efektívne práva prihláseného používateľa v kanáli |
| `channels` | `overwrites` | `TEXT` (JSON), voliteľné | prepočet bez nového requestu, ladenie |

- Prístup (`read`/`view`/`none`/`unknown`) sa **neukladá**. Počíta sa v Pythone z `permissions`, `type` a `flags`.
- Roly sa ukladať nemusia. Počítajú sa pri obnove kanálov a výsledok je v `channels.permissions`.
- Bitové polia ako `TEXT`, lebo SQLite `INTEGER` je 64-bit so znamienkom.
- Zmena rolí na serveri sa prejaví až po `--refresh`. Upozornenie na vek cache, ktoré už existuje, to pokrýva.

### 9.3 Nový modul `src/discoop/permissions.py`

Čisté funkcie bez I/O, ľahko testovateľné na anonymizovaných fixtures:
- konštanty bitov (`VIEW_CHANNEL`, `READ_MESSAGE_HISTORY`, `CONNECT`, `ADMINISTRATOR`, `MANAGE_THREADS`, `ALL`),
- `parse_bits(value: str | int | None) -> int | None`,
- `base_permissions(owner, guild_permissions) -> int`,
- `channel_permissions(base, overwrites, guild_id, role_ids, user_id) -> int`,
- voliteľne `apply_timeout(perms, timed_out_until, now)`, s maskou na konci a s výnimkou pre owner/admin,
- `access(perms, channel_type, flags) -> Access` (`StrEnum`: `read`, `view`, `none`, `unknown`).

Ďalšie zmeny:
- `models.Channel` dostane `permissions: int | None` a `flags: int` a property `access`. `models.Server` dostane
  `owner` a `permissions`.
- `is_hidden` zmizne (sekcia 6).

**Testy:**
- @everyone deny `VIEW` + allow pre rolu, ktorú člen má / nemá,
- allow jednej roly prebije deny inej roly,
- member overwrite prebije rolu,
- owner, admin,
- hlasový kanál bez `CONNECT`,
- kanál bez `READ_MESSAGE_HISTORY`,
- flag `1<<17`,
- chýbajúce `permissions` → `unknown`.

### 9.4 Správanie `channels`

- **Predvolene** sa vypíšu kanály s prístupom `read`, `view` a `unknown`. Kanály `none` sa skryjú.
- **Kategórie** sa riadia obsahom: zobrazí sa kategória, ktorá má aspoň jeden zobrazený kanál. Vlastné práva
  kategórie sa neposudzujú. Zodpovedá to pravidlu Discordu (sekcia 8) aj dnešnému `group_by_category`, ktoré
  prázdne skupiny vyhodí.
- **`--include-hidden`** ukáže aj `none`. V human režime sú stlmené s označením `[no access]`, pri celých
  skrytých kategóriách aj kategória.
- **`view`** (vidí, ale nečíta históriu, alebo hlasový kanál bez `CONNECT`) sa zobrazí so značkou
  `(no history)`.
- **Agent režim:** pribudne stĺpec `access` na konci: `id type category name access`. Hodnoty sú
  `read|view|none|unknown`. Zmenu formátu treba zapísať do návrhu (4.3) a do `agent-guide`.
- **Súhrn** (stderr): `N channels (M without access hidden, use --include-hidden)`.
- **Hľadanie mien:**
  - Presné ID alebo meno nájde aj kanál `none`. `messages` potom skončí kódom `5` bez volania API, čo je
    lepšia rada než „nenájdené“.
  - Globy (`-c "isc-*"`) a `--all-channels` berú len kanály `read`.

### 9.5 Keď prístup nejde zistiť

- Všetky kanály majú `access = unknown`, nič sa neskrýva a exit kód ostáva `0`.
- Na stderr ide **upozornenie viditeľné aj pre agenta** (nielen s `--verbose`), napr.
  `WARNING: Channel access could not be determined; all channels are listed, some may be unreadable.`
  Na to slúži `Output.warning()`, ktorú paralelne pridáva práca na `messages`. Výpis `WARNING: …` ide na stderr
  aj bez `--verbose`. `note()` agent bez `--verbose` nevidí **[OVERENÉ, kód k 2026-11-03]**.
- V `--verbose` sa pridá dôvod (napr. `member endpoint returned 403 (code 50001)`).
- Pri ďalšom `--refresh` sa výpočet skúsi znova.

### 9.6 Plán overenia (spustí používateľ)

Malý nový skript, napr. `prototype/access_probe.py`, v štýle `probe.py`: 1 request za sekundu, iba GET,
report do `prototype/out/` len so štruktúrou. Bez mien rolí, user ID a textov. ID kanálov a mená kategórií
servera sú v poriadku, analýza ich už obsahuje.

| # | Request | Čo zaznamenať | Očakávanie |
|---|---|---|---|
| 1 | `GET /users/@me/guilds` | `owner`, či `permissions` obsahuje `VIEW_CHANNEL`/`ADMINISTRATOR` (bool) | `owner: false`, bez admina |
| 2 | `GET /users/@me/guilds/{VUT}/member` | status, zoznam polí, počet rolí, či je `permissions`, `pending`, či je timeout (bool), `flags` | `200`, `roles` a `permissions` sú |
| 3 | `GET /guilds/{VUT}/members/{me}` | status, zoznam polí, či sa množina rolí zhoduje s (2) | `200`, zhoda |
| 4 | `GET /guilds/{VUT}/channels?permissions=true` | status, koľko kanálov má `permissions` (podľa typu, vrátane kategórií) | `permissions` pri všetkých kanáloch |
| – | (lokálne) výpočet zo (1)/(2) + overwrites zo (4) | počet zhôd s `permissions` zo (4): bit `VIEW`, bit `RMH`, celé číslo. ID kanálov s nezhodou | 100 % zhoda bitov `VIEW` a `RMH` |
| – | (lokálne) kontrolné kanály | `1549737445002584094` a kategórie `moderation`, `logging`, `fillers` → `VIEW` v oboch zdrojoch | `false` |
| 5 | voliteľne `GET /guilds/{VUT}/permissions/member/{me}` | status, kód chyby, zhoda s (1) | neznáme |
| 6 | voliteľne `GET /channels/1549737445002584094/messages?limit=1` | status a `code` | `403`, `50001` |
| 7 | voliteľne, ak (4) ukáže kanál s `VIEW` bez `RMH`: `GET /channels/{id}/messages?limit=1` | status a dĺžka poľa | `200`, `0` |

Spolu 4 až 7 requestov. Request 6 je jeden zámerne neplatný request (`403`). Neplatné requesty majú
limit 10 000 za 10 minút, takže jeden nevadí.

**Ručná kontrola:** počet kanálov `read`+`view` porovnať so sidebarom v Discorde. Pri porovnaní treba myslieť
na opt-in skryté kanály a resource kanály (`readme-*`). Tie Discord v zozname neukazuje, hoci prístup k nim je.

### 9.7 Odporúčaný postup

1. Používateľ spustí overenie (9.6). Výsledky sa zapíšu sem do sekcie „Overenie“ a body sa preznačia na
   **[OVERENÉ]**.
2. Rozhodnutie 9 sa zapíše ako ADR (stav `Navrhnuté`, kým ho používateľ neschváli). Hlavný zdroj bude
   `?permissions=true` alebo member endpoint, podľa výsledku.
3. Implementácia:
   - `permissions.py` + testy,
   - `models`/`cache` (schéma 2),
   - `directory` (request s `permissions=true`, fallback, `unknown`),
   - `channels` (`--include-hidden`, stĺpec `access`, upozornenie cez `warning()`),
   - aktualizácia návrhu 4.3 a 15/9.
4. Pri `messages`: mapovanie chýb zo sekcie 7 a preskočenie kanálov `none` bez requestu.

## 10. Otvorené otázky

- Funguje `?permissions=true` s user tokenom aj dnes? Má pole aj kategória? Aplikuje server implicitné maskovanie
  (bez `VIEW` → `0`)?
- Obsahuje private member objekt z `/users/@me/guilds/{id}/member` naozaj `permissions`?
- Fungujú nové endpointy z 2026-10-30 (`/permissions/member/...`) s user tokenom?
- Kedy začne REST vynechávať nedostupné kanály aj pre používateľov?
- Presný kód `403` pri hlasovom kanáli bez `CONNECT`.
- Zahŕňa `permissions` v `/users/@me/guilds` pri ownerovi všetky bity? Pri `owner: true` je to jedno.

## Zdroje

Oficiálna dokumentácia (`github.com/discord/discord-api-docs`, priečinok `developers/`, stav k 2026-11-03):
- [Permissions](https://docs.discord.com/developers/topics/permissions): bity, Permission Overwrites (pseudokód),
  Implicit Permissions, Inherited Permissions (Threads), Permission Syncing, timeout.
- [Guild: Get Guild Channels](https://docs.discord.com/developers/resources/guild#get-guild-channels) (upozornenie
  k 2026-11-16), Guild object (`owner`, `permissions`), Guild Member object (`pending`,
  `communication_disabled_until`), Get Guild Member, Get Guild Member Permissions, Add Guild Member (`pending`).
- [User: Get Current User Guilds, Get Current User Guild Member](https://docs.discord.com/developers/resources/user#get-current-user-guild-member).
- [Channel: Obfuscated Channels, Channel Flags, Get Channel Member Permissions, archived threads](https://docs.discord.com/developers/resources/channel#channel-object-obfuscated-channels).
- [Message: Get Channel Messages](https://docs.discord.com/developers/resources/message#get-channel-messages).
- [Change Log](https://docs.discord.com/developers/change-log): „Channel Obfuscation for Users and Bots“ (2026-08-12),
  „New Endpoints for getting member and role permissions…“ (2026-10-30).
- [Opcodes and Status Codes](https://docs.discord.com/developers/topics/opcodes-and-status-codes): JSON kódy
  `10003`, `10008`, `20002`, `40333`, `50001`, `50013`.

Discord Userdoccers (docs.discord.food, repo `discord-userdoccers/discord-userdoccers`):
- [Channels: List Guild Channels](https://docs.discord.food/resources/channel#list-guild-channels): parameter
  `permissions` (commit `76992e2`, 2024-06-02), flag `OBFUSCATED` (commit `ceb928b`, 2024-12-15), poznámka
  o budúcom filtrovaní a channel obfuscation v gateway (commit `20dd753`, 2026-06-24).
- [Guilds](https://docs.discord.food/resources/guild): List User Guilds, Get Current Guild Member (private member
  objekt s `permissions`), Get Guild Member, List Guild Members (nie pre user účty), roly, Guild Member Flags.
- [Permissions](https://docs.discord.food/topics/permissions): karanténa, discoverable guilds.
- [Threads](https://docs.discord.food/topics/threads): súkromné vlákna, enumerácia.
- [User Settings](https://docs.discord.food/resources/user-settings): `OPT_IN_ENABLED`, `OPT_IN_CHANNELS_ON`.
- [Errors](https://docs.discord.food/topics/errors) a [Rate Limits](https://docs.discord.food/topics/rate-limits).

Knižnice (vetva `master` k 2026-11-03):
- `dolfies/discord.py-self`:
  - `discord/abc.py` (`GuildChannel.permissions_for`, `_apply_implicit_permissions`),
  - `discord/channel.py` (hlasový kanál a `CONNECT`),
  - `discord/threads.py` (`Thread.permissions_for`),
  - `discord/permissions.py` (`_timeout_mask`),
  - `discord/http.py` (`get_member` → `GET /guilds/{id}/members/{id}`).
- `Tyrrrz/DiscordChatExporter`:
  - `DiscordChatExporter.Core/Discord/DiscordClient.cs` (`TryGetGuildMemberAsync`, mapovanie `403` na „forbidden“),
  - `DiscordChatExporter.Cli/Commands/Base/ExportCommandBase.cs` (chyby po kanáloch, bez predbežnej kontroly práv).

Komunitné hlásenia `403 / 50001 Missing Access` pri čítaní správ:
- [discord.js-selfbot-v13 #203](https://github.com/aiko-chan-ai/discord.js-selfbot-v13/issues/203),
- [discord-server-copy #37](https://github.com/itskekoff/discord-server-copy/issues/37).
