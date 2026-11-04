# Zadanie pre Antigravity: kolo 1

Stav repa pri zadaní: vetva `main`, základ je commit `94bd862` (nasledujúci commit pridal iba toto zadanie), čistý strom, `uv run pytest` = **426 prešlo** (trvá asi 2 minúty).
Toto zadanie je samostatné: nemusíš poznať konverzáciu, z ktorej vzniklo.

## 0. Pre hlavného agenta: ako to rozdeliť

Si koordinátor. Rozdeľ prácu na balíky z tabuľky v sekcii 3 a každý balík daj **jednému** agentovi Gemini Flash.
- **Fáza 1:** AG-A, AG-B a AG-C bežia súbežne, lebo ich súbory sú disjunktné.
- **Fáza 2:** po dokončení fázy 1 a zelenom `uv run pytest` ide najprv AG-E1, až potom AG-E2 (obaja menia `cli.py`, nikdy nie naraz).
- **Fáza 3:** AG-DOC až po fázach 1 a 2.
- Žiadny agent nesmie zmeniť súbor, ktorý nie je v jeho riadku tabuľky. Ak ho zmeniť potrebuje, nech to napíše do správy a nechá to tak.
- Plný `uv run pytest` púšťaš ty na konci každej fázy. Agenti počas práce púšťajú len svoje testové súbory.
- Na konci napíš správu podľa sekcie 5.

## 1. Projekt v kocke

`discoop` je Python 3.12 CLI nástroj (Typer, Rich, Textual, httpx), ktorý sťahuje správy a prílohy z Discord serverov, ktorých
je používateľ členom. Kód je v `src/discoop/`, testy v `tests/`, dokumenty v `docs/`. Nástroj iba číta a rieši sa tu jeho
robustnosť a ovládanie. Prečítaj si `CLAUDE.md` v koreni repa: sú tam pravidlá práce a dokumentácie, ktoré platia aj pre teba.

Dôležité súbory pre tvoje balíky:
- `src/discoop/api.py`: `DiscordAPI` (`request`, `get_me`, `_pace`, `between_channels`, `between_files`), 429 a opakovania.
- `src/discoop/scrape.py`: stránkovanie správ. `src/discoop/attachments.py`: sťahovanie príloh z CDN (`Downloader`, `_download`, `_fetch`).
- `src/discoop/cli.py`: Typer aplikácia. `_root` (globálne prepínače), `_MODE_FLAGS`, `_hoist_mode_flags`, `main()`, `_CliEvents`.
- `src/discoop/output.py`: `Output` (`note`, `warning`, `error`, `rows`, `fields`, `err_console`).
- `src/discoop/snowflake.py`: `Window` (`start: datetime | None`, `end: datetime`), `from_time`, `to_time`, `parse_window`.
- `src/discoop/resolve.py`: hľadanie mien (`resolve_one`, `resolve_many`, `NotFoundError`, `normalize`).
- `src/discoop/paths.py`: `data_dir()`, `config_dir()` (volať za behu, nie pri importe).
- `src/discoop/errors.py`: `ExitCode` (0 až 8), `DiscoopError`.
- `prototype/probe.py` a `prototype/README.md`: vzor pre probe skript.
- Vzory testov: `tests/test_api.py` (skriptované hodiny), `tests/test_messages.py` a `tests/test_export.py` (volanie `cli.main([...])`
  s `httpx.MockTransport`, falošný Discord v `tests/fake_messages.py`), `tests/conftest.py` (izolácia adresárov, **testy nikdy nesmú siahnuť na skutočné Documents ani dáta**).

`uv` nemusí byť v PATH. V Git Bash: `export PATH="$PATH:/c/Users/Filip/AppData/Local/Microsoft/WinGet/Packages/astral-sh.uv_Microsoft.Winget.Source_8wekyb3d8bbwe"`.
Príkazy: `uv run pytest`, `uv run pytest tests/test_xyz.py`.

## 2. Tvrdé pravidlá

1. **Žiadne commity, pushe ani zmeny gitu.** Commituje až Claude po kontrole.
2. **Discord:** nevolaj Discord API ani CDN a nespúšťaj príkazy, ktoré by ich volali (`discoop servers`, `channels`, `messages`, `login`, `status`,
   `doctor` proti skutočnej sieti a podobne). Povolené je `uv run pytest` a `uv run discoop --help`. Všetky testy bežia **offline** na `httpx.MockTransport`.
   V prehliadači na Discorde nerob nič. Nečítaj `Temp/`. Nikdy nečítaj ani nevypisuj token alebo cookies.
3. **Nemeň existujúce testy.** Smieš do testových súborov **iba pridávať** nové testy. Neodstraňuj ani neoslabuj žiadny assert,
   nepridávaj `skip` ani `xfail`. Ak existujúci test padne kvôli tvojej zmene, oprav svoj kód, nie test. Ak sa to nedá, zastav balík a napíš to do správy.
4. **Len svoje súbory.** Nemeň nič mimo súborov v riadku svojho balíka. Žiadne refaktory, premenovania ani „vylepšenia“ mimo zadania.
5. **Žiadne nové závislosti** v `pyproject.toml` ani `uv.lock`. Používaj stdlib a to, čo repo už má.
6. **Štýl:** rob to ako susedný kód (type hints, krátke docstringy, bez zbytočných komentárov). Texty pre používateľa, help, hlášky, názvy v kóde a testy **po anglicky**.
   Dokumenty v `docs/` po slovensky. Dátumy absolútne (`2026-11-04`).
7. **Bez citlivých údajov** v kóde, testoch aj dokumentoch: žiadny skutočný token, cookies, mená alebo texty správ iných ľudí. Používaj falošné hodnoty.
8. **Keď si nie si istý, zastav a napíš to do správy.** Nehádaj. Pri faktoch o Discord API, ktoré v repe nie sú overené, píš `[PREDPOKLAD]`.
9. Po každom balíku spusti jeho testy. Na konci fázy ide plný `uv run pytest` a musí prejsť **426 + tvoje nové testy**.

## 3. Balíky a vlastníctvo súborov

| Balík | Fáza | Súbory, ktoré smie meniť |
|---|---|---|
| AG-A logovanie jadro | 1 | nový `src/discoop/logs.py`, `src/discoop/api.py`, `src/discoop/scrape.py`, `src/discoop/attachments.py` (**len** riadky logovania v `_download` a `_fetch`), nový `tests/test_logs.py`, `tests/test_api.py` (len pridať), nový `docs/rozhodnutia/0018-logovanie.md`, jeden riadok v `docs/rozhodnutia/README.md` |
| AG-B pomocné moduly | 1 | nové `src/discoop/progress.py`, `profiles.py`, `tokens.py`, `src/discoop/resolve.py`, nové `tests/test_progress.py`, `tests/test_profiles.py`, `tests/test_tokens.py`, `tests/test_resolve.py` (len pridať) |
| AG-C probe skript | 1 | nový `prototype/probe_threads.py`, `prototype/README.md` (len pridať sekciu) |
| AG-E1 logovanie v CLI a upratanie | 2 | `src/discoop/cli.py`, nový `tests/test_cli_logging.py` |
| AG-E2 JSON zoznamy, doctor, priebeh | 2, po E1 | `src/discoop/cli.py`, `src/discoop/output.py`, `tests/test_servers_channels.py` (len pridať), nové `tests/test_doctor.py`, `tests/test_progress_json.py` |
| AG-DOC dokumentácia | 3 | `CHANGELOG.md`, `docs/dennik.md`, `docs/navrh-nastroja.md`, `docs/poziadavky.md`, `README.md`, `docs/odovzdanie-stavu.md`, riadok stavu v `CLAUDE.md` |

## 4. Zadanie jednotlivých balíkov

### AG-A Logovanie jadro

Cieľ: voliteľné logovanie diagnostiky. **Predvolene vypnuté**, nič sa nezapíše ani nevypíše, kým sa nezapne.

`src/discoop/logs.py` (nový):
- `setup_logging(debug: bool, log_file: Path | None) -> None` a `teardown_logging() -> None`.
- Handlery sa pripoja **iba** na logger `discoop` s `propagate = False` a úrovňou DEBUG. Nikdy `logging.basicConfig`, nikdy root logger.
  `debug=True` pridá `StreamHandler(sys.stderr)` (vytvorený pri volaní), `log_file` pridá `FileHandler` v režime append s kódovaním UTF-8.
  Loggery `httpx`, `httpcore` a `websockets` nastav na WARNING (inak by logovali celé URL a hlavičky).
- `teardown_logging()` odstráni a zavrie všetky handlery, ktoré pridal `setup_logging`, a vráti stav pred volaním. Je idempotentné.
- Hlavička logu (jeden blok na začiatku): verzia nástroja (`discoop.__version__`), OS, verzia Pythonu a riadok „IDs in this log identify private servers and channels. Do not publish it.“
- Formát riadku: ISO čas, úroveň, krátky názov loggera, potom `kľúč=hodnota` páry (napr. `api request method=GET path=/channels/123/messages attempt=1 status=200 ms=412 items=25`).

`src/discoop/api.py` (logger `discoop.api`, iba pridať logovanie, nemeniť správanie):
- Po každom pokuse requestu: `method`, `path` **bez query reťazca**, názvy parametrov (`params=before,limit`), hodnoty len pre `before`, `after`, `limit`, `archived`, `offset`, `with_counts`,
  `attempt`, `status`, trvanie v ms (`time.perf_counter()`, **nie** `self._clock`, lebo testy ho nahrádzajú), dĺžka odpovede.
- 429: `retry_after`, `global`, zdvojnásobený `delay`. Pauzy: sekundy a dôvod (`reading pause`, `rate limited (429)`, `between channels`, `between files`, obyčajný jitter).
  Tiché opakovania (sieťová chyba, 5xx) a ich backoff v sekundách. Chyba: JSON `code` (číslo) a top-level `message`; **nie** podobjekt `errors`.
- Transportné chyby loguj ako `type(e).__name__`, **nikdy** `str(e)`.

`src/discoop/scrape.py`: jeden riadok na stranu: ID kanála, počet správ, ID najstaršej a najnovšej správy, či je to posledná strana.

`src/discoop/attachments.py` (logger `discoop.attachments`, **len** `_download` a `_fetch`): ID prílohy, veľkosť, status, číslo pokusu, počet zapísaných bajtov, iba **host** z URL.
Nikdy meno súboru, cestu ani query (`ex`, `is`, `hm`).

**Nikdy nelogovať:** hlavičky (ani `client.headers`, ani `response.request.headers`), `kwargs` z `request()` (obsahujú ticket a podpísané URL), `response.text`, `response.json()`,
`repr` dataclassov (`FileJob`, `Attachment`, `Message`, `ChannelMessages`, `StoredToken`), texty správ, názvy kanálov a serverov (len ID), podpísané URL.

Testy `tests/test_logs.py` (povinné):
1. **Test úniku:** falošný token `FAKE.TOKEN.VALUE`, URL prílohy `https://cdn.example/f.png?ex=1&is=2&hm=SECRETSIG`, text správy `SECRET MESSAGE TEXT` a názov kanála `secret-channel-name`
   prejdú celým behom (`DiscordAPI` s `MockTransport`, stránkovanie, sťahovanie prílohy, 429, 5xx, chyba 403) s `setup_logging(True, tmp_path / "x.log")`.
   Prečítaj súbor logu a over, že **žiadny** z týchto reťazcov v ňom nie je. (Handlery pripájame na logger `discoop` s `propagate=False`, takže `caplog` ich nezachytí, čítaj súbor.)
2. Bez `setup_logging` sa nič nezapíše do stderr ani do súboru.
3. Po `teardown_logging()` na logger `discoop` nezostane žiadny handler. Dvojité volanie `setup_logging`/`teardown_logging` za sebou nezanechá duplicitné riadky.
4. Riadok z API má očakávané polia (`status`, `attempt`, `ms`) a cesta nemá `?`.
5. `tests/test_api.py`: pridaj aspoň jeden test, že pri zapnutom logovaní sa 429 aj sieťové opakovanie zapíšu a správanie `DiscordAPI` (počet pokusov, čakanie) sa nezmenilo.

`docs/rozhodnutia/0018-logovanie.md`: ADR podľa vzoru `0016-predvoleny-priecinok-exportov-v-tui.md` (stav **Prijaté**, dátum 2026-11-04, kontext, rozhodnutie, dôsledky).
Obsah: voliteľné, predvolene vypnuté, `--debug` na stderr a `--log FILE`, allowlist polí, čo sa nikdy neloguje, log obsahuje ID súkromných serverov, preto sa nemá zverejňovať.
Pridaj jeden riadok do indexu `docs/rozhodnutia/README.md` v rovnakom tvare ako ostatné.

### AG-B Pomocné moduly (čisté funkcie, žiadna sieť, žiadne zápisy mimo `tmp_path` v testoch)

`src/discoop/progress.py`:
- `fraction_done(start_id: int | None, end_id: int, oldest_id: int) -> float | None`: stránkovanie ide od najnovšej správy k najstaršej,
  takže `fraction = (end_id - oldest_id) / (end_id - start_id)`, orezané na 0 až 1. `None`, ak `start_id` je `None` alebo `end_id <= start_id`.
- `window_start_id(window: Window, channel_id: str | int, last: int | None = None) -> int | None`: `None`, ak `last` nie je `None`;
  inak `from_time(window.start)`, ak `window.start` nie je `None`; inak `int(channel_id)` (celá história začína vznikom kanála, ktorý je zakódovaný v jeho ID).
- `eta_seconds(elapsed: float, fraction: float | None) -> float | None`: `elapsed * (1 - fraction) / fraction`; `None`, ak `fraction` je `None`, menšie ako 0.02 alebo `elapsed <= 0`.
- `format_eta(seconds: float | None) -> str`: `""` pre `None`, inak krátky anglický tvar (`45 s`, `3 min`, `1 h 05 min`).
- Použi `from_time`/`to_time` zo `snowflake.py`, nevymýšľaj prevody odznova. Testy: hraničné hodnoty (`None`, 0, 1, mimo rozsahu, `last` zadané, `all`).

`src/discoop/profiles.py`:
- Súbor `profiles.json` v `paths.config_dir()` (volať `paths.config_dir()` v čase volania). Funkcie `load() -> dict[str, dict]`, `save(name: str, profile: dict) -> None`,
  `delete(name: str) -> bool`, `names() -> list[str]`.
- Profil má kľúče `server`, `channels` (zoznam), `from`, `to`, `last`, `mode` (všetko voliteľné). Nepovolené kľúče sa pri `save` zahodia.
- Názov profilu: po prečistení len písmená, číslice, `-`, `_`, `.`; žiadne lomky ani `..`; prázdny alebo neplatný názov je `ValueError`.
- Zápis atómový (zapísať do `.tmp` v tom istom priečinku, potom `os.replace`). Poškodený alebo chýbajúci súbor = prázdny slovník (pri poškodenom `warnings.warn`), nikdy výnimka.
- Testy v `tmp_path` s monkeypatchom `paths.config_dir` (pozri `tests/conftest.py`).

`src/discoop/tokens.py`: `estimate_tokens(text: str) -> int` (`ceil(len(text) / 4)`, v docstringu **napíš, že je to hrubý odhad**) a `format_tokens(n: int) -> str` (`850`, `12.4k`, `1.2M`).

`src/discoop/resolve.py`: v `resolve_one` aj `resolve_many` pri `NotFoundError` pridaj do `hint` vetu `Did you mean: A, B?` (najviac 3 mená, `difflib.get_close_matches` nad `normalize(item.name)`, `cutoff=0.6`,
zobraz pôvodné mená položiek). Ak nič nie je blízke, hlášky a `hint` ostanú **presne** ako doteraz. Existujúce testy musia prejsť bez zmeny. Nové testy: preklep nájde návrh, úplne iné slovo návrh nemá, glob bez zhody.

### AG-C Probe skript (agent ho len napíše, nespúšťa ho; spustí ho používateľ na svojom účte)

Nový `prototype/probe_threads.py` podľa vzoru `prototype/probe.py` (rovnaký prístup cez `DiscordAPI` a `TokenStore`, anonymizovaná správa do `prototype/out/`,
tempo 1 s medzi requestmi, `argparse` s `--guild`, `--forum`, `--delay`). **Iba GET.** Token sa nikde nečíta ani nevypisuje. Správa obsahuje **iba štruktúru**:
typy, počty, názvy polí, stavové kódy. Žiadne mená, texty správ, ID používateľov ani URL. Over `python -m py_compile prototype/probe_threads.py`, skript nespúšťaj.

Skript zistí a zapíše:
1. Veľkosť strany `GET /channels/{forum}/threads/search?archived=true&sort_by=last_message_time&sort_order=desc&limit=N&offset=0` pre `limit=25` a `limit=50`:
   koľko vlákien prišlo, hodnota `has_more`, `total_results`.
2. Dokiaľ ide `offset`: skúsiť 0, 25, 100, 500 (a ak `total_results` je väčšie, aj blízko konca). Zapísať stav a počet vrátených vlákien.
3. Odpoveď 202 („not indexed“): ak ju niektorý request vráti, zapísať stav a názvy kľúčov tela.
4. Súkromné vlákna: či medzi vláknami v textovom kanáli alebo fóre je typ 12 a ako sa označujú (`type`, `thread_metadata.locked`, `flags`). Len počty a názvy polí.
5. Rozdiel `total_results` a súčtu vlákien naprieč všetkými stranami.
6. `GET /guilds/{id}/channels`: koľko kanálov má neprázdne `last_message_id`. Pre 3 textové kanály porovnať `last_message_id` s ID najnovšej správy z `GET /channels/{id}/messages?limit=1`
   (zapísať iba `zhoduje sa` / `je staršie` / `chýba`, žiadne obsahy).

`prototype/README.md`: pridaj sekciu „4. Probe vlákien“ (príkaz `uv run python prototype/probe_threads.py`, čo robí, kde je výstup, že ho spúšťa používateľ).

### AG-E1 Logovanie v CLI a upratanie (`src/discoop/cli.py`)

- Globálne prepínače `--debug` (bool) a `--log FILE` (`Path`, nie adresár) v `_root`. Pridaj ich do `_hoist_mode_flags`, aby fungovali aj za podpríkazom
  (`discoop messages --debug ...`). `--debug` je ako ostatné booleovské príznaky v `_MODE_FLAGS`. `--log` má hodnotu: `--log FILE` aj `--log=FILE` sa musí presunúť **spolu s hodnotou**
  a hľadanie sa zastaví pri `--`.
- Záložné premenné prostredia `DISCOOP_DEBUG=1` a `DISCOOP_LOG=cesta`, spracované v `main()` (podobne ako `PLAIN_ENV` v `output.py`). Prepínače majú prednosť pred premennými.
- Po spracovaní príznakov zavolaj `logs.setup_logging(...)`, v `finally` `logs.teardown_logging()` (aj pri chybe a pri `KeyboardInterrupt`).
- Keď je zapnuté `--debug`, CLI **nezobrazí spinner** (správa sa ako v plain režime), aby stderr log nepoškodil Rich animáciu.
- `discoop ui`: `--debug` odmietni s kódom `ExitCode.BAD_ARGS` (8) a radou `Use --log FILE: the terminal UI owns the screen.`; `--log FILE` povoľ.
- Odstráň mŕtvy kód z `cli.py`: `_export_target`, `_export`, `_message_targets`, `_progress`, `_unreadable`. **Najprv `grep`-om over, že funkcia nemá žiadneho volajúceho** (v `src/` ani `tests/`);
  ak ho má, funkciu nechaj a napíš to do správy. Pozor: `service.py` má vlastnú živú `_unreadable`, tú nechaj.
- **Nemeň** `messages()`, jeho návratovú hodnotu, `_export_report` ani exit kódy (to robí Claude neskôr).
- Nové testy `tests/test_cli_logging.py` cez `cli.main([...])`: príznaky pred aj za podpríkazom, `--log=FILE` aj `--log FILE`, premenné prostredia a prednosť prepínača,
  `ui --debug` končí kódom 8, po behu nezostanú handlery na logeri `discoop`, bez prepínačov sa nevytvorí žiadny súbor logu.

### AG-E2 JSON zoznamy, doctor, priebeh (`cli.py`, `output.py`)

1. **`--format text|json`** pre `servers`, `channels`, `status` a `config list` (predvolene `text`, zlá hodnota = kód 8 s radou). Pridaj pomocnú metódu na `Output` (napr. `json(data)`),
   ktorá vypíše JSON rovnako v plain aj human režime (`json.dumps(..., ensure_ascii=False, indent=2)` na stdout).
   - `servers`: pole `{id, name, member_count}`. `channels`: **vždy plochý** zoznam `{id, name, type, type_name, category, position}` (rešpektuje `--type`, nie strom). `status`: objekt, bez `Path` objektov (`str`). `config list`: objekt kľúč → hodnota.
   - Poznámky o cache idú na stderr, stdout je čistý JSON. Predvolený TSV aj Rich výstup musia ostať **bajt po bajte rovnaké** (existujúce testy v `tests/test_servers_channels.py` musia prejsť bez zmeny).
2. **`discoop doctor`** (nový príkaz): kontrolné body a) prihlásenie cez existujúce `get_me`, b) sieť (rozlíšiť sieťovú chybu od neplatného tokenu), c) priečinok exportov (`export-dir` z configu, inak aktuálny):
   zapisovateľný cez `os.access` na najbližšieho existujúceho rodiča, **nič nevytváraj**, d) voľné miesto cez `shutil.disk_usage` (FAIL pod 100 MB, inak len informácia), e) vek cache, f) verzia nástroja.
   Výstup v plain režime: riadky `check<TAB>OK|FAIL<TAB>detail`; v human režime tabuľka. Exit kód: kód prvého zlyhaného bodu (`AUTH_REQUIRED` 2, `NETWORK` 7, inak `ERROR` 1), inak 0.
   **Žiadne zapisovacie volania na Discord** (len `GET /users/@me`). Pri neprihlásenom stave ostatné body ešte prebehnú.
3. **`--progress-json`** pri `messages`: pri tomto prepínači nie je spinner ani poznámky, na stderr ide jeden JSON objekt na riadok pre udalosti `channel_start`, `page`, `pause`, `channel_done`, `skipped`, `warning`
   (cez `_CliEvents`). Polia: `event`, indexy `index`/`total`, `channel_id`, počty, `fraction`, `eta_seconds`, `seconds` a `reason` pri pauze. **Žiadne texty správ ani mená.**
4. **Percentá a odhad času** v `_CliEvents.page`: v human spinneri aj v plain `--verbose` poznámkach doplň `~42%, about 3 min left`, keď sa dá spočítať. Použi `progress.py` z AG-B
   (`window_start_id`, `fraction_done`, `eta_seconds`, `format_eta`); na výpočet potrebuješ okno, ID kanála a čas štartu. Keď sa nedá spočítať, výstup ostane ako doteraz.
5. Nemeň `messages()` návratovú hodnotu ani exit kódy.

Testy: nové `tests/test_doctor.py` a `tests/test_progress_json.py` (obe cez `cli.main([...])` a `MockTransport`, podľa `tests/test_messages.py`), JSON zoznamy pridaj do `tests/test_servers_channels.py`.

### AG-DOC Dokumentácia (po fázach 1 a 2, píše sa po slovensky)

- `docs/poziadavky.md`: pridaj na koniec tabuľky
  `P24 | 2026-11-04 | Voliteľné logovanie diagnostiky: predvolene vypnuté, zapína sa parametrom (--debug, --log FILE), log neobsahuje token, podpísané URL ani texty správ.`
  a `P25 | 2026-11-04 | Nástroj je „inteligentný“: strojovo čitateľné zoznamy (--format json), diagnostika (discoop doctor), percentá a odhad času pri sťahovaní, návrhy pri preklepe v mene.`
- `CHANGELOG.md` (`[Unreleased]`): všetko z balíkov A, B, E1, E2. `docs/dennik.md`: nová sekcia pre tento blok (dátum 2026-11-04), **nemaž** existujúci blok „Ďalej“, len doplň.
- `docs/navrh-nastroja.md`: príkazy a prepínače (`doctor`, `--format json`, `--debug`, `--log`, `--progress-json`), sekcia o logovaní s tým, čo sa loguje a čo nikdy.
- `README.md`: krátka sekcia o logovaní a diagnostike. `docs/odovzdanie-stavu.md`: aktuálny stav. `CLAUDE.md`: iba riadok „Stav“.
- Skontroluj, že v dokumentoch nie je token, cookies ani cudzie mená či texty. Texty vychádzajú z toho, čo je v kóde, nič si nevymýšľaj.

## 5. Správa (povinná)

Zapíš ju do `prototype/out/antigravity-kolo-1-sprava.md` (priečinok git ignoruje, vytvor ho ak chýba). Pre každý balík:
- zoznam zmenených a nových súborov,
- výsledok `uv run pytest` (počet prešlo a zlyhalo, po fáze aj plný beh),
- čo sa nepodarilo alebo čo si vynechal a prečo,
- v čom si nebol istý alebo čo si musel predpokladať.

**Nič nezamlčuj.** Ak balík nie je hotový, napíš to. Claude správu neberie ako dôkaz, ale použije ju na kontrolu.

## 6. Čo sa stane potom

Claude (iný model) prevezme prácu: skontroluje, či sa zmenili len povolené súbory, prečíta diff, spustí plný `uv run pytest`, overí, že testy nie sú oslabené a že log nič nevyzradí,
a až potom commitne po balíkoch. Používateľ medzitým na svojom účte spustí `prototype/probe_threads.py`.
