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
   - Zoznam všetkých požiadaviek používateľa (P1–P17). Zdroj pravdy o tom, čo má nástroj dokázať.
3. **[docs/navrh-nastroja.md](navrh-nastroja.md):**
   - Architektúra celého nástroja, štruktúra balíka `src/discoop/`, zoznam príkazov, exit kódy, dátové toky a otvorené otázky.
4. **[docs/dennik.md](dennik.md):**
   - Chronologický denník doterajšieho vývoja, záznamy testov na reálnom účte používateľa a riešené incidenty.
5. **[docs/rozhodnutia/README.md](rozhodnutia/README.md):**
   - Register všetkých Architectural Decision Records ([ADR 0001](rozhodnutia/0001-zaznamenavanie-a-verzovanie.md) až [ADR 0013](rozhodnutia/0013-tui-a-spolocna-vrstva.md)).

---

## 2. Aktuálny stav projektu (k 2026-11-03)

- **Testovacie pokrytie:** Všetkých **262 automatizovaných testov** prechádza (`uv run pytest`).
- **Nainštalované prostredie:** Python 3.12+, projekt spravovaný cez `uv`. Spúšťanie cez `uv run discoop ...`.

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
- **Textual aplikácia (`src/discoop/tui/`):**
  - 3-stĺpcový responzívny layout inšpirovaný Discordom: *Servery* │ *Kanály* │ *Export a logy*.
  - Pri zúžení terminálu (< 95 stĺpcov) sa rozhranie automaticky prepne na responzívne záložky (klávesy `1`, `2`, `3`).
  - Tlačidlá na načítanie serverov (`R`), kanálov vybraného servera (`C`) a kompletného načítania všetkých serverov naraz (`A` – beží v bezpečnom `safe` tempe).
  - Možnosť kedykoľvek zastaviť prebiehajúcu operáciu cez tlačidlo *Stop* / kláves `Esc` (implementované cez prerušiteľný `CancelToken` v `bridge.py`).
  - Výber kanálov medzerníkom (`Space`) naprieč viacerými servermi.
  - Individuálne časové okno pre vybraný kanál cez kláves `E` (`CustomWindowModal`).
  - Plánovač úloh (`plan_jobs` v `state.py`): zoskupuje kanály s rovnakým časovým oknom do dávok; pri rôznych oknách vytvára podpriečinky (`01-7d`, `02-24h`...).
  - Živý stavový riadok zobrazujúci presný ekvivalentný príkaz CLI (`discoop messages ...`), ktorý je možné skopírovať do schránky klávesom `C`.
  - **Modálne dialógy:**
    - `HelpScreen` (`F1` / `?`): kompletný manuál k TUI a živý výpis `discoop --help` generovaný cez `command_help()`.
    - `PreviewScreen`: okamžitý náhľad stiahnutých správ priamo v TUI.
    - `SettingsModal`: nastavenie režimu (`safe`/`fast`), cieľového priečinka, zipu a prepínačov.
    - `LoginModal`: plnohodnotné prihlásenie priamo v TUI – vygenerovanie a živé zobrazenie QR kódu v termináli aj možnosť manuálneho zadania tokenu.

---

## 3. Posledné commity na vetve `main` (nepushnuté na origin)

Všetky zmeny sú lokálne otestované a zakommitované na vetve `main`. Na vzdialený repozitár (`origin`) **nie sú pushnuté** (podľa pravidla čakať na pokyn používateľa).

| Commit | Správa | Význam |
|---|---|---|
| `a236a71` | `Add safe and fast download modes to discoop` | Zavedenie režimov `safe` (jitter, čítacie pauzy, delay medzi súbormi/kanálmi) a `fast`. |
| `f346b1d` | `Rename agent mode to plain mode with --plain flag` | Premenovanie agent mode na plain mode ([ADR 0012](rozhodnutia/0012-premenovanie-agent-mode-na-plain.md), P15), zachovanie `--agent` aliasu. |
| `1d3b38b` | `Extract messages orchestration into service layer and add ui command` | Vytvorenie `src/discoop/service.py` a registrácia príkazu `discoop ui`. |
| `bf0d3f6` | `Add TUI state management, job planner and cancellation bridge` | Stavová logika TUI (`state.py`), plánovač úloh (`plan_jobs`) a `CancelToken` (`bridge.py`). |
| `21e9e5c` | `Add Textual TUI screens, modals, styles and Pilot tests` | Kompletná implementácia Textual TUI (`app.py`, `modals.py`, `discoop.tcss`) a pilotné testy. |
| `75f0310` | `Document discoop ui TUI and ADR 0013` | Dokumentácia TUI v požiadavkách (P16, P17), návrhu nástroja, denníku a zápis [ADR 0013](rozhodnutia/0013-tui-a-spolocna-vrstva.md). |
| `bde52c6` | `Add live QR code login inside TUI LoginModal` | Zapojenie živého generovania a skenovania QR kódu priamo v TUI dialógu prihlásenia. |

---

## 4. Čo nasleduje ďalej

Podľa plánu v [docs/navrh-nastroja.md](navrh-nastroja.md) (sekcia 14) a záznamu v [docs/dennik.md](dennik.md):

1. **Používateľský test TUI a safe/fast režimov na reálnom účte:**
   - Používateľ otestuje interaktívne rozhranie spustením `uv run discoop ui`.
   - Overenie správania načítania serverov/kanálov, priebehu sťahovania v `safe` tempe a prípadného prihlásenia cez QR priamo v TUI.
2. **Krok 4: Vlákna a fóra (`discoop threads`):**
   - Implementácia príkazu `discoop threads` na zobrazenie aktívnych a archivovaných vlákien kanála.
   - Podpora prepínačov `--threads / --no-threads` v príkaze `discoop messages` a integrácia do TUI výberu.
3. **Krok 5 a 6: Pomocník pre AI agentov a synchronizácia:**
   - Príkaz `discoop agent-guide` pre rýchlu referenciu príkazov priamo do kontextu LLM.
   - Prepínač `--since-last` s ukladaním synchronizačného stavu posledného behu v `cache.db` a deduplikáciou správ.
4. **Rozhodnutie 9 (Výpočet prístupu ku kanálom):**
   - Ostáva **odložené s nízkou prioritou** (používateľ to nepovažuje za prioritu a Discord ohlásil zmenu API, pri ktorej prestane nedostupné kanály vracať).
