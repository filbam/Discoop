# Denník

Chronologický záznam práce: čo sa urobilo, čo sa rozhodlo, incidenty a ďalšie kroky. Najnovšie hore.

---

## 2026-11-03

**Analýza Discord web klienta** → [analyzy/discord-analyza.md](analyzy/discord-analyza.md)
- Analýzu robil agent v Chrome používateľa (server VUT FIT) v troch behoch. Agent iba sledoval requesty,
  ktoré posiela samotný Discord klient. Token nečítal.
- Hlavné zistenia:
  - Správy, piny, vlákna aj search idú cez REST `/api/v9`. Zoznam kanálov a aktívne vlákna prichádzajú cez gateway.
  - Skryté kanály sú v dátach ako `___hidden___`.
  - Odkazy na prílohy platia 12 až 24 h a na stiahnutie netreba token.
  - REST odpovede neobsahujú rate-limit hlavičky.
- Otvorené body na overenie prototypom sú v sekcii 14 analýzy.

**Incident 1: omylom odoslaná správa.** Agent poslal z účtu používateľa správu `cdn.discordapp.com` do vlákna
vo fóre `#help-center`. Stalo sa to po zatvorení panelu vyhľadávania: ďalší klik trafil pole na písanie správy
a Enter určený pre vyhľadávanie správu odoslal.
- Používateľ správu zmazal.
- Vlákno ostalo sledované (Following).
- Opatrenie: agent na Discorde nesmie písať ani stláčať klávesy ([ADR 0003](rozhodnutia/0003-pravidla-pre-agentov-v-prehliadaci.md)).

**Incident 2: Chrome sa dvakrát zavrel.** V oboch prípadoch presne pri `tabs_close_mcp`. Karta agenta bola
jediná v okne, ktoré si agent vytvoril.
- Opatrenie: agent nikdy nezatvára karty ani okná (ADR 0003).

**Vedľajšie účinky analýzy:**
- Ako prečítané sa označilo niekoľko kanálov (zoznam je v analýze, sekcia „Vedľajšie účinky“).
- V histórii vyhľadávania Discordu pribudli 4 dotazy.

**Návrh nástroja** → [navrh-nastroja.md](navrh-nastroja.md)
- Obsahuje príkazy, výstupy (konzola, priečinok, zip), režimy human/agent, prílohy, vlákna, help a exit kódy.
- Otvorené rozhodnutia sú v sekcii 15. Názov `discoop` je prijatý (ADR 0004).

**Git**
- Repo založené lokálne a prepojené so súkromným `filbam/Discoop` ([ADR 0002](rozhodnutia/0002-sukromne-repo-a-identita.md)).
- Prvý commit `f1c6fac` (analýza + návrh) je pushnutý.
- Pri pushi bolo treba prihlásenie ako `filbam`, lebo predvolený účet `FilipBambura` súkromné repo nevidí.

**Záznamy:** zavedená štruktúra dokumentácie podľa požiadavky P12 ([ADR 0001](rozhodnutia/0001-zaznamenavanie-a-verzovanie.md)):
`CLAUDE.md`, `CHANGELOG.md`, `poziadavky.md`, `dennik.md`, `rozhodnutia/`, `analyzy/`.

**Nové požiadavky:** P13 (Windows, Linux, macOS) a P14 (QR login v termináli).

**Analýza prihlásenia** → [analyzy/discord-login.md](analyzy/discord-login.md)
- Robil ju agent vo vstavanom prehliadači aplikácie Claude, v neprihlásenom stave. Iba pozoroval prevádzku
  a čítal zdrojový kód stránky. Nič neodoslal a QR neskenoval.
- **Hlavné zistenie:** QR login (remote auth gateway `v=2`) sa dá spraviť bez prehliadača. Stačí WebSocket,
  RSA-OAEP-SHA256 a jeden REST POST.
- **Neoverené** (overí prototyp): kontrola `Origin`, captcha pri `remote-auth/login`, reálne rámce po naskenovaní.
- **Návrh upravený:** login cez QR, Playwright vypadol, cesty a keyring pre všetky OS
  ([ADR 0005](rozhodnutia/0005-qr-login-bez-prehliadaca.md)). Pribudli otvorené rozhodnutia 7 (záložný login)
  a 8 (`login` v agent režime).

**Incident 3: passkey dialóg.** Login stránka pri každom zobrazení formulára sama volá passkey autofill
(`navigator.credentials.get`). Vstavaný prehliadač na Windows z toho spravil systémové okno Windows Security
(„Insert your security key“). Používateľovi bolo odporučené okno zrušiť. Nič sa neprihlásilo.
- Opatrenie: pred otvorením `discord.com/login` vo vstavanom prehliadači používateľa upozorniť (CLAUDE.md, ADR 0003).
- Karta vstavaného prehliadača je presmerovaná z login stránky preč, aby negenerovala nové QR.

**Ďalej:**
1. Potvrdiť otvorené rozhodnutia z návrhu (sekcia 15, body 1 a 3 až 8).
2. Prototyp: QR `login` + skript na overenie otvorených bodov API.

---

## 2026-11-02

**Brainstorming.** Používateľ opísal požiadavky → [poziadavky.md](poziadavky.md) (P1–P11).
- Prezretý starý skript `discord-script.js` (FITSeeker):
  - spúšťal sa z konzoly prehliadača a volal `GET /api/v9/channels/{id}/messages`,
  - stránkoval cez `before` a časové okno počítal cez snowflake,
  - ošetroval `429` a medzi requestami robil pauzu 800 ms.
- Zistenia:
  - Discord API autentifikuje **tokenom** v hlavičke `Authorization`, nie cookies. `login` teda musí získať a uložiť token.
  - Názov `scoop` koliduje s Windows package managerom Scoop.
