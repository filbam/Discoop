# 0008: Záložný login `discoop login --token`

- **Stav:** Prijaté
- **Dátum:** 2026-11-03
- **Rozhodol:** používateľ

## Kontext

QR login (ADR 0005) závisí od neoficiálneho protokolu. Discord ho môže zmeniť alebo začať od klienta mimo
prehliadača pýtať captchu. Vtedy treba inú cestu prihlásenia.

## Možnosti

1. **Ručné vloženie tokenu:** funguje vždy a všade a je jednoduché.
2. **Prihlásenie cez prehliadač (Playwright):** je to ťažká závislosť na každom OS a na Windows ho sprevádza passkey dialóg.
3. **Email/heslo + TOTP cez API:** pravdepodobne často skončí captchou a nástroj by musel pracovať s heslom.

## Rozhodnutie

`discoop login --token`:
- **Odkiaľ sa token číta:**
  - v termináli zo skrytého promptu (`getpass`),
  - keď vstup nie je terminál, zo stdin.
- **Nikdy nie z argumentu príkazového riadku**, aby neostal v histórii shellu.
- **Overenie a uloženie:** token sa overí cez `GET /users/@me` a uloží rovnako ako po QR logine.

Možnosti 2 a 3 nie sú vo v1.

## Dôsledky

- Ak QR login zlyhá na captche alebo neznámej odpovedi, chybová hláška odporučí `--token`.
- Používateľ musí vedieť token získať (DevTools prehliadača). Postup sa doplní do helpu alebo README.
