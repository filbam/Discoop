# Návrh: `discoop`, CLI na sťahovanie správ z Discordu

Stav: **návrh na diskusiu** (3. 11. 2026). Vychádza z [discord-analyza.md](discord-analyza.md).
Body označené **[PROTOTYP]** závisia od vecí, ktoré treba ešte overiť vlastnými API volaniami (analýza, sekcia 14).

---

## 1. Ciele a hranice

**Cieľ:** stiahnuť správy a prílohy z vybraných serverov a kanálov za zvolené obdobie. Výstup je v troch podobách:
- pre AI agentov ako jednoduchý text,
- pre programy ako JSON,
- pre človeka ako farebný výstup v termináli.

**Nástroj iba číta.** Volá len `GET` endpointy. Jediná výnimka je read-only `POST /attachments/refresh-urls` **[PROTOTYP]**.
Nikdy neposiela správy, neoznačuje kanály ako prečítané (`ack`), nereaguje a nesleduje vlákna.

**Mimo v1:** DM, sledovanie v reálnom čase (gateway), lokálny archív všetkých správ s vyhľadávaním (kandidát na v2).

## 2. Názov

`scoop` koliduje s Windows package managerom Scoop. Návrh: **`discoop`** (Discord + scoop). Názov priečinka
projektu môže ostať `Scoop`. Ďalej v texte je pracovný názov `discoop`.

## 3. Technológie

| Účel | Voľba | Prečo |
|---|---|---|
| Jazyk | Python 3.12+ | rýchly vývoj, najlepšie knižnice na pekné CLI |
| CLI | Typer | príkazy, parametre a help z type hintov |
| UI pre človeka | Rich | tabuľky, stromy, progress bary, farby |
| HTTP | httpx | timeouty, retry, streamované sťahovanie súborov |
| Login | Playwright + **nainštalovaný Chrome** (`channel="chrome"`) | netreba sťahovať vlastný prehliadač |
| Uloženie tokenu | keyring (Windows Credential Manager) | token nie je v čitateľnom súbore |
| Cache a stav | SQLite (stdlib `sqlite3`) | jeden súbor, rýchle vyhľadávanie mien |
| Inštalácia | `uv tool install .` | príkaz `discoop` dostupný globálne |

## 4. Príkazy

```
discoop login                 prihlásenie v okne prehliadača (zvládne aj 2FA), uloží token
discoop logout                zmaže uložený token (--purge zmaže aj profil prehliadača)
discoop status                stav prihlásenia, účet, vek cache
discoop servers               zoznam serverov
discoop channels              zoznam kanálov servera
discoop threads               zoznam vlákien/fórum postov kanála
discoop messages              stiahnutie správ (+ príloh)
discoop config                predvolené nastavenia (napr. default server)
discoop agent-guide           kompaktná referencia pre AI agentov
```

**Globálne prepínače:** `--agent`, `--human`, `--quiet`, `--verbose`.

Server a kanál sa zadávajú cez **pomenované parametre** `-s/--server` a `-c/--channel`, nie pozične.
Pre agentov je to jednoznačnejšie. Hodnota môže byť ID alebo meno (pozri sekciu 5).
`-s` sa dá vynechať, ak:
- kanál je zadaný ID (ID kanála je globálne unikátne), alebo
- je nastavený `default-server` (`discoop config set default-server "VUT FIT"`).

### 4.1 `login`, `logout`, `status`

1. `login` spustí Chrome cez Playwright s **vlastným perzistentným profilom** (`%LOCALAPPDATA%\discoop\browser`)
   a otvorí `discord.com/login`.
2. Prihlásiš sa ručne vrátane 2FA alebo captchy. Nástroj čaká (timeout 10 min), kým klient pošle prvý request na
   `/api/v9/` s hlavičkou `Authorization`, a token si z neho vezme.
3. Overí ho cez `GET /users/@me`, uloží ho do keyringu, zatvorí prehliadač a vypíše `Prihlásený ako <meno>`.

Ďalšie vlastnosti:
- Discord vidí nástroj ako **samostatné zariadenie**, takže tvoje bežné prihlásenie v Chrome nijako neovplyvní.
- Ak token neskôr prestane platiť (odhlásenie zariadenia, zmena hesla), každý príkaz skončí kódom `2` a hláškou,
  že treba spustiť `discoop login`. Vďaka perzistentnému profilu býva opätovný login často bez 2FA.
- V agent režime `login` funguje tiež: vypíše, že čaká na prihlásenie človeka v otvorenom okne.

### 4.2 `servers`

```
discoop servers [--refresh]
```
Číta z cache. Obnoví ju `--refresh` alebo automaticky, ak je cache prázdna.
Zdroj: `GET /users/@me/guilds` **[PROTOTYP]**. Stĺpce: meno, ID, počet členov (ak je k dispozícii).

### 4.3 `channels`

```
discoop channels [-s SERVER] [--refresh] [--type text,announcement,forum,voice] [--flat]
```
- V human režime je výstup **strom podľa kategórií** zoradený podľa `position`, rovnako ako v Discorde.
  `--flat` dá plochý zoznam.
- **Skryté kanály** (`___hidden___`, flag `1<<17`) sa nevypisujú. `--include-hidden` ich zobrazí ako počet.
- Zdroj: `GET /guilds/{id}/channels` **[PROTOTYP]**. Fallback: jednorazové gateway pripojenie (len `READY`).

### 4.4 `threads`

```
discoop threads -c CHANNEL [-s SERVER] [--from 30d] [--archived|--active|--all]
```
Pri fóre vypíše posty, pri textovom kanáli vlákna. Stĺpce: meno, ID, počet správ, posledná aktivita, tagy.

### 4.5 `messages`

```
discoop messages -c CHANNEL [-c CHANNEL ...] [-s SERVER]
                 [--from WHEN] [--to WHEN] | [--last N] | [--since-last]
                 [--threads/--no-threads] [--include-system]
                 [--format text|md|json|jsonl] [--raw]
                 [--print] [--out DIR] [--zip FILE] [--no-files]
                 [--max-messages N] [--delay SEC]
```

**Výber kanálov:**
- `-c` sa dá opakovať a podporuje vzory (`-c "isc-*"`, `-c "*-terminy"`).
- `--all-channels` vezme celý server.

**Časové okno:**
- `WHEN` môže byť dátum `2026-10-01`, dátum a čas `2026-10-01T14:00`, relatívny čas `48h`, `7d`, `2w`
  alebo `all` (celá história).
- Čas sa interpretuje v lokálnej zóne. `--to` s holým dátumom znamená **vrátane celého dňa**.
- Predvolené okno je `--from 24h --to now`. Celá história sa nestiahne omylom, len cez `--from all`.
- `--last N` vráti posledných N správ.
- `--since-last` vráti len správy od posledného úspešného behu pre daný kanál (sekcia 9).

**Výstup:**
- Bez `--out`/`--zip` ide výstup do konzoly. Pri `--out`/`--zip` sa do konzoly vypíše len súhrn,
  `--print` vypíše aj samotné správy.
- `--max-messages` (predvolene 5000 na kanál) chráni agenta pred obrovským výstupom.
  Pri dosiahnutí limitu nástroj vypíše varovanie a skončí kódom `0`. Výstup obsahuje `truncated: true`.

Príklady:
```
discoop messages -s "VUT FIT" -c isc-public --from 7d
discoop messages -c 1286436864789843999 --from 2026-10-01 --to 2026-10-31 --zip D:\exporty\isc-oktober.zip
discoop messages -c "isc-*" --since-last --agent
```

### 4.6 `config`

```
discoop config set default-server "VUT FIT"
discoop config set delay 1.0
discoop config set export-dir D:\exporty
discoop config list
```
Uložené v `%LOCALAPPDATA%\discoop\config.toml`.

### 4.7 `agent-guide`

Vypíše kompaktnú referenciu pre AI na ~1 obrazovku: všetky príkazy, parametre, formát výstupu, exit kódy
a odporúčaný postup (`status` → `servers` → `channels` → `messages`). Agent sa z jedného volania naučí všetko
a nemusí prechádzať help každého príkazu.

## 5. Vyhľadávanie podľa mena

**Normalizácia mien:** malé písmená, bez diakritiky, bez emoji a symbolov.
Je to dôležité, lebo `🔒` je súčasť názvu kanála (`aeu-private🔒`). Zadanie `aeu-private` preto nájde `aeu-private🔒`.

**Poradie zhody:**
1. presné ID,
2. presné meno,
3. normalizované meno,
4. vzor (glob) na normalizovanom mene, len pri `-c`, kde je viac kanálov v poriadku.

**Nejednoznačnosť** (napr. `general` na dvoch serveroch bez `-s`) = **chyba s exit kódom 3** a zoznamom
kandidátov (meno, ID, server). Nástroj nikdy nehádá.

**Chýbajúce meno:** ak sa meno v cache nenájde, nástroj raz automaticky obnoví zoznam a skúsi to znova.

## 6. Výstupy

### 6.1 Režimy

| | `--human` | `--agent` |
|---|---|---|
| Kedy | predvolený v termináli | `--agent`, `DISCOOP_AGENT=1`, alebo keď stdout nie je terminál |
| Farby, tabuľky, stromy | áno (Rich) | nie |
| Progress | progress bary | nič; s `--verbose` jednoduché riadky na stderr |
| Chyby | farebný panel s radou | `ERROR <KÓD>: <správa>` + `HINT: <čo robiť>` na stderr |
| Interaktívne otázky | len pri `login` | nikdy |

**Dáta idú vždy na stdout, všetko ostatné na stderr.** Agent si teda môže výstup bezpečne presmerovať.

### 6.2 Formáty dát

**`text`** (predvolený v agent režime) je úsporný na tokeny:
```
=== VUT FIT / #isc-public ===
range: 2026-10-01 00:00 .. 2026-11-03 12:00 (Europe/Bratislava) | messages: 128 | threads: 3 | files: 12

[2026-10-12 14:03] Ján Novák (@jnovak) reply-to Petra: "kedy je deadline na prvý projekt…"
Do piatku 23:59, zadanie je v prílohe. Pozri aj #isc-info.
  [file] zadanie.pdf 412KB files/isc-public/1566570336231882913_zadanie.pdf
  [link] https://www.fit.vut.cz/study/... "Projekt 1"
  [reactions] ✅3 👍1

--- thread "Projekt 1 – otázky" (14 messages) ---
[2026-10-13 09:12] ...
```

Úpravy oproti surovým dátam:
- **Mentions:** `<@id>` sa prepíše na `@meno`, `<#id>` na `#kanál`, `<@&id>` na `@rola` (ak rolu nepoznáme, `@role:<id>`).
  Custom emoji `<:name:id>` sa zmení na `:name:`.
- **Systémové správy** (typ ≠ 0, 19) sa vynechajú. `--include-system` ich ponechá.
- **Poradie** je chronologické, od najstaršej správy.

**`md`:** to isté ako Markdown pre človeka alebo pre nahratie do AI. Obrázky sa vložia ako `![](files/...)`.

**`json` / `jsonl`:** normalizovaná schéma, nie surový Discord. `--raw` pridá pôvodný objekt.
```json
{
  "id": "1566570336659439696",
  "server": {"id": "461541385204400138", "name": "VUT FIT"},
  "channel": {"id": "1286436864789843999", "name": "isc-public"},
  "thread": null,
  "time": "2026-11-01T22:51:13+01:00",
  "edited": null,
  "author": {"id": "…", "name": "Ján Novák", "username": "jnovak", "bot": false},
  "text": "…",
  "reply_to": {"id": "…", "author": "Petra", "text": "…"},
  "attachments": [{"id": "…", "filename": "zadanie.pdf", "type": "application/pdf", "size": 421888, "path": "files/…", "url": "…"}],
  "links": [{"kind": "link", "url": "…", "title": "…"}],
  "reactions": [{"emoji": "✅", "count": 3}],
  "pinned": false,
  "has_thread": false
}
```
Meno autora je `global_name` a ak chýba, `username`. Prezývky zo servera REST API nedáva (analýza, sekcia 9).

### 6.3 Kam ide výstup: konzola, priečinok, zip

| Parameter | Výsledok | Prílohy |
|---|---|---|
| (nič) / `--print` | konzola | len názov a URL (URL vyprší o 12 až 24 h) |
| `--out DIR` | priečinok | stiahnuté (vypnúť cez `--no-files`) |
| `--zip FILE` | zip | stiahnuté (vypnúť cez `--no-files`) |

**Štruktúra exportu** (rovnaká pre priečinok aj zip):
```
vutfit_2026-11-03_1200/
  manifest.json            parametre behu, čas, počty, verzia nástroja, truncated
  messages.md              všetky kanály pre človeka/AI (sekcia na kanál, vlákna vnorené)
  messages.jsonl           štruktúrované dáta
  channels/
    isc-public.md          ten istý obsah rozdelený po kanáloch
  files/
    isc-public/<attachment_id>_<filename>
```
Cesty k prílohám v `.md` a `.jsonl` sú relatívne. AI s prístupom k súborom ich teda vie otvoriť.

## 7. Prílohy

- Sťahujú sa **hneď po načítaní stránky správ**, lebo podpísané URL platia len 12 až 24 h (analýza, sekcia 5).
- Ak CDN vráti `403/404` (URL exspirovala), nástroj správu načíta znova (`around=<id>&limit=1`) a URL obnoví.
  Ďalšia možnosť je `refresh-urls` **[PROTOTYP]**.
- Na CDN netreba token. Sťahuje sa bez `Authorization` hlavičky, takže token sa neposiela nikam navyše.
- Súbory sa pomenúvajú `<attachment_id>_<filename>` (unikátne, bezpečné pre Windows).
  **Deduplikácia** ide podľa `attachment_id`: pri `--since-last` do toho istého priečinka sa nič nesťahuje dvakrát.
- **Čo sa sťahuje:**
  - áno: prílohy (`attachments[]`),
  - nie: embedy (GIF, link preview, YouTube); zapíšu sa len ako `[link]`,
  - voliteľne: obrázky z embedov typu `image` (`--embed-images`).
- `--max-file-size` (predvolene 50 MB) chráni pred obrovskými videami.

## 8. Vlákna a fóra

- **Vlákna sa sťahujú predvolene.** Vypnúť sa dá cez `--no-threads`. Fórum (napr. `#help-center`) obsahuje
  *len* vlákna, takže tam sa vypnúť nedajú.
- **Postup pre kanál:**
  1. Archivované vlákna sa načítajú cez `threads/search?archived=true&sort_by=last_message_time&sort_order=desc`
     a stránkujú cez `offset`. Pri vláknach s poslednou aktivitou staršou ako `--from` sa načítavanie zastaví.
  2. Aktívne vlákna: REST cesta je **[PROTOTYP]**. Záložný zdroj: správy v stiahnutom okne s objektom `thread`
     (flag 32), kde `thread.id == message.id`.
  3. Každé vlákno sa stiahne ako samostatný kanál cez `/messages` s tým istým časovým oknom.
- Vo výstupe je vlákno vnorené pod materským kanálom. Pri fóre je to post s tagmi (`applied_tags` → mená tagov).

## 9. Sťahovanie: stránkovanie, rate limit, chyby

**Časové okno:** dátumy sa prevedú na syntetické snowflake (`(ms − 1420070400000) << 22`).
- Bežné okno: od `--to` dozadu cez `before=<najstaršie_id>&limit=100` **[PROTOTYP: 100]**, kým ID nie je staršie
  ako `--from`.
- `--since-last`: `after=<last_id>&limit=100`. Odpoveď je zostupná, ďalšia strana teda ide od `max(id)`.
  Stav sa uloží až po úspešnom dokončení kanála.

**Tempo:**
- Requesty idú **sekvenčne** s pauzou `--delay` (predvolene 1.0 s, s malým náhodným rozptylom).
- CDN sťahovanie môže bežať paralelne v 2 vláknach (CDN nie je API rate limit).
- Discord neposiela rate-limit hlavičky (analýza, sekcia 10), preto tempo nastavuje pevne nástroj.

**Chyby:**
- `429`: počká `retry_after` z tela odpovede a pokračuje **[PROTOTYP: tvar]**.
  Opakovaný `429` predĺži `delay` na dvojnásobok.
- `5xx` a sieťové chyby: 3 pokusy s backoffom.
- `401`: koniec s kódom `2` (treba login).
- `403` na kanál (Missing Access): kanál sa preskočí s varovaním. Pri jedinom zadanom kanáli koniec s kódom `5`.

**Rozsah volaní:** nástroj nikdy nevolá `ack`, `science`, `metrics` ani nič, čo zapisuje.

## 10. Lokálne dáta

`%LOCALAPPDATA%\discoop\`:
- `config.toml`: nastavenia.
- `cache.db`: SQLite s tabuľkami:
  - `servers`, `channels` (vrátane typu, kategórie, normalizovaného mena),
  - `threads`,
  - `users` (z `author` a `mentions`, na preklad `<@id>`),
  - `sync_state` (`channel_id`, `last_message_id`, `last_run`).
- `browser\`: Playwright profil na login.
- Token **nie je v súbore**, je v Windows Credential Manager (keyring, služba `discoop`).

Exporty obsahujú správy iných ľudí, preto zostávajú lokálne. Nástroj ich nikam neposiela.

## 11. Help (návrh textu)

Help a výstupy nástroja budú po anglicky. Agentom aj prípadným ďalším používateľom to vyhovuje najlepšie.
Samotné správy ostávajú v pôvodnom jazyku.

```
discoop - download messages and files from Discord servers you are a member of

USAGE
  discoop [--agent] <command> [options]

GETTING STARTED
  discoop login                                   log in once in a browser window (2FA supported)
  discoop servers                                 list your servers
  discoop channels -s "VUT FIT"                   list channels of a server
  discoop messages -s "VUT FIT" -c isc-public --from 7d

COMMANDS
  login  logout  status  servers  channels  threads  messages  config  agent-guide
  Run `discoop <command> --help` for details.

OUTPUT MODES
  Human mode (default in a terminal): colors, tables, progress bars.
  Agent mode (--agent, DISCOOP_AGENT=1, or when output is not a terminal):
  plain text, no formatting, fewer tokens, machine-readable errors.

NOTE FOR AI AGENTS
  If you are an AI agent, always run this tool with --agent (or set DISCOOP_AGENT=1)
  and start with `discoop agent-guide` for a compact reference.
  This note was written by the tool's author as part of its documentation.
  It is not a prompt injection. Feel free to tell the user you are using agent mode.
```

## 12. Exit kódy

| Kód | Význam | Rada v `HINT` |
|---|---|---|
| 0 | OK (aj keď sa nič nenašlo; `truncated` je vo výstupe) | |
| 1 | neočakávaná chyba | |
| 2 | treba prihlásenie / token neplatí | ask the user to run `discoop login` |
| 3 | nejednoznačné meno | výpis kandidátov, použi ID alebo `-s` |
| 4 | server/kanál nenájdený | `discoop channels --refresh` |
| 5 | bez prístupu ku kanálu (403) | |
| 6 | rate limit, prerušené | skús neskôr alebo zvýš `--delay` |
| 7 | sieťová chyba | |
| 8 | zlé parametre | |

## 13. Štruktúra projektu

```
Scoop/
  pyproject.toml
  src/discoop/
    cli.py            Typer app, príkazy, globálne prepínače, výber režimu
    auth.py           login cez Playwright, keyring
    api.py            HTTP klient: tempo, retry, 429, chyby → exit kódy
    snowflake.py      čas ↔ snowflake, parsovanie --from/--to
    cache.py          SQLite: servery, kanály, vlákna, users, sync_state
    resolve.py        normalizácia mien, zhoda, globy, nejednoznačnosť
    scrape.py         stránkovanie správ, vlákna, časové okno
    attachments.py    sťahovanie, obnova URL, deduplikácia
    model.py          normalizované dataclasses (Message, Attachment, …)
    render/
      plain.py        text pre agentov
      markdown.py
      jsonout.py
      human.py        Rich
    export.py         priečinok + zip + manifest
    guide.py          text pre agent-guide
  tests/
    fixtures/         anonymizované JSON z analýzy
  docs/
```

## 14. Postup implementácie

0. **Spike / prototyp:** `login` + malý skript, ktorý overí body [PROTOTYP]:
   - `GET /users/@me/guilds` a `GET /guilds/{id}/channels` s user tokenom,
   - `limit=100`,
   - REST cesta k aktívnym vláknam,
   - tvar `429` a `refresh-urls`.

   Spúšťa ho používateľ, pretože beží na jeho účte. Výsledky sa zapíšu do analýzy.
1. **Jadro:** config, cache, API klient, `servers`, `channels`, `resolve`, `status`.
2. **`messages`** → `text`/`json` do konzoly, časové okno, `--last`.
3. **Prílohy** + `--out` / `--zip` + manifest.
4. **Vlákna a fóra**, `threads`.
5. **Human režim** (Rich), `agent-guide`, help texty.
6. **`--since-last`**, deduplikácia.

**Testy:** unit testy (snowflake, parsovanie času, resolve, renderery) nad anonymizovanými fixtures, bez živého API.

## 15. Otvorené rozhodnutia

| # | Otázka | Návrh |
|---|---|---|
| 1 | Jazyk | Python |
| 2 | Názov príkazu | `discoop` |
| 3 | Jazyk helpu a hlášok | angličtina |
| 4 | Vlákna predvolene | zapnuté |
| 5 | Predvolené časové okno | 24 h, celá história len cez `--from all` |
| 6 | Predvolený formát v agent režime | `text` (JSON cez `--format json`) |

**Nápady na neskôr (v2):** lokálny archív všetkých správ v SQLite s fulltextom, `discoop sync` pre zoznam
sledovaných kanálov, zhlukovanie po sebe idúcich správ jedného autora (menej tokenov), filter `--author`,
`--has file`.
