# 0002: Súkromné repo `filbam/Discoop` a git identita

- **Stav:** Prijaté
- **Dátum:** 2026-11-03
- **Rozhodol:** používateľ

## Kontext

Projekt potrebuje vzdialené repo. Dokumentácia obsahuje ID servera a kanálov VUT FIT a popis incidentov.
Samotný nástroj je scraper, ktorý porušuje podmienky Discordu.

## Rozhodnutie

- **Repo:** `https://github.com/filbam/Discoop`, **súkromné**, vetva `main`.
- **Autor commitov:** `filbam <f.bambura@gmail.com>`, nastavený len lokálne (`git config` v repe).
- **Prihlásenie na GitHub:** pre toto repo ako `filbam` (`credential.https://github.com.username = filbam`).

## Dôsledky

- Verejné zverejnenie by vyžadovalo nové rozhodnutie a kontrolu dokumentov, ktoré obsahujú ID a incidenty.
- Git Credential Manager má ako predvolený účet `FilipBambura`, ktorý súkromné repo nevidí (`Repository not found`).
  Preto je v repe nastavené prihlásenie ako `filbam`.
