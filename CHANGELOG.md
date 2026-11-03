# Changelog

Všetky podstatné zmeny projektu. Formát podľa [Keep a Changelog](https://keepachangelog.com/sk/1.1.0/),
verzie podľa [SemVer](https://semver.org/).

## [Unreleased]

### Pridané
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
- Analýza presunutá z `docs/discord-analyza.md` do `docs/analyzy/discord-analyza.md`.
- Návrh prerobený pre prihlásenie a podporu všetkých OS:
  - login cez QR v termináli namiesto Playwright,
  - cesty k dátam cez `platformdirs`,
  - keyring s fallbackom pre Linux,
  - nové otvorené rozhodnutia 7 a 8.
- CLAUDE.md a ADR 0003: upozornenie na passkey dialóg pri `discord.com/login`.
