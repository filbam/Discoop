# 0009: `login` v agent režime odmietne

- **Stav:** Prijaté
- **Dátum:** 2026-11-03
- **Rozhodol:** používateľ

## Kontext

Prihlásenie potrebuje človeka: naskenovanie QR mobilom, alebo vloženie tokenu. QR je de facto prihlasovací odkaz
a token je plný prístup k účtu. Keby `login` bežal v agent režime, dostali by sa do kontextu AI.

## Rozhodnutie

V agent režime (`--agent`, `DISCOOP_AGENT=1`, alebo keď stdout nie je terminál) `discoop login` skončí:
- exit kódom `2`,
- hláškou, že prihlásenie musí spraviť človek,
- radou `ask the user to run discoop login in their own terminal`.

Platí to aj pre `login --token`.

## Dôsledky

- **Človek môže vynútiť human režim** cez `--human` aj tam, kde stdout nie je terminál.
- **Ostatné príkazy v agent režime** pri chýbajúcom alebo neplatnom tokene tiež vracajú kód `2` s rovnakou radou.
