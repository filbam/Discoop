# Discoop

CLI nástroj na sťahovanie správ a príloh z Discord serverov, ktorých je používateľ členom. Slúži na AI analýzu
študijných informácií. Súkromný projekt na osobné použitie.

**Stav:** rozpracované. Funguje `login` (QR kód v termináli alebo `--token`), `status`, `logout`,
`servers`, `channels` a `config`. Sťahovanie správ ešte nie je.

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
uv run pytest                # testy
```

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
