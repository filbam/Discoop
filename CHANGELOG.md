# Changelog

Všetky podstatné zmeny projektu. Formát podľa [Keep a Changelog](https://keepachangelog.com/sk/1.1.0/),
verzie podľa [SemVer](https://semver.org/).

## [Unreleased]

### Pridané
- **Voliteľné diagnostické logovanie (P24, [ADR 0018](docs/rozhodnutia/0018-logovanie.md)):**
  - Nový modul `src/discoop/logs.py` s funkciami `setup_logging`, `teardown_logging` a `DiscoopFormatter`. Predvolene je logovanie vypnuté (na logger `discoop` nie je pripojený žiadny handler), po zapnutí sa pripája výhradne naň (`propagate=False`).
  - Globálne CLI prepínače `--debug` (štruktúrovaný log na `stderr`) a `--log FILE` (append do súboru v UTF-8), ktoré fungujú pred aj za podpríkazom (`_hoist_mode_flags`).
  - Podpora premenných prostredia `DISCOOP_DEBUG=1` a `DISCOOP_LOG=cesta` (prepínač má prednosť).
  - Prísny bezpečnostný filter: nikdy sa neloguje token `Authorization`, podpísané URL príloh (`?ex=&is=&hm=`), texty správ, telá odpovedí, mená používateľov ani názvy serverov/kanálov (iba číselné ID).
  - Tretie strany (`httpx`, `httpcore`, `websockets`) sú stíšené na úroveň `WARNING`.
  - Logovanie v `api.py` (metóda, cesta bez query, povolené parametre, HTTP stav, latencia v ms, veľkosť odpovede, 429 pauzy a sieťové opakovania), `scrape.py` (stránky správ, počty, ID najstaršej/najnovšej správy) a `attachments.py` (len host z URL, status, zapísané bajty).
  - Automatické vypnutie animovaného spinnera pri `--debug`. `discoop ui --debug` je odmietnuté s kódom 8 a nápovedou (UI ovláda obrazovku), zatiaľ čo `discoop ui --log FILE` je povolené.
- **Diagnostika systému príkazom `discoop doctor` (P25):**
  - Nový príkaz `discoop doctor` na kontrolu 6 kľúčových bodov: prihlásenie (`login` cez `GET /users/@me`), dostupnosť Discord API (`network`, rozlíši chybu siete od neplatného tokenu; pri neprihlásení `skipped`), zapisovateľnosť priečinka exportov (`export_dir` z configu alebo aktuálneho priečinka cez `os.access` najbližšieho existujúceho rodiča), voľné miesto na disku cez `disk_usage` (`disk_space`, FAIL pod 100 MB), vek cache serverov (`cache`) a verzia nástroja (`version`).
  - Výstup v plain režime vo formáte `check<TAB>OK|FAIL<TAB>detail`, v human režime tabuľka (`check`, `status`, `detail`). Exit kód podľa prvého zlyhaného bodu (`AUTH_REQUIRED` 2, `NETWORK` 7, inak `ERROR` 1), pri úspechu 0.
- **Strojovo čitateľné zoznamy a formát JSON (P25):**
  - Prepínač `--format text|json` pre príkazy `servers`, `channels`, `status` a `config list`.
  - Pomocná metóda `Output.json(data)` pre unifikovaný JSON výstup na `stdout`. Diagnostické správy (napr. vek cache) idú na `stderr`.
  - `servers` vracia zoznam objektov `[{"id": "...", "name": "...", "member_count": ...}]`.
  - `channels` vracia plochý zoznam `{id, name, type, type_name, category, position}` rešpektujúci filter `--type`.
- **JSONL priebeh a odhad času pri sťahovaní správ (P25):**
  - Prepínač `--progress-json` pre `discoop messages`: emituje štruktúrované JSONL riadky na `stderr` pre udalosti `channel_start`, `page`, `pause`, `channel_done`, `skipped`, `warning`.
  - Výpočet percent dokončenia (`~42%`) a odhadu zostávajúceho času (ETA, napr. `about 3 min left`) v spinneri human režimu aj vo verbose textovom výstupe (`messages -v`).
- **Nové pomocné moduly a inteligentné správanie CLI (P25):**
  - `src/discoop/progress.py`: výpočet percent a odhadu času (`fraction_done`, `window_start_id`, `eta_seconds`, `format_eta`) na základe Discord snowflake ID.
  - `src/discoop/profiles.py`: správa pomenovaných profilov v `<config_dir>/profiles.json` (`load`, `save`, `delete`, `names`) s atomickým zápisom a validáciou.
  - `src/discoop/tokens.py`: odhad počtu tokenov textu `estimate_tokens` a formátovanie `format_tokens`.
  - `src/discoop/resolve.py`: automatické návrhy pri preklepe v názve servera alebo kanála (`Did you mean: ...?`) cez `difflib.get_close_matches` pri `NotFoundError`.
- **Výskumný probe skript pre vlákna a fóra (`prototype/probe_threads.py`):**
  - Read-only probe skript a sekcia 4 v `prototype/README.md` pre overenie správania Discord API pri vláknach a fórach (`threads/search`, offsety, typy vlákien, porovnanie `last_message_id`).
- **Inštalácia z GitHubu (P22, [ADR 0015](docs/rozhodnutia/0015-verejne-repo-a-instalacia.md)):** `uv tool install git+https://github.com/filbam/Discoop` dá príkaz `discoop` bez `uv run`. README má návod pre Windows, Linux a macOS (inštalácia, aktualizácia, odinštalovanie) a sekciu Vývoj. Repo `filbam/Discoop` je verejné.
- **Priečinok a názov exportu v TUI (P21, P23, [ADR 0016](docs/rozhodnutia/0016-predvoleny-priecinok-exportov-v-tui.md)):** riadok formulára `Path` je nahradený dvoma samostatnými riadkami `Folder` a `Name` (v tomto poradí, obidva predvolene prázdne, pri Target=preview skryté).
  - Prázdny `Name`: `discord-export-<dátum a čas>` v miestnom čase, napr. `discord-export-2026-1104-0108` (`YYYY-MMDD-HHMM`). Názov sa zafixuje pri `F5`. Kolízia automatického názvu v tej istej minúte pridá `-2`, `-3`.
  - Zadaný `Name` je vždy len názov, nikdy cesta: prečistí sa cez `safe_name` (lomky a neplatné znaky sa nahradia `_`). Kolíziu nerieši, opakovaný export do neho pokračuje. Zip dostane príponu `.zip` (nikdy `.zip.zip`).
  - Prázdny `Folder`: predvolený priečinok `discoop` v Dokumentoch používateľa (`platformdirs.user_documents_dir()`), rovnako na Windows, Linuxe aj macOS. Config `export-dir`, ak je nastavený, má prednosť. Priečinok vznikne až pri prvom exporte.
  - Neprázdny `Folder`: `~` je domovský priečinok, absolútna cesta sa použije ako je, relatívna leží vo vnútri predvoleného priečinka. Trvalo sa predvolený priečinok mení v Settings (`F2`, `Export folder`), v poli `Folder` len pre jeden export.
  - Placeholdery ukazujú skutočný predvolený priečinok (dlhá cesta sa skráti zľava, aby ostal koniec) a názov. Obnovujú sa spolu s riadkom s CLI príkazom každých 30 s. Cesty v `--out`/`--zip` sú absolútne a s lomkami. Log ukáže skutočnú cestu (`Saving to ...`).
  - CLI sa nezmenilo: `discoop messages --out/--zip` ostáva relatívne k aktuálnemu priečinku alebo `export-dir`. Popis kľúča `export-dir` spomína predvolený priečinok TUI.
  - Nová `paths.documents_dir()` a `paths.default_export_dir()`, nový `TailInput` v `widgets.py`.
- **Interaktívne terminálové rozhranie (`discoop ui`, TUI) a spoločná servisná vrstva ([ADR 0013](docs/rozhodnutia/0013-tui-a-spolocna-vrstva.md)):**
  - **Príkaz `discoop ui` a prepínač `--ui`:**
    - Plnohodnotné vizuálne terminálové prostredie postavené na knižnici Textual pre pohodlné interaktívne ovládanie klávesnicou (šípky, Enter, Space).
    - V `--plain` režime alebo mimo interaktívneho terminálu skončí kódom 8 (`BAD_ARGS`). Samotné `discoop` bez argumentov naďalej vypisuje help.
    - Lazy import knižnice `Textual`: bežné CLI príkazy neplatia žiadnu réžiu inicializácie TUI frameworku.
  - **Rozloženie ([ADR 0014](docs/rozhodnutia/0014-tui-klavesnica-jeden-strom.md)):**
    - Jeden strom (servery, kategórie, kanály; všetko predvolene zbalené), vpravo panel Export (zoznam výberu a formulár), dole log, riadok s CLI príkazom a Footer s klávesmi.
    - V úzkom okne (< 95 stĺpcov) sa ukazuje jeden panel naraz.
    - Ovládanie primárne klávesnicou (šípky, Space, Enter, Tab, `/` filter), myš je doplnok. Tabuľka klávesov je v ADR 0014.
    - Tlačidlá na načítanie serverov a kanálov jednotlivo aj hromadne (`R`, `r`, `L`) s `safe` tempom a okamžitým zastavením cez Esc.
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
  - Nový balík `src/discoop/tui/` (`app.py`, `state.py`, `bridge.py`, `modals.py`, `widgets.py`, `discoop.tcss`).
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
- **Upratanie CLI a rozšírenie testov (2026-11-04):**
  - Z `src/discoop/cli.py` bol odstránený nepoužívaný kód (`_export_target`, `_export`, `_message_targets`, `_progress`, `_unreadable`, `_local_time`).
  - Rozšírenie testovacieho balíka na 511 automatizovaných testov (85 nových testov pokrývajúcich diagnostické logovanie, doctor, JSON formáty, profily, pomocné moduly a návrhy pri preklepe).
- **TUI prerobené podľa [ADR 0014](docs/rozhodnutia/0014-tui-klavesnica-jeden-strom.md) (2026-11-04)** na základe skúšky používateľa:
  - Rozloženie: jeden strom namiesto troch stĺpcov, panel Export, log vždy dole. Pôvodný „Discord-inspired“ layout z ADR 0013 nahradený.
  - Vzhľad: téma `ansi-dark` (farby terminálu), Ctrl+P mení tému. CSS bez hex farieb, prvky vysoké 1 riadok (`compact=True`), bez emoji a veľkých tlačidiel.
  - Nový `tui/widgets.py` (`ChoiceRow`, `InputRow`, `ActionRow`, `ConfirmRow`, `FormPanel`, `FilterInput`, `SelectedList`, `ChannelTree`, `TextView`, `display_name()`).
  - Dialógy Help, Settings, Login, Preview a TimeWindow majú rovnaký vzhľad. `TextView` kreslí len viditeľné riadky (pri 5000 správach 0,1–0,4 s, `Static` 1,5–8,7 s), v Help a Preview preto nefunguje výber textu myšou.
  - Pravidlá: pohyb kurzorom nevolá Discord, naraz beží jedna sieťová operácia, Esc ukončí pauzy okamžite (aj pri `L`), výber nemení kurzor ani rozbalenie.
  - Nové: `X` vymaže celý výber, po zmene prihlásenia sa výber vyčistí, `e` a uloženie okna na nevybranom kanáli ho aj vyberie, Esc v strome vymaže aktívny filter, pri Target=preview sú skryté Attachments a Max MB, pri QR sa formulár nahradí kódom (pod 27 riadkov bez rámika a Footera).
  - Zhrnutie behu uvádza kanály, správy, preskočené, orezané a stav príloh.
  - 376 testov, nový `tests/test_tui_modals.py`.
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
- **TUI (2026-11-04):**
  - Prázdne tlačidlá (`height: 1` pri vysokom rámiku), prestavba celého stromu pri každom výbere (kurzor skákal hore), zadrhávanie.
  - Kategórie boli vždy rozbalené. Kategória bez vyberateľných kanálov ukazovala `[✓]`. Enter na kategórii ju rozbalil aj vybral.
  - Pohyb po serveroch volal sieť a súbežné workery obchádzali safe tempo.
  - Preview posielal `--print` a `--no-files` bez `--out`, čo služba odmietla. Uloženie preview prepísalo súbor.
  - Pauzy API sa nedali prerušiť, „Load all“ sa nedal zastaviť, `q` nezastavil beh, `space` a `e` pôsobili bez ohľadu na focus.
  - Pri neplatnom tokene sa ukazovalo zelené `@user`. Overenie tokenu blokovalo UI vlákno, logout šiel bez potvrdenia, token sa ukladal pred overením.
  - Nastavenia z configu (`mode`, `delay`, `export-dir`) sa v TUI neprejavili. Režim v Settings bol voľný text. Enter v poli časového okna neuložil.
  - Správa „finished successfully“ aj pri preskočených kanáloch.
  - Preview a Help brali hranaté zátvorky ako markup, Help nesedel s klávesmi, log nebol vidno bez scrollovania.
  - Variačné selektory v názvoch rozhadzovali zarovnanie (`display_name()`).
  - `WindowSpec.slug()`/`label()` pri `from_=None` a zip cesta končiaca lomkou.
  - `filter_channels` zhodoval čísla ako podreťazec ID, teraz len celé ID.
  - `TuiEvents` hádal argumenty cez `*args`, odstránené mŕtve záložné kópie tried v `state.py` a `bridge.py`.
- **Výstup `discoop messages`** po teste používateľa 2026-11-03 (3 nové regresné testy, spolu 164):
  - Embed nezopakuje URL, ktorú správa už ukazuje. GIF poslaný ako holá URL mal pod textom `[image]` s tou istou
    URL. Ostane len značka s titulkom, embed bez titulku sa vynechá. JSON má embedy celé.
  - Prázdne riadky na začiatku a konci textu správy a popisu rich embedu sa orežú, `\r\n` sa zmení na `\n`.
    V human režime je tak medzi správami vždy jeden prázdny riadok.
  - Rich embed bez URL a titulku už nemá za `[embed]` medzeru navyše.
