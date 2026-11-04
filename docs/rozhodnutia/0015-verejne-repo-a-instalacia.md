# 0015: Verejné repo a inštalácia cez `uv tool`

- **Stav:** Prijaté
- **Dátum:** 2026-11-04
- **Rozhodol:** používateľ

## Kontext

Používateľ chce (P22), aby nástroj fungoval priamo príkazom `discoop` bez `uv run`, aby sa inštaloval veľmi rýchlo na
Windows, Linuxe aj macOS a sťahoval sa z GitHubu. Povedal, že repo `github.com/filbam/Discoop` je už verejné
(ADR 0002 predpokladal súkromné).

## Možnosti

1. **`uv tool install` z GitHubu.** Zvolené.
2. **Samostatné binárky pre každý OS.** Zamietnuté: museli by sa zostavovať zvlášť pre každý OS a antivírusy na ne
   často falošne upozorňujú.
3. **Inštalačné skripty `install.sh` a `install.ps1`.** Zatiaľ nie, používateľ si ich nevyžiadal.

## Rozhodnutie

- Repo `filbam/Discoop` je **verejné**.
- Inštalácia pre používateľov: `uv tool install git+https://github.com/filbam/Discoop`, aktualizácia
  `uv tool upgrade discoop`. Postup pre každý OS je v [README.md](../../README.md).
- `uv run` ostáva pre vývoj v repe.
- Git identita `filbam` z [ADR 0002](0002-sukromne-repo-a-identita.md) ostáva.

## Dôsledky

- Žiadny token, cookies ani mená či texty správ iných ľudí nesmú ísť do gitu. `Temp/` a `prototype/out/` ostávajú
  gitom ignorované.
- Kontrola histórie 2026-11-04 `[OVERENÉ]`: 34 commitov, vzor Discord tokenu sa nenašiel, `Temp/` ani `prototype/out/`
  nikdy neboli v gite.
- Používatelia dostanú len to, čo je pushnuté. GitHub je 2026-11-04 na commite `75f0310`, lokálne je 9 nepushnutých
  commitov, takže kým sa nepushne, inštalácia dá starú verziu bez nového TUI.
- `[OVERENÉ]` (Windows, uv 0.13.7): `uv tool install` z lokálneho klonu cez `git+file://` v izolovaných priečinkoch
  trvá necelých 6 s s plnou cache, vytvorí `discoop.exe`, `discoop --version` a `--help` fungujú, `discoop.tcss` je
  nainštalované, `uv tool upgrade discoop` prevzal nový commit. Anonymný `git ls-remote` na GitHub funguje.
- `[PREDPOKLAD]`: samotná inštalácia z GitHubu, Linux, macOS, automatické stiahnutie Pythonu uv-čkom a beh TUI z takejto
  inštalácie.
