# Discoop

CLI nástroj na sťahovanie správ a príloh z Discord serverov, ktorých je používateľ členom. Výstup slúži na AI
analýzu študijných informácií (hlavne server VUT FIT). Je to osobný projekt na študijné účely. Používateľ vie,
že scraping porušuje podmienky Discordu.

Stav: návrh, zatiaľ bez kódu. Začni od [docs/poziadavky.md](docs/poziadavky.md) a
[docs/navrh-nastroja.md](docs/navrh-nastroja.md).

## Dokumentácia: zaznamenávaj všetko

Používateľ chce mať všetko zapísané v repe a verzované v gite ([ADR 0001](docs/rozhodnutia/0001-zaznamenavanie-a-verzovanie.md)).

| Čo | Kam |
|---|---|
| Požiadavky používateľa | [docs/poziadavky.md](docs/poziadavky.md) |
| Návrh nástroja | [docs/navrh-nastroja.md](docs/navrh-nastroja.md) |
| Analýzy, prieskumy, merania | `docs/analyzy/<tema>.md` |
| Rozhodnutia (ADR) | `docs/rozhodnutia/NNNN-nazov.md` + riadok v [indexe](docs/rozhodnutia/README.md) |
| Zmeny projektu | [CHANGELOG.md](CHANGELOG.md), sekcia `[Unreleased]` |
| Priebeh práce, incidenty, ďalšie kroky | [docs/dennik.md](docs/dennik.md) |

Pravidlá:
- **Kedy zapisovať:** záznam aktualizuj v tom istom kroku ako samotnú zmenu, nie dodatočne.
  - Nová požiadavka od používateľa → `poziadavky.md`.
  - Rozhodnutie → ADR.
  - Hotová zmena → `CHANGELOG.md`.
  - Na konci pracovného bloku → zápis do `dennik.md`.
- **Stav ADR:**
  - `Prijaté` = rozhodol alebo jasne súhlasil používateľ.
  - `Navrhnuté` = tvoj návrh bez jeho súhlasu.
  - Zmenené rozhodnutie nemaž. Nový ADR ho nahradí a starý dostane stav `Nahradené ADR NNNN`.
- **Analýzy:** pri každom fakte rozlišuj `[OVERENÉ]` a `[PREDPOKLAD]`.
- **Dátumy:** vždy absolútne (`2026-11-03`).
- **Jazyk:** dokumenty po slovensky, technické termíny, kód a commit správy po anglicky.
- **Bez citlivých údajov:** žiadny token, cookies ani mená či texty správ iných ľudí. Príklady anonymizuj.

## Git

- Repo: `github.com/filbam/Discoop` (súkromné), vetva `main` ([ADR 0002](docs/rozhodnutia/0002-sukromne-repo-a-identita.md)).
- **Autor:** commity píše `filbam <f.bambura@gmail.com>` (lokálny `git config`).
- **Prihlásenie na GitHub:** ako `filbam` (`credential.https://github.com.username`). Predvolený účet
  `FilipBambura` súkromné repo nevidí.
- **Commit správy:** po anglicky, s Co-Authored-By riadkom.
- **Commit a push:** iba na pokyn používateľa.

## Práca s Discordom používateľa

Platí po incidentoch z 2026-11-03 ([ADR 0003](docs/rozhodnutia/0003-pravidla-pre-agentov-v-prehliadaci.md)):
- **Žiadna klávesnica.** Agent v prehliadači používateľa na Discorde nesmie písať ani stláčať klávesy.
- **Klikanie len na navigáciu:** kanály v sidebare, tlačidlá v hlavičke kanála, zatvorenie panelov.
  Nikdy nie na zoznam správ, reakcie, composer, Follow ani Join.
- **Nikdy nezatváraj karty ani okná** (`tabs_close_mcp` dvakrát zhodil celý Chrome). Kartu nechaj otvorenú používateľovi.
- **Iba čítanie.** Token ani cookies nikdy nečítaj a nepoužívaj.
- **Overenia cez vlastné API volania** robí prototyp, ktorý spúšťa používateľ na svojom účte.
