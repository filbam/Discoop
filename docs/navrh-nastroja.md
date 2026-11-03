# Návrh: `discoop`, CLI na sťahovanie správ z Discordu

Stav: **návrh na diskusiu** (3. 11. 2026). Vychádza z [analyzy/discord-analyza.md](analyzy/discord-analyza.md).
Prijaté rozhodnutia sú v [rozhodnutia/](rozhodnutia/README.md).
Body označené **[PROTOTYP]** závisia od vecí, ktoré treba ešte overiť vlastnými API volaniami (analýza, sekcia 14).
Prototyp 2026-11-03 väčšinu z nich overil (analýza, sekcia 15). Overené body sú označené **[OVERENÉ]**.

---

## 1. Ciele a hranice

**Cieľ:** stiahnuť správy a prílohy z vybraných serverov a kanálov za zvolené obdobie. Výstup je v troch podobách:
- pre AI agentov ako jednoduchý text,
- pre programy ako JSON,
- pre človeka ako farebný výstup v termináli.

**Nástroj iba číta.** Volá len `GET` endpointy. Jediná výnimka je read-only `POST /attachments/refresh-urls` **[OVERENÉ]**.
Nikdy neposiela správy, neoznačuje kanály ako prečítané (`ack`), nereaguje a nesleduje vlákna.

**Mimo v1:** DM, sledovanie v reálnom čase (gateway), lokálny archív všetkých správ s vyhľadávaním (kandidát na v2).

## 2. Názov

`scoop` koliduje s Windows package managerom Scoop. Návrh: **`discoop`** (Discord + scoop). Názov priečinka
projektu môže ostať `Scoop`. Ďalej v texte je pracovný názov `discoop`.

## 3. Technológie

Nástroj beží na **Windows, Linuxe aj macOS** (P13). Žiadna časť nesmie závisieť od jedného OS.

| Účel | Voľba | Prečo |
|---|---|---|
| Jazyk | Python 3.12+ | rýchly vývoj, najlepšie knižnice na pekné CLI |
| CLI | Typer | príkazy, parametre a help z type hintov |
| UI pre človeka | Rich | tabuľky, stromy, progress bary, farby |
| HTTP | httpx | timeouty, retry, streamované sťahovanie súborov |
| Login | QR cez remote auth gateway: `websockets` + `cryptography` + `segno` (QR v termináli) | bez prehliadača, na všetkých OS ([ADR 0005](rozhodnutia/0005-qr-login-bez-prehliadaca.md)) |
| Uloženie tokenu | keyring (Windows Credential Manager, macOS Keychain, Linux Secret Service) | token nie je v čitateľnom súbore. Na Linuxe bez Secret Service fallback, sekcia 10 |
| Cesty k dátam | platformdirs | správny adresár na každom OS |
| Cache a stav | SQLite (stdlib `sqlite3`) | jeden súbor, rýchle vyhľadávanie mien |
| Inštalácia | `uv tool install .` | príkaz `discoop` dostupný globálne |

## 4. Príkazy

```
discoop login                 prihlásenie naskenovaním QR kódu v termináli mobilom, uloží token
discoop logout                zmaže uložený token
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

Hlavná cesta je **QR login bez prehliadača** (P14, [ADR 0005](rozhodnutia/0005-qr-login-bez-prehliadaca.md)).
Protokol popisuje [analyzy/discord-login.md](analyzy/discord-login.md).

1. `login` sa pripojí na `wss://remote-auth-gateway.discord.gg/?v=2` (s `Origin: https://discord.com`),
   vygeneruje kľúč RSA-2048 a prejde handshake (`hello` → `init` → `nonce_proof` → `pending_remote_init`).
2. V termináli vykreslí QR kód `https://discord.com/ra/<fingerprint>` s odpočtom platnosti (`timeout_ms`, pozorované ~4 – 5,7 min).
   Naskenuješ ho v mobilnej aplikácii Discord (Settings → Scan QR Code).
3. Po naskenovaní vypíše „Prihlasuje sa <meno>, potvrď na telefóne“ (`pending_ticket`).
4. Po potvrdení (`pending_login`) zavolá `POST /users/@me/remote-auth/login`, dešifruje token, overí ho cez
   `GET /users/@me`, uloží ho do keyringu a vypíše `Prihlásený ako <meno>`.
5. Keď QR vyprší (`4003`) alebo zrušíš prihlásenie na telefóne (`cancel`), vygeneruje nový QR. Po 3 pokusoch skončí.

Ďalšie vlastnosti:
- **2FA netreba riešiť** v termináli. Prihlásenie potvrdzuje tvoj už prihlásený mobil.
- **Samostatné zariadenie:** Discord vidí nástroj ako novú reláciu, tvoje bežné prihlásenie sa nezmení.
- **Neplatný token** (odhlásené zariadenie, zmena hesla): každý príkaz skončí kódom `2` s hláškou, že treba
  spustiť `discoop login`.
- **Bezpečnosť:** QR ani token sa nikdy nelogujú.
- **Záložná cesta** a správanie `login` v agent režime sú otvorené rozhodnutia (sekcia 15, body 7 a 8).

### 4.2 `servers`

```
discoop servers [--refresh]
```
Číta z cache. Obnoví ju `--refresh` alebo automaticky, ak je cache prázdna.
Zdroj: `GET /users/@me/guilds?with_counts=true` **[OVERENÉ]**. Stĺpce: meno, ID, počet členov (`approximate_member_count`).

**Implementované 2026-11-03:**
- Human režim vypíše tabuľku. Agent režim vypíše hlavičku `id members name` a riadky, kde sú stĺpce oddelené tabulátorom,
  zoradené podľa mena.
- Ak sa použila cache, na stderr pribudne poznámka s jej vekom (agent ju vidí len s `--verbose`).

### 4.3 `channels`

```
discoop channels [-s SERVER] [--refresh] [--type text,forum,...] [--flat]
```
- **Poradie** je ako v sidebare Discordu: najprv kanály bez kategórie, potom kategórie podľa `position`.
  V kategórii sú textové kanály nad hlasovými, potom podľa `position` a nakoniec podľa ID.
- **Human režim:** strom podľa kategórií. `--flat` dá tabuľku.
- **Agent režim:** vždy riadky so stĺpcami `id type category name` oddelenými tabulátorom.
- **Filter `--type`** (čiarkami): `text, voice, announcement, stage, directory, forum, media`.
- **Skryté kanály** (`___hidden___`, flag `1<<17`) sa nevypisujú.
- **Pozor, zistené pri teste 2026-11-03:** REST vracia **aj kanály, ktoré používateľ nevidí**, a to s reálnym menom
  (napr. kategórie `moderation`, `logging`). `channels` ich zatiaľ vypisuje tiež.
  - Riešenie je rozhodnutie 9 (sekcia 15): vypočítať prístup z `permission_overwrites` a rolí používateľa.
    Od 2026-11-03 je **odložené** s nízkou prioritou.
  - Prepínač `--include-hidden` sa môže vrátiť ako „ukáž aj nedostupné“.
- **Zdroj:** `GET /guilds/{id}/channels` **[OVERENÉ]**.
- **Bez prístupu:** `403`/`404` na server skončí kódom `5`.
- **Server** sa zadáva cez `-s` (meno alebo ID), inak sa použije `default-server`. Keď nie je ani jedno,
  nástroj skončí kódom `8` s radou.

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

**Implementované 2026-11-03 (krok 2, čaká na test používateľa):**
- **Prepínače:** `-c` (opakovateľný), `-s`, `--from`, `--to`, `--last`, `--format text|json`, `--include-system`,
  `--max-messages`. Prepínače neskorších krokov zatiaľ nie sú (`--threads/--no-threads`, `--out`, `--zip`,
  `--print`, `--no-files`, `--since-last`, `--raw`, `--delay`, formáty `md` a `jsonl`). Tempo je z `config set delay`.
- **Výber kanálov:**
  - `-c` berie meno, ID alebo glob vzor. Mená a vzory sa hľadajú v kanáloch servera z `-s` alebo `default-server`
    a **preskakujú kategórie**, takže kategória `general` a kanál `general` sa nebijú.
  - **Holé ID bez `-s`** sa hľadá v cache všetkých serverov. Ak tam nie je, nástroj zavolá `GET /channels/{id}`
    **[PREDPOKLAD]**, z `guild_id` zistí server a stiahne jeho zoznam kanálov. `default-server` sa pri ID nepoužije.
  - Čítajú sa textové, hlasové a stage kanály, oznamy a vlákna zadané cez ID. Kategória alebo fórum skončí
    kódom `8`. Vzor, ktorý nájde len kanály bez správ (napr. fóra), skončí kódom `4`.
  - **`--all-channels` zatiaľ nie je.** REST vracia aj nedostupné kanály a bez výpočtu prístupu (rozhodnutie 9, odložené)
    by skončil stovkami `403`.
- **Časové okno:**
  - Formáty podľa návrhu, navyše `now`, čas so zónou (`2026-10-01T14:00+02:00`, `…Z`) a medzera namiesto `T`.
  - Relatívny čas má len jednotky `h`, `d`, `w`. `1m` je chyba, lebo sa dá čítať ako minúta aj mesiac.
  - **Bez `--from` je okno 24 h pred `--to`.** Pri predvolenom `--to now` sú to posledné 24 h ([ADR 0011](rozhodnutia/0011-predvolene-spravanie-messages.md)).
  - `--from` platí vrátane, `--to` bez.
  - **`--last N`** sa dá kombinovať s `--from`/`--to`: vráti N najnovších správ v okne. Bez `--from` berie celú
    históriu, nie 24 h.
  - Zlá hodnota, `--to all` alebo `--from` po `--to` skončí kódom `8` ešte pred volaním API.
- **Limity:**
  - `--max-messages` (predvolene 5000 na kanál) je podľa návrhu. Pri dosiahnutí limitu nástroj vypíše varovanie
    na stderr, hlavička má `truncated: yes`, JSON `"truncated": true` a exit kód je `0`.
  - `--last N` sa za orezanie nepovažuje, je to presne to, čo sa pýtalo.
- **Systémové správy:** za bežné sa okrem typov 0 a 19 považujú aj 20 a 23 (odpovede botov na slash
  a kontextové príkazy). Návrh mal len 0 a 19. `--include-system` ukáže aj ostatné.
- **Formát `text`** je podľa 6.2 s týmito odchýlkami a doplnkami:
  - Príloha je `[file] meno veľkosť URL`. Lokálna cesta pribudne s exportom.
  - Hlavička nemá `threads:` (vlákna sú krok 4). Zóna je ako posun `UTC+01:00`, nie meno
    (IANA meno sa na Windows bez ďalšej knižnice spoľahlivo zistiť nedá).
  - Riadok autora môže mať značky `[bot]`, `(edited)`, `(pinned)`, `(forwarded)`, `(system message, type N)`.
  - `[thread] "meno" N messages` pri správe, z ktorej vzniklo vlákno.
  - Embedy podľa typu: `[link]`, `[gif]`, `[image]`, `[video]`, `[embed]`. Rich embed (boti) má aj popis a polia,
    odsadené o 4 medzery. Ďalej `[sticker]`.
  - `<t:unix>` sa prepíše na lokálny čas a `</príkaz:id>` na `/príkaz`. `<@&id>` je vždy `@role:<id>`, mená rolí sa
    nesťahujú. Neznámy používateľ alebo kanál je `@user:<id>`, `#channel:<id>`.
  - Reply bez `referenced_message` je `reply-to (message not available)`. Citát má najviac 80 znakov.
  - Medzi správami nie je prázdny riadok (menej tokenov). Správa začína riadkom `[YYYY-MM-DD HH:MM]`.
- **Formát `json`:** jeden objekt `{from, to, last, truncated, channels: [...], messages: [...]}`.
  - `channels` má pri každom kanáli server, kanál, počet správ a súborov a `truncated`.
  - Správy majú schému zo 6.2, doplnené sú polia `type`, `stickers`, `forwarded` a `links[].description`.
  - V prílohách chýba `path` (až pri exporte). `thread` je zatiaľ vždy `null`.
  - `text` má prepísané mentions rovnako ako formát `text`.
  - V agent režime je JSON na jednom riadku, v human režime odsadený.
- **Human režim** (návrh presný vzhľad neopisoval): rovnaký layout ako `text`, s farbami a s prázdnym riadkom
  medzi správami. Dlhé riadky zalamuje terminál, nie Rich, aby URL ostali celé. Počas sťahovania beží spinner
  na stderr. Poznámka na konci pripomenie, že predvolené okno je 24 h.
- **Forwardy** (`message_snapshots` pri `message_reference.type 1`) sa zobrazia s textom a prílohami pôvodnej
  správy a značkou `(forwarded)`. Tvar je **[PREDPOKLAD]** (analýza, sekcia 4).
- **Viac kanálov:** nedostupný (`NO_ACCESS`) alebo neznámy (`NOT_FOUND`) kanál sa preskočí s varovaním. Keď sa
  nedá prečítať žiadny, koniec s kódom prvej chyby. Ostatné chyby ukončia celý beh.
- **Prázdna prvá strana** (`200 []`): poznámka na stderr, že pred koncom okna nie sú žiadne správy, alebo chýba
  právo `READ_MESSAGE_HISTORY` (agent ju vidí s `--verbose`). Keď kanál staršie správy má a v okne len nie sú,
  poznámka sa nevypíše. Chyby `403`/`404` sú v sekcii 9.

### 4.6 `config`

```
discoop config set default-server "VUT FIT"
discoop config set delay 1.0
discoop config get delay
discoop config unset delay
discoop config list
```
Uložené v `config.toml` v konfiguračnom adresári (sekcia 10).

**Implementované 2026-11-03:**
- **Kľúče:** `default-server` a `delay` (predvolene 1.0 s).
- **`default-server`** sa pri `set` vyhľadá ako server (meno alebo ID) a uloží sa jeho **ID**, takže
  premenovanie servera nastavenie nerozbije.
- **`export-dir`** pribudne spolu s exportom (`messages --out/--zip`).
- **Neznámy kľúč** alebo zlá hodnota skončí kódom `8`.

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
  Ďalšia možnosť je `refresh-urls` **[OVERENÉ]** (`{"attachment_urls": [...]}` → `{"refreshed_urls": [{original, refreshed}]}`).
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
  2. Aktívne vlákna: `threads/search?archived=false` pre každý kanál **[OVERENÉ]**. `GET /guilds/{id}/threads/active`
     je len pre botov (`403`, kód 20002). Doplnkový zdroj: správy v stiahnutom okne s objektom `thread`
     (flag 32), kde `thread.id == message.id`.
  3. Každé vlákno sa stiahne ako samostatný kanál cez `/messages` s tým istým časovým oknom.
- Vo výstupe je vlákno vnorené pod materským kanálom. Pri fóre je to post s tagmi (`applied_tags` → mená tagov).

## 9. Sťahovanie: stránkovanie, rate limit, chyby

**Časové okno:** dátumy sa prevedú na syntetické snowflake (`(ms − 1420070400000) << 22`).
- Bežné okno: od `--to` dozadu cez `before=<najstaršie_id>&limit=100` **[OVERENÉ: max 100]**, kým ID nie je staršie
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
- `403` na kanál s kódom `50001` (Missing Access) alebo `50013` (Missing Permissions): kanál sa preskočí
  s varovaním. Pri jedinom zadanom kanáli koniec s kódom `5`.
- `403` s iným kódom (`10008` z anti-abuse systému, `40333` z Cloudflare, …) **nie je „bez prístupu“**: koniec
  s kódom `1`, hláška obsahuje `message` z odpovede a rada je počkať a zvýšiť `delay`.
- `404` (`10003` Unknown Channel): kód `4` a rada `discoop channels --refresh`.
- `200 []` môže znamenať aj chýbajúce `READ_MESSAGE_HISTORY`. Odlíšiť sa to dá až výpočtom prístupu (rozhodnutie 9, odložené).
- Kódy chýb sú **[PREDPOKLAD]** podľa [analyzy/pristup-ku-kanalom.md](analyzy/pristup-ku-kanalom.md), sekcia 7.
  Implementované 2026-11-03 v `messages` (krok 2).

**Rozsah volaní:** nástroj nikdy nevolá `ack`, `science`, `metrics` ani nič, čo zapisuje.

## 10. Lokálne dáta

Adresáre určí `platformdirs` podľa OS:

| OS | Dáta (cache) | Konfigurácia |
|---|---|---|
| Windows | `%LOCALAPPDATA%\discoop\` | to isté |
| macOS | `~/Library/Application Support/discoop/` | to isté |
| Linux | `~/.local/share/discoop/` | `~/.config/discoop/` |

Obsah:
- `config.toml`: nastavenia.
- `cache.db`: SQLite s tabuľkami:
  - **teraz** (2026-11-03): `servers`, `channels` (typ, kategória, pozícia, téma) a `fetched` (kedy sa čo obnovilo).
    Normalizované mená sa počítajú v Pythone, kanálov je pár stoviek.
  - **neskôr**, so `messages`: `threads`, `users` (z `author` a `mentions`, na preklad `<@id>`) a
    `sync_state` (`channel_id`, `last_message_id`, `last_run`).
  - **Cache je jednorazová.** `login` aj `logout` ju zmažú a pri zmene schémy (`PRAGMA user_version`)
    sa postaví znova.
- **Token nie je v súbore.** Je v systémovom úložisku hesiel cez keyring (služba `discoop`):
  Windows Credential Manager, macOS Keychain alebo Linux Secret Service.
- **Linux bez Secret Service** (napr. server bez GUI): token ide do súboru `token` s právami `0600`
  a nástroj na to upozorní.

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
    auth.py           QR login (remote auth gateway), keyring, záložný login
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

**Stav 2026-11-03 (po kroku 2):** správy sú v týchto moduloch, mierne inak ako v strome vyššie:
- `snowflake.py`: čas ↔ snowflake, parsovanie `--from/--to`, okno,
- `scrape.py`: stránkovanie správ v okne (vlákna pribudnú v kroku 4),
- `normalize.py`: surová správa → `models.Message`, prepis mentions (nový modul),
- `models.py`: dataclasses pre správy pribudli k serverom a kanálom (namiesto `model.py`),
- `render/text.py`: formát `text` pre agentov aj Rich výstup pre človeka, jeden layout (namiesto `plain.py` a `human.py`),
- `render/jsonout.py`: formát `json`.

## 14. Postup implementácie

0. **Spike / prototyp** (2026-11-03: **hotové**. Login aj probe prešli, výsledky v analýzach):
   QR `login` + malý skript, ktorý overí body [PROTOTYP]:
   - QR login: či gateway vyžaduje `Origin`, či `remote-auth/login` pýta captchu, reálne rámce po naskenovaní,
   - `GET /users/@me/guilds` a `GET /guilds/{id}/channels` s user tokenom,
   - `limit=100`,
   - REST cesta k aktívnym vláknam,
   - tvar `429` a `refresh-urls`.

   Spúšťa ho používateľ, pretože beží na jeho účte. Výsledky sa zapíšu do analýzy.
1. **Jadro:** config, cache, API klient, `servers`, `channels`, `resolve`, `status`.
2. **`messages`** → `text`/`json` do konzoly, časové okno, `--last` (2026-11-03: **hotové**, čaká na test
   používateľa, podrobnosti v 4.5).
3. **Prílohy** + `--out` / `--zip` + manifest.
4. **Vlákna a fóra**, `threads`.
5. **Human režim** (Rich), `agent-guide`, help texty.
6. **`--since-last`**, deduplikácia.

**Testy:** unit testy (snowflake, parsovanie času, resolve, renderery) nad anonymizovanými fixtures, bez živého API.

## 15. Otvorené rozhodnutia

| # | Otázka | Návrh |
|---|---|---|
| 1 | Jazyk | Python: **prijaté** ([ADR 0006](rozhodnutia/0006-python.md)) |
| 2 | Názov príkazu | `discoop`: **prijaté** ([ADR 0004](rozhodnutia/0004-nazov-discoop.md)) |
| 3 | Jazyk helpu a hlášok | angličtina: **prijaté** ([ADR 0007](rozhodnutia/0007-anglictina-v-nastroji.md)) |
| 4 | Vlákna predvolene | zapnuté: **prijaté** ([ADR 0011](rozhodnutia/0011-predvolene-spravanie-messages.md)) |
| 5 | Predvolené časové okno | 24 h, celá história len cez `--from all`: **prijaté** ([ADR 0011](rozhodnutia/0011-predvolene-spravanie-messages.md)) |
| 6 | Predvolený formát v agent režime | `text` (JSON cez `--format json`): **prijaté** ([ADR 0011](rozhodnutia/0011-predvolene-spravanie-messages.md)) |
| 7 | Záložný login | **prijaté** ([ADR 0008](rozhodnutia/0008-zalozny-login-token.md)): `discoop login --token`, token zo skrytého promptu alebo stdin, nie z argumentu, aby neostal v histórii shellu. Prihlásenie cez prehliadač nie vo v1 (ťažká závislosť na každom OS). Email a heslo nie (captcha, práca s heslom) |
| 9 | Kanály bez prístupu v `channels` | **Odložené** (2026-11-03, nízka priorita): používateľ to nepovažuje za dôležité a Discord podľa changelogu 2026-08-12 plánuje, že REST prestane vracať nedostupné kanály aj používateľom. Podklady: [analyzy/pristup-ku-kanalom.md](analyzy/pristup-ku-kanalom.md).<br>Pôvodný návrh: vypočítať prístup (`VIEW_CHANNEL`, pri čítaní aj `READ_MESSAGE_HISTORY`):<br>• základné práva servera z `permissions` v `/users/@me/guilds`, vlastník servera má všetky práva,<br>• prepisy `permission_overwrites` pre @everyone, roly používateľa a jeho samotného.<br>Roly používateľa treba získať (`GET /users/@me/guilds/{id}/member`, overiť). Nedostupné kanály predvolene skryť, `--include-hidden` ich ukáže |
| 8 | `login` v agent režime | **prijaté** ([ADR 0009](rozhodnutia/0009-login-v-agent-rezime.md)): odmietnuť s kódom `2` a pokynom „požiadaj používateľa, nech spustí `discoop login`“. Prihlásenie potrebuje človeka s mobilom a QR je citlivý |

**Nápady na neskôr (v2):** lokálny archív všetkých správ v SQLite s fulltextom, `discoop sync` pre zoznam
sledovaných kanálov, zhlukovanie po sebe idúcich správ jedného autora (menej tokenov), filter `--author`,
`--has file`.
