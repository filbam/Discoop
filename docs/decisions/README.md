# Rozhodnutia (ADR)

Každé rozhodnutie má vlastný súbor `NNNN-nazov.md`. Zmenené rozhodnutie sa nemaže. Nahradí ho nový ADR
a starý dostane stav `Nahradené ADR NNNN`.

**Stavy:**
- `Prijaté`: rozhodol alebo jasne súhlasil používateľ.
- `Navrhnuté`: čaká na súhlas.
- `Nahradené`: rozhodnutie zmenil novší ADR.

Rozhodnutia, ktoré ešte nie sú vyriešené, sú v [design.md, sekcia 15](../design.md#15-otvorené-rozhodnutia).

| # | Rozhodnutie | Stav | Dátum |
|---|---|---|---|
| [0001](0001-record-everything-and-version-it.md) | Zaznamenávať všetko a verzovať v gite | Prijaté | 2026-11-03 |
| [0002](0002-private-repo-and-identity.md) | Súkromné repo `filbam/Discoop`, identita `filbam` | Prijaté, súkromné repo nahradené ADR 0015 | 2026-11-03 |
| [0003](0003-rules-for-agents-in-the-users-browser.md) | Pravidlá pre agentov v prehliadači používateľa | Prijaté | 2026-11-03 |
| [0004](0004-name-discoop.md) | Názov nástroja `discoop` | Prijaté | 2026-11-03 |
| [0005](0005-qr-login-without-a-browser.md) | QR login v termináli bez prehliadača | Prijaté | 2026-11-03 |
| [0006](0006-python.md) | Implementácia v Pythone (uv, Typer, Rich, …) | Prijaté | 2026-11-03 |
| [0007](0007-english-in-the-tool.md) | Help a hlášky nástroja po anglicky | Prijaté | 2026-11-03 |
| [0008](0008-fallback-login-token.md) | Záložný login `discoop login --token` | Prijaté | 2026-11-03 |
| [0009](0009-login-in-agent-mode.md) | `login` v agent režime odmietne | Prijaté | 2026-11-03 |
| [0010](0010-work-through-agents.md) | Práca cez agentov, hlavný Claude ich riadi | Prijaté | 2026-11-03 |
| [0011](0011-default-behaviour-of-messages.md) | Predvolené správanie `messages`: vlákna zapnuté, okno 24 h, formát `text` | Prijaté | 2026-11-03 |
| [0012](0012-rename-agent-mode-to-plain.md) | Premenovanie „agent mode“ na „plain mode“ (`--plain`) | Prijaté | 2026-11-03 |
| [0013](0013-tui-and-shared-service-layer.md) | Interaktívne terminálové rozhranie (TUI) a spoločná servisná vrstva | Prijaté, rozloženie TUI nahradené ADR 0014 | 2026-11-03 |
| [0014](0014-tui-keyboard-one-tree.md) | TUI: ovládanie klávesnicou, jeden strom, farby terminálu | Prijaté | 2026-11-03 |
| [0015](0015-public-repo-and-installation.md) | Verejné repo a inštalácia cez `uv tool` | Prijaté | 2026-11-04 |
| [0016](0016-default-export-folder-in-tui.md) | Predvolený priečinok exportov v TUI: `Documents/discoop` | Prijaté | 2026-11-04 |
| [0017](0017-reliable-export-and-partial-success.md) | Spoľahlivý export a čiastočný úspech | Prijaté | 2026-11-04 |
| [0018](0018-logging.md) | Voliteľné diagnostické logovanie (`--debug`, `--log`) | Prijaté | 2026-11-04 |
| [0019](0019-threads.md) | Vlákna a príspevky na fórach (podklad: [probe](../analyses/thread-probe-2026-11-04.md)) | Prijaté | 2026-11-04 |
| [0020](0020-since-last.md) | Prírastkové sťahovanie (`--since-last`) | Prijaté | 2026-11-04 |

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
