# Probe vlákien: stránkovanie, aktívne vlákna, správy vlákien a `last_message_id`

Dátum: 2026-11-04. Typ: meranie na účte používateľa. Dva behy skriptu `prototype/probe_threads.py` (iba GET
requesty, tempo 1 request za sekundu): prvý o 12:14 UTC (53 requestov), druhý o 12:58 UTC (59 requestov, skript
medzitým rozšírený, pozri sekciu 10).

**Legenda:** **[OVERENÉ]** = pozorované v jednom z reportov `prototype/out/probe-threads-20261104-121417.json`
(1. beh) a `prototype/out/probe-threads-20261104-125820.json` (2. beh). Oba sú lokálne a git ich ignoruje.
**[PREDPOKLAD]** = v týchto reportoch nepozorované: vyplýva z dokumentácie, z iného záznamu v repe alebo je to úsudok.
Zdroj je uvedený v zátvorke.

**Metodika:**
- Z reportov som čítal len štruktúru: stavové kódy, počty, názvy polí a kľúčov. Tento dokument neobsahuje mená
  používateľov, kanálov ani vlákien, texty správ ani ID používateľov. Z ID tu stojí iba ID servera VUT FIT.
- Starší beh `probe-threads-20261104-121242.json` som nepoužil.
- Sekcie 2 až 6 opisujú hlavne 1. beh, sekcia 7 je 2. beh. Kde 2. beh niečo uzavrel, sekcie 2 až 6 na to odkazujú.
- Súvisiace záznamy: [discord-analysis.md](discord-analysis.md) (sekcia 6 Vlákna a fóra, pozorovanie v prehliadači) a
  [design.md](../design.md) (sekcia 8 Vlákna a fóra).

---

## 1. Zhrnutie

Stav po oboch behoch.

| # | Otázka | Odpoveď v skratke |
|---|---|---|
| 1 | Veľkosť strany `threads/search` | `limit=25` funguje, `limit=50` dalo `400` (kód `50035`, v oboch behoch). Hodnoty 26 až 49 sú neotestované |
| 2 | Dosah `offset` | `0`, `25`, `100`, `500` aj `1808` vrátili po 25 vlákien. 40 po sebe idúcich strán dalo 1000 unikátnych vlákien, 0 duplicít (v oboch behoch) |
| 3 | Koniec zoznamu | **Prázdna strana ho označuje** (offset 1833 aj 1858: `200`, 0 vlákien). **Krátka strana je tiež koniec** (12 vlákien, ďalšia strana 0) |
| 4 | `has_more` a `total_results` | `has_more: true` na poslednej strane bolo falošne pozitívne. `total_results` archivovaného zoznamu sedelo (1833), pri aktívnych vláknach nie (14 oproti 12 vráteným, príčina neznáma). Koniec sa z nich určovať nesmie |
| 5 | `202` „not indexed“ | V 112 requestoch (oba behy) nenastala. To nie je dôkaz, že nenastane |
| 6 | Súkromné vlákna | Žiadne viditeľné. Všetkých 66 skontrolovaných vlákien malo typ 11 a nebolo zamknutých |
| 7 | `GET /guilds/{id}/threads/active` | `403`, kód `20002`, „Only bots can use this endpoint“ |
| 8 | Vlákna v textovom kanáli | **Fungujú v jednom čitateľnom kanáli** (archivované: 25, aktívne: 4). Kanál bez prístupu dal `403` (kód `50001`). Iné textové a oznamovacie kanály sú neoverené |
| 9 | Správy vlákna | `GET /channels/{thread_id}/messages` dalo `200` vo všetkých 3 volaniach, vlákno sa číta ako obyčajný kanál |
| 10 | Štartovacia správa fórum postu | Je to prvá správa vlákna a jej ID sa rovná ID vlákna (25 z 25 vo `first_messages`, aj pri 2 prečítaných postoch) |
| 11 | `last_message_id` v zozname kanálov | Je pri 385 zo 412 kanálov. V 2 z 2 čitateľných vzoriek sa zhodovalo s najnovšou správou (oba behy rovnako). Vzoriek je málo |

---

## 2. Nastavenie behov

**1. beh:**
- 53 requestov za 64,0 s, štart 2026-11-04 12:14:17 UTC **[OVERENÉ]**.
- Server: VUT FIT, ID `461541385204400138` **[OVERENÉ]**.
- Cieľové fórum: `help-center` (typ kanála 15), v ňom 1833 archivovaných vlákien (`total_results` na prvej aj
  poslednej z 40 strán) **[OVERENÉ]**.
- Rate-limit hlavičky (`x-ratelimit-*`, `retry-after`) sa v žiadnej z 53 odpovedí neobjavili **[OVERENÉ]**.

**2. beh:** 59 requestov za 73,0 s, štart 2026-11-04 12:58:20 UTC, ten istý server a fórum **[OVERENÉ]**.

**Spoločné:**
- Všetky requesty boli GET. Nič sa nezapísalo ani nezmenilo **[OVERENÉ]** (skript posiela iba GET).
- Parametre vyhľadávania vlákien: `archived`, `sort_by=last_message_time`, `sort_order=desc`, `limit`, `offset`
  **[OVERENÉ]**.
- Zoradenie výsledkov probe nekontroloval. Že sú naozaj od najnovšieho vlákna, je **[PREDPOKLAD]** (parametre server
  prijal, rovnaké posiela aj klient Discordu, pozri [discord-analysis.md](discord-analysis.md), sekcia 6).

---

## 3. Vyhľadávanie vlákien vo fóre (`threads/search`)

### 3.1 Veľkosť strany

| Požiadavka | Výsledok |
|---|---|
| `archived=true&limit=25&offset=0` | `200`, 25 vlákien **[OVERENÉ]** |
| `archived=true&limit=50&offset=0` | `400`, kód `50035` „Invalid Form Body“, telo má kľúče `code`, `errors`, `message` **[OVERENÉ]** |

- Jediný rozdiel medzi týmito dvoma requestmi bol `limit`, takže dôvodom odmietnutia je pravdepodobne práve on
  **[PREDPOKLAD]**. Podrobnosť v poli `errors` sa do reportu nezapisovala.
- Hodnoty 26 až 49 sa neskúšali **[OVERENÉ]**. Že maximum je presne 25, je **[PREDPOKLAD]**.
- Výsledok sa v 2. behu zopakoval **[OVERENÉ]**.

### 3.2 Offsety a stránkovanie

- Offsety `0`, `25`, `100`, `500` a `1808` vrátili každý `200` a 25 vlákien **[OVERENÉ]** (oba behy). Offset `1808` je
  `total_results − 25`, teda posledná plná strana.
- Stránkovanie od offsetu 0 s krokom 25 vyčerpalo 40 strán: 1000 vrátených vlákien, 1000 unikátnych, 0 duplicít
  **[OVERENÉ]** (oba behy). Zastavil ho strop 40 strán v probe (`stop_reason: max_pages_reached`), nie API.
- Počas stránkovania sa `total_results` nezmenilo (1833) **[OVERENÉ]**. Zoznam sa teda medzi stranami nepresúval natoľko,
  aby vznikli duplicity.
- Strana za koncom: pozri sekciu 7.6.
- Neotestované: strany medzi offsetmi 1000 a 1807 (unikátnosť).

### 3.3 `has_more` a `total_results` sú nespoľahlivé

| Pozorovanie | Hodnoty |
|---|---|
| Offset `1808`, `archived=true` | `has_more: true`, hoci `1808 + 25 = 1833 = total_results` **[OVERENÉ]** |
| Všetkých 5 skúmaných offsetov | `has_more: true`, vrátane poslednej strany **[OVERENÉ]** |
| Aktívne vlákna fóra (`archived=false`) | 12 vrátených, `total_results: 14`, `has_more: false` **[OVERENÉ]** |

- Pri poslednej strane boli možné dva výklady: `has_more` je falošne pozitívne, alebo je `total_results` nižšie ako
  skutočný počet. 2. beh to rozhodol: offset 1833 vrátil 0 vlákien, teda `has_more: true` na offsete 1808 bolo
  **falošne pozitívne** (sekcia 7.6) **[OVERENÉ]**.
- Pri aktívnych vláknach `total_results` prevyšuje počet vrátených o 2, v oboch behoch rovnako **[OVERENÉ]**. Podobný
  rozdiel (15 oproti 13) je zapísaný aj v [discord-analysis.md](discord-analysis.md), sekcia 14. Ďalšia strana (offset 25)
  bola prázdna, takže chýbajúce 2 vlákna nie sú na nej (sekcia 7.5). Prečo `total_results` hovorí 14, ostáva
  nevysvetlené.
- **Dôsledok:** koniec stránkovania sa nesmie určovať z `has_more` ani z `total_results`. Hodí sa najviac ako hrubý
  odhad pre ukazovateľ priebehu.

### 3.4 Odpoveď `202`

- V 112 requestoch (53 + 59) nepadla ani jedna `202` **[OVERENÉ]** (`count_202: 0` v oboch behoch).
- To nie je dôkaz, že nikdy nenastane. Pri vyhľadávaní správ sa `202` s `retry_after` očakáva
  **[PREDPOKLAD]** ([discord-analysis.md](discord-analysis.md), sekcia 8). Pre `threads/search` to nikto neoveril.

### 3.5 Tvar odpovede

- Kľúče odpovede `200`: `first_messages`, `has_more`, `members`, `threads`, `total_results` **[OVERENÉ]**.
- Obsah `first_messages` a `members` zistil až 2. beh (sekcia 7.4).

---

## 4. Aktívne vlákna

| Zdroj | Výsledok |
|---|---|
| `GET /guilds/{id}/threads/active` | `403`, kód `20002`, „Only bots can use this endpoint.“, telo má kľúče `code`, `message` **[OVERENÉ]** (oba behy) |
| `threads/search?archived=false` vo fóre | `200`, 12 vlákien, `total_results: 14`, `has_more: false` **[OVERENÉ]** (oba behy) |
| `threads/search` (archivované aj aktívne) v textovom kanáli, ktorý bol prvý v zozname (1. beh) | `403`, kód `50001` „Missing Access“ **[OVERENÉ]** |
| `threads/search?archived=false` v čitateľnom textovom kanáli (2. beh) | `200`, 4 vlákna **[OVERENÉ]** |

- Aktívne vlákna fóra sa dajú čítať cez `threads/search?archived=false` **[OVERENÉ]**. Úplnosť (12 z 14) je
  otázna, pozri sekciu 3.3.
- **1. beh** zobral prvý textový kanál (typ 0) zo zoznamu bez kontroly, či doň používateľ vidí. Prvý vzorec
  neskoršej kontroly `last_message_id` (prvý textový kanál s `last_message_id`) dal `403` aj pri čítaní správ
  **[OVERENÉ]**. Že išlo o ten istý kanál, report priamo nedokazuje (ID vzoriek sa neukladajú), vyplýva to z toho, že
  oba výbery idú v poradí zoznamu **[PREDPOKLAD]**.
- **2. beh** vybral kandidátov podľa najnovšieho `last_message_id` a prvý z nich odpovedal `200` (sekcia 7.2).

---

## 5. Vlákna: typy a polia

**1. beh:** skontrolovaných bolo 37 unikátnych vlákien: prvých 25 archivovaných vlákien fóra a 12 aktívnych vlákien
fóra (guildový endpoint ani textový kanál nevrátili nič) **[OVERENÉ]**. **2. beh:** 66 vlákien (sekcia 7.7).

| Vlastnosť | Pozorovanie |
|---|---|
| Typ | všetkých 37 (1. beh) aj všetkých 66 (2. beh) má typ 11 (verejné vlákno) **[OVERENÉ]** |
| Súkromné vlákna (typ 12) | 0 v oboch behoch **[OVERENÉ]** |
| `thread_metadata.locked` | `false` pri všetkých **[OVERENÉ]** |
| `flags` | `0` pri všetkých **[OVERENÉ]** |

**Polia vlákna v 1. behu** (zjednotenie cez 37 vlákien, nie je isté, že ich má každé vlákno) **[OVERENÉ]**:
`applied_tags`, `bitrate`, `flags`, `guild_id`, `id`, `last_message_id`, `member_count`, `member_ids_preview`,
`message_count`, `name`, `owner`, `owner_id`, `parent_id`, `rate_limit_per_user`, `rtc_region`, `thread_metadata`,
`total_message_sent`, `type`, `user_limit`. V 2. behu pribudlo `last_pin_timestamp` (sekcia 7.7).

**Polia `thread_metadata`** **[OVERENÉ]**: `archive_timestamp`, `archived`, `auto_archive_duration`,
`create_timestamp`, `locked` (v oboch behoch rovnaké). Pole `invitable`, ktoré sa objavilo v zázname z prehliadača
([discord-analysis.md](discord-analysis.md), sekcia 6), tu nebolo.

- Absencia súkromných vlákien je slabý dôkaz. Vzorka je jedno fórum (najnovších 25 archivovaných a 12 aktívnych vlákien)
  a jeden textový kanál (25 archivovaných a 4 aktívne). Fórum navyše obsahuje len verejné vlákna (typ 11)
  **[PREDPOKLAD]** (dokumentácia). Používateľ tiež nemusí mať právo, ktoré súkromné vlákna odhaľuje **[PREDPOKLAD]**.
- Polia `owner`, `owner_id` a `member_ids_preview` nesú údaje o ľuďoch **[PREDPOKLAD]** (z
  [discord-analysis.md](discord-analysis.md), sekcia 6). Treba s nimi zaobchádzať podľa pravidiel o citlivých údajoch.

---

## 6. `last_message_id` v zozname kanálov

`GET /guilds/{id}/channels` vrátil 412 kanálov **[OVERENÉ]** (oba behy rovnako):

| Typ kanála | S `last_message_id` | Všetkých |
|---|---|---|
| 0 text | 354 | 358 |
| 5 oznamovací | 12 | 12 |
| 15 fórum | 9 | 9 |
| 2 hlasový | 9 | 10 |
| 13 stage | 1 | 1 |
| 4 kategória | 0 | 22 |
| **Spolu** | **385** | **412** |

**Porovnanie s najnovšou správou:** probe vzal prvé 3 textové kanály s `last_message_id` v poradí zoznamu a z každého
načítal `GET /channels/{id}/messages?limit=1` **[OVERENÉ]**.
- Vzorka 1: `403`, správy nečitateľné.
- Vzorky 2 a 3: `200`, ID najnovšej správy sa **zhodovalo** s `last_message_id` kanála.
- Teda 2 zo 2 čitateľných vzoriek sa zhodovali. Fórum, oznamovací kanál ani hlasový kanál sa nevzorkovali.
- 2. beh tento výber nezmenil (rovnaké kanály, rovnaké výsledky), takže **nepriniesol nič nové** (sekcia 7.8).

**Čo z toho plynie:**
- `last_message_id` je pri väčšine kanálov, kde dáva zmysel, vyplnené **[OVERENÉ]**. Pri kategóriách chýba (alebo je
  `null`) a tiež pri 4 textových a 1 hlasovom kanáli **[OVERENÉ]** (27 kanálov bez hodnoty).
- Že je spoľahlivé, je **[PREDPOKLAD]**: dve vzorky nestačia.
- Hodnota môže ukazovať na zmazanú správu. V [discord-analysis.md](discord-analysis.md), sekcia 14, je kanál, ktorého
  `last_message_id` bol novší než najnovšia čitateľná správa. Oficiálna dokumentácia hovorí, že nemusí ukazovať na
  existujúcu správu **[PREDPOKLAD]**. Takáto chyba je neškodná: zbytočne sa urobí jeden request.
- Nebezpečná by bola opačná chyba, `last_message_id` staršie než skutočne najnovšia správa. Nepozorovali sme ju, ale
  dve vzorky ju nevylučujú.
- Pri fóre ukazuje `last_message_id` na posledný vytvorený post, nie na poslednú správu v niektorom poste
  **[PREDPOKLAD]** (oficiálna dokumentácia). Správy vo vláknach sa do `last_message_id` rodičovského kanála
  pravdepodobne nepremietajú **[PREDPOKLAD]** (úsudok z dokumentácie, nepozorované).

---

## 7. Druhý beh (2026-11-04, 12:58 UTC)

Report `prototype/out/probe-threads-20261104-125820.json`. Skript bol rozšírený (sekcia 10), aby zodpovedal otvorené
otázky z 1. behu.

### 7.1 Opakovateľnosť

- 59 requestov za 73,0 s **[OVERENÉ]**.
- Výsledky 1. behu sa zopakovali **[OVERENÉ]**:
  - `limit=25` dalo `200` a `total_results` 1833, `limit=50` dalo `400` (kód `50035`),
  - offsety 0, 25, 100, 500 a 1808 vrátili po 25 vlákien a `has_more: true`,
  - 40 strán dalo 1000 unikátnych vlákien bez duplicít,
  - aktívne vlákna fóra: 12 vrátených, `total_results` 14, `has_more: false`,
  - `GET /guilds/{id}/threads/active` dalo `403` (kód `20002`),
  - štatistika `last_message_id` v zozname kanálov (385 zo 412).
- Rate-limit hlavičky sa neobjavili, `202` nenastala **[OVERENÉ]**. Žiadna zaznamenaná odpoveď nemala stav `429`
  (všetky mali `200`, `400` alebo `403`). Prípadné opakovanie klienta po `429` by report nezachytil.

### 7.2 Vlákna v textovom kanáli

- Kandidátov (textové a oznamovacie kanály s `last_message_id`, od najnovšieho) bolo 6, skúšať sa muselo iba prvého:
  odpovedal `200` **[OVERENÉ]**.
- `archived=true` (limit 25, offset 0): `200`, **25 vlákien** (plná strana), kľúč `threads` prítomný **[OVERENÉ]**.
- `archived=false`: `200`, **4 vlákna** **[OVERENÉ]**.
- `threads/search` teda funguje aj v textovom kanáli **[OVERENÉ pre jeden kanál]**. Pre ostatné textové kanály, ktoré
  používateľ vidí, je to **[PREDPOKLAD]** (rovnaké API). Kanály bez prístupu dávajú `403` (sekcia 4).
- Report nezaznamenal typ kandidáta (0 alebo 5), ani `total_results` či `has_more` pri textovom kanáli. Oznamovacie
  kanály (typ 5) preto nepovažujem za otestované a či je 25 archivovaných vlákien celý zoznam, nevieme. Stránkovanie
  v textovom kanáli sa neskúšalo **[OVERENÉ]**.

### 7.3 Správy vlákna

Tri volania `GET /channels/{thread_id}/messages`, všetky `200` **[OVERENÉ]**:

| Vlákno | Volanie | Výsledok |
|---|---|---|
| najnovší archivovaný post fóra | `limit=1&after=0` | 1 správa typu 0, ID sa rovná ID vlákna |
| najnovší aktívny post fóra | `limit=1&after=0` | 1 správa typu 0, ID sa rovná ID vlákna |
| najnovší archivovaný post fóra | `limit=100` | 6 správ, typy 0 (5×) a 19 (1×), dávka úplná (6 < 100), najstaršia správa má ID vlákna |

- Vlákno sa číta ako obyčajný kanál, archivované aj aktívne **[OVERENÉ]**.
- Server prijal `after=0` a vrátil najstaršiu správu vlákna **[OVERENÉ]** (pri oboch vláknach sa jej ID rovnalo ID
  vlákna a pri dávke 100 bola najstaršia v dávke).
- Typ 19 je odpoveď (reply) **[PREDPOKLAD]** (dokumentácia). Pole `message_reference` a `referenced_message` sa v dávke
  objavili **[OVERENÉ]**.
- Polia správ vo vlákne (zjednotenie cez dávku 6 správ) **[OVERENÉ]**: `attachments`, `author`, `channel_id`,
  `components`, `content`, `edited_timestamp`, `embeds`, `flags`, `id`, `mention_everyone`, `mention_roles`, `mentions`,
  `message_reference`, `pinned`, `position`, `reactions`, `referenced_message`, `timestamp`, `tts`, `type`.
- Neotestované: vlákno s viac ako 100 správami (stránkovanie `before`/`after` vo vlákne). Že funguje rovnako ako v
  kanáli, je **[PREDPOKLAD]**.

### 7.4 Štartovacia správa fórum postu a `first_messages`

- `first_messages` v odpovedi `threads/search` (prvá strana archivovaných vlákien fóra) je pole s 25 správami pre 25
  vlákien **[OVERENÉ]**. Všetkých 25 správ má **ID rovné ID vlákna**, `channel_id` rovné ID vlákna a typ 0
  **[OVERENÉ]**.
- To isté platí pri oboch prečítaných postoch: najstaršia správa vlákna má ID vlákna (sekcia 7.3) **[OVERENÉ]**.
  ID štartovacej správy fórum postu sa teda rovná ID vlákna, a je to prvá správa vlákna.
- Polia správ vo `first_messages` **[OVERENÉ]**: `attachments`, `author`, `channel_id`, `components`, `content`,
  `edited_timestamp`, `embeds`, `flags`, `id`, `mention_everyone`, `mention_roles`, `mentions`, `pinned`, `position`,
  `reactions`, `timestamp`, `tts`, `type`. Sú to teda plné objekty správ vrátane `attachments`. Obsah poľa `attachments`
  probe neskúmal, či teda prílohy štartovacej správy prichádzajú už s vyhľadávaním, je **[PREDPOKLAD]**.
- `members` je prítomné, ale prázdne (0 položiek) **[OVERENÉ]**.
- Pre vlákna v textových kanáloch to neplatí automaticky a neskúšalo sa (v prehliadači `first_messages` pri textovom
  kanáli chýbalo, [discord-analysis.md](discord-analysis.md), sekcia 6).

### 7.5 Krátka strana je koniec

- Aktívne vyhľadávanie vo fóre vrátilo 12 vlákien (menej ako 25), `total_results` 14, `has_more: false` **[OVERENÉ]**.
- Ďalšia strana toho istého vyhľadávania (`offset=25`): `200`, **0 vlákien**, `has_more: false` **[OVERENÉ]**.
- Rozdiel 12 oproti 14 teda nie je spôsobený vláknami na ďalšej strane **[OVERENÉ]**. Prečo `total_results` hovorí 14,
  ostáva nevysvetlené.
- Je to jedno pozorovanie krátkej strany a to v zozname aktívnych vlákien. Pri archivovanom zozname sa krátka strana
  nevyskytla: posledná strana mala 25 vlákien a až nasledujúca bola prázdna **[OVERENÉ]**.

### 7.6 Strana za koncom

- Archivované vyhľadávanie pri `offset=1833` (`= total_results`) a `offset=1858` (`= total_results + 25`): obe
  `200` a **0 vlákien** **[OVERENÉ]**. Server ani pri offsete za koncom nevrátil chybu.
- Prázdna strana teda označuje koniec zoznamu **[OVERENÉ]**.
- Strana na offsete 1808 mala 25 vlákien a offset 1833 ich mal 0, takže zoznam mal presne 1833 vlákien a
  `total_results` pre archivovaný zoznam fóra sedelo **[OVERENÉ]** (pri nezmenenom zozname medzi requestami).
- `has_more: true` na offsete 1808 bolo preto falošne pozitívne **[OVERENÉ]**. Výklad, že `total_results` je nižšie
  než skutočný počet, je pre archivovaný zoznam vylúčený.

### 7.7 Typy a polia vlákien

- 66 unikátnych vlákien: 25 archivovaných a 12 aktívnych z fóra, 25 archivovaných a 4 aktívne z textového kanála
  (súčet počtov z reportu) **[OVERENÉ]**.
- Všetkých 66 má typ 11, žiadne nie je zamknuté (`locked: false`), `flags` je 0 a súkromných vlákien (typ 12) je 0
  **[OVERENÉ]**.
- Polia vlákna: tie isté 19 ako v 1. behu plus **`last_pin_timestamp`** **[OVERENÉ]**. Že pochádza z vlákien
  textového kanála, je **[PREDPOKLAD]** (vzorka sa zmenila práve pridaním týchto vlákien, report neuvádza polia po
  jednotlivých vláknach).
- Polia `thread_metadata` sú tie isté 5 **[OVERENÉ]**.

### 7.8 `last_message_id`

- Porovnanie s najnovšou správou dalo rovnaký výsledok ako v 1. behu: vzorka 1 `403`, vzorky 2 a 3 `200` so zhodou
  **[OVERENÉ]**. Skript vyberá kanály v poradí zoznamu, takže ide o tie isté 3 kanály.
- Otázka spoľahlivosti `last_message_id` je teda stále zodpovedaná len slabo (2 čitateľné vzorky, sekcia 6).

---

## 8. Čo ostáva neoverené

**Uzavreté 2. behom:**
- `threads/search` v textovom kanáli (funguje v jednom čitateľnom kanáli, sekcia 7.2),
- čítanie správ vlákna cez `GET /channels/{thread_id}/messages` (sekcia 7.3),
- ID štartovacej správy fórum postu sa rovná ID vlákna (sekcia 7.4),
- či krátka strana znamená koniec (sekcia 7.5) a čo vráti strana za koncom (sekcia 7.6),
- či bol `has_more: true` na poslednej strane falošne pozitívne (sekcia 7.6).

**Stále otvorené:**
1. **Ďalšie textové kanály.** Overený je jeden kanál. Neznáme sú: typ 5 (oznamovacie kanály), `total_results` a
   `has_more` pri textovom kanáli, stránkovanie cez `offset` tam, a či tam chýba `first_messages`.
2. **Súkromné vlákna (typ 12).** Medzi 66 vláknami neboli žiadne. Či sa pre tohto používateľa vôbec dajú vidieť, je
   neznáme.
3. **Odpoveď `202`** pri `threads/search` (v 112 requestoch nenastala).
4. **Okraje stránkovania:** limity 26 až 49, unikátnosť strán po offsete 1000, zoradenie výsledkov, krátka strana
   v archivovanom zozname (pozorovaná len pri aktívnych vláknach).
5. **Prečo je `total_results` pri aktívnych vláknach o 2 vyššie** než počet vrátených (14 oproti 12).
6. **Vlákno s viac ako 100 správami** a stránkovanie vo vlákne. Tiež ID prvej správy vlákna v textovom kanáli: vlákno
   vzniknuté zo správy má ID rovné ID tejto správy v rodičovskom kanáli **[PREDPOKLAD]**
   ([design.md](../design.md), sekcia 8, `thread.id == message.id`), vo vlákne samom to neoverené ostáva.
7. **Spoľahlivosť `last_message_id`:** iba 2 čitateľné vzorky, žiadna z fóra, oznamovacieho ani hlasového kanála.

---

## 9. Dôsledky pre návrh

1. **Veľkosť strany:** vždy `limit=25`. Vyššie hodnoty nepoužívať (50 dáva `400`).
2. **Koniec stránkovania** archivovaných aj aktívnych vlákien určiť podľa prvej z týchto podmienok, nikdy podľa
   `has_more` či `total_results`:
   - prázdna strana (potvrdené: offset 1833 aj 1858 dali `200` a 0 vlákien),
   - krátka strana, teda menej ako 25 (potvrdené: strana s 12 vláknami, ďalšia mala 0),
   - začiatok časového okna (vlákno s poslednou aktivitou staršou ako `--from`, ak je zoradenie naozaj podľa poslednej
     správy, pozri sekciu 2),
   - strop počtu strán ako poistka.

   Pravidlo „skonči na prázdnej alebo krátkej strane“ je 2. behom potvrdené. Krátka strana bola pozorovaná raz a to pri
   aktívnych vláknach. Ak je posledná strana plná (25), koniec oznámi až ďalšia, prázdna strana, čo stojí jeden
   request navyše.
3. **`total_results`** používať najviac ako hrubý odhad pre ukazovateľ priebehu. Pri archivovanom zozname fóra
   sedelo, pri aktívnych nie (14 oproti 12).
4. **Aktívne vlákna** čítať cez `threads/search?archived=false` po kanáloch. Guildový endpoint je len pre botov.
   Overené vo fóre a v jednom textovom kanáli. Záložný zdroj z [design.md](../design.md), sekcia 8
   (správy s objektom `thread`), môže ostať pre kanály, kde vyhľadávanie zlyhá.
5. **`403` (kód `50001`) pri vyhľadávaní vlákien v jednom kanáli** brať ako „bez prístupu“ a ten kanál preskočiť, nie
   zrušiť celý beh. Pred volaním netreba hádať prístup, stačí spracovať odpoveď.
6. **`202`** ošetriť (krátke čakanie a opakovanie s horným limitom), aj keď v 112 requestoch nenastala.
7. **Typ 12** (súkromné vlákno) nesmie spadnúť na neznámej hodnote. V týchto dátach nebolo.
8. **Správy vlákna** sťahovať obyčajným stránkovaním správ s ID vlákna ako ID kanála
   (`GET /channels/{thread_id}/messages`, `limit`, `before`/`after`). Overené: `limit=1&after=0` (najstaršia správa) a
   `limit=100`, archivované aj aktívne vlákno. Stránkovanie nad 100 správ vo vlákne je **[PREDPOKLAD]**.
   Exportér musí zvládnuť aj správy typu 19 (odpoveď) s poľami `message_reference` a `referenced_message`.
9. **Štartovacia správa fórum postu** je prvá správa vlákna s ID rovným ID vlákna. Žiadny osobitný prípad netreba:
   normálne sťahovanie vlákna od začiatku ju obsiahne. `first_messages` z vyhľadávania môže ušetriť requesty, ale nie je
   potrebné a spoliehať sa naň ako na jediný zdroj nemá zmysel. Pri vláknach z textových kanálov sa to neoverovalo.
10. **Preskakovanie neaktívnych kanálov (`--since-last`)** cez `last_message_id` zo zoznamu kanálov (netreba žiadny
    request navyše). Kanál sa preskočí len vtedy, keď je `last_message_id` neprázdne a nie je novšie než uložený
    kurzor. Pri `null` sa kanál nepreskakuje. Všetko ostáva **[PREDPOKLAD]**, lebo máme 2 čitateľné vzorky. Poistky:
    - vždy mať spôsob, ako preskakovanie vypnúť a prejsť všetko,
    - fóra a kanály, v ktorých sa sťahujú vlákna, podľa `last_message_id` nepreskakovať, kým sa inak nezistí, či majú
      nové správy vlákna (nové správy v starých postoch a vláknach ho pravdepodobne nemenia, pozri sekciu 6),
    - hodnotu brať len ako dôvod nepreskočiť (zmazaná správa dá zbytočný request, nič sa nestratí).

---

## 10. Rozšírený skript (podklad 2. behu)

Skript `prototype/probe_threads.py` bol medzi behmi rozšírený (návod v [prototype/README.md](../../prototype/README.md),
sekcia 4). 2. beh spustil všetky nové kontroly, asi 59 až 64 requestov. Nové kontroly:
- `threads_search_text_candidates` a `threads_search_text_active`: vyhľadávanie vlákien v najviac 6 textových kanáloch
  s najnovším `last_message_id`, kým jeden neodpovie `200` (sekcia 7.2),
- `thread_messages_readable`: čítanie správ vo vlákne cez `GET /channels/{thread_id}/messages` (sekcia 7.3). Prvé
  volanie berie najstaršiu správu (`limit=1&after=0`), pretože najnovšia (`limit=1` bez kotvy) by sa s ID vlákna
  rovnala len pri vlákne s jedinou správou. Server `after=0` prijal (sekcia 7.3),
- `threads_search_first_messages`: počty a názvy polí z `first_messages` a `members` bez ďalšieho requestu
  (sekcia 7.4),
- `threads_search_after_short_page`: ak aktívne vyhľadávanie vo fóre vráti menej ako 25 vlákien, probe si vypýta aj
  ďalšiu stranu (`offset=25`) a zapíše stavový kód, počet vlákien a `has_more` (sekcia 7.5),
- `threads_search_past_end`: archivované vyhľadávanie vo fóre pri `offset = total_results` a `total_results + 25`;
  ak `total_results` nie je známe, kontrola sa preskočí (sekcia 7.6).

Report ostáva štruktúrny, bez ID a textov.
