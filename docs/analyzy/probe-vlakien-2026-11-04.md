# Probe vlákien: stránkovanie, aktívne vlákna a `last_message_id`

Dátum: 2026-11-04. Typ: meranie na účte používateľa. Jeden beh skriptu `prototype/probe_threads.py` (iba GET
requesty, tempo 1 request za sekundu).

**Legenda:** **[OVERENÉ]** = pozorované v reporte `prototype/out/probe-threads-20261104-121417.json` (lokálny,
git ho ignoruje). **[PREDPOKLAD]** = v tomto reporte nepozorované: vyplýva z dokumentácie, z iného záznamu v repe
alebo je to úsudok. Zdroj je uvedený v zátvorke.

**Metodika:**
- Z reportu som čítal len štruktúru: stavové kódy, počty, názvy polí a kľúčov. Tento dokument neobsahuje mená
  používateľov, kanálov ani vlákien, texty správ ani ID používateľov. Z ID tu stojí iba ID servera VUT FIT.
- Starší beh `probe-threads-20261104-121242.json` som nepoužil.
- Súvisiace záznamy: [discord-analyza.md](discord-analyza.md) (sekcia 6 Vlákna a fóra, pozorovanie v prehliadači) a
  [navrh-nastroja.md](../navrh-nastroja.md) (sekcia 8 Vlákna a fóra).

---

## 1. Zhrnutie

| # | Otázka | Odpoveď v skratke |
|---|---|---|
| 1 | Veľkosť strany `threads/search` | `limit=25` funguje, `limit=50` dalo `400` (kód `50035`). Hodnoty 26 až 49 sú neotestované |
| 2 | Dosah `offset` | `0`, `25`, `100`, `500` aj `1808` vrátili po 25 vlákien. 40 po sebe idúcich strán dalo 1000 unikátnych vlákien, 0 duplicít |
| 3 | `has_more` a `total_results` | Nespoľahlivé: `has_more: true` na poslednej strane a `total_results` 14 pri 12 vrátených. Koniec stránkovania sa z nich určovať nesmie |
| 4 | `202` „not indexed“ | V 53 requestoch nenastala (to nie je dôkaz, že nenastane) |
| 5 | Súkromné vlákna | Žiadne viditeľné. Všetkých 37 skontrolovaných vlákien malo typ 11 a nebolo zamknutých |
| 6 | `GET /guilds/{id}/threads/active` | `403`, kód `20002`, „Only bots can use this endpoint“ |
| 7 | Vlákna v textovom kanáli | **Nezodpovedané.** Skúšaný kanál dal `403` (kód `50001`), lebo probe vybral prvý textový kanál bez kontroly prístupu |
| 8 | `last_message_id` v zozname kanálov | Je pri 385 zo 412 kanálov. V 2 z 2 čitateľných vzoriek sa zhodovalo s najnovšou správou. Vzoriek je málo |

---

## 2. Nastavenie behu

- 53 requestov za 64,0 s, štart 2026-11-04 12:14:17 UTC **[OVERENÉ]**.
- Server: VUT FIT, ID `461541385204400138` **[OVERENÉ]**.
- Cieľové fórum: `help-center` (typ kanála 15), v ňom 1833 archivovaných vlákien (`total_results` na prvej aj
  poslednej z 40 strán) **[OVERENÉ]**.
- Rate-limit hlavičky (`x-ratelimit-*`, `retry-after`) sa v žiadnej z 53 odpovedí neobjavili **[OVERENÉ]**.
- Všetky requesty boli GET. Nič sa nezapísalo ani nezmenilo **[OVERENÉ]** (skript posiela iba GET).
- Parametre vyhľadávania vlákien: `archived`, `sort_by=last_message_time`, `sort_order=desc`, `limit`, `offset`
  **[OVERENÉ]**.
- Zoradenie výsledkov probe nekontroloval. Že sú naozaj od najnovšieho vlákna, je **[PREDPOKLAD]** (parametre server
  prijal, rovnaké posiela aj klient Discordu, pozri [discord-analyza.md](discord-analyza.md), sekcia 6).

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

### 3.2 Offsety a stránkovanie

- Offsety `0`, `25`, `100`, `500` a `1808` vrátili každý `200` a 25 vlákien **[OVERENÉ]**. Offset `1808` je
  `total_results − 25`, teda posledná plná strana.
- Stránkovanie od offsetu 0 s krokom 25 vyčerpalo 40 strán: 1000 vrátených vlákien, 1000 unikátnych, 0 duplicít
  **[OVERENÉ]**. Zastavil ho strop 40 strán v probe (`stop_reason: max_pages_reached`), nie API.
- Počas stránkovania sa `total_results` nezmenilo (1833) **[OVERENÉ]**. Zoznam sa teda medzi stranami nepresúval natoľko,
  aby vznikli duplicity.
- Neotestované: strany medzi offsetmi 1000 a 1807 (unikátnosť), offset 1833 a vyššie (očakáva sa prázdna strana
  **[PREDPOKLAD]**), tvar odpovede pri krátkej strane v strede zoznamu.

### 3.3 `has_more` a `total_results` sú nespoľahlivé

| Pozorovanie | Hodnoty |
|---|---|
| Offset `1808`, `archived=true` | `has_more: true`, hoci `1808 + 25 = 1833 = total_results` **[OVERENÉ]** |
| Všetkých 5 skúmaných offsetov | `has_more: true`, vrátane poslednej strany **[OVERENÉ]** |
| Aktívne vlákna fóra (`archived=false`) | 12 vrátených, `total_results: 14`, `has_more: false` **[OVERENÉ]** |

- Pri poslednej strane sú možné dva výklady: `has_more` je falošne pozitívne, alebo je `total_results` nižšie ako
  skutočný počet. Report to nerozlišuje, na to treba offset 1833 **[PREDPOKLAD]**.
- Pri aktívnych vláknach `total_results` prevyšuje počet vrátených o 2. Podobný rozdiel (15 oproti 13) je zapísaný aj
  v [discord-analyza.md](discord-analyza.md), sekcia 14. Príčina nie je známa.
- **Dôsledok:** koniec stránkovania sa nesmie určovať z `has_more` ani z `total_results`. Hodí sa najviac ako hrubý
  odhad pre ukazovateľ priebehu.

### 3.4 Odpoveď `202`

- V 53 requestoch nepadla ani jedna `202` **[OVERENÉ]** (`count_202: 0`).
- To nie je dôkaz, že nikdy nenastane. Pri vyhľadávaní správ sa `202` s `retry_after` očakáva
  **[PREDPOKLAD]** ([discord-analyza.md](discord-analyza.md), sekcia 8). Pre `threads/search` to nikto neoveril.

### 3.5 Tvar odpovede

- Kľúče odpovede `200`: `first_messages`, `has_more`, `members`, `threads`, `total_results` **[OVERENÉ]**.
- Obsah `first_messages` a `members` probe v tomto behu neprezeral, takže je overená len prítomnosť kľúčov.
  Z prehliadača je zaznamenané, že pri fóre je `first_messages` naplnené a štartovacia správa má rovnaké ID ako vlákno
  ([discord-analyza.md](discord-analyza.md), sekcia 6). Z tokenu cez tento probe to **neoverené** ostáva.

---

## 4. Aktívne vlákna

| Zdroj | Výsledok |
|---|---|
| `GET /guilds/{id}/threads/active` | `403`, kód `20002`, „Only bots can use this endpoint.“, telo má kľúče `code`, `message` **[OVERENÉ]** |
| `threads/search?archived=false` vo fóre | `200`, 12 vlákien, `total_results: 14`, `has_more: false` **[OVERENÉ]** |
| `threads/search` (archivované aj aktívne) v skúšanom textovom kanáli | `403`, kód `50001` „Missing Access“ **[OVERENÉ]** |

- Aktívne vlákna fóra sa dajú čítať cez `threads/search?archived=false` **[OVERENÉ]**. Úplnosť (12 z 14) je otázna,
  pozri sekciu 3.3.
- **Text kanály zostávajú nezodpovedané.** Probe zobral prvý textový kanál (typ 0) zo zoznamu bez kontroly, či doň
  používateľ vidí. Prvý vzorec neskoršej kontroly `last_message_id` (prvý textový kanál s `last_message_id`)
  dal `403` aj pri čítaní správ **[OVERENÉ]**. Že ide o ten istý kanál, report priamo nedokazuje (ID vzoriek sa
  neukladajú), vyplýva to z toho, že oba výbery idú v poradí zoznamu **[PREDPOKLAD]**.
- Preto z tohto behu nevieme povedať, či `threads/search` funguje aj v textových kanáloch a koľko vlákien tam vráti.

---

## 5. Vlákna: typy a polia

Skontrolovaných bolo 37 unikátnych vlákien: prvých 25 archivovaných vlákien fóra a 12 aktívnych vlákien fóra
(guildový endpoint ani textový kanál nevrátili nič) **[OVERENÉ]**.

| Vlastnosť | Pozorovanie |
|---|---|
| Typ | všetkých 37 má typ 11 (verejné vlákno) **[OVERENÉ]** |
| Súkromné vlákna (typ 12) | 0 **[OVERENÉ]** |
| `thread_metadata.locked` | `false` pri všetkých 37 **[OVERENÉ]** |
| `flags` | `0` pri všetkých 37 **[OVERENÉ]** |

**Polia vlákna** (zjednotenie cez 37 vlákien, nie je isté, že ich má každé vlákno) **[OVERENÉ]**:
`applied_tags`, `bitrate`, `flags`, `guild_id`, `id`, `last_message_id`, `member_count`, `member_ids_preview`,
`message_count`, `name`, `owner`, `owner_id`, `parent_id`, `rate_limit_per_user`, `rtc_region`, `thread_metadata`,
`total_message_sent`, `type`, `user_limit`.

**Polia `thread_metadata`** **[OVERENÉ]**: `archive_timestamp`, `archived`, `auto_archive_duration`,
`create_timestamp`, `locked`. Pole `invitable`, ktoré sa objavilo v zázname z prehliadača
([discord-analyza.md](discord-analyza.md), sekcia 6), v týchto 37 vláknach nebolo.

- Absencia súkromných vlákien je slabý dôkaz. Vzorka je jedno fórum a v ňom iba najnovších 25 archivovaných a 12
  aktívnych vlákien. Fórum navyše obsahuje len verejné vlákna (typ 11) **[PREDPOKLAD]** (dokumentácia), takže tento
  výsledok o súkromných vláknach v textových kanáloch nehovorí nič. Používateľ tiež nemusí mať právo, ktoré súkromné
  vlákna odhaľuje **[PREDPOKLAD]**.
- Polia `owner`, `owner_id` a `member_ids_preview` nesú údaje o ľuďoch **[PREDPOKLAD]** (z [discord-analyza.md](discord-analyza.md),
  sekcia 6). Treba s nimi zaobchádzať podľa pravidiel o citlivých údajoch.

---

## 6. `last_message_id` v zozname kanálov

`GET /guilds/{id}/channels` vrátil 412 kanálov **[OVERENÉ]**:

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

**Čo z toho plynie:**
- `last_message_id` je pri väčšine kanálov, kde dáva zmysel, vyplnené **[OVERENÉ]**. Pri kategóriách chýba (alebo je
  `null`) a tiež pri 4 textových a 1 hlasovom kanáli **[OVERENÉ]** (27 kanálov bez hodnoty).
- Že je spoľahlivé, je **[PREDPOKLAD]**: dve vzorky nestačia.
- Hodnota môže ukazovať na zmazanú správu. V [discord-analyza.md](discord-analyza.md), sekcia 14, je kanál, ktorého
  `last_message_id` bol novší než najnovšia čitateľná správa. Oficiálna dokumentácia hovorí, že nemusí ukazovať na
  existujúcu správu **[PREDPOKLAD]**. Takáto chyba je neškodná: zbytočne sa urobí jeden request.
- Nebezpečná by bola opačná chyba, `last_message_id` staršie než skutočne najnovšia správa. Nepozorovali sme ju, ale
  dve vzorky ju nevylučujú.
- Pri fóre ukazuje `last_message_id` na posledný vytvorený post, nie na poslednú správu v niektorom poste
  **[PREDPOKLAD]** (oficiálna dokumentácia). Správy vo vláknach sa do `last_message_id` rodičovského kanála
  pravdepodobne nepremietajú **[PREDPOKLAD]** (úsudok z dokumentácie, nepozorované).

---

## 7. Čo ostáva neoverené

1. **Vlákna v textových kanáloch cez `threads/search`.** Skúšaný kanál dal `403`. Neznáme je, či endpoint v textovom
   kanáli funguje, či vracia súkromné vlákna a či chýba `first_messages` (v prehliadači chýbalo,
   [discord-analyza.md](discord-analyza.md), sekcia 6).
2. **Čítanie správ vlákna z tokenu** cez `GET /channels/{thread_id}/messages`. V prehliadači sa takto správy vlákna
   čítajú ([discord-analyza.md](discord-analyza.md), sekcia 6), tento probe ho nevolal.
3. **ID štartovacej správy fórum postu sa rovná ID vlákna.** Zo záznamu z prehliadača áno, tento probe obsah
   `first_messages` neskúmal.
4. **Súkromné vlákna (typ 12).** Neviditeľné vo fóre, v textových kanáloch neskúšané.
5. **Odpoveď `202`** pri `threads/search`.
6. **Okraje stránkovania:**
   - limity 26 až 49,
   - offset 1833 a vyššie (strana za koncom),
   - či krátka strana (menej ako 25) naozaj znamená koniec: aktívne vlákna fóra vrátili 12 z 14 a ďalšia strana sa
     nevyžiadala,
   - unikátnosť strán po offsete 1000,
   - zoradenie výsledkov.
7. **Spoľahlivosť `last_message_id`:** iba 2 čitateľné vzorky, žiadna z fóra, oznamovacieho ani hlasového kanála.

---

## 8. Dôsledky pre návrh

1. **Veľkosť strany:** vždy `limit=25`. Vyššie hodnoty nepoužívať (50 dáva `400`).
2. **Koniec stránkovania** archivovaných vlákien určiť podľa prvej z týchto podmienok, nikdy podľa `has_more` či
   `total_results`:
   - prázdna strana,
   - krátka strana (menej ako 25),
   - začiatok časového okna (vlákno s poslednou aktivitou staršou ako `--from`, ak je zoradenie naozaj podľa poslednej
     správy, pozri sekciu 2),
   - strop počtu strán ako poistka.

   Poistka na krátku stranu: aktívne vlákna ukázali 12 vrátených z 14 uvedených, takže strana môže byť kratšia, než
   sa čaká. Pri archivovaných vláknach sa to nepozorovalo. Ak by záležalo na úplnosti, jeden request navyše na ďalšom
   offsete (prázdna strana) ju potvrdí.
3. **`total_results`** používať najviac ako hrubý odhad pre ukazovateľ priebehu, nikdy ako počet na porovnanie s
   výsledkom.
4. **Aktívne vlákna** čítať cez `threads/search?archived=false` po kanáloch. Guildový endpoint je len pre botov. Pre
   textové kanály to ostáva neoverené, preto nechať v návrhu aj záložný zdroj (správy s objektom `thread`, pozri
   [navrh-nastroja.md](../navrh-nastroja.md), sekcia 8).
5. **`403` (kód `50001`) pri vyhľadávaní vlákien v jednom kanáli** brať ako „bez prístupu“ a ten kanál preskočiť, nie
   zrušiť celý beh. Pred volaním netreba hádať prístup, stačí spracovať odpoveď.
6. **`202`** ošetriť (krátke čakanie a opakovanie s horným limitom), aj keď v 53 requestoch nenastala.
7. **Typ 12** (súkromné vlákno) nesmie spadnúť na neznámej hodnote. V týchto dátach nebolo.
8. **Preskakovanie neaktívnych kanálov (`--since-last`)** cez `last_message_id` zo zoznamu kanálov (netreba žiadny
   request navyše). Kanál sa preskočí len vtedy, keď je `last_message_id` neprázdne a nie je novšie než uložený
   kurzor. Pri `null` sa kanál nepreskakuje. Všetko ostáva **[PREDPOKLAD]**, lebo máme 2 čitateľné vzorky. Poistky:
   - vždy mať spôsob, ako preskakovanie vypnúť a prejsť všetko,
   - fóra a kanály, v ktorých sa sťahujú vlákna, podľa `last_message_id` nepreskakovať, kým sa inak nezistí, či majú
     nové správy vlákna (nové správy v starých postoch a vláknach ho pravdepodobne nemenia, pozri sekciu 6),
   - hodnotu brať len ako dôvod nepreskočiť (zmazaná správa dá zbytočný request, nič sa nestratí).

---

## 9. Ďalší beh

Skript `prototype/probe_threads.py` je rozšírený tak, aby druhý beh zodpovedal otvorené otázky z sekcie 7
(návod v [prototype/README.md](../../prototype/README.md), sekcia 4). Beží približne 1,5 minúty (asi 59 až 64 requestov). Nové kontroly:
- `threads_search_text_candidates` a `threads_search_text_active`: vyhľadávanie vlákien v najviac 6 textových kanáloch
  s najnovším `last_message_id`, kým jeden neodpovie `200` (body 1 a 4),
- `thread_messages_readable`: čítanie správ vo vlákne cez `GET /channels/{thread_id}/messages` (body 2 a 3). Prvé
  volanie berie najstaršiu správu (`limit=1&after=0`), pretože najnovšia (`limit=1` bez kotvy) by sa s ID vlákna
  rovnala len pri vlákne s jedinou správou. Že server prijme `after=0`, je **[PREDPOKLAD]**. Ak ho odmietne, nahradí ho
  dávka `limit=100` (jej najstaršia správa, ak je dávka úplná),
- `threads_search_first_messages`: počty a názvy polí z `first_messages` a `members` bez ďalšieho requestu (bod 3).
- `threads_search_after_short_page`: ak aktívne vyhľadávanie vo fóre vráti menej ako 25 vlákien, probe si vypýta aj
  ďalšiu stranu (`offset=25`) a zapíše stavový kód, počet vlákien a `has_more` (bod 6, krátka strana),
- `threads_search_past_end`: archivované vyhľadávanie vo fóre pri `offset = total_results` a `total_results + 25`,
  zapíše stavový kód a počet vlákien oboch strán (bod 6, strana za koncom). Ak `total_results` nie je známe, kontrola
  sa preskočí. Výsledok rozhodne aj o tom, či bol `has_more: true` na poslednej strane (sekcia 3.3) falošne
  pozitívne, alebo je `total_results` nižšie než skutočný počet.

Report ostáva štruktúrny, bez ID a textov.
