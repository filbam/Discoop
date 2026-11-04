# Denník

Chronologický záznam práce: čo sa urobilo, čo sa rozhodlo, incidenty a ďalšie kroky. Najnovšie hore.

---

## 2026-11-04

**Prerobené TUI (`discoop ui`, P18–P20, [ADR 0014](rozhodnutia/0014-tui-klavesnica-jeden-strom.md)):**
- **Nález používateľa** (2026-11-03, po prvom vyskúšaní TUI z ADR 0013): veľa tlačidiel bez textu, nefunkčné šípky,
  kanály nie sú zbalené, rozhranie zadrháva. Chcel klávesnicu ako primárne ovládanie, jednoduchšie a terminálovejšie UI.
- **Príčiny a opravy:**
  - Prázdne tlačidlá: `height: 1` pri predvolenom vysokom rámiku, rámik zabral celý riadok.
  - Zadrhávanie: pri každom výbere sa prestaval celý strom a kurzor skákal hore. Pohyb po serveroch volal sieť
    a súbežné workery obchádzali safe tempo.
  - Kategórie boli vždy rozbalené. Kategória bez vyberateľných kanálov ukazovala `[✓]` (`all([])`).
    Enter na kategórii ju rozbalil a zároveň vybral kanály.
  - Preview nefungoval: posielal `--print` a `--no-files` bez `--out`, čo služba odmietla.
  - Pauzy API sa nedali prerušiť a „Load all“ sa nedal zastaviť. `q` nezastavil beh. `space` a `e` pôsobili bez ohľadu na focus.
  - Pri neplatnom tokene sa ukazovalo zelené `@user`. Overenie tokenu blokovalo UI vlákno, logout šiel bez potvrdenia.
  - Nastavenia z configu (`mode`, `delay`, `export-dir`) sa v TUI neprejavili.
  - Správa „finished successfully“ aj pri preskočených kanáloch. Zhrnutie teraz uvádza kanály, správy, preskočené,
    orezané a stav príloh.
  - Log nebol vidno bez scrollovania. Enter v poli časového okna neuložil. Režim v Settings bol voľný text.
  - Preview a Help brali hranaté zátvorky ako markup. Uloženie preview prepísalo súbor. Help nesedel s klávesmi.
  - Variačné selektory v názvoch rozhadzovali zarovnanie (`display_name()`, len pri zobrazení).
  - `WindowSpec.slug()`/`label()` pri `from_=None` a zip cesta končiaca lomkou.
  - `filter_channels` zhodoval čísla ako podreťazec ID, teraz len celé ID.
  - `TuiEvents` hádal argumenty cez `*args`, v `state.py` a `bridge.py` boli mŕtve záložné kópie tried.
- **Nové rozloženie:**
  - Jeden strom (servery → kategórie → kanály, všetko predvolene zbalené), vpravo panel Export (zoznam výberu a formulár),
    dole log, riadok s CLI príkazom a Footer s klávesmi klikateľný myšou. V úzkom okne (< 95 stĺpcov) jeden panel naraz.
  - Téma `ansi-dark` (farby terminálu), Ctrl+P mení tému. CSS bez hex farieb, prvky vysoké 1 riadok (`compact=True`),
    bez emoji a veľkých tlačidiel.
  - Nový `widgets.py`: `ChoiceRow`, `InputRow`, `ActionRow`, `ConfirmRow`, `FormPanel`, `FilterInput`, `SelectedList`,
    `ChannelTree`, `TextView`, `display_name()`. Dialógy v `modals.py` (Help, Settings, Login, Preview, TimeWindow)
    majú rovnaký vzhľad. Nový `tests/test_tui_modals.py`.
- **Pravidlá správania:** pohyb kurzorom nevolá Discord, naraz beží jedna sieťová operácia, Esc ukončí pauzy okamžite
  (aj pri `L`), výber nemení kurzor ani rozbalenie.
- **Doplnky mimo pôvodnej tabuľky opráv:**
  - `X` na zozname výberu vymaže celý výber (hromadné zrušenie inak zmizlo spolu s tlačidlami, doplnené po kontrole).
  - Po zmene prihlásenia sa výber vyčistí. `e` a uloženie okna na nevybranom kanáli ho aj vyberie.
  - Esc v strome pri aktívnom filtri filter vymaže. Pri Target=preview sú skryté Attachments a Max MB.
  - Pri QR sa formulár nahradí kódom. Pod 27 riadkov zmizne rámik a Footer, aby sa QR zmestil do 80×24.
  - `TextView` kreslí len viditeľné riadky: zmena formátu pri 5000 správach trvá 0,1–0,4 s (`Static` 1,5–8,7 s).
    Cena: v Help a Preview nefunguje výber textu myšou.
  - Token z TUI sa ukladá až po overení na UI vlákne, Esc počas overovania nič neuloží.
- **Názov exportu v TUI (P21):** riadok `Path` nahradil `Name` s predvoleným názvom `YYYY-MMDD-HHMM` (dátum a čas).
  Prvá verzia spájala názov a cestu v jednom poli (holý názov do priečinka exportov, lomka alebo absolútna cesta ako
  cesta) a bez `export-dir` šla do `exports` v aktuálnom priečinku. To používateľ ešte v ten deň zmenil, pozri P23 nižšie.
  Kolízia automatického názvu dostane `-2`, `-3`. Podrobnosti v `navrh-nastroja.md` (4.8).
- **Ako prebiehala práca:** podľa [ADR 0010](rozhodnutia/0010-praca-cez-agentov.md) cez agentov, hlavný Claude výsledky
  kontroloval (diff, `uv run pytest`, SVG screenshoty vykreslené do PNG). Commity (všetky na `main`, nepushnuté):
  `a7a5347` (rozhodnutia P18–P20, ADR 0014), `470c127` (preview joby a typované udalosti), `4e13acb` (hlavná obrazovka),
  `4dc5f8b` (dialógy).
- **Overené `[OVERENÉ]`:** `uv run pytest`: 385 testov prechádza. Automatické testy cez Textual Pilot s falošnými dátami,
  vzhľad podľa screenshotov. QR v `ansi-dark` má len čierne a biele segmenty.
- **Neoverené `[PREDPOKLAD]`:** beh v skutočnom termináli (Windows Terminal), reálny účet, skenovanie QR telefónom.
- **Známe obmedzenia:**
  - Esc počas bežiacej HTTP požiadavky zaberie až po jej skončení (timeout 20 s).
  - Pauzy pri opakovaní sťahovania príloh v `attachments.py` sa nedajú prerušiť hneď.
  - V šírke 80 stĺpcov sa Footer nezmestí celý.
  - CLI príkaz v riadku má vždy `--delay` z configu.

**Inštalácia a verejné repo (P22, [ADR 0015](rozhodnutia/0015-verejne-repo-a-instalacia.md)):**
- Používateľ chce príkaz `discoop` bez `uv run`, rýchlu inštaláciu na Windows, Linuxe aj macOS z GitHubu. Repo
  `filbam/Discoop` je verejné. Zvolené `uv tool install git+https://github.com/filbam/Discoop`, návod pre každý OS je v README.
- História gitu skontrolovaná: 34 commitov, vzor Discord tokenu sa nenašiel, `Temp/` ani `prototype/out/` nikdy neboli v gite.
- **Overené `[OVERENÉ]`** (Windows, uv 0.13.7): inštalácia z lokálneho klonu cez `git+file://` v izolovaných priečinkoch
  trvá necelých 6 s, `discoop --version` a `--help` fungujú, `discoop.tcss` je nainštalované, `uv tool upgrade discoop`
  prevzal nový commit, anonymný `git ls-remote` na GitHub funguje.
- **Neoverené `[PREDPOKLAD]`:** samotná inštalácia z GitHubu, Linux, macOS, automatické stiahnutie Pythonu uv-čkom, beh TUI z takejto inštalácie.
- GitHub je na `75f0310`, lokálne je 9 nepushnutých commitov.

**Priečinok a názov exportu v TUI, dve polia (P23, [ADR 0016](rozhodnutia/0016-predvoleny-priecinok-exportov-v-tui.md)):**
- Používateľ rozhodol, že `Name` nemá byť cesta a export nemá ísť podľa miesta spustenia terminálu. Formulár má teraz
  samostatné riadky `Folder` a `Name`. Prázdny `Name` je `discord-export-<dátum a čas>`, prázdny `Folder` je `discoop`
  v Dokumentoch používateľa (`platformdirs.user_documents_dir()`, rovnako na Windows, Linuxe aj macOS). Config `export-dir`
  má prednosť, v Settings sa mení trvalo a v poli `Folder` pre jeden export. CLI sa nezmenilo.
- Relatívny `Folder` leží vo vnútri predvoleného priečinka, `~` a absolútna cesta sa použijú ako sú. Zadaný `Name` sa
  prečistí cez `safe_name` a nikdy nevyjde z priečinka. Cesty v `--out`/`--zip` sú absolútne a s lomkami, takže riadok
  s CLI príkazom nepotrebuje citovanie ani na Windows. `export.py` vytvára aj nadradené priečinky (priečinok aj zip),
  preto predvolený priečinok vznikne pri prvom exporte. Test to overuje.
- Placeholder `Folder` ukazuje skutočnú cestu. Dlhá cesta (napr. Dokumenty v OneDrive) sa skráti zľava (`TailInput`),
  aby ostal koniec.
- Testy podmieňajú `paths.documents_dir()` v `conftest.py` na priečinok v `tmp_path`, skutočné Dokumenty sa nemenia.
- **Opravené mimochodom:** `tests/test_attachments.py::test_retries_after_server_errors_and_network_errors` spadol
  2026-11-04 po 07:00 UTC (08:00 miestneho času). Tri `Downloader` v ňom bežali na skutočných hodinách a pevné odkazy z testu
  (`NOW + 20 h`) už vypršali. Doplnené `now=NOW.timestamp`. Nesúvisí s P23.
- **Overené `[OVERENÉ]`:** `uv run pytest`: 426 testov prechádza, bez varovaní (`-W error`). Skutočný priečinok
  `C:\Users\Filip\Documents\discoop` pred prácou ani po nej neexistuje.
- **Neoverené `[PREDPOKLAD]`:** Linux a macOS (cesta podľa dokumentácie `platformdirs`), Dokumenty presmerované do
  OneDrive, beh v skutočnom termináli.
- **Mimo rozsahu:** `Save` v Preview ukladá naďalej do `export-dir`, inak `exports` v aktuálnom priečinku.

**Antigravity kolo 1 — logovanie, diagnostika, JSON výstupy, pomocné moduly a probe vlákien (P24, P25, [ADR 0018](rozhodnutia/0018-logovanie.md)):**
- **Rozdelenie práce podľa ADR 0010:** práca prebiehala v troch fázach cez špecializované balíky agentov (AG-A, AG-B, AG-C, AG-E1, AG-E2, AG-DOC).
- **Balík A (`src/discoop/logs.py`, `api.py`, `scrape.py`, `attachments.py`, ADR 0018):**
  - Implementovaná infraštruktúra diagnostického logovania (`setup_logging`, `teardown_logging`, `DiscoopFormatter`).
  - Predvolene je logovanie úplne vypnuté (žiadny handler), po zapnutí sa pripája výhradne na logger `discoop` (`propagate=False`). Knižnice tretích strán (`httpx`, `httpcore`, `websockets`) sú stíšené na `WARNING`.
  - Prísny bezpečnostný filter: nikdy sa neloguje token `Authorization`, podpísané URL príloh (`?ex=&is=&hm=`), texty správ, telá odpovedí, mená používateľov ani názvy kanálov/serverov (iba číselné ID).
  - Logovanie volaní API (`api.py`), stránkovania (`scrape.py`) a sťahovania príloh (`attachments.py`).
- **Balík B (`src/discoop/progress.py`, `profiles.py`, `tokens.py`, `resolve.py`):**
  - `progress.py`: výpočet percent dokončenia (`fraction_done`), počiatočného snowflake kanála (`window_start_id`) a odhadu zostávajúceho času (`eta_seconds`, `format_eta`).
  - `profiles.py`: správa pomenovaných profilov nastavení v `<config_dir>/profiles.json` (`load`, `save`, `delete`, `names`) s atomickým zápisom cez `.tmp` a `os.replace`.
  - `tokens.py`: hrubý odhad počtu tokenov textu `estimate_tokens` (`len(text)/4`) a formátovanie `format_tokens`.
  - `resolve.py`: fuzzy hľadanie a automatické návrhy pri preklepe v mene servera alebo kanála (`Did you mean: ...?`) cez `difflib.get_close_matches(..., cutoff=0.6)`.
- **Balík C (`prototype/probe_threads.py`, `prototype/README.md`):**
  - Vytvorený nový read-only probe skript `prototype/probe_threads.py` na prieskum správania Discord API pri vláknach a fórach (`threads/search`, offsety, typy vlákien, neindexované odpovede 202 a konzistencia `last_message_id`). Skript nečíta ani nevypisuje token a je pripravený pre spustenie používateľom na jeho účte.
- **Balík E1 (`src/discoop/cli.py`):**
  - Globálne CLI prepínače `--debug` a `--log FILE` fungujú pred aj za podpríkazom vďaka hoisting mechanizmu (`_hoist_mode_flags`).
  - Podpora premenných prostredia `DISCOOP_DEBUG` a `DISCOOP_LOG` (prepínač v CLI má prednosť).
  - Vypnutie Rich spinnera pri `--debug`, aby nedochádzalo k poškodeniu výstupu v termináli.
  - Odmietnutie `discoop ui --debug` s návratovým kódom `8` (`BAD_ARGS`) a nápovedou použiť `--log FILE` (`discoop ui --log FILE` je povolené).
  - Vyčistený mŕtvy kód z `cli.py` (`_export_target`, `_export`, `_message_targets`, `_progress`, `_unreadable`, `_local_time`).
- **Balík E2 (`src/discoop/cli.py`, `src/discoop/output.py`):**
  - Prepínač `--format text|json` pre príkazy `servers`, `channels`, `status` a `config list` cez unifikovanú metódu `Output.json()`.
  - Nový príkaz `discoop doctor` na diagnostiku 6 bodov: prihlásenie (`login`), dostupnosť Discord API (`network`), zapisovateľnosť priečinka exportov (`export_dir`), voľné miesto na disku (`disk_space`), vek cache (`cache`) a verzia nástroja (`version`). Plain režim vypíše tabulátorom oddelené riadky, human režim tabuľku.
  - Prepínač `--progress-json` pre `discoop messages`: emituje štruktúrované JSONL udalosti na stderr (`channel_start`, `page`, `pause`, `channel_done`, `skipped`, `warning`).
  - Zobrazenie percent a odhadu času (ETA) v `messages` (v human spinneri aj vo verbose režime).
- **Overené `[OVERENÉ]`:** `uv run pytest`: všetkých 511 testov prechádza (85 nových testov v `test_logs.py`, `test_api.py`, `test_progress.py`, `test_profiles.py`, `test_tokens.py`, `test_resolve.py`, `test_cli_logging.py`, `test_servers_channels.py`, `test_doctor.py`, `test_progress_json.py`). Test úniku dát potvrdil, že do logu neprenikne token, podpisy CDN ani texty správ.
- **Neoverené `[PREDPOKLAD]`:** Spustenie `probe_threads.py` na skutočnom účte používateľa.

**Ďalej:**
1. Používateľ rozhodne o pushi. GitHub je na `75f0310`, takže inštalácia z GitHubu dá starú verziu bez nového TUI a diagnostiky.
2. Používateľ otestuje `discoop ui` na reálnom účte vrátane prihlásenia cez QR (vo vývoji `uv run discoop ui`, po pushi aj
   inštaláciu z GitHubu, vrátane Linuxu a macOSu, ak ich má).
3. Používateľ spustí `uv run python prototype/probe_threads.py` na svojom účte (server s fórami/vláknami) a skontroluje výstup v `prototype/out/`.
4. Krok 4: vlákna a fóra (`threads`, `--threads/--no-threads`) na základe výsledkov z probe skriptu.
5. Kroky 5–6: `agent-guide` a help texty, `--since-last` s deduplikáciou.
6. Rozhodnutie 9 (výpočet prístupu ku kanálom) ostáva odložené (nízka priorita).

---

## 2026-11-03

**Analýza Discord web klienta** → [analyzy/discord-analyza.md](analyzy/discord-analyza.md)
- Analýzu robil agent v Chrome používateľa (server VUT FIT) v troch behoch. Agent iba sledoval requesty,
  ktoré posiela samotný Discord klient. Token nečítal.
- Hlavné zistenia:
  - Správy, piny, vlákna aj search idú cez REST `/api/v9`. Zoznam kanálov a aktívne vlákna prichádzajú cez gateway.
  - Skryté kanály sú v dátach ako `___hidden___`.
  - Odkazy na prílohy platia 12 až 24 h a na stiahnutie netreba token.
  - REST odpovede neobsahujú rate-limit hlavičky.
- Otvorené body na overenie prototypom sú v sekcii 14 analýzy.

**Incident 1: omylom odoslaná správa.** Agent poslal z účtu používateľa správu `cdn.discordapp.com` do vlákna
vo fóre `#help-center`. Stalo sa to po zatvorení panelu vyhľadávania: ďalší klik trafil pole na písanie správy
a Enter určený pre vyhľadávanie správu odoslal.
- Používateľ správu zmazal.
- Vlákno ostalo sledované (Following).
- Opatrenie: agent na Discorde nesmie písať ani stláčať klávesy ([ADR 0003](rozhodnutia/0003-pravidla-pre-agentov-v-prehliadaci.md)).

**Incident 2: Chrome sa dvakrát zavrel.** V oboch prípadoch presne pri `tabs_close_mcp`. Karta agenta bola
jediná v okne, ktoré si agent vytvoril.
- Opatrenie: agent nikdy nezatvára karty ani okná (ADR 0003).

**Vedľajšie účinky analýzy:**
- Ako prečítané sa označilo niekoľko kanálov (zoznam je v analýze, sekcia „Vedľajšie účinky“).
- V histórii vyhľadávania Discordu pribudli 4 dotazy.

**Návrh nástroja** → [navrh-nastroja.md](navrh-nastroja.md)
- Obsahuje príkazy, výstupy (konzola, priečinok, zip), režimy human/agent, prílohy, vlákna, help a exit kódy.
- Otvorené rozhodnutia sú v sekcii 15. Názov `discoop` je prijatý (ADR 0004).

**Git**
- Repo založené lokálne a prepojené so súkromným `filbam/Discoop` ([ADR 0002](rozhodnutia/0002-sukromne-repo-a-identita.md)).
- Prvý commit `f1c6fac` (analýza + návrh) je pushnutý.
- Pri pushi bolo treba prihlásenie ako `filbam`, lebo predvolený účet `FilipBambura` súkromné repo nevidí.

**Záznamy:** zavedená štruktúra dokumentácie podľa požiadavky P12 ([ADR 0001](rozhodnutia/0001-zaznamenavanie-a-verzovanie.md)):
`CLAUDE.md`, `CHANGELOG.md`, `poziadavky.md`, `dennik.md`, `rozhodnutia/`, `analyzy/`.

**Nové požiadavky:** P13 (Windows, Linux, macOS) a P14 (QR login v termináli).

**Analýza prihlásenia** → [analyzy/discord-login.md](analyzy/discord-login.md)
- Robil ju agent vo vstavanom prehliadači aplikácie Claude, v neprihlásenom stave. Iba pozoroval prevádzku
  a čítal zdrojový kód stránky. Nič neodoslal a QR neskenoval.
- **Hlavné zistenie:** QR login (remote auth gateway `v=2`) sa dá spraviť bez prehliadača. Stačí WebSocket,
  RSA-OAEP-SHA256 a jeden REST POST.
- **Neoverené** (overí prototyp): kontrola `Origin`, captcha pri `remote-auth/login`, reálne rámce po naskenovaní.
- **Návrh upravený:** login cez QR, Playwright vypadol, cesty a keyring pre všetky OS
  ([ADR 0005](rozhodnutia/0005-qr-login-bez-prehliadaca.md)). Pribudli otvorené rozhodnutia 7 (záložný login)
  a 8 (`login` v agent režime).

**Incident 3: passkey dialóg.** Login stránka pri každom zobrazení formulára sama volá passkey autofill
(`navigator.credentials.get`). Vstavaný prehliadač na Windows z toho spravil systémové okno Windows Security
(„Insert your security key“). Používateľovi bolo odporučené okno zrušiť. Nič sa neprihlásilo.
- Opatrenie: pred otvorením `discord.com/login` vo vstavanom prehliadači používateľa upozorniť (CLAUDE.md, ADR 0003).
- Karta vstavaného prehliadača je presmerovaná z login stránky preč, aby negenerovala nové QR.

**Prvý prototyp.** Rozhodnutia z otázok zapísané ako ADR 0006–0009:
- Python, angličtina v nástroji, `login --token`, login v agent režime odmietne.
- Pravidlo commitov: commit sám po krokoch, push len na pokyn.
- uv nainštalované cez winget.

Kód (`src/discoop/`, 42 testov):
- `login` (QR + `--token` + `--trace`), `status`, `logout`, režimy human/agent, keyring, REST klient.
- `prototype/probe.py` na overenie REST endpointov.

**Overené na reálnom Discorde** (`login --handshake-only`): QR gateway prijal spojenie z terminálového klienta
(Python `websockets` s `Origin: https://discord.com`). Handshake prebehol až po `pending_remote_init`.
Do účtu sa nikto neprihlásil.

**Odchýlka od plánu:** neznáme `op` sa (ako vo webovom klientovi) ignorujú a iba zapíšu do trace. Neznámy close kód
skončí chybou s radou na `--token`.

**Prototyp spustený používateľom (2026-11-03 popoludní):**
- **`discoop login` cez QR funguje na reálnom účte.** Prvý pokus prešiel bez captchy.
  - Sken ~52 s, potvrdenie na telefóne ~16 s.
  - Token je uložený vo Windows Credential Manager.
  - QR sa v termináli (PowerShell) dal naskenovať.
  - `timeout_ms` bol ~5,7 min, platnosť QR teda kolíše viac, než sa myslelo.
- **`prototype/probe.py`** (13 API requestov, bez rate limitov a bez rate-limit hlavičiek), výsledky
  v [analýze, sekcia 15](analyzy/discord-analyza.md#15-overenie-prototypom-2026-11-03):
  - zoznam serverov aj kanálov ide cez REST, gateway nebude treba,
  - `limit` max 100,
  - `after` vracia najbližšie novšie správy zoradené od najnovšej,
  - aktívne vlákna cez `threads/search?archived=false`. `guilds/{id}/threads/active` je len pre botov,
  - CDN funguje bez tokenu,
  - `refresh-urls` funguje.
- **Návrh aktualizovaný:** body [PROTOTYP] sú teraz [OVERENÉ].
- **Stále otvorené:**
  - tvar `429`,
  - stránkovanie pinov,
  - nesúlad `total_results` 15 a 13 vrátených vlákien vo fóre,
  - `refresh-urls` pri exspirovanej URL.

**Krok 1 implementácie (servers, channels, config, cache, vyhľadávanie mien):**
- Hotové, 71 testov, commity `1d31ba4` a `ce466c7`.
- Proti reálnemu Discordu to zatiaľ spustil len používateľ, podľa CLAUDE.md volá API iba on.
- **Odchýlky od návrhu:**
  - `--include-hidden` vypadol, lebo sa zdalo, že REST skryté kanály nevracia. Neskorší test ukázal opak.
  - `default-server` sa ukladá ako ID.
  - `export-dir` sa odložil na export.
- **Cache** sa maže pri login aj logout, aby po prihlásení iným účtom neostali staré servery.

**Test používateľa** (log v `Temp/`, lokálny, gitom ignorovaný):
- **Funguje:** `servers`, `channels` (strom, `--flat`, `--type`), `config set default-server`, `--agent channels`.
  - 8 serverov, VUT FIT má 390 kanálov.
- **Zistenie:** REST `GET /guilds/{id}/channels` vracia **aj kanály, ktoré používateľ nevidí**, s reálnymi menami.
  - Napríklad celé kategórie `moderation`, `logging`, `fillers`.
  - Aj `#přípravné-kurzy` (`1549737445002584094`), ktorý klient zobrazil ako `___hidden___`.
  - Predchádzajúce tvrdenie „REST skryté kanály nevracia“ bolo chybné. Analýza (sekcie 13–15) aj návrh (4.3)
    sú opravené.
  - Riešenie je otvorené rozhodnutie 9: výpočet prístupu z práv a rolí.

**Zmena spôsobu práce** ([ADR 0010](rozhodnutia/0010-praca-cez-agentov.md)):
- Hlavná konverzácia pri implementácii minula kontext a musela sa zhrnúť.
- Používateľ určil: prácu robia agenti, hlavný Claude ich riadi, kontroluje výsledok (diff, `uv run pytest`)
  a commituje.
- Agenti necommitujú. Píšuci agenti nemenia rovnaké súbory a denník v bloku práce píše len jeden.
- `CLAUDE.md` má novú sekciu „Práca cez agentov“ a aktuálny stav projektu.

**Prieskum prístupu ku kanálom** → [analyzy/pristup-ku-kanalom.md](analyzy/pristup-ku-kanalom.md)
- Robil ho agent z dokumentácie a cudzieho kódu, bez volaní Discord API.
- REST vie vrátiť vypočítané práva cez `GET /guilds/{id}/channels?permissions=true` (Userdoccers).
- Záložná cesta: roly z `GET /users/@me/guilds/{id}/member` a lokálny výpočet z `permission_overwrites`.
  `/guilds/{id}/roles` netreba.
- Všetko je zatiaľ **[PREDPOKLAD]**. Overenie na účte používateľa je odložené spolu s rozhodnutím 9.
- `is_hidden` (`___hidden___`, flag `1<<17`) je obfuskácia v gatewayi. REST ju nikdy nepošle, takže v `channels`
  nič nefiltruje.
- Discord oznámil (changelog 2026-08-12), že REST prestane vracať nedostupné kanály: pre botov od 2026-11-16,
  pre používateľov neskôr.
- Opt-in kanály sú len zobrazovacia preferencia.
- **Rozhodnutie 9 (výpočet prístupu) je odložené s nízkou prioritou.** Používateľ povedal, že nie je dôležité,
  ak by s ním boli problémy. Rozpracovaný `prototype/access_probe.py`, `src/discoop/permissions.py`
  a `tests/test_permissions.py` sa zahodili.

**Rozhodnutia 4 až 6** ([ADR 0011](rozhodnutia/0011-predvolene-spravanie-messages.md)): používateľ potvrdil, že
vlákna sa predvolene sťahujú, predvolené okno je 24 h (celá história len cez `--from all`) a formát v agent
režime je `text`.

**Krok 2 implementácie (`messages` do konzoly):**
- Hotové, 161 testov (90 nových). Discord v testoch nahrádza `httpx.MockTransport` s anonymizovanými správami.
- Proti reálnemu Discordu to nebežalo. Lokálne bežali len `--help` a chybné vstupy, ktoré skončia pred volaním API.
- **Obsah:**
  - výber kanálov menom, ID alebo vzorom, aj viac `-c` naraz,
  - časové okno prepočítané na snowflake, stránkovanie po 100 cez `before`, `--last N`,
  - formáty `text` a `json`, v human režime farebný text,
  - prílohy len ako meno, veľkosť a URL.
- **Chyby podľa prieskumu prístupu:**
  - `403` s kódom 50001/50013 → kód 5,
  - iný `403` (anti-abuse, Cloudflare) → kód 1, lebo to nie je chýbajúci prístup,
  - `404` → kód 4,
  - prázdna prvá strana → poznámka o možnom chýbajúcom `READ_MESSAGE_HISTORY`.
- **Odchýlky od návrhu** (podrobne v návrhu, sekcia 4.5):
  - bez `--from` je okno 24 h pred `--to`,
  - `--last` sa dá kombinovať s `--from`/`--to`,
  - správy typu 20 a 23 (odpovede botov na príkazy) nie sú systémové,
  - zóna v hlavičke je posun `UTC+01:00`, nie meno,
  - `--all-channels` čaká na výpočet prístupu (rozhodnutie 9, odložené),
  - z návrhu pribudli aj `--max-messages` a `--include-system`.
- **Neoverené na účte:** `GET /channels/{id}` (ID kanála, ktoré nie je v cache), kódy chýb `403` a tvar forwardov.

**Test kroku 2 používateľom** (log v `Temp/`, lokálny, gitom ignorovaný):
- **Všetkých 6 príkazov fungovalo** (VUT FIT, kanál `1282100102743330887`):
  - human režim s predvoleným oknom 24 h (aj poznámka o 24 h na konci) a s `--last 30`,
  - `--agent --from 7d`,
  - `--agent --format json --from 2026-11-01 --to 2026-11-02`: `--to` s holým dátumom berie celý deň,
    okno končí 2026-11-03 00:00,
  - `--agent -v --from all --max-messages 300`: stránkovanie po 100 s priebehom na stderr, `WARNING`
    a `truncated: yes`,
  - kanál bez prístupu (`1549737445002584094`): `ERROR NO_ACCESS`, exit 5.
- **Overené na účte:**
  - Kanál bez `VIEW_CHANNEL` vráti `403` s kódom `50001` alebo `50013`. Ktorý z nich, výstup neukazuje.
    Zapísané v analýze prístupu (sekcie 1 a 7) a v návrhu (sekcia 9).
  - Forward sa zobrazil so značkou `(forwarded)`, textom aj prílohou. Značka vyžaduje `message_reference.type 1`
    aj neprázdne `message_snapshots`.
- **Opravy výstupu** (agent, 3 nové regresné testy, spolu 164):
  - **Duplicitná URL:** GIF poslaný ako holá URL mal pod textom `[image]` s tou istou URL. Embed teraz nezopakuje
    URL, ktorú správa už ukazuje: ostane len značka s titulkom (`[gif] "…"`), embed bez titulku sa vynechá.
    JSON má embedy celé, lebo je to úplný štruktúrovaný formát pre skripty a budúci export.
  - **Reakcie:** dva riadky `[reactions]` pri jednej správe sa v logu nenašli. Kód vypisuje jeden riadok na
    správu a Discord posiela jednu položku na emoji. Super reakcie (`count_details.burst`) sú teraz pri počte,
    `🔥5 (2 super)`, v JSON pole `reactions[].super`.
  - **Prázdne riadky:** dvojitý prázdny riadok v human režime sa v logu tiež nenašiel. Preventívne sa orežú
    prázdne riadky na začiatku a konci textu správy aj popisu rich embedu a `\r\n` sa zmení na `\n`. Text
    končiaci `\n` predtým dal v human režime dva prázdne riadky za správou.
  - Rich embed bez URL a titulku mal za `[embed]` medzeru navyše.
- **Na zváženie, nemenené:** reply na správu, ktorá má len prílohu, nemá citát (`reply-to meno` bez textu).
  Rich embed, ktorý má len obrázok (bez URL, titulku a popisu), sa vo výstupe nezobrazí vôbec.

**Krok 3 implementácie (prílohy, `--out`, `--zip`, manifest):**
- Hotové, 223 testov (59 nových v `test_attachments.py` a `test_export.py`).
- **Sťahovanie príloh:**
  - Samostatný klient bez tokenu: token sa posiela výhradne na Discord API, CDN requesty (`cdn.discordapp.com`, `media.discordapp.net`) idú bez hlavičky `Authorization`.
  - Obnova expirovaných podpisov cez `POST /attachments/refresh-urls` v dávkach po 50 pred stiahnutím (pri expirácii do 60 s) aj po odmietnutí CDN (403, 404, 410) v tempe nastavenom v konfigurácii (`delay`).
  - Bezpečné mená pre Windows, Linux a macOS: skrátenie na 100 znakov a 200 bajtov, zachovanie prípony, orezanie bodiek a medzier, prefix `_` pre rezervované mená Windows (`CON`, `NUL`, ...).
  - Priečinky kanálov skrátené na 50 znakov, pri kolízii názvov kanálov prípona `_<id>`.
  - Zlyhaná príloha (chyba siete, prekročenie redirectov, neplatná URL) nezastaví export celého kanála, zapíše sa do manifestu a súhrn chýb ide na stderr.
- **Export do priečinka a zipu:**
  - Štruktúra: `manifest.json`, `messages.md`, `messages.jsonl`, `channels/<meno>.md` a `files/<kanál>/<attachment_id>_<meno>`.
  - Atomický zápis: `.part` pre stiahnuté súbory a staging priečinok pre zip archív.
  - Ochrana existujúcich dát: odmietnutie neprázdneho priečinka alebo súboru, ktorý nie je exportom discoop.
  - Opakovaný beh opätovne použije už stiahnuté súbory so zhodným ID a veľkosťou (`present`), a to aj z predchádzajúceho `.zip` archívu.
  - Kompresia v zip: `ZIP_DEFLATED` pre texty a manifest, `ZIP_STORED` pre súbory v `files/`.
- **Prepínače a konfigurácia:**
  - `--print` popri exporte vypíše správy na stdout s relatívnymi cestami, súhrn ide na stderr.
  - `--no-files` preskočí sťahovanie súborov (`skipped`), `--max-file-size` preskočí súbory nad zadanú veľkosť v MB.
  - Formáty `md` a `jsonl` sú dostupné aj pre konzolu.
  - `discoop config set export-dir <cesta>` ukladá predvolený priečinok pre relatívne exportné cesty ako absolútnu cestu.
- **Potvrdené defaulty:** dávkovanie po 50 a predstih 60 s pri `refresh-urls`, sekvenčné sťahovanie CDN s timeoutom 60 s a 3 pokusmi (pauzy 1 s a 2 s), limity mien 100/50 znakov a 200 bajtov, overenie cieľa cez `manifest.json`, `ZIP_STORED` pre `files/`.

**Test kroku 3 používateľom** (log v `Temp/`, lokálny, gitom ignorovaný):
- **Všetky 4 príkazy fungovali** (VUT FIT, kanál `1282100102743330887`, 84 správ za 7 dní, 5 príloh):
  - `--out exports/fit-krok3`: úspešne stiahol 4 prílohy; jedna príloha (8,3 MB) zlyhala na HTTP 504 Gateway Timeout z CDN – export korektne pokračoval, nezhavaroval a zapísal chybu do manifestu aj do varovania na stderr.
  - Opakovaný beh do toho istého priečinka: okamžite rozpoznal 4 už stiahnuté súbory (`already present: 4`), znova ich nesťahoval a skúsil len chýbajúcu prílohu.
  - `--zip exports/fit-krok3.zip --print`: v agent režime vytvoril zip archív (všetkých 5 príloh stiahnutých vrátane tej, čo predtým dostala 504) a na stdout vypísal správy s lokálnymi cestami (`files/...`).
  - `--out exports/fit-nofiles --no-files`: export bez sťahovania príloh (`skipped: 5`), správy a manifest uložené.
- **Overené na účte:**
  - Odolnosť voči chybám CDN (504): export nezhavaroval a korektne pokračoval.
  - Detekcia a znovupoužitie existujúcich príloh funguje.
  - Zip archív aj export bez príloh (`--no-files`) fungujú.

**Režimy sťahovania safe a fast (bezpečné imitovanie prehliadača vs rýchle dávkové tempo):**
- Používateľ si všimol, že nástroj sťahuje príliš rýchlo a navrhol dva režimy sťahovania:
  1. `safe`: sťahuje pomaly a bezpečne, imituje scrollovanie v prehliadači, obsahuje náhodné intervaly a pauzy. Predvolený režim.
  2. `fast`: doterajší stav s dávkovým sťahovaním po 100 správach a pevnou pauzou `delay`.
- **Implementácia a overenie (231 testov, 8 nových/aktualizovaných):**
  - `config.py`: kľúč `mode` (`safe` / `fast`), funkcia `parse_mode`, konfigurácia `discoop config set mode safe|fast`.
  - `api.py`: v `safe` režime dávka 25 správ (`limit=25`), náhodný jitter 2.0 až 4.5 s pred každým volaním API, čítacie pauzy 8.0 až 15.0 s každých 5 až 8 requestov (s hlásením cez `on_pause`), pauza 3.0 až 6.0 s pri prepnutí kanála (`between_channels()`), pauza 1.0 až 3.0 s medzi sťahovaním súborov z CDN (`between_files()`), backoff na 429 s automatickým zdvojnásobením intervalu. V `fast` režime dávka 100 správ, pevný `delay` (predvolene 1.0 s), bez čítacích pauz a bez pauz medzi súbormi/kanálmi.
  - `scrape.py`: podpora voliteľného `page_size`, ktorý sa riadi podľa `api.page_size` (25 pre safe, 100 pre fast).
  - `attachments.py`: zapojenie `between_files()` do sťahovacej slučky príloh pre ďalšie súbory (2..N).
  - `cli.py`: nové prepínače `--safe`, `--fast` a `--delay` v `discoop messages`, vzájomná kontrola kolízie `--safe` a `--fast`, prenos režimu do `DiscordAPI` a prepojenie `on_pause` na Rich status / agent stderr notifikáciu.
  - `export.py` & `manifest.json`: manifest zaznamenáva použitý režim v objekte `query.mode` (`"safe"` / `"fast"`).

**Premenovanie „agent mode“ na „plain mode“ (`--plain`, P15, [ADR 0012](rozhodnutia/0012-premenovanie-agent-mode-na-plain.md)):**
- Používateľ navrhol premenovať režim, aby jasne vyjadroval absenciu vykresľovania farieb a grafických prvkov, pričom v helpe ostáva informácia, že je vhodný pre AI agentov a skripty.
- Schválené riešenie:
  - Primárny prepínač je `--plain` (Plain mode), premenná prostredia `DISCOOP_PLAIN=1`.
  - Pôvodný `--agent` a `DISCOOP_AGENT=1` zostávajú plne funkčné ako skrytý alias pre spätnú kompatibilitu.
  - V helpe a sekcii `NOTE FOR AI AGENTS` je vysvetlené, že plain mode odstraňuje farby a rich formátovanie, čím šetrí tokeny a je ľahko parsovateľný.
- Overené automatickými testami (232 testov).

**Interaktívne terminálové rozhranie TUI (`discoop ui`, P16–P17, [ADR 0013](rozhodnutia/0013-tui-a-spolocna-vrstva.md)):**
- Používateľ požadoval pre `--human` režim vizuálne prostredie v termináli v štýle Discordu/prieskumníka ovládané klávesnicou (šípky, `Space`, `Tab`, `Enter`, skratky), ktoré funguje ako nadstavba nad jadrom nástroja, dynamicky sa prispôsobuje zmene veľkosti okna a obsahuje vstavaný Help s návodom aj výpisom `discoop --help`.
- **Spoločná servisná vrstva (`src/discoop/service.py`):**
  - Orchestrácia `list_servers`, `list_channels`, `load_all`, `resolve_targets`, `validate_export_target` a `run_messages` vyčlenená z `cli.py` do `service.py`.
  - CLI aj TUI volajú rovnaké funkcie; každá úloha v TUI sa prekladá na `MessagesRequest` a v spodnej lište zobrazuje ekvivalentný príkaz `discoop messages ...`.
- **Architektúra a stav TUI (`src/discoop/tui/`):**
  - Postavené na knižnici `Textual` (lazy import len pri `discoop ui` / `--ui`, v `--plain` režime skončí kódom `8`).
  - `state.py`: správa výberu kanálov naprieč servermi (`SelectionState`), globálne a individuálne časové okná (`WindowSpec`), zoskupovanie kanálov s rovnakým oknom do úloh (`plan_jobs`, pri viacerých úlohách podpriečinky `01-7d`, `02-...`), vyhľadávanie kanálov bez diakritiky a emoji (`filter_channels`).
  - `bridge.py`: prerušiteľný spánok (`CancelToken`) pre okamžité zastavenie (`Esc`) aj počas čítacích pauz v `safe` režime a premostenie udalostí z background worker vlákna do UI.
  - `app.py`, `modals.py`, `discoop.tcss`: 3-stĺpcový Discord layout (*Servery* │ *Kanály* │ *Export a priebeh*) s automatickým prepnutím na záložky pri zúžení okna (< 95 stĺpcov), tlačidlá na obnovu serverov, kanálov vybraného servera a načítanie úplne všetkého v `safe` tempe, modálne okná pre vlastný čas kanála (`E`), vstavaný prehliadač správ, nastavenia, prihlásenie a obrazovku Help (`F1`/`?`) s generovaným výpisom `discoop --help`.

**Ďalej (nahradené zoznamom v sekcii 2026-11-04):**
1. Krok 4: vlákna a fóra (`threads`, `--threads/--no-threads`).
2. Rozhodnutie 9 (výpočet prístupu ku kanálom) ostáva odložené (nízka priorita).

Hotové z predchádzajúceho zoznamu: krok 3, jeho test používateľom, safe/fast režimy sťahovania a interaktívne rozhranie TUI (discoop ui).

---

## 2026-11-02

**Brainstorming.** Používateľ opísal požiadavky → [poziadavky.md](poziadavky.md) (P1–P11).
- Prezretý starý skript `discord-script.js` (FITSeeker):
  - spúšťal sa z konzoly prehliadača a volal `GET /api/v9/channels/{id}/messages`,
  - stránkoval cez `before` a časové okno počítal cez snowflake,
  - ošetroval `429` a medzi requestami robil pauzu 800 ms.
- Zistenia:
  - Discord API autentifikuje **tokenom** v hlavičke `Authorization`, nie cookies. `login` teda musí získať a uložiť token.
  - Názov `scoop` koliduje s Windows package managerom Scoop.
