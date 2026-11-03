# 0005: QR login v termináli bez prehliadača

- **Stav:** Prijaté
- **Dátum:** 2026-11-03
- **Rozhodol:** používateľ (požiadavky P13 a P14), technické riešenie podľa [analyzy/discord-login.md](../analyzy/discord-login.md)

## Kontext

Pôvodný návrh prihlasoval cez Chrome ovládaný Playwrightom. Používateľ chce prihlásenie naskenovaním QR kódu
v termináli (P14) a nástroj musí bežať na Windows, Linuxe aj macOS (P13). Prehliadač ako závislosť je na
každom OS iný a ťažký.

Analýza ukázala, že Discord QR login je obyčajný protokol:
- WebSocket `wss://remote-auth-gateway.discord.gg/?v=2` s JSON správami,
- RSA-OAEP-SHA256,
- jeden REST POST `/users/@me/remote-auth/login`.

Nepotrebuje nič, čo vie iba prehliadač.

## Možnosti

1. **QR login cez remote auth gateway priamo z nástroja.** Nepotrebuje prehliadač, 2FA rieši potvrdenie na mobile.
2. **Prihlásenie cez prehliadač (Playwright).** Zvládne captchu aj passkey, ale potrebuje Chrome alebo Chromium
   na každom OS. Na Windows navyše `discord.com/login` sám vyvolá systémový passkey dialóg.
3. **Email/heslo + TOTP cez API.** Nástroj by pracoval s heslom a pravdepodobne by často dostával captchu.

## Rozhodnutie

Hlavná cesta prihlásenia je **možnosť 1**:
- **Knižnice:** `websockets`, `cryptography`, `httpx`, `segno` (QR v termináli).
- **Pripojenie:** s hlavičkou `Origin: https://discord.com`.
- **Uloženie tokenu:** keyring.

Playwright z hlavnej cesty vypadáva. Záložné cesty sú otvorené rozhodnutie
([navrh-nastroja.md, sekcia 15](../navrh-nastroja.md#15-otvorené-rozhodnutia), body 7 a 8).

## Dôsledky

- **Prototyp musí overiť:**
  - či gateway vyžaduje `Origin`,
  - či `remote-auth/login` od ne-prehliadačového klienta nepýta captchu,
  - reálne rámce po naskenovaní.
- **Riziko zmeny protokolu:** Discord ho môže zmeniť, `v=2` je už druhá verzia. Nástroj musí pri neznámej správe
  alebo close kóde skončiť zrozumiteľnou chybou a ponúknuť záložnú cestu.
- **QR je de facto prihlasovací odkaz.** QR ani token sa nesmú dostať do logov.
- **Menej závislostí:** odpadá Playwright aj profil prehliadača.
