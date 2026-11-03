# 0001: Zaznamenávať všetko a verzovať v gite

- **Stav:** Prijaté
- **Dátum:** 2026-11-03
- **Rozhodol:** používateľ (požiadavka P12)

## Kontext

Projekt sa rozbieha cez brainstorming, analýzy a návrhy v konverzácii s AI. Bez zápisu by sa zistenia,
rozhodnutia a ich dôvody stratili. Ďalšie sedenie by ich musela AI zisťovať odznova.

## Rozhodnutie

Všetko podstatné sa zapisuje do repa a verzuje v gite:

| Čo | Kam |
|---|---|
| Požiadavky | `docs/poziadavky.md` |
| Návrh | `docs/navrh-nastroja.md` |
| Analýzy | `docs/analyzy/<tema>.md` |
| Rozhodnutia | `docs/rozhodnutia/NNNN-nazov.md` |
| Zmeny projektu | `CHANGELOG.md` |
| Priebeh práce a incidenty | `docs/dennik.md` |

Pravidlá pre AI sú v `CLAUDE.md`, ktorý sa načíta pri každom sedení v tomto repe.

## Dôsledky

- Záznam sa aktualizuje v tom istom kroku ako zmena.
- Dokumenty nesmú obsahovať token, cookies ani mená a texty správ iných ľudí.
- Analýza Discordu sa presunula do `docs/analyzy/`.
