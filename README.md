# Discoop

CLI nástroj na sťahovanie správ a príloh z Discord serverov, ktorých je používateľ členom. Slúži na AI analýzu
študijných informácií. Osobný projekt na študijné účely.

**Upozornenie:** scraping porušuje podmienky Discordu. Nástroj používaš na vlastné riziko, hrozí zablokovanie účtu.

**Stav:** rozpracované. Funguje `login` (QR kód v termináli alebo `--token`), `status`, `logout`,
`servers`, `channels`, `threads`, `config`, `messages` (výpis správ do konzoly, sťahovanie príloh a odolný export do priečinka
alebo zipu s manifestom a automatickou obnovou, režimy sťahovania `safe` a `fast`, prírastkové sťahovanie `--since-last`, delenie na tokeny `--max-tokens`), interaktívne terminálové rozhranie `discoop ui` (TUI), diagnostika `doctor`, diagnostické logovanie, správa profilov a referencia `discoop agent-guide`. Vlákna a fóra sú plne podporované.

## Inštalácia

Python netreba inštalovať zvlášť: [uv](https://docs.astral.sh/uv/) použije Python 3.12+ a ak chýba, sám si ho stiahne.

**1. Nainštaluj uv** (len raz), potom otvor nový terminál.

Windows:

```
winget install --id astral-sh.uv -e
```

Linux a macOS:

```
curl -LsSf https://astral.sh/uv/install.sh | sh
```

macOS cez Homebrew (alternatíva):

```
brew install uv
```

**2. Nainštaluj discoop** (rovnako na všetkých OS):

```
uv tool install git+https://github.com/filbam/Discoop
```

```
uv tool update-shell
```

Otvor nový terminál a over inštaláciu:

```
discoop --version
```

**Aktualizácia:**

```
uv tool upgrade discoop
```

**Odinštalovanie:** najprv `discoop logout` (zmaže uložený token), potom:

```
uv tool uninstall discoop
```

Reláciu v Discorde zruš v Settings → Devices.

Na Linuxe bez keyringu (Secret Service) sa token uloží do súboru s právami `0600`.

## Použitie

```
discoop --help
discoop login         # QR kód naskenuj v Discord appke: Settings → Scan QR Code
discoop status
discoop ui            # interaktívne terminálové rozhranie (TUI)
discoop servers
discoop channels -s "VUT FIT"
discoop threads -s "VUT FIT" -c help-center       # zoznam vlákien a fórum príspevkov
discoop agent-guide   # kompaktná textová referencia pre AI agentov
discoop profiles      # zoznam uložených profilov nastavení
discoop config set default-server "VUT FIT"
discoop config set export-dir ~/discord-exports   # priečinok exportov (TUI: predvolený, CLI: pre relatívne cesty)
discoop config set mode safe               # režim: safe (predvolený) alebo fast
```

Interaktívne terminálové rozhranie (TUI ovládané klávesnicou: jeden strom serverov, kategórií a kanálov, šípky na pohyb,
Space/Enter na výber, Tab na prepnutie panelu, `F5` spustí export, `P` uloží výber ako profil a `p` ho načíta, `o` otvorí priečinok posledného exportu, Help cez `F1`; farby podľa terminálu):

```
discoop ui
```

Export z TUI ide predvolene do priečinka `discoop` v Dokumentoch (Windows `C:\Users\<meno>\Documents\discoop`, Linux
a macOS `~/Documents/discoop`) pod názvom `discord-export-<dátum a čas>`. Pole `Folder` zmení priečinok pre jeden export,
pole `Name` názov (nikdy nie cestu). Predvolený priečinok trvalo zmeníš v Settings (`F2`, `Export folder`) alebo cez
`discoop config set export-dir <priečinok>`. Príkaz `discoop messages --out/--zip` sa tým nemení, jeho relatívne cesty
platia od aktuálneho priečinka (alebo od `export-dir`, ak je nastavený).

Správy do konzoly (predvolene posledných 24 hodín, od najstaršej):

```
discoop messages -s "VUT FIT" -c isc-public              # posledných 24 h (safe režim, vrátane vlákien)
discoop messages -s "VUT FIT" -c isc-public --no-threads  # vypnutie sťahovania vlákien
discoop messages -s "VUT FIT" -c isc-public --since-last  # len nové správy od posledného exportu
discoop messages -s "VUT FIT" -c isc-public --fast       # rýchly režim (100 správ/dávka)
discoop messages -s "VUT FIT" -c isc-public --from 7d
discoop messages -c 1286436864789843999 --from 2026-10-01 --to 2026-10-31
discoop messages -s "VUT FIT" -c "isc-*" --last 20       # 20 najnovších z každého kanála
discoop messages -s "VUT FIT" -c isc-public --format json
discoop messages -s "VUT FIT" -c isc-public --format md   # Markdown
discoop --plain messages -s "VUT FIT" -c isc-public      # úsporný čistý text (pre AI agentov a skripty)
```

Export správ a stiahnutie príloh:

```
discoop messages -s "VUT FIT" -c isc-public --from 30d --out exports/isc
discoop messages -c 1286436864789843999 --from all --zip exports/isc.zip
discoop messages -s "VUT FIT" -c isc-public --out exports/isc --print    # uloží a vypíše správy
discoop messages -s "VUT FIT" -c isc-public --out exports/isc --no-files # len text a manifest
discoop messages -s "VUT FIT" -c isc-public --out exports/isc --max-file-size 10 # vynechá súbory > 10 MB
discoop messages -s "VUT FIT" -c isc-public --out exports/isc --max-tokens 50000 # rozdelí do parts/part-NNN.md
discoop messages --save-profile fit-study -s "VUT FIT" -c "isc-*" --from 7d      # uloženie profilu
discoop messages --profile fit-study                                             # načítanie profilu
```

- `--safe` (predvolené): imituje ľudské scrollovanie – menšie dávky (25 správ), náhodné pauzy 2–4,5 s medzi požiadavkami, pauzy na čítanie 8–15 s každých 5–8 strán, rozostupy medzi prepnutím kanálov (3–6 s) a medzi sťahovaním súborov z CDN (1–3 s).
- `--fast`: rýchle dávkové sťahovanie (100 správ na požiadavku, pevný interval).
- `--plain`: čistý textový výstup bez farieb, Rich tabuliek a efektov (menej tokenov, strojovo čitateľný; ideálny pre AI agentov a skripty; `--agent` funguje ako spätný alias).
- `--delay SEC`: nastavenie intervalu požiadaviek (predvolene 1,0 s; v safe režime škáluje náhodné intervaly).
- `--from`/`--to`: dátum (`2026-10-01`), dátum a čas (`2026-10-01T14:00`), relatívny čas (`48h`, `7d`, `2w`),
  `now`, pri `--from` aj `all` (celá história). Čas je lokálny, holý dátum v `--to` zahŕňa celý deň.
- `--last N`: N najnovších správ, bez `--from` z celej histórie.
- `--max-messages N` (predvolene 5000 na kanál) chráni pred obrovským výstupom.
- `--out DIR` / `--zip FILE`: vytvorí priečinok alebo zip s `manifest.json`, `messages.md`, `messages.jsonl`, `channels/*.md` a prílohami v `files/<kanál>/`. Opakovaný export do existujúceho cieľa použije už stiahnuté súbory. Bez `--out`/`--zip` sú prílohy len odkazy na Discord CDN, ktoré platia 12 až 24 h.
- `--threads` / `--no-threads`: sťahovanie vlákien a príspevkov vo fórach (predvolene zapnuté). Fórum vyžaduje zapnuté vlákna.
- `--since-last`: prírastkové sťahovanie – nadviaže na posledný úspešný export každého kanála (stav uložený v `sync-state.json`). Vylučuje sa s `--from`, `--to` a `--last`. Kanál, v ktorom od posledného behu nič nepribudlo, sa preskočí bez požiadaviek (kanál s vláknami len svoje vlastné správy, jeho vlákna sa čítajú ďalej, fórum sa nepreskakuje).
- `--max-tokens N`: s `--out` aj `--zip` pridá do exportu súbory `parts/part-NNN.md`, v ktorých je `messages.md` rozdelený na časti po najviac N odhadovaných tokenoch (delí sa len medzi správami, správa ostane celá). Bez `--out`/`--zip` skončí chybou.
- `--profile NAME` / `--save-profile NAME`: načítanie a uloženie pomenovaného profilu parametrov.
- **Odolný export a návratový kód `9` (`PARTIAL`):**
  - Export sa zapisuje priebežne po kanáloch do dočasného umiestnenia `<cieľ>.partial`. Hotový export sa publikuje až po úspešnom dokončení celého behu, takže predchádzajúci hotový export sa nikdy nepoškodí.
  - Ak bol export prerušený (Ctrl+C, výpadok siete), opätovné spustenie rovnakého príkazu automaticky pokračuje od neuložených kanálov bez ich opätovného sťahovania.
  - Ak sú niektoré kanály nedostupné (HTTP 403 `NO_ACCESS` / 404 `NOT_FOUND`), vynechané vlákno alebo zlyhá stiahnutie niektorej prílohy, Discoop poctivo vráti kód ukončenia `9` (`ExitCode.PARTIAL`) a vypíše odporúčanie pre používateľa/agenta.

Overenie API prototypom popisuje [prototype/README.md](prototype/README.md).

## Logovanie a diagnostika

Nástroj obsahuje diagnostické príkazy na kontrolu stavu a voliteľné bezpečné logovanie:

```
discoop doctor                         # diagnostika prihlásenia, siete, export priečinka a disku
discoop servers --format json          # strojovo čitateľný JSON výstup (aj pre channels, status, config list)
discoop messages ... --progress-json   # JSONL udalosti o priebehu na stderr pre skripty
discoop --debug messages ...           # podrobný diagnostický log na stderr (vypne spinner)
discoop --log discoop.log messages ... # zápis diagnostického logu do súboru
```

- `--debug` a `--log FILE`: voliteľné logovanie (predvolene vypnuté). Možno aktivovať aj premennými `DISCOOP_DEBUG=1` a `DISCOOP_LOG=cesta`. Log **nikdy neobsahuje** autentifikačný token, podpisy CDN URL, texty správ ani mená používateľov (iba číselné ID).
- `discoop doctor`: overí 6 bodov: prihlásenie (`login`), dostupnosť Discord API (`network`), zapisovateľnosť priečinka exportov (`export_dir`), voľné miesto (`disk_space`, FAIL pod 100 MB), vek cache (`cache`) a verziu nástroja (`version`). Plain režim vypíše riadky oddelené tabulátorom, human režim tabuľku.
- `--format json`: strojový JSON výstup pre `servers`, `channels`, `status` a `config list`.
- `--progress-json`: štruktúrované JSONL správy o priebehu sťahovania na `stderr` s percentami a odhadom zostávajúceho času (ETA).

## Vývoj

Vývoj v repe ide cez `uv run` (príkaz `discoop` je potom `uv run discoop`):

```
git clone https://github.com/filbam/Discoop
cd Discoop
uv sync                      # závislosti do .venv
uv run discoop --help
uv run pytest                # testy
```

## Dokumentácia

| Dokument | Obsah |
|---|---|
| [docs/requirements.md](docs/requirements.md) | čo má nástroj robiť |
| [docs/design.md](docs/design.md) | príkazy, výstupy, architektúra, postup implementácie |
| [docs/analyses/](docs/analyses/) | analýzy (napr. dáta Discord web klienta) |
| [docs/decisions/](docs/decisions/README.md) | rozhodnutia (ADR) |
| [docs/journal.md](docs/journal.md) | priebeh práce, incidenty, ďalšie kroky |
| [CHANGELOG.md](CHANGELOG.md) | zmeny projektu |
