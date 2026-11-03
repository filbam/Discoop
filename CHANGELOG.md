# Changelog

Všetky podstatné zmeny projektu. Formát podľa [Keep a Changelog](https://keepachangelog.com/sk/1.1.0/),
verzie podľa [SemVer](https://semver.org/).

## [Unreleased]

### Pridané
- **Interaktívne terminálové rozhranie (`discoop ui`, TUI) a spoločná servisná vrstva ([ADR 0013](docs/rozhodnutia/0013-tui-a-spolocna-vrstva.md)):**
  - **Príkaz `discoop ui` a prepínač `--ui`:**
    - Plnohodnotné vizuálne terminálové prostredie postavené na knižnici Textual pre pohodlné interaktívne ovládanie klávesnicou (šípky, Enter, Space).
    - V `--plain` režime alebo mimo interaktívneho terminálu skončí kódom 8 (`BAD_ARGS`). Samotné `discoop` bez argumentov naďalej vypisuje help.
    - Lazy import knižnice `Textual`: bežné CLI príkazy neplatia žiadnu réžiu inicializácie TUI frameworku.
  - **Responzívny layout v štýle Discordu:**
    - 3 stĺpce v širokom okne (servery, kanály, nastavenia exportu a náhľad správ); automatické prispôsobenie na záložkový systém v úzkom okne.
    - Strom kategórií a kanálov s indikáciou prístupu a stavu výberu (začiarkavacie políčka).
    - Tlačidlá na načítanie serverov a kanálov jednotlivo aj hromadne („Načítať všetko“) s bezpečným `safe` tempovaním a možnosťou okamžitého zrušenia (storno).
  - **Pokročilá správa exportu a plánovanie úloh:**
    - Nastavenie globálneho časového okna (`--from`/`--to`), režimu sťahovania (`safe`/`fast`) a cieľa exportu (priečinok alebo ZIP).
    - Možnosť nastavenia individuálneho časového okna pre konkrétny vybraný kanál (per-channel custom window).
    - Automatické zoskupovanie kanálov podľa rovnakého časového okna: kanály so zhodným oknom tvoria jednu úlohu; pri viacerých úlohách sa exporty ukladajú do podpriečinkov (`cieľ/01-7d/`, ...) alebo očíslovaných archívov (`cieľ-01-7d.zip`).
    - Živý CLI príkazový riadok v spodnej lište TUI zobrazujúci presný ekvivalentný príkaz `discoop messages ...`.
    - Vstavaný náhľad správ vybraného kanála priamo v rozhraní.
  - **Vstavaný Help (`F1` / `?`):**
    - Modálna nápoveda s dvoma záložkami: návod na ovládanie TUI a kompletný živý výpis `discoop --help` vrátane podpríkazov generovaný z Typer aplikácie.
  - **Spoločná servisná vrstva (`src/discoop/service.py`):**
    - Zjednotená orchestrácia biznis logiky (`list_servers`, `list_channels`, `load_all`, `run_messages`) pre CLI aj TUI. Žiadna duplicita pri práci s Discord API, cache a exportom.
  - Nový balík `src/discoop/tui/` (`app.py`, `state.py`, `bridge.py`, `modals.py`, `discoop.tcss`).
- **Dva režimy sťahovania (`safe` a `fast`):**
  - **`safe` režim (predvolený):**
    - Imituje prirodzené ľudské správanie a scrollovanie v prehliadači na zníženie rizika blokovania účtu.
    - Stránkuje správy po menších dávkach (25 správ na požiadavku namiesto 100).
    - Náhodný interval (jitter) 2,0 až 4,5 s medzi požiadavkami.
    - Dlhšia „čítacia“ pauza 8,0 až 15,0 s každých 5 až 8 stránok s notifikáciou v progress bare a vo verbose výstupe.
    - Náhodná pauza 3,0 až 6,0 s pri prechode na ďalší kanál.
    - Náhodná pauza 1,0 až 3,0 s medzi sťahovaním jednotlivých príloh z Discord CDN.
    - Pri `429 Rate Limit` automaticky počká `retry_after` a zdvojnásobí intervaly pre zvyšok behu.
  - **`fast` režim:**
    - Pôvodný rýchly režim: 100 správ na požiadavku, pevný interval z `delay` (predvolene 1,0 s), bez čítacích pauz a bez čakania medzi súbormi z CDN.
  - **Nové CLI prepínače pre `discoop messages`:**
    - `--safe`: vynúti bezpečný režim s náhodnými intervalmi.
    - `--fast`: vynúti rýchly režim.
    - `--delay SEC`: nastavenie základného intervalu požiadaviek (v safe režime škáluje náhodné intervaly).
  - **Nové konfiguračné nastavenie:**
    - `discoop config set mode safe|fast`: trvalá zmena predvoleného režimu.
  - Použitý režim (`safe` / `fast`) sa zaznamenáva do `manifest.json` v exporte (`query.mode`).
- **Krok 3 implementácie: sťahovanie príloh, export do priečinka a zipu, manifest.**
  - **Export do priečinka a zipu:** `discoop messages --out DIR` a `--zip FILE`.
    - Štruktúra: `manifest.json`, `messages.md`, `messages.jsonl`, `channels/<kanál>.md` a `files/<kanál>/<attachment_id>_<meno>`.
    - Cesty v `messages.md` a `messages.jsonl` sú relatívne k priečinku exportu (`files/...`), v `channels/*.md` k danému súboru (`../files/...`). Obrázky (`image/*`) sa v Markdown vkladajú priamo ako `![meno](cesta) veľkosť`.
    - Opakovaný export do existujúceho priečinka alebo zipu opätovne použije už stiahnuté kompletné prílohy (`present`) a znova ich nesťahuje.
    - Sťahovanie prebieha cez dočasné súbory `.part` a `.zip` sa stavia v staging priečinku a nahradí starší archív až po kompletnom dokončení.
    - Ochrana pred prepísaním iných dát: neprázdny priečinok alebo súbor, ktorý nie je exportom discoop (chýba manifest s `"tool": "discoop"`), nástroj odmietne kódom 8 ešte pred volaním API.
  - **Sťahovanie príloh z CDN:**
    - Sťahovanie prebieha samostatným HTTP klientom **bez tokenu** (Discord CDN nevyžaduje autentifikáciu). `DiscordAPI` odmietne volania mimo API base.
    - Obnova exspirovaných podpisov (`ex` v minulosti alebo do 60 s) a URL odmietnutých CDN (403, 404, 410) cez `POST /attachments/refresh-urls` v dávkach po 50 v tempe nastavenom v konfigurácii (`delay`).
    - Zlyhaná príloha (chyba siete, zlyhané obnovenie URL, limit presmerovaní) nezastaví export, zaznamená sa v manifeste ako `failed` a súhrn chýb sa vypíše na stderr.
    - Bezpečné mená súborov pre Windows, Linux a macOS: skrátenie na 100 znakov a 200 bajtov, zachovanie prípony, orezanie bodiek a medzier, prefix `_` pre rezervované mená Windows (`CON`, `NUL`, ...), deduplikácia a bezpečné priečinky kanálov (max 50 znakov, pri kolízii `_<id>`).
  - **Nové prepínače a formáty:**
    - `--print`: popri exporte vypíše správy aj do konzoly (s lokálnymi cestami k stiahnutým súborom); bez neho sa pri exporte vypíše len súhrn.
    - `--no-files`: export bez sťahovania príloh (v manifeste ako `skipped`).
    - `--max-file-size`: vynechanie príloh nad zadanú veľkosť v MB (predvolene 50 MB, `0` = bez limitu).
    - `--format md` a `--format jsonl` v konzole aj s `--print`.
    - `discoop config set export-dir <priečinok>`: predvolený priečinok pre relatívne cesty `--out`/`--zip`.
  - Nové moduly `attachments.py`, `export.py`, testy `test_attachments.py`, `test_export.py` (spolu 223 testov).
- `discoop messages`: super reakcie sú pri počte reakcie (`🔥5 (2 super)`), v JSON pole `reactions[].super`.
- **Krok 2 implementácie: `discoop messages`** vypíše správy kanálov do konzoly.
  - **Výber:** `-c` meno, ID alebo vzor (`isc-*`), dá sa opakovať. Server cez `-s` alebo `default-server`,
    holé ID kanála server nepotrebuje.
  - **Časové okno:** `--from`/`--to` (dátum, dátum a čas, `48h`/`7d`/`2w`, `now`, `--from all`), predvolene 24 h.
    `--last N` vráti N najnovších správ. Hranice okna sa prepočítajú na snowflake, stránkuje sa po 100 cez `before`.
  - **Formáty:** `text` (úsporný pre agentov, farebný v human režime) a `json`. Mentions, custom emoji
    a časové značky sú prepísané na čitateľný text. Prílohy sú vo výstupe len ako meno, veľkosť a URL.
  - `--max-messages` (predvolene 5000 na kanál, potom varovanie a `truncated`) a `--include-system`.
  - **Chyby:** `403` s kódom 50001/50013 → kód 5, iný `403` (anti-abuse, Cloudflare) → kód 1, `404` → kód 4,
    zlé vstupy → kód 8 ešte pred volaním API. Pri viacerých kanáloch sa nedostupný kanál preskočí s varovaním.
  - Nové moduly `snowflake.py`, `scrape.py`, `normalize.py`, `render/text.py`, `render/jsonout.py`.
  - 161 testov (90 nových), Discord je v nich nahradený `httpx.MockTransport` s anonymizovanými správami.
- ADR 0011: vlákna predvolene zapnuté, predvolené okno 24 h, predvolený formát v agent režime `text`
  (rozhodnutia 4 až 6 z návrhu).
- ADR 0010: prácu robia agenti, hlavný Claude ich riadi, kontroluje a commituje. Pravidlá v `CLAUDE.md`,
  sekcia „Práca cez agentov“.
- **Krok 1 implementácie:** `discoop servers`, `discoop channels`, `discoop config`.
  - Zoznamy sa ukladajú do lokálnej SQLite cache a obnovujú cez `--refresh`, pri prvom použití,
    alebo raz automaticky, keď sa meno nenájde.
  - **Vyhľadávanie podľa mena:** najprv ID, potom presné meno, potom meno bez rozdielu veľkosti písmen,
    diakritiky a emoji. Glob vzory sú pripravené pre `messages`. Nejednoznačné meno skončí kódom 3 so zoznamom kandidátov.
  - **`channels`:** strom podľa kategórií v poradí ako v Discorde, `--flat`, `--type`. V agent režime riadky
    oddelené tabulátorom.
  - **`config`:** kľúče `default-server` (uloží sa ID servera) a `delay`.
  - **Login a logout** mažú cache.
  - 71 testov.
- **Prvý prototyp:** Python balík `discoop` (uv, Typer, Rich).
  - `discoop login`: QR kód v termináli cez remote auth gateway, alebo `--token` zo skrytého promptu/stdin.
    Voliteľný anonymizovaný `--trace`. V agent režime login odmietne.
  - `discoop status` a `discoop logout`.
  - Režimy `--agent`/`--human`:
    - help s poznámkou pre AI agentov,
    - chyby `ERROR <CODE>` / `HINT` a stabilné exit kódy.
  - Token sa ukladá do keyringu OS, na Linuxe bez Secret Service do súboru `0600`.
  - REST klient s tempom, retry pri 429 a 5xx a 401 → kód 2.
  - Testy (42): kryptografia, celý QR tok proti falošnému gatewayu, trace bez tajomstiev, CLI, token store.
- `prototype/probe.py`: jednorazové overenie otvorených bodov API.
- ADR 0006–0009: Python, angličtina v nástroji, záložný `login --token`, login v agent režime.
- Analýza dát Discord web klienta: [docs/analyzy/discord-analyza.md](docs/analyzy/discord-analyza.md).
- Návrh nástroja `discoop`: [docs/navrh-nastroja.md](docs/navrh-nastroja.md).
- Štruktúra dokumentácie:
  - pravidlá v `CLAUDE.md`,
  - `CHANGELOG.md` a `README.md`,
  - požiadavky (`docs/poziadavky.md`) a denník (`docs/dennik.md`),
  - rozhodnutia ADR 0001–0004 v `docs/rozhodnutia/`.
- `.gitignore` (Python, lokálne nastavenia, exporty z Discordu).
- Požiadavky P13 (Windows, Linux, macOS) a P14 (QR login v termináli).
- Analýza prihlásenia (QR remote auth, email/heslo, MFA, passkey): [docs/analyzy/discord-login.md](docs/analyzy/discord-login.md).
- ADR 0005: QR login v termináli bez prehliadača.

### Zmenené
- **Premenovanie „agent mode“ na „plain mode“ (`--plain`, [ADR 0012](docs/rozhodnutia/0012-premenovanie-agent-mode-na-plain.md)):**
  - Globálny prepínač `--plain` poskytuje čistý textový výstup bez farieb, Rich tabuliek a efektov, s chybami a notifikáciami na stderr a stabilnými exit kódmi.
  - V helpe a dokumentácii je explicitne uvedené, že plain mode je ideálny pre AI agentov a automatizované skripty (menej tokenov, jednoduchý parsing).
  - Prepínač `--agent` a premenná prostredia `DISCOOP_AGENT` zostávajú zachované ako spätná kompatibilita (nová premenná je `DISCOOP_PLAIN`).
- Analýza prístupu (sekcie 1 a 7) a návrh (sekcia 9): `403` pri kanáli bez `VIEW_CHANNEL` je overený testom
  používateľa 2026-11-03. Presný kód (`50001` alebo `50013`) výstup neukazuje.
- Návrh 4.5: správanie `messages` po teste používateľa (embedy bez duplicitnej URL, reakcie, orezané texty).
- Návrh: rozhodnutia 4 až 6 prijaté (ADR 0011). Sekcia 4.5 opisuje implementovaný `messages` a odchýlky,
  sekcia 9 mapovanie chýb `403`/`404` podľa analýzy prístupu ku kanálom.
- Chybové hlášky Discord API obsahujú aj JSON kód chyby (`… (code 50035)`).
- Návrh a denník: rozhodnutie 9 (výpočet prístupu ku kanálom) je odložené s nízkou prioritou.
- `CLAUDE.md`: aktuálny stav projektu namiesto „návrh, zatiaľ bez kódu“.
- Analýzy doplnené o výsledky prototypu:
  - `discord-analyza.md`, sekcia 15,
  - `discord-login.md`, sekcia 7: reálny QR login bez captchy.
- Návrh: overené body [PROTOTYP] sú teraz [OVERENÉ].
- Analýza presunutá z `docs/discord-analyza.md` do `docs/analyzy/discord-analyza.md`.
- Návrh prerobený pre prihlásenie a podporu všetkých OS:
  - login cez QR v termináli namiesto Playwright,
  - cesty k dátam cez `platformdirs`,
  - keyring s fallbackom pre Linux,
  - nové otvorené rozhodnutia 7 a 8.
- CLAUDE.md a ADR 0003: upozornenie na passkey dialóg pri `discord.com/login`.

### Opravené
- **Výstup `discoop messages`** po teste používateľa 2026-11-03 (3 nové regresné testy, spolu 164):
  - Embed nezopakuje URL, ktorú správa už ukazuje. GIF poslaný ako holá URL mal pod textom `[image]` s tou istou
    URL. Ostane len značka s titulkom, embed bez titulku sa vynechá. JSON má embedy celé.
  - Prázdne riadky na začiatku a konci textu správy a popisu rich embedu sa orežú, `\r\n` sa zmení na `\n`.
    V human režime je tak medzi správami vždy jeden prázdny riadok.
  - Rich embed bez URL a titulku už nemá za `[embed]` medzeru navyše.
