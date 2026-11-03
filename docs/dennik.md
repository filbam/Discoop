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

**Prvý prototyp.** Rozhodnutia z otázok zapísané ako ADR 0006–0009:
- Python, angličtina v nástroji, `login --token`, login v agent režime odmietne.
- Pravidlo commitov: commit sám po krokoch, push len na pokyn.
- uv nainštalované cez winget.

Kód (`src/discoop/`, 42 testov):
- `login` (QR + `--token` + `--trace`), `status`, `logout`, režimy human/agent, keyring, REST klient.
- `prototype/probe.py` na overenie REST endpointov.

**Overené na reálnom Discorde** (`login --handshake-only`): QR gateway prijal spojenie z terminálového klienta
(Python `websockets` s `Origin: https://discord.com`). Handshake prebehol až po `pending_remote_init`.
Do účtu sa nikto neprihlásil.

**Odchýlka od plánu:** neznáme `op` sa (ako vo webovom klientovi) ignorujú a iba zapíšu do trace. Neznámy close kód
skončí chybou s radou na `--token`.

**Prototyp spustený používateľom (2026-11-03 popoludní):**
- **`discoop login` cez QR funguje na reálnom účte.** Prvý pokus prešiel bez captchy.
  - Sken ~52 s, potvrdenie na telefóne ~16 s.
  - Token je uložený vo Windows Credential Manager.
  - QR sa v termináli (PowerShell) dal naskenovať.
  - `timeout_ms` bol ~5,7 min, platnosť QR teda kolíše viac, než sa myslelo.
- **`prototype/probe.py`** (13 API requestov, bez rate limitov a bez rate-limit hlavičiek), výsledky
  v [analýze, sekcia 15](analyzy/discord-analyza.md#15-overenie-prototypom-2026-11-03):
  - zoznam serverov aj kanálov ide cez REST, gateway nebude treba,
  - `limit` max 100,
  - `after` vracia najbližšie novšie správy zoradené od najnovšej,
  - aktívne vlákna cez `threads/search?archived=false`. `guilds/{id}/threads/active` je len pre botov,
  - CDN funguje bez tokenu,
  - `refresh-urls` funguje.
- **Návrh aktualizovaný:** body [PROTOTYP] sú teraz [OVERENÉ].
- **Stále otvorené:**
  - tvar `429`,
  - stránkovanie pinov,
  - nesúlad `total_results` 15 a 13 vrátených vlákien vo fóre,
  - `refresh-urls` pri exspirovanej URL.

**Krok 1 implementácie (servers, channels, config, cache, vyhľadávanie mien):**
- Hotové, 71 testov, commity `1d31ba4` a `ce466c7`.
- Proti reálnemu Discordu to zatiaľ spustil len používateľ, podľa CLAUDE.md volá API iba on.
- **Odchýlky od návrhu:**
  - `--include-hidden` vypadol, lebo sa zdalo, že REST skryté kanály nevracia. Neskorší test ukázal opak.
  - `default-server` sa ukladá ako ID.
  - `export-dir` sa odložil na export.
- **Cache** sa maže pri login aj logout, aby po prihlásení iným účtom neostali staré servery.

**Test používateľa** (log v `Temp/`, lokálny, gitom ignorovaný):
- **Funguje:** `servers`, `channels` (strom, `--flat`, `--type`), `config set default-server`, `--agent channels`.
  - 8 serverov, VUT FIT má 390 kanálov.
- **Zistenie:** REST `GET /guilds/{id}/channels` vracia **aj kanály, ktoré používateľ nevidí**, s reálnymi menami.
  - Napríklad celé kategórie `moderation`, `logging`, `fillers`.
  - Aj `#přípravné-kurzy` (`1549737445002584094`), ktorý klient zobrazil ako `___hidden___`.
  - Predchádzajúce tvrdenie „REST skryté kanály nevracia“ bolo chybné. Analýza (sekcie 13–15) aj návrh (4.3)
    sú opravené.
  - Riešenie je otvorené rozhodnutie 9: výpočet prístupu z práv a rolí.

**Ďalej:**
1. Rozhodnutie 9: výpočet prístupu ku kanálom. Treba overiť, ako pre user token získať roly člena.
2. Potvrdiť zvyšné rozhodnutia z návrhu (sekcia 15, body 4 až 6). Týkajú sa `messages`.
3. Krok 2: `messages` do konzoly (`text`/`json`), časové okno, `--last`.

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
