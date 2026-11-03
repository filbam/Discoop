# Rozhodnutia (ADR)

Každé rozhodnutie má vlastný súbor `NNNN-nazov.md`. Zmenené rozhodnutie sa nemaže. Nahradí ho nový ADR
a starý dostane stav `Nahradené ADR NNNN`.

**Stavy:**
- `Prijaté`: rozhodol alebo jasne súhlasil používateľ.
- `Navrhnuté`: čaká na súhlas.
- `Nahradené`: rozhodnutie zmenil novší ADR.

Rozhodnutia, ktoré ešte nie sú vyriešené, sú v [navrh-nastroja.md, sekcia 15](../navrh-nastroja.md#15-otvorené-rozhodnutia).

| # | Rozhodnutie | Stav | Dátum |
|---|---|---|---|
| [0001](0001-zaznamenavanie-a-verzovanie.md) | Zaznamenávať všetko a verzovať v gite | Prijaté | 2026-11-03 |
| [0002](0002-sukromne-repo-a-identita.md) | Súkromné repo `filbam/Discoop`, identita `filbam` | Prijaté | 2026-11-03 |
| [0003](0003-pravidla-pre-agentov-v-prehliadaci.md) | Pravidlá pre agentov v prehliadači používateľa | Prijaté | 2026-11-03 |
| [0004](0004-nazov-discoop.md) | Názov nástroja `discoop` | Prijaté | 2026-11-03 |
| [0005](0005-qr-login-bez-prehliadaca.md) | QR login v termináli bez prehliadača | Prijaté | 2026-11-03 |
| [0006](0006-python.md) | Implementácia v Pythone (uv, Typer, Rich, …) | Prijaté | 2026-11-03 |
| [0007](0007-anglictina-v-nastroji.md) | Help a hlášky nástroja po anglicky | Prijaté | 2026-11-03 |
| [0008](0008-zalozny-login-token.md) | Záložný login `discoop login --token` | Prijaté | 2026-11-03 |
| [0009](0009-login-v-agent-rezime.md) | `login` v agent režime odmietne | Prijaté | 2026-11-03 |
| [0010](0010-praca-cez-agentov.md) | Práca cez agentov, hlavný Claude ich riadi | Prijaté | 2026-11-03 |
| [0011](0011-predvolene-spravanie-messages.md) | Predvolené správanie `messages`: vlákna zapnuté, okno 24 h, formát `text` | Prijaté | 2026-11-03 |
| [0012](0012-premenovanie-agent-mode-na-plain.md) | Premenovanie „agent mode“ na „plain mode“ (`--plain`) | Prijaté | 2026-11-03 |
| [0013](0013-tui-a-spolocna-vrstva.md) | Interaktívne terminálové rozhranie (TUI) a spoločná servisná vrstva | Prijaté | 2026-11-03 |

## Šablóna

```markdown
# NNNN: Názov rozhodnutia

- **Stav:** Navrhnuté | Prijaté | Nahradené ADR NNNN
- **Dátum:** YYYY-MM-DD
- **Rozhodol:** používateľ | návrh Claude

## Kontext
Prečo bolo treba rozhodnúť.

## Možnosti
Zvažované alternatívy.

## Rozhodnutie
Čo sa rozhodlo.

## Dôsledky
Čo z toho vyplýva.
```
