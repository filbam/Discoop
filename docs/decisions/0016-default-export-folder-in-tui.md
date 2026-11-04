# 0016: Predvolený priečinok exportov v TUI

- **Stav:** Prijaté
- **Dátum:** 2026-11-04
- **Rozhodol:** používateľ

## Kontext

Export z TUI šiel bez `export-dir` v configu do priečinka `exports` v aktuálnom priečinku. Kam export skončil, záviselo
od toho, kde používateľ spustil terminál, a nedalo sa to predvídať. Riadok formulára `Name` (P21) navyše spájal názov
a cestu v jednom poli. Používateľ chce (P23) samostatné polia `Folder` a `Name`, predvolený názov
`discord-export-<dátum a čas>` a predvolený priečinok, ktorý je na každom OS na rovnakom, predvídateľnom mieste.

## Možnosti

1. **Aktuálny priečinok** (doterajšie `exports`). Zamietnuté: výsledok závisí od miesta spustenia terminálu.
2. **Priečinok Stiahnuté (Downloads).** Zamietnuté: export nie je stiahnutý súbor a priečinok je plný iných vecí.
3. **Dátový priečinok nástroja** (`AppData\Local\discoop`, `~/.local/share/discoop`). Zamietnuté: je skrytý a používateľ
   by export ťažko našiel. Je tam aj `cache.db`.
4. **Domovský priečinok.** Zamietnuté: export by zasorili hlavný priečinok.
5. **`discoop` v Dokumentoch používateľa.** Zvolené.

## Rozhodnutie

- Predvolený priečinok exportov v TUI je `discoop` v Dokumentoch používateľa. Nájde ho `platformdirs.user_documents_dir()`
  (`paths.default_export_dir()`), rovnakým kódom na Windows, Linuxe aj macOS. Pri hľadaní sa nič nevytvára, priečinok
  vznikne až pri prvom exporte.
- Config `export-dir`, ak je nastavený, má prednosť. V Settings (`F2`, riadok `Export folder`) sa priečinok mení trvalo,
  v poli `Folder` len pre jeden export.
- Formulár má dve polia: `Folder` a `Name`.
  - Prázdny `Folder` je predvolený priečinok. Cesta s `~` alebo absolútna sa použije tak, ako je. Relatívna cesta leží
    vo vnútri predvoleného priečinka.
  - Prázdny `Name` je `discord-export-<dátum a čas>` (`discord-export-2026-1104-0108`). Zadaný `Name` je vždy len názov,
    nikdy cesta: prečistí sa cez `safe_name` (lomky a neplatné znaky sa nahradia `_`).
  - Kolízia v tej istej minúte (`-2`, `-3`) sa rieši len pri automatickom názve. Zadaný názov sa nemení, opakovaný export
    do neho pokračuje.
- Cesty v `--out` a `--zip` riadku TUI sú absolútne a s lomkami (`/`). Windows ich prijme a riadok s CLI príkazom sa
  nemusí citovať.
- CLI sa nemení. `discoop messages --out/--zip` ostáva relatívne k aktuálnemu priečinku alebo k `export-dir`.
  Nový predvolený priečinok platí len v TUI.

## Dôsledky

- `[OVERENÉ]` na Windows (platformdirs 4.14.3): `user_documents_dir()` vráti `C:\Users\Filip\Documents`, takže predvolený
  priečinok je `C:\Users\Filip\Documents\discoop`.
- `[PREDPOKLAD]`: Linux a macOS podľa dokumentácie `platformdirs` (Linux číta XDG `XDG_DOCUMENTS_DIR`, inak `~/Documents`,
  macOS `~/Documents`). Nevyskúšané. Na Linuxe bez priečinka Documents vráti `platformdirs` aj tak cestu `~/Documents`
  a export si ju vytvorí (`export.py` vytvára aj nadradené priečinky).
- `[PREDPOKLAD]`: Dokumenty presmerované do OneDrive. Windows vtedy hlási presmerovanú cestu a export pôjde do OneDrive,
  teda sa môže synchronizovať do cloudu. Kto to nechce, nastaví `Export folder` v Settings.
- Export obsahuje cudzie správy. Priečinok v Dokumentoch je mimo repa, takže ho git nezahrnie.
- Uloženie náhľadu (`Save` v Preview) ostáva pri doterajšom správaní (`export-dir`, inak `exports` v aktuálnom priečinku).
  Zmena je zatiaľ mimo tohto rozhodnutia.
- Testy podmieňajú `paths.documents_dir()` na priečinok v `tmp_path`, takže sa nikdy nedotknú skutočných Dokumentov.
