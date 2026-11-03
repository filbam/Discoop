# Changelog

Všetky podstatné zmeny projektu. Formát podľa [Keep a Changelog](https://keepachangelog.com/sk/1.1.0/),
verzie podľa [SemVer](https://semver.org/).

## [Unreleased]

### Pridané
- ADR 0010: prácu robia agenti, hlavný Claude ich riadi, kontroluje a commituje. Pravidlá v `CLAUDE.md`,
  sekcia „Práca cez agentov“.
- **Krok 1 implementácie:** `discoop servers`, `discoop channels`, `discoop config`.
  - Zoznamy sa ukladajú do lokálnej SQLite cache a obnovujú cez `--refresh`, pri prvom použití,
    alebo raz automaticky, keď sa meno nenájde.
  - **Vyhľadávanie podľa mena:** najprv ID, potom presné meno, potom meno bez rozdielu veľkosti písmen,
    diakritiky a emoji. Glob vzory sú pripravené pre `messages`. Nejednoznačné meno skončí kódom 3 so zoznamom kandidátov.
  - **`channels`:** strom podľa kategórií v poradí ako v Discorde, `--flat`, `--type`. V agent režime riadky
    oddelené tabulátorom.
  - **`config`:** kľúče `default-server` (uloží sa ID servera) a `delay`.
  - **Login a logout** mažú cache.
  - 71 testov.
- **Prvý prototyp:** Python balík `discoop` (uv, Typer, Rich).
  - `discoop login`: QR kód v termináli cez remote auth gateway, alebo `--token` zo skrytého promptu/stdin.
    Voliteľný anonymizovaný `--trace`. V agent režime login odmietne.
  - `discoop status` a `discoop logout`.
  - Režimy `--agent`/`--human`:
    - help s poznámkou pre AI agentov,
    - chyby `ERROR <CODE>` / `HINT` a stabilné exit kódy.
  - Token sa ukladá do keyringu OS, na Linuxe bez Secret Service do súboru `0600`.
  - REST klient s tempom, retry pri 429 a 5xx a 401 → kód 2.
  - Testy (42): kryptografia, celý QR tok proti falošnému gatewayu, trace bez tajomstiev, CLI, token store.
- `prototype/probe.py`: jednorazové overenie otvorených bodov API.
- ADR 0006–0009: Python, angličtina v nástroji, záložný `login --token`, login v agent režime.
- Analýza dát Discord web klienta: [docs/analyzy/discord-analyza.md](docs/analyzy/discord-analyza.md).
- Návrh nástroja `discoop`: [docs/navrh-nastroja.md](docs/navrh-nastroja.md).
- Štruktúra dokumentácie:
  - pravidlá v `CLAUDE.md`,
  - `CHANGELOG.md` a `README.md`,
  - požiadavky (`docs/poziadavky.md`) a denník (`docs/dennik.md`),
  - rozhodnutia ADR 0001–0004 v `docs/rozhodnutia/`.
- `.gitignore` (Python, lokálne nastavenia, exporty z Discordu).
- Požiadavky P13 (Windows, Linux, macOS) a P14 (QR login v termináli).
- Analýza prihlásenia (QR remote auth, email/heslo, MFA, passkey): [docs/analyzy/discord-login.md](docs/analyzy/discord-login.md).
- ADR 0005: QR login v termináli bez prehliadača.

### Zmenené
- `CLAUDE.md`: aktuálny stav projektu namiesto „návrh, zatiaľ bez kódu“.
- Analýzy doplnené o výsledky prototypu:
  - `discord-analyza.md`, sekcia 15,
  - `discord-login.md`, sekcia 7: reálny QR login bez captchy.
- Návrh: overené body [PROTOTYP] sú teraz [OVERENÉ].
- Analýza presunutá z `docs/discord-analyza.md` do `docs/analyzy/discord-analyza.md`.
- Návrh prerobený pre prihlásenie a podporu všetkých OS:
  - login cez QR v termináli namiesto Playwright,
  - cesty k dátam cez `platformdirs`,
  - keyring s fallbackom pre Linux,
  - nové otvorené rozhodnutia 7 a 8.
- CLAUDE.md a ADR 0003: upozornenie na passkey dialóg pri `discord.com/login`.
