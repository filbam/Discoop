# Discoop

CLI nástroj na sťahovanie správ a príloh z Discord serverov, ktorých je používateľ členom. Slúži na AI analýzu
študijných informácií. Súkromný projekt na osobné použitie.

**Stav:** rozpracované. Funguje `login` (QR kód v termináli alebo `--token`), `status`, `logout`,
`servers`, `channels`, `config` a `messages` (výpis správ do konzoly, sťahovanie príloh a export do priečinka
alebo zipu s manifestom). Vlákna a fóra ešte nie sú.

## Inštalácia a použitie

Potrebné sú Python 3.12+ a [uv](https://docs.astral.sh/uv/).

```
uv sync                      # závislosti do .venv
uv run discoop --help
uv run discoop login         # QR kód naskenuj v Discord appke: Settings → Scan QR Code
uv run discoop status
uv run discoop servers
uv run discoop channels -s "VUT FIT"
uv run discoop config set default-server "VUT FIT"
uv run discoop config set export-dir exports      # predvolený priečinok pre exporty
uv run pytest                # testy
```

Správy do konzoly (predvolene posledných 24 hodín, od najstaršej):

```
uv run discoop messages -s "VUT FIT" -c isc-public              # posledných 24 h
uv run discoop messages -s "VUT FIT" -c isc-public --from 7d
uv run discoop messages -c 1286436864789843999 --from 2026-10-01 --to 2026-10-31
uv run discoop messages -s "VUT FIT" -c "isc-*" --last 20       # 20 najnovších z každého kanála
uv run discoop messages -s "VUT FIT" -c isc-public --format json
uv run discoop messages -s "VUT FIT" -c isc-public --format md   # Markdown
uv run discoop --agent messages -s "VUT FIT" -c isc-public      # úsporný text pre AI
```

Export správ a stiahnutie príloh:

```
uv run discoop messages -s "VUT FIT" -c isc-public --from 30d --out exports/isc
uv run discoop messages -c 1286436864789843999 --from all --zip exports/isc.zip
uv run discoop messages -s "VUT FIT" -c isc-public --out exports/isc --print    # uloží a vypíše správy
uv run discoop messages -s "VUT FIT" -c isc-public --out exports/isc --no-files # len text a manifest
uv run discoop messages -s "VUT FIT" -c isc-public --out exports/isc --max-file-size 10 # vynechá súbory > 10 MB
```

- `--from`/`--to`: dátum (`2026-10-01`), dátum a čas (`2026-10-01T14:00`), relatívny čas (`48h`, `7d`, `2w`),
  `now`, pri `--from` aj `all` (celá história). Čas je lokálny, holý dátum v `--to` zahŕňa celý deň.
- `--last N`: N najnovších správ, bez `--from` z celej histórie.
- `--max-messages N` (predvolene 5000 na kanál) chráni pred obrovským výstupom.
- `--out DIR` / `--zip FILE`: vytvorí priečinok alebo zip s `manifest.json`, `messages.md`, `messages.jsonl`, `channels/*.md` a prílohami v `files/<kanál>/`. Opakovaný export do existujúceho cieľa použije už stiahnuté súbory. Bez `--out`/`--zip` sú prílohy len odkazy na Discord CDN, ktoré platia 12 až 24 h.

Globálna inštalácia príkazu `discoop`: `uv tool install .`

Overenie API prototypom popisuje [prototype/README.md](prototype/README.md).

## Dokumentácia

| Dokument | Obsah |
|---|---|
| [docs/poziadavky.md](docs/poziadavky.md) | čo má nástroj robiť |
| [docs/navrh-nastroja.md](docs/navrh-nastroja.md) | príkazy, výstupy, architektúra, postup implementácie |
| [docs/analyzy/](docs/analyzy/) | analýzy (napr. dáta Discord web klienta) |
| [docs/rozhodnutia/](docs/rozhodnutia/README.md) | rozhodnutia (ADR) |
| [docs/dennik.md](docs/dennik.md) | priebeh práce, incidenty, ďalšie kroky |
| [CHANGELOG.md](CHANGELOG.md) | zmeny projektu |
