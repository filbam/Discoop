# 0003: Pravidlá pre agentov v prehliadači používateľa

- **Stav:** Prijaté
- **Dátum:** 2026-11-03
- **Rozhodol:** zavedené po incidentoch, používateľ pod týmito pravidlami nechal analýzu pokračovať

## Kontext

Analýzu Discordu robil AI agent v reálnom Chrome používateľa, prihlásenom do Discordu ([denník 2026-11-03](../journal.md)).

1. **Odoslaná správa:** agent mal povolené písať do vyhľadávania. Klik trafil pole na písanie správy a Enter
   odoslal správu z účtu používateľa.
2. **Zavretý Chrome:** zatvorenie karty agenta (`tabs_close_mcp`) dvakrát zhodilo celý Chrome.

## Rozhodnutie

Agent v prehliadači používateľa na Discorde:
- **nepíše a nestláča žiadne klávesy** (ani vyhľadávanie),
- **kliká len na navigáciu**: kanály v sidebare, tlačidlá v hlavičke kanála, zatvorenie panelov.
  Nikdy nie na zoznam správ, reakcie, composer, Follow ani Join.
- **nezatvára karty ani okná.** Kartu nechá otvorenú a zavrie ju používateľ.
- **iba číta.** Uprednostňuje sledovanie network requestov, token ani cookies nečíta a nerobí vlastné API volania.
- **pri čomkoľvek nečakanom okamžite zastaví** a ohlási to.

## Dôsledky

- Veci, ktoré vyžadujú vlastné API volania (limity, REST endpointy, tvar `429`), sa overujú prototypom,
  ktorý spúšťa používateľ.
- Pri analýze sa niektoré kanály vždy označia ako prečítané. Je to vedľajší účinok otvorenia kanála
  a pred analýzou treba používateľa upozorniť.
- **Doplnené 2026-11-03:** `discord.com/login` pri každom zobrazení formulára sám volá passkey autofill
  (`navigator.credentials.get`). Vstavaný prehliadač na Windows z toho spraví systémové okno Windows Security.
  Pred otvorením login stránky treba používateľa upozorniť, aby okno zrušil.
