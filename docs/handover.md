# Odovzdanie stavu projektu discoop (Handoff)

Tento dokument slúži ako kompletný a prehľadný súhrn stavu projektu `discoop` pre ďalšieho AI agenta alebo vývojára, ktorý preberá prácu na repozitári.

---

## 1. Úvod a povinné čítanie

Pred začatím akejkoľvek práce si **povinne prečítaj** nasledujúce dokumenty:

1. **[CLAUDE.md](../CLAUDE.md):**
   - **Práca cez subagentov ([ADR 0010](decisions/0010-work-through-agents.md)):** Hlavný Claude riadi prácu, zadáva agentom konkrétne ohraničené úlohy a sám kontroluje výsledky (diff, testy). Subagenti sami necommitujú ani nepushujú.
   - **Zákaz živých volaní Discord API:** Automatizované testy bežia **výhradne offline** cez MockTransport a anonymizované fixtures v `tests/fixtures/`. Živé API smie spúšťať len používateľ na svojom účte.
   - **Git pravidlá:** Vetva `main`, autor `filbam <f.bambura@gmail.com>`. Commitovanie po každom overenom kroku (robí hlavný Claude), **zákaz `git push` bez výslovného pokynu používateľa**.
   - **Zaznamenávanie všetkého ([ADR 0001](decisions/0001-record-everything-and-version-it.md)):** Každá zmena, rozhodnutie alebo požiadavka musí byť zapísaná v dokumentácii v tom istom pracovnom kroku.
2. **[docs/requirements.md](requirements.md):**
   - Zoznam všetkých požiadaviek používateľa (P1–P30). Zdroj pravdy o tom, čo má nástroj dokázať.
3. **[docs/design.md](design.md):**
   - Architektúra celého nástroja, štruktúra balíka `src/discoop/`, zoznam príkazov, exit kódy, dátové toky a otvorené otázky.
4. **[docs/journal.md](journal.md):**
   - Chronologický denník doterajšieho vývoja, záznamy testov na reálnom účte používateľa a riešené incidenty.
5. **[docs/decisions/README.md](decisions/README.md):**
   - Register všetkých Architectural Decision Records ([ADR 0001](decisions/0001-record-everything-and-version-it.md) až [ADR 0020](decisions/0020-since-last.md)).
6. **[docs/analyses/thread-probe-2026-11-04.md](analyses/thread-probe-2026-11-04.md):**
   - Výsledky probe meraní pre vlákna, fóra a `last_message_id` na reálnom účte Discordu s dôsledným rozlíšením `[OVERENÉ]` a `[PREDPOKLAD]`.
7. **[docs/analyses/real-account-check-2026-11-04.md](analyses/real-account-check-2026-11-04.md):**
   - Výsledky skúšky nástroja `discoop` na reálnom účte (2026-11-04, režim `safe`, malé okná): čo sa overilo, známe obmedzenie pri prílohách, otvorené pozorovania a zoznam toho, čo ostáva neoverené.

---

## 2. Aktuálny stav projektu (k 2026-11-04)

- **Testovacie pokrytie:** Všetkých **870 automatizovaných testov** prechádza (`uv run pytest`). Všetky bežia offline proti falošnému Discordu (`httpx.MockTransport`). Funkcie kola 2 sa 2026-11-04 čiastočne overili aj na reálnom účte (odolný export s prerušením skriptom, vlákna a fóra, `--since-last`, `--max-tokens` so zipom, logy, `--progress-json`, `doctor`, beh `discoop ui` s QR prihlásením; podrobne [analýza](analyses/real-account-check-2026-11-04.md)). Čo ostáva neoverené, je v sekcii 4.
- **Pôvod kola 2:** implementáciu (P26–P30) urobil Antigravity podľa `docs/briefs/antigravity-round-2.md`, potom ju skontroloval hlavný Claude a nálezy nechal opraviť. Čo sa našlo a opravilo, je v [journal.md](journal.md), sekcia 2026-11-04.
- **Nainštalované prostredie:** Python 3.12+, projekt spravovaný cez `uv`. Vývoj v repe ide cez `uv run discoop ...`, používatelia majú nainštalovaný príkaz `discoop` (`uv tool install git+https://github.com/filbam/Discoop`, návod v [README.md](../README.md)).
- **Repo je verejné** (P22, [ADR 0015](decisions/0015-public-repo-and-installation.md)). Do gitu nesmie ísť token, cookies ani mená a texty správ iných ľudí. `[OVERENÉ]`: inštalácia z lokálneho klonu na Windows. `[PREDPOKLAD]`: inštalácia z GitHubu, Linux, macOS.

### Prehľad implementovaných funkcií

#### A. Autentifikácia a identita (`login.py`, `remote_auth/`, `tokenstore.py`)
- **`discoop login`:**
  - Primárna cesta: **QR login bez prehliadača** v termináli ([ADR 0005](decisions/0005-qr-login-without-a-browser.md), P14) cez Discord remote auth gateway (WebSocket, RSA-OAEP-SHA256 výmena kľúčov, vykreslenie QR cez `segno`).
  - Podpora testovacieho handshake bez prihlásenia (`--handshake-only`).
  - Záložné prihlásenie cez `--token` zo skrytého interaktívneho vstupu alebo stdin ([ADR 0008](decisions/0008-fallback-login-token.md)). V plain režime je interaktívny login odmietnutý s kódom `2` ([ADR 0009](decisions/0009-login-in-agent-mode.md)).
- **`discoop status`:** Vypíše stav prihlásenia, informácie o účte používateľa a vek lokálnej cache.
- **`discoop logout`:** Bezpečne odstráni token zo systémového keyringu OS (Windows Credential Manager, macOS Keychain, Linux Secret Service).

#### B. Servery, kanály a konfigurácia (`cache.py`, `config.py`, `resolve.py`)
- **`discoop servers` & `discoop channels`:**
  - Výpis serverov a kanálov, ukladanie do lokálnej SQLite databázy `cache.db` (umiestnenej podľa štandardov OS cez `platformdirs`).
  - Vyhľadávanie a filtrovanie kanálov podľa ID, presného mena alebo glob vzorov (`resolve.py`). Vyhľadávanie je odolné voči diakritike, veľkosti písmen a odstraňuje emoji.
- **`discoop config`:**
  - Správa konfiguračných hodnôt: `default-server`, `delay`, `export-dir`, `mode` (`safe` / `fast`).

#### C. Sťahovanie správ (`cli.py`, `service.py`, `scrape.py`, `snowflake.py`)
- **`discoop messages`:**
  - Časové okná: `--from`, `--to` (dátum, dátum a čas alebo relatívne `7d`, `48h`, `2w`, `now`, pri `--from` aj `all`), `--last N` vráti N najnovších správ. Prepočet na Discord snowflake ID.
  - Formáty výstupu pre konzolu: `text` (predvolený čistý text), `md` (Markdown), `json` a `jsonl`.
  - Prepínač `--print` (súbežný výpis správ popri exporte).

#### D. Odolný export a sťahovanie príloh (`export.py`, `attachments.py`, [ADR 0017](decisions/0017-reliable-export-and-partial-success.md), P26)
- **Zápis po kanáloch a staging `<cieľ>.partial`:**
  - `ExportWriter` zapisuje správy a súbory priebežne po jednotlivých kanáloch do dočasného umiestnenia `<cieľ>.partial` (pri zip archíve `<názov>.zip.partial`), bez držania celej histórie v pamäti.
  - Atomické publikovanie do cieľového priečinka alebo zip súboru nastáva až pri úspešnom dokončení celého behu (`close(complete=True)`). Predchádzajúci hotový export sa nikdy neprepíše prerušeným behom.
- **Automatická obnova (resume):**
  - Ak pri spustení exportu existuje rozpracovaný `<cieľ>.partial` a jeho odtlačok (`request_fingerprint`) zodpovedá požiadavke, beh automaticky preskočí hotové kanály a ich stiahnuté prílohy a pokračuje v sťahovaní zvyšných kanálov. Odtlačok zahŕňa aj `threads` a `since_last`: prerušený export s vláknami nepokračuje beh s `--no-threads` a normálny beh nenadviaže na `--since-last` (a opačne), začne odznova. Režim sťahovania a `--max-tokens` odtlačok nemenia.
  - Relatívne okná sa počítajú od pôvodného času vzniku behu (`Resume.created`).
  - Prepínač `--print` v kombinácii s obnovou, kde už sú hotové kanály, je odmietnutý (kód 8) ešte pred sťahovaním správ.
- **Poctivý výsledok a návratový kód `ExitCode.PARTIAL = 9`:**
  - Preskočenie nedostupného kanála pre chýbajúce oprávnenie (HTTP 403 `NO_ACCESS`), neexistenciu (HTTP 404 `NOT_FOUND`), chybu sťahovania prílohy alebo preskočenie chybného vlákna vyústi do kódu ukončenia `9`.
  - Zámerné vynechanie súborov používateľom cez `--no-files` alebo `--max-file-size` kód 9 nevyvoláva (vracia kód 0).
- **CDN klient a bezpečnosť:**
  - Prílohy sťahuje samostatný HTTP klient **bez tokenu v hlavičkách** (ochrana pred únikom pri CDN presmerovaniach).
  - Obnova exspirovaných podpisov cez read-only `POST /attachments/refresh-urls` v dávkach po 50 (s predstihom 60 s pred vypršaním alebo po chybách 403, 404, 410) priebežne po jednotlivých kanáloch.
  - Bezpečné mená súborov pre Windows, Linux a macOS (limit 100 znakov / 200 bajtov, orezanie bodiek a medzier, prefix `_` pre rezervované názvy Windows ako `CON`, `NUL`).
  - Atomický zápis jednotlivých súborov s príponou `.part`.
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

#### F. Plain mode (`--plain`, [ADR 0012](decisions/0012-rename-agent-mode-to-plain.md), P15)
- Režim pôvodne nazvaný „agent mode“ bol premenovaný na **Plain mode**.
- Prepínač `--plain` alebo premenná prostredia `DISCOOP_PLAIN=1`.
- Výstup je čistý, nestylovaný text bez ANSI kódov, tabuliek a Rich prvkov (šetrí tokeny pre AI agentov a je priamo parsovateľný).
- Pôvodný prepínač `--agent` a `DISCOOP_AGENT=1` sú ponechané ako plne funkčné skryté spätné aliasy.

#### G. Interaktívne terminálové rozhranie TUI (`discoop ui`, [ADR 0013](decisions/0013-tui-and-shared-service-layer.md), P16–P17)
- **Spoločná servisná vrstva (`src/discoop/service.py`):**
  - Vyčlenená biznis logika pre načítanie serverov (`list_servers`), kanálov (`list_channels`), kompletnej štruktúry (`load_all`), rezolúciu cieľov (`resolve_targets`) a sťahovanie správ (`run_messages`).
  - Spoločná pre CLI aj TUI. TUI akcie sa mapujú na `MessagesRequest`.
- **Textual aplikácia (`src/discoop/tui/`, rozloženie a klávesy podľa [ADR 0014](decisions/0014-tui-keyboard-one-tree.md)):**
  - Hlavná obrazovka: jeden strom (servery → kategórie → kanály, všetko predvolene zbalené), vpravo panel Export (zoznam výberu a formulár), dole log, riadok s CLI príkazom (kopírovanie `c`) a klikateľný Footer. V úzkom okne (< 95 stĺpcov) jeden panel naraz (`1`, `2`, `3`, Tab).
  - Ovládanie primárne klávesnicou: šípky, Space/Enter, `/` filter, `e` vlastné okno kanála, `x`/Delete odoberie z výberu, `X` vymaže celý výber, `r`/`R`/`L` načítanie (`L` = kanály všetkých serverov), `F5` export, Esc zastaví operáciu, `q` koniec, `P` uloží a `p` načíta profil, `o` otvorí priečinok posledného exportu. Tabuľka je v ADR 0014, nové klávesy v jeho sekcii „Doplnenie 2026-11-04“.
  - Vzhľad: téma `ansi-dark` (farby terminálu, Ctrl+P mení tému), ovládacie prvky `compact=True`, bez emoji.
  - Pravidlá: pohyb kurzorom nevolá Discord, naraz beží jedna sieťová operácia, Esc ukončí aj pauzy safe režimu (`CancelToken` v `bridge.py`), výber nemení kurzor ani rozbalenie.
  - `widgets.py`: `ChoiceRow`, `InputRow`, `TailInput`, `ActionRow`, `ConfirmRow`, `FormPanel`, `FilterInput`, `SelectedList`, `ChannelTree`, `TextView`, `display_name()`.
  - **Priečinok a názov exportu (P21, P23, [ADR 0016](decisions/0016-default-export-folder-in-tui.md)):** formulár má samostatné riadky `Folder` a `Name` (obidva predvolene prázdne). Prázdny `Name` je `discord-export-<dátum a čas>` (`discord-export-2026-1104-0108`), zadaný `Name` je len názov a nikdy cesta. Prázdny `Folder` je `discoop` v Dokumentoch používateľa (`paths.default_export_dir()` cez `platformdirs`, Windows, Linux aj macOS), config `export-dir` má prednosť, relatívny `Folder` leží v predvolenom priečinku. Mení sa v Settings (`Export folder`, trvalo) alebo v poli `Folder` (jeden export). CLI sa nemení. `[OVERENÉ]` na Windows, `[PREDPOKLAD]` na Linuxe a macOS.
  - Plánovač úloh (`plan_jobs` v `state.py`): kanály s rovnakým oknom do jednej úlohy, pri rôznych oknách podpriečinky (`01-7d`, `02-24h`...).
  - **Dialógy (`modals.py`):** Help (`F1`/`?`, živý `discoop --help`), Settings (`F2`), Login (`F3`, QR alebo token, token sa ukladá po overení), Preview, TimeWindow.
  - **Vylepšenia z 2. kola (P30):**
    - Perzistentný stav TUI v `<config_dir>/tui-state.json` viazaný na ID účtu (`tuistate.py`): automatická obnova výberu kanálov po serveroch, časových okien, režimu `safe`/`fast`, polí `Folder`/`Name`, prepínača vlákien a dátumov posledných exportov kanálov. Obnovuje sa voči kanálom z cache, ID, ktoré tam nie sú, sa zahodia. Stav sa ukladá až po tom, čo sa uložený stav účtu načítal (opravený štartovací súbeh, ktorý ho mohol prepísať predvolenými hodnotami). Zlyhanie disku TUI nezhodí (varovanie v logu). Zápis nie je oneskorený (debounce): beží pri každej zmene (`_save_tui_state`). Dátum posledného exportu sa pri náhľade (preview) nezapisuje.
    - Prepínač Threads vo formulári exportu pre zapnutie/vypnutie sťahovania vlákien.
    - Správa profilov cez klávesové skratky: `P` (veľké) uloží aktuálny výber, časové okno a režim ako profil, `p` (malé) načíta uložený profil. `L` je „načítať kanály všetkých serverov“. Profily sú v `profiles.json` spolu s profilmi z CLI. Ručne upravený profil so zlými typmi hodnôt TUI toleruje.
    - Klávesová skratka `o` otvorí priečinok posledného exportu (pri zipe priečinok, v ktorom zip leží) v systémovom prieskumníkovi (`os.startfile` / `xdg-open` / `open`). Je aktívna po dokončenom exporte a nie počas behu úlohy.
    - Prípony riadkov kanálov v strome: každý kanál má stlmenú príponu zarovnanú doprava s časom od poslednej aktivity (`now`, `5m`, `3h`, `2d`, `4mo`, `1y`, z `Channel.last_message_id`) a pri kanáli exportovanom z tohto účtu s dátumom posledného exportu (`exp 11-03`, miestny dátum, s rokom, ak je z iného roka). V úzkom riadku vypadne najprv dátum exportu, potom aktivita, názov kanála sa nikdy nekráti. Obnovujú sa po exporte, po obnovení stavu a každých 60 s (`format_activity` a `format_last_exported` v `tuistate.py`, vykreslenie v `ChannelTree`).
    - Zobrazenie percent a odhadu času (ETA) v progress bare podľa `progress.py`.
    - Fixovanie názvu exportu v poli `Name` po prerušení, takže stlačenie `F5` v ďalšej minúte pokračuje v existujúcom `.partial`.
  - **Fóra a media kanály v TUI (2026-11-04):** vyberajú sa ako ostatné kanály (výber berie `MESSAGE_TYPES` aj `FORUM_TYPES`; kategória sa nevyberá, jej výber vyberie jej kanály). Ich príspevky sú vlákna, preto pri Threads = no a vybranom fóre formulár ukáže varovanie a `F5` štart odmietne hláškou ešte pred prvým volaním Discordu (služba by to odmietla s kódom 8). Overené len testami s falošným Discordom (`tests/test_tui_forums.py`).
  - **Známe obmedzenia:** TUI nemá `--since-last` ani `--max-tokens`. Esc počas bežiacej HTTP požiadavky zaberie až po jej skončení (timeout 20 s), pauzy pri opakovaní sťahovania príloh v `attachments.py` sa nedajú prerušiť hneď, v šírke 80 stĺpcov sa Footer nezmestí celý, CLI príkaz má vždy `--delay` z configu, v Help a Preview nefunguje výber textu myšou.
  - **Overenie:** pôvodne iba Pilot testy s falošnými dátami a screenshoty. Používateľ 2026-11-04 potvrdil, že `discoop ui` na reálnom účte funguje a že sa v ňom prihlásil cez QR ([analýza](analyses/real-account-check-2026-11-04.md)). Neoverené ostáva Ctrl+C v TUI, výber fór a prepínač Threads na reálnom účte; samostatne nepotvrdené sú aj skratka `o`, profily `P`/`p`, prípony v strome a `tui-state.json`. Linux a macOS tiež.

#### H. Voliteľné diagnostické logovanie (`logs.py`, [ADR 0018](decisions/0018-logging.md), P24)
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

#### L. Vlákna a príspevky na fórach (`threads.py`, [ADR 0019](decisions/0019-threads.md), P27)
- **Analýza a probe:** overené na používateľskom účte v [docs/analyses/thread-probe-2026-11-04.md](analyses/thread-probe-2026-11-04.md). Skúška samotného nástroja na reálnom účte (výpis vlákien, export fóra, `message_count` bez štartovacej správy príspevku): [docs/analyses/real-account-check-2026-11-04.md](analyses/real-account-check-2026-11-04.md).
- **Sťahovanie vlákien v `messages`:**
  - Vlákna sú predvolene zapnuté (`request.threads = True`), možnosť ich vypnúť cez `--no-threads`.
  - Fóra (typ 15) a mediálne kanály (typ 16) sú plnohodnotnými cieľmi `messages` (sťahujú svoje vlákna). Fórum s `--no-threads` je odmietnuté s kódom 8. V TUI sa vyberajú ako ostatné kanály, pri Threads = no sa štart odmietne už vo formulári.
  - Sťahovanie aktívnych aj archivovaných vlákien cez `GET /channels/{id}/threads/search` s `limit=25`, stránkovaním podľa offsetu a detekciou konca prázdnou alebo neúplnou stranou (< 25).
  - Vnorenie sekcií vlákien v `channels/<kanál>.md`, plochý formát v `messages.jsonl` s atribútom `thread`, prílohy vlákien smerujú do `files/<rodič>/`.
  - Limity `--max-messages` a `--last N` platia nezávisle na kanál a na každé vlákno.
  - HTTP 403/404 na jednotlivom vlákne vlákno preskočí s varovaním a beh pokračuje s kódom ukončenia 9 (`ExitCode.PARTIAL`).
- **Príkaz `discoop threads`:**
  - Rýchly výpis vlákien kanála a príspevkov vo fórach bez sťahovania správ (`-s SERVER -c CHANNEL`).
  - Podpora formátov `human` (Rich tabuľka), `plain` (TSV) a `--format json`.

#### M. Prírastkové sťahovanie a kontrola disku (`syncstate.py`, [ADR 0020](decisions/0020-since-last.md), P28)
- **Prepínač `messages --since-last`:**
  - Sťahuje správy novšie ako posledný úspešný export každého kanála a vlákna.
  - Perzistentný súbor `sync-state.json` v `paths.data_dir()` oddelený od SQLite cache (prežije `clear_cache`), kľúčovaný ID používateľského účtu.
  - Exkluzívna spodná hranica `min_id = int(saved_id) + 1` chráni pred duplicitami.
  - Posun stavu nastáva až po úspešnom a úplnom dokončení exportu kanála (nie pri chybe ani pri `truncated`).
  - Preskakovanie neaktívnych kanálov: zoznam kanálov servera sa pri `--since-last` obnoví a ak má kanál uložený stav a `Channel.last_message_id <= saved_id`:
    - kanál, ktorý nemôže mať vlákna, alebo akýkoľvek kanál pri `--no-threads`: preskočí sa úplne (0 požiadaviek, `_is_channel_unchanged` v `service.py`),
    - textový alebo oznamovací kanál so zapnutými vláknami: jeho vlastné správy sa nesťahujú, ale zoznam jeho vlákien sa načíta a vlákna sa stiahnu ako inak (`_is_own_unchanged`),
    - fórum a media kanál sa nepreskakujú nikdy.
    - `[PREDPOKLAD]` `last_message_id` textového kanála je spoľahlivé: z probe vlákien (2 vzorky) a z kontroly na reálnom účte 2026-11-04 (20 z 25 čitateľných kanálov sedelo, v 4 ukazovalo na novšiu správu, v 1 bola správa novšia než pole). Ak by ho Discord oneskoroval, nová správa kanála by sa mohla vynechať, až kým v ňom nepribudne ďalšia.
  - Po prerušenom a obnovenom behu si kanály uložené prerušeným behom ponechajú starý stav a nabudúce sa stiahnu znova (duplicity, nič sa nestratí). Beh na to upozorní poznámkou.
  - Kontrola voľného miesta na disku: pred stiahnutím príloh každého kanála (`service._check_disk_space`) sa spočíta, čo sa naozaj stiahne (`ExportWriter.bytes_to_download`: bez súborov, ktoré už v exporte sú, bez `--no-files` a nad `--max-file-size`), a porovná s voľným miestom cez `shutil.disk_usage`. Ak nezostáva aspoň 50 MB bezpečnostná rezerva, beh zlyhá s kódom 1 pred odoslaním požiadaviek na CDN.

#### N. Delenie na tokeny, odhad tokenov a profily v CLI (`split.py`, `profiles.py`, P29)
- **Delenie na tokeny (`--max-tokens N`):**
  - Modul `src/discoop/split.py` a funkcia `split_markdown(text, max_tokens)` delí `messages.md` na očíslované časti `parts/part-NNN.md` s hlavičkou `<!-- discoop part X of Y -->`. Delí sa len na skutočných hraniciach správ a nadpisov kanálov a vlákien: správa s riadkom `# Nadpis` ostane celá. Obmedzenie: riadok v tele správy, ktorý presne vyzerá ako `[2026-01-01 10:00] x` hneď za prázdnym riadkom, sa od hlavičky správy odlíšiť nedá. Správa väčšia ako limit ide sama do jednej časti s varovaním.
  - `--max-tokens` funguje s `--out` aj `--zip` (bez nich kód 8 pred volaním API). Časti sa zapisujú do staging priečinka pri `close(complete=True)` a publikujú sa spolu s exportom, takže pád pred koncom nenechá v cieli žiadne `parts/`. Pri opakovanom exporte do priečinka sa staré `parts/part-*.md` nahradia novými. Časti nie sú v manifeste.
  - Súhrn exportu zobrazuje riadok s odhadom počtu tokenov: `tokens: ~... (estimate, about 4 characters per token)`.
- **Pomenované profily v CLI:**
  - Prepínače `--profile NAME` (načítanie s možnosťou prebitia) a `--save-profile NAME` (uloženie nastavení pred sťahovaním).
  - Príkazy `discoop profiles` (zoznam profilov s podporou `--format json`) a `discoop profiles delete NAME`.

#### O. Príručka pre AI agentov (`agent_guide.py`, P30)
- **Príkaz `discoop agent-guide`:**
  - Čistý nestylovaný text pre AI agentov s presným postupom `status` → `servers` → `channels` → `messages`.
  - Kompletná tabuľka kódov ukončenia generovaná priamo z `ExitCode`.
  - Dynamický abecedný zoznam všetkých registrovaných príkazov z aplikácie Typer s ich jednoriadkovými popismi.
  - Odkaz na príkaz v sekcii `NOTE FOR AI AGENTS` v `discoop --help`.

---

## 3. Posledné commity na vetve `main`

GitHub (`origin/main`) je na `94bd862`, novšie commity sú len lokálne (`git log --oneline origin/main..HEAD`). Push iba na pokyn používateľa. Kým nie je pushnuté, inštalácia z GitHubu dá starú verziu bez logovania, vlákien, odolného exportu a nového TUI.

| Commit | Správa | Význam |
|---|---|---|
| `a236a71` | `Add safe and fast download modes to discoop` | Zavedenie režimov `safe` (jitter, čítacie pauzy, delay medzi súbormi/kanálmi) a `fast`. |
| `f346b1d` | `Rename agent mode to plain mode with --plain flag` | Premenovanie agent mode na plain mode ([ADR 0012](decisions/0012-rename-agent-mode-to-plain.md), P15), zachovanie `--agent` aliasu. |
| `1d3b38b` | `Extract messages orchestration into service layer and add ui command` | Vytvorenie `src/discoop/service.py` a registrácia príkazu `discoop ui`. |
| `bf0d3f6` | `Add TUI state management, job planner and cancellation bridge` | Stavová logika TUI (`state.py`), plánovač úloh (`plan_jobs`) a `CancelToken` (`bridge.py`). |
| `21e9e5c` | `Add Textual TUI screens, modals, styles and Pilot tests` | Kompletná implementácia Textual TUI (`app.py`, `modals.py`, `discoop.tcss`) a pilotné testy. |
| `75f0310` | `Document discoop ui TUI and ADR 0013` | Dokumentácia TUI v požiadavkách (P16, P17), návrhu nástroja, denníku a zápis [ADR 0013](decisions/0013-tui-and-shared-service-layer.md). |
| `bde52c6` | `Add live QR code login inside TUI LoginModal` | Zapojenie živého generovania a skenovania QR kódu priamo v TUI dialógu prihlásenia. |
| `a7a5347` | `Record keyboard-first TUI decisions` | Požiadavky P18–P20 a ADR 0014. |
| `470c127` | `Fix TUI preview jobs and typed event bridge` | Oprava preview jobov, typované udalosti namiesto `*args`. |
| `4e13acb` | `Redesign TUI main screen` | Jeden strom, panel Export, `widgets.py`, téma `ansi-dark`. |
| `4dc5f8b` | `Restyle TUI dialogs for keyboard use` | Help, Settings, Login, Preview, TimeWindow v rovnakom vzhľade, `tests/test_tui_modals.py`. |
| `72eeef4` | `Document TUI redesign` | Dokumentácia prerobeného TUI. |
| `db16aef` | `Add export name row to the TUI` | Riadok `Name` v TUI (P21). |
| `94bd862` | `Split the TUI export path into Folder and Name` | Polia `Folder` a `Name` (P23, [ADR 0016](decisions/0016-default-export-folder-in-tui.md)). |
| `a162832` | `Add optional diagnostic logging with a leak test (ADR 0018)` | Kolo 1: logovanie `--debug`/`--log`. |
| `83bb692` | `Add a crash-safe ExportWriter with staging, resume and PARTIAL exit code` | Základ odolného exportu ([ADR 0017](decisions/0017-reliable-export-and-partial-success.md)). |
| `05ff654` | `Add resumable export, threads, --since-last, --max-tokens, profiles and agent-guide` | Kolo 2: obnova exportu, vlákna a fóra, `--since-last`, delenie na tokeny, profily v CLI, `agent-guide`. |
| `bd3cacc` | `Add saved TUI state, profiles, threads toggle, open-folder key and tree suffixes` | Kolo 2: vylepšenia TUI (P30). |

---

## 4. Čo nasleduje ďalej

Všetkých 6 krokov pôvodného implementačného plánu je implementovaných a otestovaných proti falošnému Discordu (870 testov prechádza). Časť kola 2 sa 2026-11-04 overila aj na reálnom účte (podrobne [analýza](analyses/real-account-check-2026-11-04.md)).

1. **Používateľské testy na reálnom účte, ktoré ešte chýbajú:**
   - **Odolný export a obnova:** skutočné Ctrl+C z konzoly počas čakania na sieť a počas sťahovania súboru. Prerušenie skriptom (kód 130, `.partial`, obnova) sa na reálnom účte overilo.
   - **Vlákna a fóra:** export fóra so stovkami príspevkov od začiatku do konca, súkromné vlákna (typ 12) a HTTP 202 (neobjavili sa), export s množstvom príloh (videná 1 príloha).
   - **Prírastkové sťahovanie `--since-last`:** vlákno, ktoré medzi dvoma behmi dostane novú odpoveď. Preskakovanie nezmenených kanálov a nadviazanie na predchádzajúci beh sa overilo.
   - **TUI v reálnom termináli:** Ctrl+C v TUI, výber fór a prepínač Threads, ukladanie (`P`) a načítanie (`p`) profilov, otvorenie priečinka exportu (`o`), prípony riadkov kanálov v strome a perzistentnosť `tui-state.json`. Používateľ potvrdil len beh `discoop ui` a QR prihlásenie.
2. **Git:**
   - Používateľ rozhodne o pushi commitov na GitHub (GitHub je zatiaľ na staršom commite).
3. **Rozhodnutie 9 (Výpočet prístupu ku kanálom):**
   - Ostáva **odložené s nízkou prioritou** (používateľ to nepovažuje za dôležité a Discord avizuje zmenu API, pri ktorej prestane nedostupné kanály vracať).
4. **Otvorené drobnosti:**
   - Linux a macOS sú neoverené (inštalácia z GitHubu, TUI, cesty cez `platformdirs`).
   - Príloha, ktorú API popíše inak než CDN (iná veľkosť a typ obsahu), sa pri opakovanom exporte sťahuje znova: opätovné použitie podľa ID a veľkosti ju nepozná ([analýza](analyses/real-account-check-2026-11-04.md), sekcia 4). Neopravené a neškodné. Možná oprava: uvoľniť kontrolu veľkosti alebo ukladať do manifestu skutočnú veľkosť.
   - Pri kóde 130 sa nevypíše riadok „Interrupted.“, hoci kód má `out.error(...)`. Vetva vyzerá nedosiahnuteľná.
   - `--progress-json`: nezistilo sa, či stránky správ vlákien emitujú udalosť `page`.
   - Uloženie v náhľade (`PreviewScreen`, kláves `s`) ide do `export-dir` alebo do `exports` v aktuálnom priečinku, nie do `Documents/discoop` ako export z formulára. Či to tak ostane, je otvorená otázka.
   - Repo nemá súbor `LICENSE`.
   - `profiles.load()` pri poškodenom súbore stále vydá Python `UserWarning` (v TUI by sa vypísal do terminálu). `split`, `syncstate` a `tui/tuistate` už hlásia len cez log a udalosť `warning`.
   - `_save_tui_state` nie je oneskorený (debounce): zapisuje `tui-state.json` pri každej zmene výberu alebo formulára.
