# Odovzdanie stavu projektu discoop (Handoff)

Tento dokument slúži ako kompletný a prehľadný súhrn stavu projektu `discoop` pre ďalšieho AI agenta alebo vývojára, ktorý preberá prácu na repozitári.

---

## 1. Úvod a povinné čítanie

Pred začatím akejkoľvek práce si **povinne prečítaj** nasledujúce dokumenty:

1. **[CLAUDE.md](../CLAUDE.md):**
   - **Práca cez subagentov ([ADR 0010](rozhodnutia/0010-praca-cez-agentov.md)):** Hlavný Claude riadi prácu, zadáva agentom konkrétne ohraničené úlohy a sám kontroluje výsledky (diff, testy). Subagenti sami necommitujú ani nepushujú.
   - **Zákaz živých volaní Discord API:** Automatizované testy bežia **výhradne offline** cez MockTransport a anonymizované fixtures v `tests/fixtures/`. Živé API smie spúšťať len používateľ na svojom účte.
   - **Git pravidlá:** Vetva `main`, autor `filbam <f.bambura@gmail.com>`. Commitovanie po každom overenom kroku (robí hlavný Claude), **zákaz `git push` bez výslovného pokynu používateľa**.
   - **Zaznamenávanie všetkého ([ADR 0001](rozhodnutia/0001-zaznamenavanie-a-verzovanie.md)):** Každá zmena, rozhodnutie alebo požiadavka musí byť zapísaná v dokumentácii v tom istom pracovnom kroku.
2. **[docs/poziadavky.md](poziadavky.md):**
   - Zoznam všetkých požiadaviek používateľa (P1–P25). Zdroj pravdy o tom, čo má nástroj dokázať.
3. **[docs/navrh-nastroja.md](navrh-nastroja.md):**
   - Architektúra celého nástroja, štruktúra balíka `src/discoop/`, zoznam príkazov, exit kódy, dátové toky a otvorené otázky.
4. **[docs/dennik.md](dennik.md):**
   - Chronologický denník doterajšieho vývoja, záznamy testov na reálnom účte používateľa a riešené incidenty.
5. **[docs/rozhodnutia/README.md](rozhodnutia/README.md):**
   - Register všetkých Architectural Decision Records ([ADR 0001](rozhodnutia/0001-zaznamenavanie-a-verzovanie.md) až [ADR 0018](rozhodnutia/0018-logovanie.md)).

---

## 2. Aktuálny stav projektu (k 2026-11-04)

- **Testovacie pokrytie:** Všetkých **511 automatizovaných testov** prechádza (`uv run pytest`).
- **Nainštalované prostredie:** Python 3.12+, projekt spravovaný cez `uv`. Vývoj v repe ide cez `uv run discoop ...`, používatelia majú nainštalovaný príkaz `discoop` (`uv tool install git+https://github.com/filbam/Discoop`, návod v [README.md](../README.md)).
- **Repo je verejné** (P22, [ADR 0015](rozhodnutia/0015-verejne-repo-a-instalacia.md)). Do gitu nesmie ísť token, cookies ani mená a texty správ iných ľudí. `[OVERENÉ]`: inštalácia z lokálneho klonu na Windows. `[PREDPOKLAD]`: inštalácia z GitHubu, Linux, macOS.

### Prehľad implementovaných funkcií

#### A. Autentifikácia a identita (`auth.py`, `tokenstore.py`)
- **`discoop login`:**
  - Primárna cesta: **QR login bez prehliadača** v termináli ([ADR 0005](rozhodnutia/0005-qr-login-bez-prehliadaca.md), P14) cez Discord remote auth gateway (WebSocket, RSA-OAEP-SHA256 výmena kľúčov, vykreslenie QR cez `segno`).
  - Podpora testovacieho handshake bez prihlásenia (`--handshake-only`).
  - Záložné prihlásenie cez `--token` zo skrytého interaktívneho vstupu alebo stdin ([ADR 0008](rozhodnutia/0008-zalozny-login-token.md)). V plain režime je interaktívny login odmietnutý s kódom `2` ([ADR 0009](rozhodnutia/0009-login-v-agent-rezime.md)).
- **`discoop status`:** Vypíše stav prihlásenia, informácie o účte používateľa a vek lokálnej cache.
- **`discoop logout`:** Bezpečne odstráni token zo systémového keyringu OS (Windows Credential Manager, macOS Keychain, Linux Secret Service).

#### B. Servery, kanály a konfigurácia (`cache.py`, `config.py`, `resolve.py`)
- **`discoop servers` & `discoop channels`:**
  - Výpis serverov a kanálov, ukladanie do lokálnej SQLite databázy `cache.db` (umiestnenej podľa štandardov OS cez `platformdirs`).
  - Vyhľadávanie a filtrovanie kanálov podľa ID, presného mena alebo glob vzorov (`resolve.py`). Vyhľadávanie je odolné voči diakritike, veľkosti písmen a odstraňuje emoji.
- **`discoop config`:**
  - Správa konfiguračných hodnôt: `default-server`, `delay`, `export-dir`, `mode` (`safe` / `fast`).

#### C. Sťahovanie správ (`messages.py`, `scrape.py`, `snowflake.py`)
- **`discoop messages`:**
  - Časové okná: absolútne `--from`, `--to` (ISO formát alebo dátum), relatívne `--last` (`7d`, `24h`, `30m`). Prepočet na Discord snowflake ID.
  - Formáty výstupu pre konzolu: `text` (predvolený čistý text), `md` (Markdown), `json` a `jsonl`.
  - Prepínače `--print` (súbežný výpis správ popri exporte) a `--dry-run`.

#### D. Krok 3: Export a sťahovanie príloh (`export.py`, `attachments.py`)
- **Cieľ exportu:**
  - `--out DIR`: export do adresárovej štruktúry (`manifest.json`, `messages.md`, `messages.jsonl`, `channels/<kanál>.md`, `files/<kanál>/<att_id>_<meno>`).
  - `--zip FILE`: komprimovaný zip archív (texty `ZIP_DEFLATED`, súbory `ZIP_STORED`).
- **CDN klient a bezpečnosť:**
  - Prílohy sťahuje samostatný HTTP klient **bez tokenu v hlavičkách** (ochrana pred únikom pri CDN presmerovaniach).
  - Obnova exspirovaných podpisov cez read-only `POST /attachments/refresh-urls` v dávkach po 50 (s predstihom 60 s pred vypršaním alebo po chybách 403, 404, 410).
  - Bezpečné mená súborov pre Windows, Linux a macOS (limit 100 znakov / 200 bajtov, orezanie bodiek a medzier, prefix `_` pre rezervované názvy Windows ako `CON`, `NUL`).
  - Podpora filtrov `--no-files` a `--max-file-size` (v MB).
  - Atomický zápis (`.part` súbory, staging zip) a ochrana existujúcich priečinkov pred prepísaním neznámych dát.
  - Opätovné použitie už stiahnutých súborov so zhodným ID a veľkosťou (`present`), zlyhanie CDN nezastaví export ostatných správ.

#### E. Režimy sťahovania: `safe` vs `fast` (`api.py`)
Nástroj umožňuje voľbu tempa cez konfiguráciu (`discoop config set mode safe|fast`) alebo prepínačmi `--safe` / `--fast`:
1. **`safe` (predvolený režim):**
   - Imituje prirodzené správanie používateľa v prehliadači s dôrazom na minimalizáciu rizika detekcie a zablokovania účtu.
   - Dávky po 25 správach (`limit=25`).
   - Náhodný jitter 2.0 až 4.5 s pred každým volaním API.
   - Čítacie pauzy 8.0 až 15.0 s každých 5 až 8 stránok (s notifikáciou cez callback `on_pause`).
   - Pauza 3.0 až 6.0 s pri prepnutí kanála (`between_channels()`).
   - Pauza 1.0 až 3.0 s medzi sťahovaním jednotlivých súborov z CDN (`between_files()`).
   - Automatický exponenciálny backoff so zdvojnásobením intervalu pri HTTP 429.
2. **`fast`:**
   - Dávky po 100 správach (`limit=100`).
   - Pevný nastaviteľný `delay` (predvolene 1.0 s).
   - Žiadne náhodné čítacie pauzy ani zdržania medzi kanálmi a súbormi.

#### F. Plain mode (`--plain`, [ADR 0012](rozhodnutia/0012-premenovanie-agent-mode-na-plain.md), P15)
- Režim pôvodne nazvaný „agent mode“ bol premenovaný na **Plain mode**.
- Prepínač `--plain` alebo premenná prostredia `DISCOOP_PLAIN=1`.
- Výstup je čistý, nestylovaný text bez ANSI kódov, tabuliek a Rich prvkov (šetrí tokeny pre AI agentov a je priamo parsovateľný).
- Pôvodný prepínač `--agent` a `DISCOOP_AGENT=1` sú ponechané ako plne funkčné skryté spätné aliasy.

#### G. Interaktívne terminálové rozhranie TUI (`discoop ui`, [ADR 0013](rozhodnutia/0013-tui-a-spolocna-vrstva.md), P16–P17)
- **Spoločná servisná vrstva (`src/discoop/service.py`):**
  - Vyčlenená biznis logika pre načítanie serverov (`list_servers`), kanálov (`list_channels`), kompletnej štruktúry (`load_all`), rezolúciu cieľov (`resolve_targets`) a sťahovanie správ (`run_messages`).
  - Spoločná pre CLI aj TUI. TUI akcie sa mapujú na `MessagesRequest`.
- **Textual aplikácia (`src/discoop/tui/`, rozloženie a klávesy podľa [ADR 0014](rozhodnutia/0014-tui-klavesnica-jeden-strom.md)):**
  - Hlavná obrazovka: jeden strom (servery → kategórie → kanály, všetko predvolene zbalené), vpravo panel Export (zoznam výberu a formulár), dole log, riadok s CLI príkazom (kopírovanie `c`) a klikateľný Footer. V úzkom okne (< 95 stĺpcov) jeden panel naraz (`1`, `2`, `3`, Tab).
  - Ovládanie primárne klávesnicou: šípky, Space/Enter, `/` filter, `e` vlastné okno kanála, `x`/Delete odoberie z výberu, `X` vymaže celý výber, `r`/`R`/`L` načítanie, `F5` export, Esc zastaví operáciu, `q` koniec. Tabuľka je v ADR 0014.
  - Vzhľad: téma `ansi-dark` (farby terminálu, Ctrl+P mení tému), ovládacie prvky `compact=True`, bez emoji.
  - Pravidlá: pohyb kurzorom nevolá Discord, naraz beží jedna sieťová operácia, Esc ukončí aj pauzy safe režimu (`CancelToken` v `bridge.py`), výber nemení kurzor ani rozbalenie.
  - `widgets.py`: `ChoiceRow`, `InputRow`, `TailInput`, `ActionRow`, `ConfirmRow`, `FormPanel`, `FilterInput`, `SelectedList`, `ChannelTree`, `TextView`, `display_name()`.
  - **Priečinok a názov exportu (P21, P23, [ADR 0016](rozhodnutia/0016-predvoleny-priecinok-exportov-v-tui.md)):** formulár má samostatné riadky `Folder` a `Name` (obidva predvolene prázdne). Prázdny `Name` je `discord-export-<dátum a čas>` (`discord-export-2026-1104-0108`), zadaný `Name` je len názov a nikdy cesta. Prázdny `Folder` je `discoop` v Dokumentoch používateľa (`paths.default_export_dir()` cez `platformdirs`, Windows, Linux aj macOS), config `export-dir` má prednosť, relatívny `Folder` leží v predvolenom priečinku. Mení sa v Settings (`Export folder`, trvalo) alebo v poli `Folder` (jeden export). CLI sa nemení. `[OVERENÉ]` na Windows, `[PREDPOKLAD]` na Linuxe a macOS.
  - Plánovač úloh (`plan_jobs` v `state.py`): kanály s rovnakým oknom do jednej úlohy, pri rôznych oknách podpriečinky (`01-7d`, `02-24h`...).
  - **Dialógy (`modals.py`):** Help (`F1`/`?`, živý `discoop --help`), Settings (`F2`), Login (`F3`, QR alebo token, token sa ukladá po overení), Preview, TimeWindow.
  - **Známe obmedzenia:** Esc počas bežiacej HTTP požiadavky zaberie až po jej skončení (timeout 20 s), pauzy pri opakovaní sťahovania príloh v `attachments.py` sa nedajú prerušiť hneď, v šírke 80 stĺpcov sa Footer nezmestí celý, CLI príkaz má vždy `--delay` z configu, v Help a Preview nefunguje výber textu myšou.
  - **Neoverené:** beh v skutočnom termináli (Windows Terminal), reálny účet, skenovanie QR telefónom. Overené sú Pilot testy s falošnými dátami a screenshoty.

#### H. Voliteľné diagnostické logovanie (`logs.py`, [ADR 0018](rozhodnutia/0018-logovanie.md), P24)
- **Modul `src/discoop/logs.py`:** `setup_logging`, `teardown_logging`, `DiscoopFormatter`. Predvolene vypnuté (žiadny handler), po zapnutí sa pripája výhradne na logger `discoop` (`propagate=False`).
- **Aktivácia:** globálne prepínače `--debug` (stderr) a `--log FILE` (súbor) alebo premenné prostredia `DISCOOP_DEBUG=1` a `DISCOOP_LOG=cesta`. Hoisting mechanizmus umožňuje použitie pred aj za podpríkazom.
- **Bezpečnostné záruky:** nikdy sa nelogujú autentifikačné tokeny, podpisy v CDN URL (`ex`, `is`, `hm`), texty správ, telá odpovedí, mená používateľov ani názvy kanálov/serverov (iba číselné snowflake ID). Loggery tretích strán (`httpx`, `httpcore`, `websockets`) sú stíšené na `WARNING`.
- **Integrácia s UI:** pri `--debug` sa vypína spinner. Príkaz `discoop ui --debug` je odmietnutý s kódom 8 (UI vlastní obrazovku), ale `discoop ui --log FILE` je povolené.

#### I. Diagnostika prostredia (`discoop doctor`, P25)
- **Nový príkaz `discoop doctor`:**
  - Kontroluje 6 kľúčových bodov behového prostredia:
    - `login`: prihlásenie cez `GET /users/@me` (`api.get_me()`),
    - `network`: dostupnosť Discord API (rozlíši sieťovú chybu od neplatného tokenu; pri neprihlásenom stave `skipped`),
    - `export_dir`: zapisovateľnosť priečinka exportov (`export-dir` z configu, inak aktuálny priečinok) cez `os.access` najbližšieho existujúceho rodiča (nič nevytvára),
    - `disk_space`: voľné miesto cez `shutil.disk_usage` (FAIL pod 100 MB, inak veľkosť v MB),
    - `cache`: vek cache serverov,
    - `version`: verzia nástroja (`__version__`).
  - Výstup: v plain režime riadky oddelené tabulátorom `check<TAB>OK|FAIL<TAB>detail`, v human režime tabuľka (`check`, `status`, `detail`).
  - Exit kód podľa prvého zlyhaného bodu (`AUTH_REQUIRED` 2, `NETWORK` 7, inak `ERROR` 1), pri úspechu 0.

#### J. Strojovo čitateľné výstupy a JSONL priebeh (P25)
- **JSON formát (`--format text|json`):**
  - Implementovaný na príkazoch `servers`, `channels`, `status` a `config list` cez `Output.json()`.
  - `servers` vracia zoznam objektov `[{"id": "...", "name": "...", "member_count": ...}]`.
  - `channels` vracia vždy plochý zoznam objektov `{id, name, type, type_name, category, position}`.
  - `status` a `config list` vracajú štruktúrované JSON objekty na stdout.
- **Priebeh sťahovania (`--progress-json`):**
  - Pre `discoop messages`: zapisuje JSONL udalosti na stderr (`channel_start`, `page`, `pause`, `channel_done`, `skipped`, `warning`).
  - Výpočet percent dokončenia (`~42%`) a odhadu času (ETA, napr. `about 3 min left`) podľa snowflake ID v spinneri aj vo verbose výstupe.

#### K. Pomocné moduly (`progress.py`, `profiles.py`, `tokens.py`, `resolve.py`, P25)
- **`src/discoop/progress.py`:** čisté funkcie `fraction_done`, `window_start_id`, `eta_seconds`, `format_eta` na kalkuláciu percent a odhadu zostávajúceho času podľa snowflake ID správ.
- **`src/discoop/profiles.py`:** správa profilov v `<config_dir>/profiles.json` (`load`, `save`, `delete`, `names`) s atomickým ukladaním.
- **`src/discoop/tokens.py`:** hrubý odhad počtu tokenov textu `estimate_tokens` (`len(text)/4`) a formátovanie `format_tokens`.
- **`src/discoop/resolve.py`:** fuzzy návrhy pri preklepoch v názve servera alebo kanála (`Did you mean: ...?`) cez `difflib.get_close_matches`.

#### L. Výskumný probe skript pre vlákna a fóra (`prototype/probe_threads.py`)
- Read-only probe skript a sekcia 4 v `prototype/README.md` pre overenie správania Discord API pri vláknach a fórach pred implementáciou kroku 4. Skript je pripravený pre spustenie používateľom na jeho účte.

---

## 3. Posledné commity na vetve `main`

GitHub (`origin`) je na `75f0310`, commity po ňom (9 nepushnutých) sú len lokálne. Push iba na pokyn používateľa. Kým nie je pushnuté, inštalácia z GitHubu dá starú verziu bez nového TUI.

| Commit | Správa | Význam |
|---|---|---|
| `a236a71` | `Add safe and fast download modes to discoop` | Zavedenie režimov `safe` (jitter, čítacie pauzy, delay medzi súbormi/kanálmi) a `fast`. |
| `f346b1d` | `Rename agent mode to plain mode with --plain flag` | Premenovanie agent mode na plain mode ([ADR 0012](rozhodnutia/0012-premenovanie-agent-mode-na-plain.md), P15), zachovanie `--agent` aliasu. |
| `1d3b38b` | `Extract messages orchestration into service layer and add ui command` | Vytvorenie `src/discoop/service.py` a registrácia príkazu `discoop ui`. |
| `bf0d3f6` | `Add TUI state management, job planner and cancellation bridge` | Stavová logika TUI (`state.py`), plánovač úloh (`plan_jobs`) a `CancelToken` (`bridge.py`). |
| `21e9e5c` | `Add Textual TUI screens, modals, styles and Pilot tests` | Kompletná implementácia Textual TUI (`app.py`, `modals.py`, `discoop.tcss`) a pilotné testy. |
| `75f0310` | `Document discoop ui TUI and ADR 0013` | Dokumentácia TUI v požiadavkách (P16, P17), návrhu nástroja, denníku a zápis [ADR 0013](rozhodnutia/0013-tui-a-spolocna-vrstva.md). |
| `bde52c6` | `Add live QR code login inside TUI LoginModal` | Zapojenie živého generovania a skenovania QR kódu priamo v TUI dialógu prihlásenia. |
| `a7a5347` | `Record keyboard-first TUI decisions` | Požiadavky P18–P20 a ADR 0014. |
| `470c127` | `Fix TUI preview jobs and typed event bridge` | Oprava preview jobov, typované udalosti namiesto `*args`. |
| `4e13acb` | `Redesign TUI main screen` | Jeden strom, panel Export, `widgets.py`, téma `ansi-dark`. |
| `4dc5f8b` | `Restyle TUI dialogs for keyboard use` | Help, Settings, Login, Preview, TimeWindow v rovnakom vzhľade, `tests/test_tui_modals.py`. |
| `72eeef4` | `Document TUI redesign` | Dokumentácia prerobeného TUI. |
| `db16aef` | `Add export name row to the TUI` | Riadok `Name` v TUI (P21). |

---

## 4. Čo nasleduje ďalej

Podľa plánu v [docs/navrh-nastroja.md](navrh-nastroja.md) (sekcia 14) a záznamu v [docs/dennik.md](dennik.md):

1. **Používateľský test prerobeného TUI na reálnom účte:**
   - Používateľ otestuje `discoop ui` (vo vývoji `uv run discoop ui`) v skutočnom termináli vrátane načítania serverov/kanálov, exportu v `safe` tempe a prihlásenia cez QR.
2. **Spustenie probe skriptu a krok 4 (Vlákna a fóra):**
   - Používateľ na svojom účte spustí pripravený skript `uv run python prototype/probe_threads.py` (anonymizovaný výstup do `prototype/out/`) na overenie stránkovania archivovaných a aktívnych vlákien, správania offsetov vo fórach a konzistencie `last_message_id`.
   - Na základe zistení z probe skriptu: implementácia príkazu `discoop threads` na zobrazenie aktívnych a archivovaných vlákien kanála.
   - Podpora prepínačov `--threads / --no-threads` v príkaze `discoop messages` a integrácia do TUI výberu.
3. **Krok 5 a 6: Pomocník pre AI agentov a synchronizácia:**
   - Príkaz `discoop agent-guide` pre rýchlu referenciu príkazov priamo do kontextu LLM.
   - Prepínač `--since-last` s ukladaním synchronizačného stavu posledného behu v `cache.db` a deduplikáciou správ.
4. **Rozhodnutie 9 (Výpočet prístupu ku kanálom):**
   - Ostáva **odložené s nízkou prioritou** (používateľ to nepovažuje za prioritu a Discord ohlásil zmenu API, pri ktorej prestane nedostupné kanály vracať).
