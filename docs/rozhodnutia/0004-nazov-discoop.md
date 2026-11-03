# 0004: Názov nástroja `discoop`

- **Stav:** Prijaté
- **Dátum:** 2026-11-03
- **Rozhodol:** používateľ (repo pomenoval `Discoop`)

## Kontext

Pracovný názov projektu bol `Scoop`. Príkaz `scoop` však koliduje s rozšíreným Windows package managerom
Scoop (scoop.sh). Ak by bol nainštalovaný, príkazy by sa bili.

## Možnosti

- `scoop`: koliduje.
- `fitseeker`: názov starého skriptu, ale viaže sa na FIT, hoci nástroj má fungovať pre ľubovoľný server.
- `discoop` (Discord + scoop): bez kolízie, nadväzuje na pôvodný názov.

## Rozhodnutie

Nástroj, Python balík aj príkaz sa volajú **`discoop`**. GitHub repo je `filbam/Discoop`.
Lokálny priečinok projektu môže ostať `Scoop`.

## Dôsledky

- Premenná prostredia pre agent režim: `DISCOOP_AGENT`.
- Lokálne dáta: `%LOCALAPPDATA%\discoop\`.
- Kľúč v keyringu: `discoop`.
