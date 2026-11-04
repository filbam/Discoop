# Discoop

CLI nástroj na sťahovanie správ a príloh z Discord serverov, ktorých je používateľ členom. Výstup slúži na AI
analýzu študijných informácií (hlavne server VUT FIT). Je to osobný projekt na študijné účely. Používateľ vie,
že scraping porušuje podmienky Discordu.

Stav (2026-11-04): implementované sú `login` (QR aj `--token`), `status`, `logout`, `servers`, `channels`
a `config` so SQLite cache, `messages` do konzoly aj s exportom príloh do priečinka a zipu (`--out`, `--zip`, manifest), režimy sťahovania `safe` (predvolený) a `fast` a interaktívne terminálové rozhranie TUI (`discoop ui`, ovládané klávesnicou, jeden strom, [ADR 0014](docs/rozhodnutia/0014-tui-klavesnica-jeden-strom.md)).
Aktuálne ďalšie kroky sú v bloku „Ďalej“ najnovšej sekcie [denníka](docs/dennik.md). Začni od [docs/poziadavky.md](docs/poziadavky.md) a
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

## Práca cez agentov

Hlavný Claude prácu nerobí sám, vysiela agentov a riadi ich ([ADR 0010](docs/rozhodnutia/0010-praca-cez-agentov.md)).
- **Hlavný Claude:**
  - hovorí s používateľom, delí prácu na kroky a píše agentom samostatné zadania
    (čo je hotové, ktoré súbory, čo má byť výsledkom, ako to overiť),
  - výsledok kontroluje sám (diff, `uv run pytest`), správa agenta nie je dôkaz,
  - sám nepíše kód ani dokumenty, chyby vracia agentovi. Výnimka: triviálna oprava pri kontrole.
- **Agenti:**
  - robia celý krok vrátane testov a záznamov podľa tohto súboru,
  - necommitujú a nepushujú,
  - na konci vrátia stručnú správu: čo zmenili, ako to overili, čo ostalo otvorené.
- **Súbežnosť:** čítajúci agenti môžu bežať naraz. Píšuci agenti nikdy nemenia rovnaké súbory, inak idú za sebou.
  Denník v jednom bloku práce píše len jeden agent.
- **Discord:** pravidlá pre Discord API (sekcia Vývoj) a sekcia Práca s Discordom platia pre agentov rovnako.
  Agent v prehliadači používateľa pracuje len podľa ADR 0003 a len keď o to používateľ požiada.

## Git

- Repo: `github.com/filbam/Discoop` (verejné), vetva `main` ([ADR 0002](docs/rozhodnutia/0002-sukromne-repo-a-identita.md), [ADR 0015](docs/rozhodnutia/0015-verejne-repo-a-instalacia.md)).
- **Autor:** commity píše `filbam <f.bambura@gmail.com>` (lokálny `git config`).
- **Prihlásenie na GitHub:** ako `filbam` (`credential.https://github.com.username`). Push ide cez tento účet,
  predvolený je `FilipBambura`.
- **Commit správy:** po anglicky, s Co-Authored-By riadkom.
- **Commit:** sám po každom hotovom a otestovanom kroku (dohodnuté 2026-11-03). Commituje hlavný Claude
  po kontrole práce agenta ([ADR 0010](docs/rozhodnutia/0010-praca-cez-agentov.md)).
- **Push:** iba na pokyn používateľa.

## Vývoj

- **Jazyk a nástroje:** Python 3.12+, balíky cez uv ([ADR 0006](docs/rozhodnutia/0006-python.md)), kód v `src/discoop/`, testy v `tests/`.
- **uv mimo PATH:** v shelli Claude môže chýbať. Vtedy
  `export PATH="$PATH:/c/Users/Filip/AppData/Local/Microsoft/WinGet/Packages/astral-sh.uv_Microsoft.Winget.Source_8wekyb3d8bbwe"`.
- **Príkazy:** `uv sync`, `uv run pytest`, `uv run discoop …`.
- **Help a hlášky nástroja** sú po anglicky ([ADR 0007](docs/rozhodnutia/0007-anglictina-v-nastroji.md)).
- **Discord API** volá len prototyp alebo nástroj, ktorý spúšťa používateľ. Výnimka: `login --handshake-only`
  (neprihlásené spojenie s QR gatewayom) na overenie spojenia.
- **Výstupy prototypu** (`prototype/out/`) sú anonymizované a gitom ignorované.

## Práca s Discordom používateľa

Platí po incidentoch z 2026-11-03 ([ADR 0003](docs/rozhodnutia/0003-pravidla-pre-agentov-v-prehliadaci.md)):
- **Žiadna klávesnica.** Agent v prehliadači používateľa na Discorde nesmie písať ani stláčať klávesy.
- **Klikanie len na navigáciu:** kanály v sidebare, tlačidlá v hlavičke kanála, zatvorenie panelov.
  Nikdy nie na zoznam správ, reakcie, composer, Follow ani Join.
- **Nikdy nezatváraj karty ani okná** (`tabs_close_mcp` dvakrát zhodil celý Chrome). Kartu nechaj otvorenú používateľovi.
- **Iba čítanie.** Token ani cookies nikdy nečítaj a nepoužívaj.
- **Overenia cez vlastné API volania** robí prototyp, ktorý spúšťa používateľ na svojom účte.
- **Passkey dialóg na login stránke:** `discord.com/login` vo vstavanom prehliadači na Windows sám vyvolá systémové
  okno Windows Security. Používateľa vopred upozorni, nech ho zruší. Po analýze kartu presmeruj z login stránky preč (napr. `https://example.com`), inak generuje nové QR.
