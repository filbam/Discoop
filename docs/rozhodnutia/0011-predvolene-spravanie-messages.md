# 0011: Predvolené správanie `messages`: vlákna, časové okno, formát

- **Stav:** Prijaté
- **Dátum:** 2026-11-03
- **Rozhodol:** používateľ

## Kontext

Návrh nechal pri príkaze `messages` tri otvorené rozhodnutia (sekcia 15, body 4 až 6). Treba ich mať uzavreté
pred implementáciou `messages` (návrh, sekcia 14, krok 2). Predvolené hodnoty určujú, čo dostane agent alebo
človek, keď prepínače nezadá:
- či sa stiahnu aj vlákna,
- aké staré správy sa stiahnu,
- v akom tvare príde výstup v agent režime.

## Možnosti

1. **Vlákna:** predvolene sťahovať (`--no-threads` ich vypne), alebo predvolene nie (`--threads` ich zapne).
   Na serveri VUT FIT je veľa študijných informácií vo vláknach a vo fórach.
2. **Časové okno:** krátke predvolené okno (24 h), dlhšie (napr. 7 dní), alebo celá história. Celá história
   veľkého kanála znamená tisíce správ, veľa requestov a obrovský výstup pre agenta.
3. **Formát v agent režime:** `text` (úsporný na tokeny) alebo `json` (pre programy).

## Rozhodnutie

- **Vlákna sa predvolene sťahujú.** Vypnúť sa dajú cez `--no-threads`, okrem fóra, ktoré obsahuje len vlákna.
- **Predvolené časové okno je 24 h** (`--from 24h --to now`). Celá história sa stiahne len cez `--from all`.
- **Predvolený formát v agent režime je `text`.** JSON sa zapína cez `--format json`.

## Dôsledky

- Agent, ktorý zabudne zadať okno, dostane malý výstup. Celú históriu nestiahne omylom.
- Vlákna pribudnú v kroku 4 (návrh, sekcia 14). Kým nie sú implementované, `messages` vlákna nesťahuje
  a prepínač `--no-threads` ešte neexistuje.
- Programy, ktoré chcú štruktúrované dáta, musia zadať `--format json`.
