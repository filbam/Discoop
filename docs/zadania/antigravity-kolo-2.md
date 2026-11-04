# Zadanie pre Antigravity: kolo 2 (dokončenie celého plánu)

Toto zadanie je samostatné: nemusíš poznať konverzáciu, z ktorej vzniklo. Je to pokračovanie po kole 1 (to je hotové a commitnuté).
Tentoraz dokončujete **celý zvyšok plánu naraz**. Claude potom skontroluje výsledok a opraví chyby, ktoré nájde.
Takže: radšej jednoduché a správne riešenie než ambiciózne a rozbité.

## 0. Pre hlavného agenta (koordinátora): ako postupovať

Si koordinátor. Prácu rozdeľ na balíky z tabuľky v sekcii 3 a každý balík daj **jednému** agentovi Gemini Flash.

1. **Najprv sám** (bez delegovania): prečítaj `CLAUDE.md` a túto sekciu 0 až 3, spusti `git status`, `git log --oneline -5` a plný `uv run pytest`.
   Zapíš do správy (sekcia 5) úvodný stav: počet prešlo/zlyhalo a zoznam padajúcich testov.
2. Fázy idú **po sebe**. V jednej fáze bežia súbežne iba balíky s disjunktnými súbormi (tabuľka v sekcii 3). Do ďalšej fázy neprejdi,
   kým plný `uv run pytest` nie je zelený. Výnimka: padá test v súbore, ktorý patrí balíku, čo v tej fáze ešte beží. Vtedy počkaj a spusti znova.
3. Po **každej fáze** doplň do správy blok pre danú fázu (sekcia 5). Správa sa píše **priebežne**, nie až na konci:
   ak vás niečo zastaví uprostred (limit použitia, chyba), Claude podľa správy zistí, kam ste sa dostali.
4. Agent smie meniť iba súbory zo svojho riadku v tabuľke. Ak potrebuje zmeniť iný súbor, napíše to do správy a nechá to tak.
5. Počas práce púšťa agent len svoje testové súbory. **Plný `uv run pytest` púšťaš ty** na konci fázy (trvá asi 2 minúty).
6. Nemáš sa koho pýtať. Pri nejasnosti vyber **najjednoduchšie riešenie, ktoré spĺňa text zadania**, a napíš ho do správy do bloku „Rozhodnutia“.
   Balík zastav len vtedy, ak by pokračovanie znamenalo porušiť tvrdé pravidlo zo sekcie 2.

## 1. Projekt v kocke a stav pri zadaní

`discoop` je Python 3.12 CLI nástroj (Typer, Rich, Textual, httpx), ktorý sťahuje správy a prílohy z Discord serverov, ktorých je používateľ
členom (hlavne VUT FIT), pre analýzu cez AI. Kód je v `src/discoop/`, testy v `tests/`, dokumenty v `docs/` (po slovensky).
Prečítaj `CLAUDE.md` (pravidlá práce a dokumentácie) a potom: `docs/navrh-nastroja.md`, `docs/poziadavky.md`, `docs/rozhodnutia/README.md`
a **`docs/analyzy/probe-vlakien-2026-11-04.md`** (overené fakty o Discord API pre vlákna; kde je `[PREDPOKLAD]`, nespoliehaj sa na to).

`uv` nemusí byť v PATH. V Git Bash: `export PATH="$PATH:/c/Users/Filip/AppData/Local/Microsoft/WinGet/Packages/astral-sh.uv_Microsoft.Winget.Source_8wekyb3d8bbwe"`.
Príkazy: `uv run pytest`, `uv run pytest tests/test_xyz.py`, `uv run discoop --help`.

**Hotové a commitnuté (základ je commit `05255cd`):**
- Logovanie `--debug`/`--log` (`logs.py`), `doctor`, `--format json` pre zoznamy, `--progress-json`, `progress.py`, `profiles.py`, `tokens.py`, návrhy pri preklepe v `resolve.py`.
- **Odolný export** (`src/discoop/export.py`, commit `83bb692`): `ExportWriter` zapisuje po kanáloch do `<cieľ>.partial` (pri zipe `<názov>.zip.partial`)
  a do cieľa publikuje až pri `close(complete=True)`, takže hotový export sa prerušeným behom nikdy nepokazí. Manifest má polia
  `request`, `targets`, `skipped_channels`, `interrupted`, `partial`, `complete`. `ExitCode.PARTIAL = 9` (`errors.py`).
  Rozhranie: `ExportWriter(target, as_zip, *, query, options, api, cdn, created, tz, now, sleep, progress)` s metódami
  `open(targets, resume)`, `add_channel(result)`, `add_skipped(channel, reason)`, `close(complete)`, `fetch_files(results)`; funkcie
  `find_unfinished(target, fingerprint=None)`, `request_fingerprint(targets, query, options, tz)`, `skip_reason(code)`, `is_partial(...)`, `staging_path(target)`.
  Pri obnove sa relatívne okno („posledný deň“) musí rátať od `Resume.created`. Podrobnosti sú v docstringoch v `export.py`.
- **Dáta pre vlákna** (commit `275374f`): `models.Thread`, `ForumTag`, `Channel.last_message_id`/`available_tags`, `threads.py`
  (`fetch_threads`, `fetch_all_threads`, `FetchedThreads`, `Stop`, `is_thread_container`, `in_window`), `Directory.threads(channel, window, refresh=...)`,
  cache schéma 2. Vždy `limit=25`; koniec zoznamu je prázdna alebo krátka strana (`has_more` a `total_results` sa neberú ako spoľahlivé).
- Overené (probe 2026-11-04): vlákna fungujú na fóre aj v textovom kanáli; správy vlákna sa čítajú ako správy kanála (`/channels/{ID vlákna}/messages`);
  pri fóre má prvá správa rovnaké ID ako vlákno; správy môžu mať typ 19 (odpoveď).

**Rozpracované a NECOMMITNUTÉ (dvaja predošlí agenti boli uprostred práce prerušení):**
`git status` ukáže zmenené `service.py`, `cli.py`, `tui/app.py`, `tui/bridge.py`, `export.py`, `attachments.py`, `models.py`, `render/text.py`,
`render/jsonout.py`, `tests/export_helpers.py`, `tests/test_export.py`, `tests/test_messages.py`, `tests/test_tui_app.py`, `tests/test_tui_modals.py`
a nové `tests/test_export_threads.py`, `tests/test_thread_render.py`. Patrí to balíkom **R2-A** a **R2-C** (fáza 1). Nadviaž na to, čo tam je
(prečítaj `git diff`), nič z toho nezahadzuj a nepíš odznova. Chýba hlavne: ADR 0017, doladenie testov a časť špecifikácie.
`tests/test_export.py` už má jednu zdôvodnenú úpravu (konštanta `SOON` kvôli reálnym hodinám) a `tests/test_messages.py` jednu (kód 0 → 9). Obe nechaj.
**Známy padajúci test na začiatku:** `tests/test_export.py::test_url_refused_by_the_cdn_is_refreshed` (čaká jednu dávku `[4]`, po zápise po kanáloch sú to dávky `[3, 1]`).
Je to zámerná zmena správania: prílohy sa sťahujú po kanáloch, takže sa URL obnovujú po kanáloch. Oprav ten test tak, aby overil to isté
(všetky 4 URL boli obnovené, po kanáloch) a zdôvodni to v správe.

## 2. Tvrdé pravidlá

1. **Žiadne zápisové príkazy gitu** (`add`, `commit`, `push`, `checkout`, `stash`, `reset`). Commituje až Claude po kontrole.
2. **Discord:** nevolaj Discord API ani CDN a nespúšťaj príkazy, ktoré by ich volali. Povolené je `uv run pytest` a `uv run discoop --help`.
   Všetky testy bežia **offline** (`httpx.MockTransport`, falošné objekty v `tests/fake_messages.py`, `tests/fake_threads.py`, `tests/export_helpers.py`).
   Nič z `Temp/`. Nikdy nečítaj ani nevypisuj token alebo cookies.
3. **Nemeň existujúce testy.** Do testových súborov smieš **pridávať** nové testy. Neodstraňuj a neoslabuj assert, žiadny `skip` ani `xfail`.
   Jediné povolené úpravy existujúcich assertov sú tie, čo sú výslovne uvedené v sekcii 1 alebo v balíku. Každú takú úpravu zdôvodni v správe.
4. **Len svoje súbory** (tabuľka v sekcii 3). Žiadne refaktory, premenovania ani „vylepšenia“ mimo zadania.
5. **Žiadne nové závislosti** v `pyproject.toml` ani `uv.lock`. **Nespúšťaj** `uvx`, `pip`, `npm` ani nič, čo niečo sťahuje. Lint nástroje nie sú nainštalované, nepoužívaj ich.
6. **Nové polia** v existujúcich dataclassoch (`MessagesRequest`, `MessagesOutcome`, `Channel`, `ChannelMessages`, ...) len na koniec a s predvolenou hodnotou
   (testy a TUI ich vytvárajú pozične). Nové metódy v `Events` len ako prázdne predvolené implementácie.
7. **Štýl:** ako susedný kód (type hints, krátke docstringy, málo komentárov). Texty pre používateľa, help, hlášky, názvy v kóde a testy **po anglicky**
   (ADR 0007). Dokumenty v `docs/` po slovensky, dátumy absolútne (`2026-11-04`).
8. **Konce riadkov:** `.py` súbory majú LF. Nespoliehaj sa na `grep -c` s `\r` (v tomto shelli klame); počítaj bajty cez Python. Markdown dokumenty v tomto
   checkoute majú väčšinou CRLF (git to normalizuje); pri úprave zachovaj, čo súbor má, a nemiešaj.
9. **Bez citlivých údajov:** v kóde, testoch aj dokumentoch žiadny skutočný token, cookies, mená alebo texty správ iných ľudí. Používaj falošné hodnoty.
10. Fakty o Discord API, ktoré v repe nie sú overené, píš ako `[PREDPOKLAD]`, overené ako `[OVERENÉ]` (pravidlo z CLAUDE.md).
11. Padá test v súbore, ktorý nevlastníš, kvôli rozpracovanej práci iného balíka? Počkaj minútu a spusti znova. Cudzí súbor neopravuj.
12. Nikdy nemaž priečinky `*.partial` ani nič mimo `tmp_path` v testoch. Testy nesmú siahnuť na skutočné Documents ani dáta (izoluje to `tests/conftest.py`).

## 3. Balíky, fázy a vlastníctvo súborov

| Balík | Fáza | Súbory, ktoré smie meniť |
|---|---|---|
| **R2-A** dokončiť odolný export v service, cli, TUI | 1 | `src/discoop/service.py`, `src/discoop/cli.py` (príkaz `messages` a to, čo potrebuje), `src/discoop/tui/bridge.py`, `src/discoop/tui/app.py`, `src/discoop/tui/modals.py`, `tests/test_messages.py`, `tests/test_service.py`, `tests/test_tui_app.py`, `tests/test_tui_modals.py`, nové testy, nový `docs/rozhodnutia/0017-spolahlivy-export-a-ciastocny-uspech.md`, jeden riadok v `docs/rozhodnutia/README.md` |
| **R2-C** dokončiť vlákna v renderi a exporte | 1 | `src/discoop/models.py` (iba `ChannelMessages` a metadáta vlákna), `src/discoop/render/text.py`, `src/discoop/render/jsonout.py`, `src/discoop/export.py`, `src/discoop/attachments.py`, `tests/export_helpers.py`, `tests/test_export.py`, `tests/test_export_writer.py`, `tests/test_attachments.py`, `tests/test_thread_render.py`, `tests/test_export_threads.py`, nové testy |
| **R3** vlákna v service a cli | 2 | `src/discoop/service.py`, `src/discoop/cli.py`, `tests/test_messages.py` (len pridať), `tests/test_service.py` (len pridať), nový `tests/test_threads_cli.py`, nový `docs/rozhodnutia/0019-vlakna.md`, jeden riadok v `docs/rozhodnutia/README.md` |
| **R4-D** `--since-last` a kontrola miesta na disku | 3 | `src/discoop/service.py`, `src/discoop/cli.py`, `src/discoop/snowflake.py`, nový `src/discoop/syncstate.py`, nové `tests/test_syncstate.py`, `tests/test_since_last.py`, nový `docs/rozhodnutia/0020-since-last.md`, jeden riadok v `docs/rozhodnutia/README.md` |
| **R4-G** TUI: stav, profily, prepínač vlákien, otvorenie priečinka, percentá | 3 | `src/discoop/tui/*`, `src/discoop/paths.py`, `src/discoop/config.py`, `tests/test_tui_*.py`, nové TUI testy |
| **R5-H** `--max-tokens`, odhad tokenov, `--profile` | 4 | `src/discoop/cli.py`, `src/discoop/service.py`, nový `src/discoop/split.py`, nové `tests/test_split.py`, `tests/test_profile_cli.py` |
| **R5-G** modul `agent-guide` (bez zápisu do `cli.py`) | 4 | nový `src/discoop/agent_guide.py`, nový `tests/test_agent_guide.py` |
| **R5-R** registrácia príkazu `agent-guide` a odkaz v helpe | 5 | `src/discoop/cli.py`, `tests/test_agent_guide.py` (len pridať) |
| **R6-DOC** dokumentácia | 6 | `CHANGELOG.md`, `docs/dennik.md`, `docs/navrh-nastroja.md`, `docs/poziadavky.md`, `README.md`, `docs/odovzdanie-stavu.md`, riadok stavu v `CLAUDE.md`, stavy ADR 0017/0019/0020 |

Poradie: fáza 1 (R2-A ‖ R2-C) → fáza 2 (R3) → fáza 3 (R4-D ‖ R4-G) → fáza 4 (R5-H ‖ R5-G) → fáza 5 (R5-R) → fáza 6 (R6-DOC) → záverečný plný `uv run pytest`.
`service.py` a `cli.py` sa nikdy nemenia dvoma agentmi naraz (preto sú R3, R5-R sériové a v paralelných fázach ich vlastní vždy len jeden balík).

## 4. Špecifikácie balíkov

### R2-A: odolný export v service, cli, TUI (fáza 1)
Cieľ: pád, Ctrl+C alebo zrušenie v 30. kanáli zo 40 nestratí 29 hotových a ten istý príkaz pokračuje sám; preskočený kanál alebo zlyhaná príloha
sa hlási poctivo kódom 9; používateľ vidí, čo sa stalo a čo má urobiť. Veľká časť je už v strome, skontroluj to voči bodom:
1. `service.run_messages`: pri exporte (`--out`/`--zip`) používa `ExportWriter` po kanáloch (nič nedržať celé v pamäti). Bez exportu (len konzola) ostáva pamäťová cesta, ale preskočený kanál sa tiež počíta ako čiastočný výsledok.
2. Automatická obnova: ak `find_unfinished` zodpovedá odtlačku požiadavky, hotové kanály sa preskočia (nesťahujú sa ani neťahajú ich prílohy) a udalosť
   `Events.resumed(done, total)` (predvolene prázdna) povie koľko. CLI vypíše poznámku („Continuing an unfinished export: 29 of 40 channels are already saved.“). Žiadny nový prepínač.
3. Prerušenie (`Cancelled`, `KeyboardInterrupt`, neočakávaná chyba): writer sa zavrie s `complete=False` a používateľ dostane poznámku „Saved N of M channels in <cesta>.partial. Run the same command again to continue.“
   Ctrl+C musí ďalej vyústiť do kódu 130 v `main()`; nesmie sa prehltnúť.
4. `MessagesOutcome` má nové polia s predvolenými hodnotami (preskočené kanály, počet obnovených, príznak `partial`). TUI súhrn ukáže preskočené kanály a radu na obnovu (F5 spustí ten istý export znova).
   Oprav docstring v `tui/bridge.py`, ak ešte odporuje novému správaniu.
5. `cli.messages` vráti `ExitCode.PARTIAL` (9) pri čiastočnom výsledku: kanál preskočený pre prístup alebo neexistenciu, alebo príloha v stave `failed`.
   Preskočenie pre veľkosť (`--max-file-size`) a `--no-files` sa **nepočíta**. Súhrn po obnove berie súčty z `exported.manifest["counts"]` a `exported.jobs`, nie z `Exported.results`.
   `--print` spolu s obnovou, kde už sú hotové kanály, sa odmietne (BAD_ARGS + rada) pred akýmkoľvek volaním API.
6. ADR 0017 „Spoľahlivý export a čiastočný úspech“ (po slovensky, formát ako ostatné ADR; stav **Prijaté** pre kód 9 a automatickú obnovu: používateľ plán schválil 2026-11-04;
   mechanizmus `<cieľ>.partial` opíš ako implementáciu). Riadok do indexu `docs/rozhodnutia/README.md` (skontroluj, či tam už nie je).
7. Testy: pád v 2. kanáli zo 3 a opätovný beh dokončí bez nového sťahovania kanála 1 (over počty requestov na fake), Ctrl+C/`Cancelled` nechá obnoviteľný `.partial`,
   kód 9 pri preskočenom kanáli (export aj konzola) a pri zlyhanej prílohe, ale 0 pri preskočení pre veľkosť a pri `--no-files`, poznámka o obnove, odmietnutie `--print`, súhrn v TUI,
   hotový export zostane nedotknutý po prerušenom obnovení cez CLI.

### R2-C: vlákna v renderi a exporte (fáza 1)
Cieľ: renderovanie a export vedia niesť **vlákna vnorené pod rodičovským kanálom** (zatiaľ sa nič nesťahuje; štruktúra sa testuje ručne zostavenými objektmi). Rozpracované v strome.
Návrh (v `models.ChannelMessages` už je):
- `ChannelMessages.threads: tuple[ChannelMessages, ...] = ()` a `thread: Thread | None = None` (metadáta vnoreného vlákna). Vnorená položka má `channel` = `Thread.as_channel(server_id)`, vlákno nemá vlastné vlákna.
  `file_count` rodiča zahŕňa súbory vlákien. Fórum samo nemá správy, všetko je vo `threads`.
- **Text** (`render/text.py`): sekcia kanála, potom podsekcia pre každé vlákno (názov, vytvorené, posledná aktivita, archivované/zamknuté, počet správ, názvy tagov fóra, správy vlákna rovnakým formátom).
  Hlavička kanála ukáže `threads: N`. Ak vlákna nie sú, výstup musí ostať **bajt po bajte rovnaký** ako dnes (všetky existujúce testy prejdú bez zmeny).
- **JSON riadky** (`render/jsonout.py`): správy vlákna majú pole identifikujúce vlákno (id, name, parent_id); existujúce `thread`/`has_thread` (správa, ktorá vlákno založila) nerozbi. `messages.jsonl` je plochý.
- **Export**: `channels/<rodič>.md` obsahuje vnorené sekcie; `messages.md`/`messages.jsonl` sú ploché; prílohy vlákien idú do `files/<priečinok rodiča>/` (mená sú unikátne vďaka ID prílohy);
  `plan()` a `with_paths()` prechádzajú vnorené výsledky; manifest `channels[]` má počet vlákien a `file_count` vrátane súborov vlákien (bez mien vlákien v manifeste).
  `ExportWriter.add_channel` berie rodiča s vláknami ako **jednu jednotku**; výstup po kanáloch musí byť bajt po bajte rovnaký ako jednorazový `export()` aj s vláknami; obnova po páde funguje.
- Testy: render s 0, 1 a viacerými vláknami (text aj jsonl), fórum bez vlastných správ, export do priečinka aj zipu s vláknami, rovnosť `ExportWriter` vs `export()` bajt po bajte, pád a obnova, `plan()` s deduplikáciou ID príloh medzi rodičom a vláknom.

### R3: vlákna v service a cli (fáza 2)
Cieľ: `messages` sťahuje aj vlákna (fóra a vlákna textových kanálov) a nový príkaz `discoop threads` ich vypíše.
1. `MessagesRequest.threads: bool = True` (nové pole na koniec); `to_argv` pridá `--no-threads`, keď je `False`. CLI: `messages --threads/--no-threads` (predvolene zapnuté).
   Help povie, že vlákna pridávajú veľa požiadaviek a veľké fórum (stovky príspevkov) je v režime `safe` pomalé.
2. `resolve_targets`: fórum (typ 15) a media kanál (typ 16) sú platné ciele (nemajú vlastné správy, obsah sú vlákna). Odstráň hlášku „threads come in a later version“.
   Kategórie ostávajú odmietnuté. Fórum s `--no-threads` sa odmietne (BAD_ARGS, rada: „A forum only has threads: drop --no-threads“).
3. V `run_messages` pre kanál typu text/oznámenia/fórum (`threads.is_thread_container`), keď `request.threads`: zavolaj `directory.threads(channel, window, refresh=True)`, zoraď vlákna od najstaršieho,
   pre každé stiahni správy rovnakou cestou ako pre kanál (`scrape.fetch_messages` s ID vlákna, rovnaká normalizácia) a pripoj ich ako `ChannelMessages(server, thread.as_channel(server.id), messages, truncated, thread=thread)`
   do `threads=` rodiča. Vlákna bez správ v okne vynechaj. `--max-messages` a `--last N` platia **zvlášť na kanál a zvlášť na každé vlákno** (zapíš do ADR 0019).
   Rodič s vláknami ide do `ExportWriter.add_channel` ako jedna jednotka.
4. Chyby: 403/404 pri jednom vlákne → vlákno sa preskočí s varovaním (`events.warning`) a výsledok je čiastočný (kód 9). Chyba pri zozname vlákien kanála → vlákna toho kanála sa preskočia s varovaním,
   správy samotného kanála sa uložia, výsledok je čiastočný. Neúplný zoznam (`FetchedThreads.problem`) → varovanie a čiastočný výsledok.
5. Priebeh: nová prázdna `Events.thread(index, total, channel, thread)` (alebo ekvivalent); CLI ukáže v spinneri/`--verbose` „thread i of n“ a `--progress-json` dostane udalosť `thread` (ID a počty, **bez názvov a textov**).
6. Príkaz `discoop threads -s SERVER -c CHANNEL [--from ...] [--to ...] [--refresh] [--format text|json]`: vypíše vlákna kanála (id, archived, messages, posledná aktivita v lokálnom čase, tagy, názov).
   Predvolené okno `--from 30d` (dlhšie cez `--from all`). Platí plain/human pravidlo ako pri `channels` (plain = TSV bez farieb; `--format json` = zoznam objektov). Kanál, ktorý nemôže mať vlákna, → BAD_ARGS.
7. ADR 0019 „Vlákna a príspevky na fórach“ (Prijaté: používateľ vlákna chcel a plán schválil; popíš okno, per-vlákno limity, čo je `[PREDPOKLAD]`).
8. Testy: fórum end-to-end (`tests/fake_threads.py` má `threads/search`; vlákno čítaj ako kanál), textový kanál s vláknami, `--no-threads`, fórum s `--no-threads` odmietnuté, 403 na vlákne → kód 9 a ostatné sa uložia,
   `to_argv`, príkaz `threads` (TSV aj JSON), pád a obnova s vláknami. Ak fake nevie niečo odpovedať, rozšír ho **len** novým pomocným súborom v `tests/` (nemeň `tests/fake_messages.py` ani `tests/fake_threads.py`).

### R4-D: `--since-last` a kontrola miesta na disku (fáza 3)
1. Nový `src/discoop/syncstate.py`: JSON súbor `sync-state.json` v `paths.data_dir()` (samostatne od cache, aby ho `clear_cache` nezmazalo), kľúčovaný ID účtu (jedno volanie `api.get_me()` pri použití `--since-last`).
   Tvar: `{"version": 1, "accounts": {"<user_id>": {"channels": {"<channel_id>": {"last_message_id": "...", "updated": "<ISO UTC>"}}}}}`. Atomický zápis, poškodený súbor = prázdny stav s varovaním (vzor: `profiles.py`).
2. `messages --since-last`: vylučuje sa s `--from`, `--to`, `--last` (BAD_ARGS). Pre kanál so stavom je okno „správy s ID **väčším** ako uložené ID“ (pozor: `Window.after_id` je **inkluzívne**, treba +1) až po teraz.
   Kanál bez stavu sa berie ako predvolené okno (posledných 24 hodín) a vypíše sa o tom poznámka. Vlákna: okno každého vlákna začína od uloženého ID vlákna, ak ho má, inak od času `updated` rodiča.
3. Stav sa posunie **až po úplne dokončenom behu** (export `close(complete=True)` alebo úspešný konzolový výstup) a len pre kanály, ktoré boli stiahnuté celé (nie `truncated`, nie preskočené, nie zlyhané). Uloží sa ID najnovšej videnej správy.
4. Preskakovanie neaktívnych kanálov: ak `Channel.last_message_id` nie je prázdne a je `<=` uloženému ID, kanál sa nesťahuje (0 požiadaviek, počíta sa ako „unchanged“). Zoznam kanálov sa pri `--since-last` obnoví (`refresh`).
   **Len pre kanály, ktoré nie sú kontajnery vlákien, alebo keď je `--no-threads`** (nové odpovede vo vláknách pravdepodobne nemenia `last_message_id` rodiča, `[PREDPOKLAD]`); fóra sa nepreskakujú nikdy.
5. Kontrola miesta: pred sťahovaním príloh kanála spočítaj veľkosť príloh, ktoré sa naozaj stiahnu (bez `present`, `--no-files`, väčších ako `--max-file-size`), a porovnaj s `shutil.disk_usage` rodiča cieľa.
   Ak nezostane aspoň 50 MB rezervy, `DiscoopError(ExitCode.ERROR, "Not enough free space: need about X MB, Y MB free.", rada)` **pred** sťahovaním tej dávky.
6. ADR 0020 „Prírastkové sťahovanie (`--since-last`)“ (Prijaté).
7. Testy: prvý beh bez stavu = predvolené okno, druhý beh berie len novšie správy (over parametre `after` na fake), hranica je exkluzívna (správa s uloženým ID sa nezduplikuje), vylučovanie s `--from/--to/--last`,
   stav sa neposunie po chybe ani po `truncated`, stav prežije `clear_cache`, poškodený súbor, preskočenie neaktívneho kanála (0 požiadaviek), fórum sa nepreskakuje, chyba o mieste na disku pred sťahovaním.

### R4-G: TUI (fáza 3)
Prečítaj `tui/state.py`, `tui/app.py` (klávesové skratky: `F5, F1, F2, F3, /, Esc, R, L, c, q, 1-3, Tab` sú obsadené; nové skratky vyber tak, aby sa neprekrývali a doplň ich do obrazovky Help) a existujúce testy (`tests/test_tui_*.py`, Pilot).
1. **Stav TUI** `tui-state.json` v `paths.config_dir()`, viazaný na ID účtu: uloží a pri štarte obnoví výber kanálov (po serveroch), globálne aj individuálne okná, režim safe/fast, Folder/Name, prepínač vlákien.
   Pri načítaní zahoď ID, ktoré už neexistujú. Žiadne tokeny. Atomický zápis, poškodený súbor = predvolené hodnoty. Testy cez `tmp_path`.
2. **Prepínač Threads** (zodpovedá `MessagesRequest.threads` z fázy 2) v nastaveniach exportu; `plan_jobs` ho prenesie do požiadavky a do kópie príkazu (`to_argv`).
3. **Profily** cez `profiles.py`: jedna skratka uloží aktuálny výber ako profil (modál s názvom), druhá profil načíta (modál so zoznamom). Formát profilu: `{"server", "channels", "from", "to", "last", "mode"}`.
4. **Otvorenie priečinka exportu** po dokončení (skratka na obrazovke súhrnu): `os.startfile` (Windows), `open` (macOS), `xdg-open` (Linux) cez **vymeniteľnú funkciu**, aby ju testy nahradili (v testoch sa nikdy nič nespúšťa).
5. **Percentá a odhad času** v priebehu cez `progress.py` (rovnako ako `_CliEvents.page` v `cli.py`); `bridge.py` posiela `fraction` a `eta_seconds` v udalosti `page`.
6. V strome pri kanáloch tlmený údaj o poslednej aktivite (z `Channel.last_message_id` cez snowflake čas, napr. „2d ago“) a pri exportovaných kanáloch dátum posledného exportu zo stavu. Ak by to zhoršilo čitateľnosť v 80x24, vynechaj a napíš do správy.
7. Testy cez Pilot: obnova stavu, zahodenie neplatných ID, prepínač vlákien v príkaze, profily (uložiť/načítať), otvorenie priečinka s podvrhnutou funkciou, percentá v priebehu. 80x24 aj širší terminál.

### R5-H: tokeny a profily v CLI (fáza 4)
1. Nový `src/discoop/split.py` (čisté funkcie): `split_markdown(text: str, max_tokens: int) -> list[str]` delí `messages.md` na časti s odhadom tokenov (`tokens.estimate_tokens`) najviac `max_tokens`.
   **Nikdy nerozdeľ správu na dve časti** (zisti z `render/text.py`, ako vyzerá hranica správy; viacriadkové správy aj správy s prázdnymi riadkami v texte to musia zvládnuť). Správa väčšia ako limit ide sama do jednej časti (varovanie).
   Každá časť začína jednoriadkovou hlavičkou `<!-- discoop part 2 of 5 -->`.
2. `messages --max-tokens N` (len s `--out`; so `--zip` BAD_ARGS pred akýmkoľvek volaním API): po dokončenom exporte zapíše `parts/part-001.md`, ... do priečinka exportu (staré časti najprv zmaže len v `parts/`). Časti nie sú v manifeste.
3. Odhad tokenov v súhrne exportu: riadok napr. `tokens: ~12.4k (estimate, about 4 characters per token)` z `messages.md` (`tokens.format_tokens`); pri `--format json` súhrnu pole `tokens_estimate`, ak taký výstup existuje.
4. `messages --profile NAME` načíta uložený profil (`server`, `channels`, `from`, `to`, `last`, `mode`) ako predvolené hodnoty, explicitné prepínače ich prebijú. Neznámy profil → BAD_ARGS s návrhom (`difflib`) a zoznamom profilov.
   `messages --save-profile NAME` uloží efektívne argumenty po overení, **pred** sťahovaním. Nový príkaz `discoop profiles` vypíše názvy (`--format json`) a `discoop profiles delete NAME` profil zmaže.
5. Testy: delenie (hranice správ, obrovská správa, viacriadkové správy, prázdny vstup), `--max-tokens` so `--zip` odmietnuté pred API, vznik `parts/` s očakávaným počtom častí, riadok s tokenmi v súhrne, `--profile` (načítanie, prebitie, neznámy), `--save-profile`, `profiles` a `profiles delete`.

### R5-G a R5-R: `agent-guide` (fáza 4 a 5)
- **R5-G**: modul `src/discoop/agent_guide.py` s `build_guide(app: typer.Typer) -> str` (čistá funkcia, `cli.py` neimportuje). Text pre AI agentov (anglicky, čistý text bez farieb): pevný postup `status` → `servers` → `channels` → `messages`
  (s `--plain`, `--format json`, `--progress-json`, `--out`), tabuľka kódov ukončenia **zložená z `ExitCode`** (aby nezastarala), pravidlá (prihlásenie robí používateľ príkazom `discoop login`; neposielaj token; veľké sťahovania v režime `safe`),
  a **zoznam všetkých príkazov z Typer aplikácie s jednoriadkovým popisom** (nový príkaz sa objaví sám). Testy: každý registrovaný príkaz je v texte, všetky kódy z `ExitCode` sú v texte, výstup neobsahuje ANSI.
- **R5-R** (až po R5-H): zaregistruj príkaz `discoop agent-guide` v `cli.py` (volá `agent_guide.build_guide(app)`), dopíš odkaz naň do `--help` (sekcia pre AI agentov) a test, že príkaz beží a vypíše text.

### R6-DOC: dokumentácia (fáza 6)
Všetko po slovensky, s `[OVERENÉ]`/`[PREDPOKLAD]`, bez tokenov a cudzích údajov. Čítaj skutočný kód a správy balíkov z `prototype/out/antigravity-kolo-2-sprava.md`, nepíš nič, čo sa nespravilo.
- `docs/poziadavky.md`: P26 odolný export a poctivý výsledok (kód 9, obnova), P27 vlákna a príspevky na fórach, P28 prírastkové sťahovanie `--since-last`, P29 delenie na tokeny/odhad/profily, P30 `agent-guide` a stav TUI. Všetko dátum 2026-11-04, zdroj: plán schválený používateľom.
- `CHANGELOG.md` (`[Unreleased]`), `docs/dennik.md` (nová sekcia pre toto kolo, blok „Ďalej“ zachovaj a aktualizuj, čo ostáva: otestovať na reálnom účte), `docs/navrh-nastroja.md` (kódy ukončenia vrátane 9, atómový zápis a `.partial`, vlákna, `--since-last`, tokeny, profily, `agent-guide`, `threads`),
  `README.md` (stručné príklady), `docs/odovzdanie-stavu.md`, riadok stavu v `CLAUDE.md` (počet testov z posledného plného behu), stavy ADR 0017/0019/0020 v indexe.
- Odkaz na `docs/analyzy/probe-vlakien-2026-11-04.md` tam, kde sa píše o vláknach.

## 5. Správa (povinná, píše sa priebežne)

Súbor `prototype/out/antigravity-kolo-2-sprava.md` (git ho ignoruje). Po každej fáze pridaj blok:
- **Fáza N, balíky:** zoznam zmenených/nových súborov pre každý balík.
- **Plný `uv run pytest`:** počet prešlo/zlyhalo, trvanie, zoznam padajúcich testov (ak nejaké ostali).
- **Zmenené existujúce asserty:** súbor, test, čo a prečo (inak „žiadne“).
- **Rozhodnutia:** kde si vybral jednoduchšie riešenie a prečo; čo je `[PREDPOKLAD]`.
- **Čo sa nepodarilo / čo ostalo otvorené:** nič nezamlčať.
Na konci pridaj záverečný súhrn: výsledok plného `uv run pytest`, čo nie je dokončené, na čo si dať pozor pri kontrole.

## 6. Čo bude Claude po vás kontrolovať

`git status` voči tabuľke vlastníctva, `git diff -- tests/` (žiadny odstránený ani oslabený assert, žiadny skip/xfail), plný `uv run pytest`, `pyproject.toml` bez novej závislosti,
predvolený výstup príkazov bajt po bajte rovnaký (kde to zadanie hovorí), reálne správanie pádu a obnovy exportu (odolnosť hotového exportu), logy bez úniku tokenu, dokumenty bez cudzích údajov a bez tvrdení, ktoré kód nespĺňa.
Potom commity po balíkoch. Čo nie je isté, označ v správe: dôveryhodná správa s chýbajúcou položkou je lepšia ako úplná správa s nepravdou.
