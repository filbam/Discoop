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
| Inštalácia | `uv tool install git+https://github.com/filbam/Discoop` | príkaz `discoop` dostupný globálne na Windows, Linuxe aj macOS ([ADR 0015](rozhodnutia/0015-verejne-repo-a-instalacia.md)) |

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
discoop ui                    interaktívne terminálové rozhranie (TUI)
discoop doctor                diagnostika prostredia, tokenu a priečinka exportov
discoop profiles              správa pomenovaných profilov nastavení
```

**Globálne prepínače:** `--plain` (alias `--agent`), `--human`, `--quiet`, `--verbose`, `--debug`, `--log FILE`.

Prepínače `--debug` a `--log FILE` (prípadne premenné prostredia `DISCOOP_DEBUG=1` a `DISCOOP_LOG=cesta`) zapínajú voliteľné štruktúrované diagnostické logovanie na stderr, resp. do súboru ([ADR 0018](rozhodnutia/0018-logovanie.md)). Vďaka hoistingu prepínačov fungujú pred aj za podpríkazom (napr. `discoop messages --debug ...`). Pri `--debug` sa automaticky vypne Rich animovaný spinner, aby logy nepoškodzovali terminál. Príkaz `discoop ui --debug` je odmietnutý s kódom 8 (UI plne ovláda obrazovku), ale `discoop ui --log FILE` je povolené.

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
- **Strojový výstup:** `discoop status [--format text|json]` umožňuje získať stav prihlásenia ako štruktúrovaný JSON objekt na stdout.

### 4.2 `servers`

```
discoop servers [--refresh] [--format text|json]
```
Číta z cache. Obnoví ju `--refresh` alebo automaticky, ak je cache prázdna.
Zdroj: `GET /users/@me/guilds?with_counts=true` **[OVERENÉ]**. Stĺpce: meno, ID, počet členov (`approximate_member_count`).

**Implementované 2026-11-03:**
- Human režim vypíše tabuľku. Agent režim vypíše hlavičku `id members name` a riadky, kde sú stĺpce oddelené tabulátorom,
  zoradené podľa mena.
- Prepínač `--format text|json`: formát `json` vráti strojovo čitateľné pole objektov `[{"id": "...", "name": "...", "member_count": ...}]` na stdout. Poznámky o cache idú na stderr.
- Ak sa použila cache, na stderr pribudne poznámka s jej vekom (agent ju vidí len s `--verbose`).

### 4.3 `channels`

```
discoop channels [-s SERVER] [--refresh] [--type text,forum,...] [--flat] [--format text|json]
```
- **Poradie** je ako v sidebare Discordu: najprv kanály bez kategórie, potom kategórie podľa `position`.
  V kategórii sú textové kanály nad hlasovými, potom podľa `position` a nakoniec podľa ID.
- **Human režim:** strom podľa kategórií. `--flat` dá tabuľku.
- **Agent režim:** vždy riadky so stĺpcami `id type category name` oddelenými tabulátorom.
- **JSON formát (`--format json`):** vždy plochý zoznam objektov `{id, name, type, type_name, category, position}` na stdout (rešpektuje filter `--type`, nie strom). Poznámky o cache idú na stderr.
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
discoop threads -s SERVER -c CHANNEL [--from WHEN] [--to WHEN] [--refresh] [--format text|json]
```
Príkaz na prehľadný výpis vlákien kanála a príspevkov vo fórach bez sťahovania správ ([ADR 0019](rozhodnutia/0019-vlakna.md)):
- **Podporované kanály:** fórum (typ 15), mediálny kanál (typ 16), textový kanál (typ 0) a oznamovací kanál (typ 5). Ak zadaný kanál nepodporuje vlákna, príkaz skončí s kódom 8 (`BAD_ARGS`).
- **Časové okno:** predvolené okno je 30 dní (`--from 30d`), celá história sa zobrazí cez `--from all`.
- **Formáty:**
  - *Human režim:* Rich tabuľka so stĺpcami `ID`, `Archived`, `Messages`, `Last activity` (v miestnom čase), `Tags` (názvy tagov vo fóre) a `Name`.
  - *Plain režim:* riadky oddelené tabulátorom (TSV) s hlavičkou.
  - *JSON formát (`--format json`):* pole JSON objektov `{id, name, parent_id, type, archived, locked, message_count, created, last_activity, tags}`.

### 4.5 `messages`

```
discoop messages -c CHANNEL [-c CHANNEL ...] [-s SERVER]
                 [--from WHEN] [--to WHEN] | [--last N] | [--since-last]
                 [--threads/--no-threads] [--include-system]
                 [--format text|md|json|jsonl] [--raw]
                 [--print] [--out DIR] [--zip FILE] [--no-files]
                 [--max-messages N] [--delay SEC]
                 [--safe | --fast] [--progress-json]
                 [--max-tokens N] [--profile NAME] [--save-profile NAME]
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

**Implementované (kroky 2–6, stav k 2026-11-04):**
- **Prepínače:** `-c` (opakovateľný), `-s`, `--from`, `--to`, `--last`, `--since-last`, `--threads/--no-threads`,
  `--format text|md|json|jsonl`, `--include-system`, `--max-messages`, `--out DIR`, `--zip FILE`, `--print`,
  `--no-files`, `--max-file-size MB`, `--safe`, `--fast`, `--delay SEC`, `--progress-json`,
  `--max-tokens N`, `--profile NAME`, `--save-profile NAME`.
- **Odolný export po kanáloch, staging `.partial` a kód 9 ([ADR 0017](rozhodnutia/0017-spolahlivy-export-a-ciastocny-uspech.md)):**
  - Trieda `ExportWriter` (`src/discoop/export.py`) zapisuje priebežne po kanáloch do staging priečinka `<cieľ>.partial` (pri zipe `<názov>.zip.partial`), bez držania celého exportu v pamäti.
  - Hotový export sa publikuje až po `close(complete=True)`. Predchádzajúci hotový export sa nikdy neprepíše prerušeným behom.
  - Automatická obnova (resume): opätovné spustenie rovnakého príkazu automaticky nadviaže na rozpracovaný beh a preskočí už hotové kanály a ich prílohy. Relatívne časové okná sa počítajú od pôvodného času `created`.
  - Kombinácia `--print` s obnovou, kde už sú hotové kanály, je odmietnutá s kódom 8 ešte pred sťahovaním správ.
  - Nový kód ukončenia `9` (`ExitCode.PARTIAL`) pri preskočení nedostupného kanála (403/404), zlyhanej prílohe alebo chybe vlákna. Súbory vynechané cez `--no-files` alebo `--max-file-size` kód 9 nevyvolávajú.
- **Plná podpora vlákien a fór ([ADR 0019](rozhodnutia/0019-vlakna.md)):**
  - Predvolene zapnuté (`request.threads = True`), vypnutie cez `--no-threads`.
  - Fóra (typ 15) a mediálne kanály (typ 16) sú plnohodnotnými cieľmi `messages` (sťahujú svoje vlákna). Fórum s `--no-threads` je odmietnuté kódom 8. V TUI sa vyberajú ako ostatné kanály, pri Threads = no sa štart odmietne už vo formulári (bez volania Discordu).
  - Sťahovanie aktívnych aj archivovaných vlákien cez `threads/search` s `limit=25`, stránkovaním podľa offsetu a detekciou konca prázdnou/neúplnou stranou (podľa [docs/analyzy/probe-vlakien-2026-11-04.md](analyzy/probe-vlakien-2026-11-04.md)).
  - Limity `--max-messages` a `--last N` platia nezávisle na kanál a na každé vlákno.
- **Prírastkové sťahovanie `--since-last` ([ADR 0020](rozhodnutia/0020-since-last.md)):**
  - Sťahuje len správy novšie ako posledný úspešný export. Stav sa ukladá do `sync-state.json` viazaného na ID používateľského účtu v `paths.data_dir()` nezávisle od `cache.db` (prežije `clear_cache`).
  - Exkluzívna spodná hranica snowflake `saved_id + 1` chráni pred duplikátmi. Stav sa posúva až po úspešnom dokončení exportu kanála.
  - Preskakovanie neaktívnych kanálov: zoznam kanálov servera sa pri `--since-last` obnoví a ak má kanál uložený stav a `Channel.last_message_id <= saved_id`, v kanáli samotnom nič nepribudlo:
    - kanál, ktorý nemôže mať vlákna, alebo akýkoľvek kanál pri `--no-threads`: preskočí sa úplne (0 requestov),
    - textový alebo oznamovací kanál so zapnutými vláknami: jeho vlastné správy sa nesťahujú, ale zoznam jeho vlákien sa načíta a vlákna sa stiahnu ako inak,
    - fórum a media kanál sa nepreskakujú nikdy.
    - `[PREDPOKLAD]` `last_message_id` textového kanála je spoľahlivé (posunie sa s každou novou správou): potvrdené len na dvoch vzorkách z probe vlákien.
  - Po prerušenom a obnovenom behu si kanály uložené prerušeným behom ponechajú starý stav a pri najbližšom `--since-last` sa stiahnu znova (duplicity, nič sa nestratí). Beh na to upozorní poznámkou.
  - Preventívna kontrola voľného miesta na disku pred stiahnutím príloh každého kanála: počíta sa len to, čo sa naozaj stiahne (`ExportWriter.bytes_to_download`), a odmietne sa s kódom 1, ak nezostane aspoň 50 MB bezpečnostná rezerva (`service._check_disk_space`).
- **Delenie na tokeny a odhad tokenov:**
  - Prepínač `--max-tokens N` (s `--out` aj `--zip`, bez nich kód 8 pred volaním API) rozdelí `messages.md` na očíslované časti `parts/part-NNN.md` s hlavičkou `<!-- discoop part X of Y -->`. Delí sa len na hraniciach správ a nadpisov kanálov a vlákien: správa s riadkom `# Nadpis` ostane celá. Obmedzenie: riadok v tele správy, ktorý presne vyzerá ako `[2026-01-01 10:00] x` hneď za prázdnym riadkom, sa od hlavičky správy odlíšiť nedá. Správa väčšia ako limit ide sama do jednej časti s varovaním.
  - Časti vznikajú až pri dokončení exportu v staging priečinku a publikujú sa spolu s ostatnými súbormi (do priečinka aj do zipu), takže pád pred koncom nenechá v cieli žiadne `parts/`. Pri opakovanom exporte do priečinka sa staré `parts/part-*.md` nahradia novými (alebo zmažú, ak nové nie sú). Časti nie sú v manifeste a `--max-tokens` nie je súčasťou odtlačku obnovy.
  - V súhrne exportu sa zobrazuje riadok s odhadom tokenov `tokens: ~... (estimate, about 4 characters per token)`.
- **Pomenované profily v CLI:**
  - Prepínače `--profile NAME` (načítanie s možnosťou prebitia) a `--save-profile NAME` (uloženie nastavení pred spustením), príkazy `discoop profiles` a `discoop profiles delete NAME`.
- **Priebeh a odhad času (`--progress-json`, percentá, ETA):**
  - Prepínač `--progress-json` potláča spinner a textové poznámky a na stderr zapisuje jeden JSON objekt na riadok (JSONL) pre udalosti `channel_start`, `page`, `pause`, `channel_done`, `skipped`, `warning`. Obsahuje polia `event`, `index`, `total`, `channel_id`, `fraction`, `eta_seconds`, `seconds`, `reason` (bez textov správ a mien).
  - Pri bežnom behu (v human spinneri aj v plain režime s `-v`) sa na základe snowflake ID priebežne zobrazujú percentá dokončenia a odhad zostávajúceho času (napr. `~42%, about 3 min left`).
- **Režimy sťahovania (`--safe` vs `--fast`):**
  - `--safe` (predvolený): bezpečný režim imitujúci bežného používateľa v prehliadači. Stránkovanie po 25 správach, náhodný rozptyl (jitter) 2.0 až 4.5 s medzi API requestami, čítacie pauzy 8.0 až 15.0 s každých 5 až 8 requestov, pauza 3.0 až 6.0 s pri prepnutí kanála a 1.0 až 3.0 s medzi sťahovaním príloh z CDN.
  - `--fast`: rýchly dávkový režim vhodný pre exporty s limitom 100 správ na request, pevnou pauzou podľa `--delay` (alebo z konfigurácie, predvolene 1.0 s), bez dodatočných čítacích pauz a bez pauz medzi súbormi/kanálmi.
  - `--safe` a `--fast` sa navzájom vylučujú. Nastaviť sa dajú aj trvalo cez `discoop config set mode safe|fast`.
- **Výber kanálov:**
  - `-c` berie meno, ID alebo glob vzor. Mená a vzory sa hľadajú v kanáloch servera z `-s` alebo `default-server`
    a **preskakujú kategórie**, takže kategória `general` a kanál `general` sa nebijú.
  - **Holé ID bez `-s`** sa hľadá v cache všetkých serverov. Ak tam nie je, nástroj zavolá `GET /channels/{id}`
    **[PREDPOKLAD]**, z `guild_id` zistí server a stiahne jeho zoznam kanálov. `default-server` sa pri ID nepoužije.
  - Čítajú sa textové, hlasové a stage kanály, oznamy a vlákna zadané cez ID. Fórum (typ 15) a media kanál (typ 16)
    sú tiež platné ciele, sťahujú len svoje vlákna ([ADR 0019](rozhodnutia/0019-vlakna.md)). Kategória skončí
    kódom `8`. Vzor, ktorý nájde len kanály, z ktorých sa nedá čítať (napr. kategórie), skončí kódom `4`.
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
  - Príloha je `[file] meno veľkosť URL` (alebo lokálna cesta pri exporte s `--print`).
  - Hlavička má `threads: N (M messages)` len vtedy, keď kanál má vlákna ([ADR 0019](rozhodnutia/0019-vlakna.md)). Zóna je ako posun `UTC+01:00`, nie meno
    (IANA meno sa na Windows bez ďalšej knižnice spoľahlivo zistiť nedá).
  - Riadok autora môže mať značky `[bot]`, `(edited)`, `(pinned)`, `(forwarded)`, `(system message, type N)`.
  - `[thread] "meno" N messages` pri správe, z ktorej vzniklo vlákno.
  - Embedy podľa typu: `[link]`, `[gif]`, `[image]`, `[video]`, `[embed]`. Rich embed (boti) má aj popis a polia,
    odsadené o 4 medzery. Ďalej `[sticker]`.
  - **Embed nezopakuje URL, ktorú správa už ukazuje** (v texte alebo v predchádzajúcom embede). Ostane len značka
    s titulkom, napr. `[link] "Studium"` pod URL v texte. Embed bez titulku a popisu sa vynechá celý, napr. GIF
    poslaný ako holá URL. JSON má embedy celé.
  - **`[reactions]` je jeden riadok** so všetkými reakciami správy. Zápis `🔥5 (2 super)` znamená 5 reakcií, z toho 2 super.
  - **Prázdne riadky na začiatku a na konci textu** správy aj popisu rich embedu sa orežú, `\r\n` sa zmení na `\n`.
  - `<t:unix>` sa prepíše na lokálny čas a `</príkaz:id>` na `/príkaz`. `<@&id>` je vždy `@role:<id>`.
  - Reply bez `referenced_message` je `reply-to (message not available)`. Citát má najviac 80 znakov.
  - Medzi správami nie je prázdny riadok (menej tokenov). Správa začína riadkom `[YYYY-MM-DD HH:MM]`.
- **Formát `md`:** Markdown s hlavičkou `# server / #kanál`, zoznamom detailov (`- `) a správami oddelenými prázdnym riadkom. Obrázky (`image/*`) sa vkladajú priamo ako `![meno](cesta) veľkosť`, ostatné súbory ako odkazy `[meno](cesta) veľkosť`. V `channels/<kanál>.md` majú cesty prefix `../files/...`.
- **Formát `json`:** jeden objekt `{from, to, last, truncated, channels: [...], messages: [...]}`.
- **Formát `jsonl`:** jeden riadok JSON správy podľa schémy zo sekcie 6.2 (bez hlavičky, tá je v manifeste).
- **Export (`--out`, `--zip`):**
  - Vytvorí štruktúru: `manifest.json`, `messages.md`, `messages.jsonl`, `channels/<meno>.md` a `files/<kanál>/<attachment_id>_<meno>`. S `--max-tokens N` aj `parts/part-NNN.md`.
  - Predvolene vypíše do konzoly súhrn. `--print` vypíše správy na stdout s relatívnymi cestami k lokálnym súborom a súhrn ide na stderr.
  - `--no-files` preskočí sťahovanie príloh (v manifeste ako `skipped`).
  - `--max-file-size` (predvolene 50 MB, `0` = bez limitu) preskočí väčšie súbory.

### 4.6 `config`

```
discoop config set default-server "VUT FIT"
discoop config set delay 1.0
discoop config set export-dir "exports"
discoop config set mode safe
discoop config get delay
discoop config unset delay
discoop config list [--format text|json]
```
Uložené v `config.toml` v konfiguračnom adresári (sekcia 10).

**Implementované 2026-11-03:**
- **Kľúče:** `default-server`, `delay` (predvolene 1.0 s), `export-dir` a `mode` (hodnoty `safe` alebo `fast`, predvolene `safe`).
- **`mode`** (pridané pre bezpečné sťahovanie): určuje predvolený režim sťahovania (`safe` alebo `fast`).
- **`default-server`** sa pri `set` vyhľadá ako server (meno alebo ID) a uloží sa jeho **ID**, takže
  premenovanie servera nastavenie nerozbije.
- **`export-dir`** (pridané v kroku 3): priečinok pre relatívne cesty `--out`/`--zip`. Ukladá sa ako absolútna cesta.
  V TUI je to predvolený priečinok exportov, bez neho `Documents/discoop` ([ADR 0016](rozhodnutia/0016-predvoleny-priecinok-exportov-v-tui.md)).
  CLI bez neho ostáva pri aktuálnom priečinku.
- **Strojový výstup:** `discoop config list --format json` vráti konfiguráciu ako JSON objekt na stdout.
- **Neznámy kľúč** alebo zlá hodnota skončí kódom `8`.

### 4.7 `agent-guide`

```
discoop agent-guide
```

Vypíše kompaktnú referenciu pre AI na ~1 obrazovku v čistom texte bez ANSI sekvencií:
- odporúčaný pracovný postup (`status` → `servers` → `channels` → `messages`),
- kompletnú tabuľku exit kódov vytvorenú priamo z výčtu `ExitCode`,
- dynamický zoznam všetkých registrovaných príkazov a podpríkazov z Typer aplikácie s ich jednoriadkovými popismi.
Odkaz na `discoop agent-guide` je uvedený priamo v sekcii `NOTE FOR AI AGENTS` v `discoop --help`.

### 4.10 `profiles`

```
discoop profiles [--format text|json]
discoop profiles delete NAME
```

Správa pomenovaných profilov nastavení v `<config_dir>/profiles.json`:
- `discoop profiles`: zoznam profilov (v human a plain režime názvy profilov, v `--format json` JSON pole názvov).
- `discoop profiles delete NAME`: zmaže profil zo súboru (ak neexistuje, skončí s kódom 8 a návrhom podobných mien).
- Profily ukladajú parametre `server`, `channels`, `from`, `to`, `last`, `mode`.

### 4.8 `ui`

```
discoop ui
discoop --ui
```

Interaktívne terminálové rozhranie (TUI) postavené na knižnici Textual (P16, P17, [ADR 0013](rozhodnutia/0013-tui-a-spolocna-vrstva.md)). Slúži ako vizuálna nadstavba pre `--human` režim. V `--plain` režime alebo pri nespustení v termináli (`not sys.stdout.isatty()`) skončí kódom `8`.

**Rozloženie ([ADR 0014](rozhodnutia/0014-tui-klavesnica-jeden-strom.md), nahrádza tri stĺpce z ADR 0013):**
- **Jeden strom** servery → kategórie → kanály, všetko predvolene zbalené. Vpravo panel *Export* (zoznam výberu a formulár: časové okno, režim `safe`/`fast`, cieľ `folder`/`zip`/`preview`, formát, prílohy, Max MB, Start).
- Dole log (vždy viditeľný), pod ním riadok s ekvivalentným CLI príkazom `discoop messages ...` a Footer s klávesmi (klikateľný myšou). V úzkom okne (< 95 stĺpcov) sa ukazuje jeden panel naraz.
- **Vzhľad:** téma Textual `ansi-dark` (farby terminálu, Ctrl+P mení tému), CSS bez hex farieb, ovládacie prvky vysoké jeden riadok (`compact=True`), bez emoji a veľkých tlačidiel. Pri Target=preview sú skryté Attachments a Max MB. Pri QR sa formulár nahradí kódom (pod 27 riadkov zmizne rámik a Footer, aby sa QR zmestil do 80×24).
- **Klávesy:** primárne klávesnica, myš je doplnok. Úplná tabuľka (šípky, Space, Enter, Tab, `/`, `e`, `x`/`X`, `a`, `r`, `R`, `L`, `F5`, Esc, `c`, F1–F3, `q`) je v ADR 0014. Klávesy `P`, `p` a `o` (profily a otvorenie priečinka exportu) a prípony riadkov kanálov v strome sú v jeho sekcii „Doplnenie 2026-11-04“.

**Priečinok a názov exportu (P21, P23, [ADR 0016](rozhodnutia/0016-predvoleny-priecinok-exportov-v-tui.md)):**
- Formulár má pri Target=folder a zip dva samostatné riadky v tomto poradí: `Folder` a `Name` (obidva predvolene prázdne, pri preview skryté). `Name` nikdy nie je cesta.
- **`Folder`:** prázdny = predvolený priečinok. Ten je `export-dir` z configu, inak `discoop` v Dokumentoch používateľa (`platformdirs.user_documents_dir()`, na Windows, Linuxe aj macOS rovnakým kódom, nič sa nevytvára pri zobrazení, priečinok vznikne pri exporte). `~` sa rozbalí, absolútna cesta sa použije ako je, relatívna leží vo vnútri predvoleného priečinka. Placeholder ukazuje skutočný predvolený priečinok, dlhý sa skráti zľava (`TailInput`), aby ostal jeho koniec.
- **`Name`:** prázdny = `discord-export-<dátum a čas>` (`YYYY-MMDD-HHMM`, miestny čas, napr. `discord-export-2026-1104-0108`), zafixuje sa pri `F5`. Zadaný názov sa prečistí cez `safe_name` (lomky a neplatné znaky sa nahradia `_`), takže nikdy nevyjde z priečinka. Placeholder ukazuje aktuálny názov. Placeholdery a riadok s CLI príkazom sa obnovujú každých 30 s.
- Kolízia automatického názvu v tej istej minúte: `-2`, `-3`. Názov zadaný používateľom kolíziu nerieši, opakovaný export do neho pokračuje. Zip dostane príponu `.zip` (nie `.zip.zip`). Pri viacerých úlohách platia podpriečinky `<názov>/01-7d` alebo archívy `<názov>-01-7d.zip` ako vyššie.
- Cesty `--out`/`--zip` v riadku s CLI príkazom a v požiadavke sú absolútne a s lomkami (`Path.as_posix()`), takže ich Windows prijme a `shlex.join` ich nemusí citovať. Log po štarte ukáže skutočnú cestu (`Saving to ...`).
- Predvolený priečinok mení trvalo Settings (`F2`, `Export folder` = `export-dir`), pre jeden export pole `Folder`. CLI sa nemení, relatívne `--out`/`--zip` ostávajú k aktuálnemu priečinku alebo `export-dir`.

**Načítanie dát a tempovanie:**
- Pohyb kurzorom nikdy nevolá Discord. Sieť volá len explicitná akcia: → alebo Enter na nenačítanom serveri, `r`, `R`, `L`, `F5`.
- Naraz beží najviac jedna sieťová operácia. `L` (všetky servery) beží v `safe` tempe.
- Esc zastaví operáciu a ukončí pauzy okamžite (prerušiteľný `CancelToken`), už načítané dáta ostanú.
- Výber nemení kurzor ani rozbalenie stromu. Po zmene prihlásenia sa výber vyčistí.

**Úlohy, perzistentný stav a profily:**
- **Perzistentný stav TUI (`tui-state.json`):** uložený v konfiguračnom adresári a kľúčovaný ID používateľského účtu (`tuistate.py`). Pri štarte automaticky obnoví vybrané kanály podľa serverov, globálne aj vlastné časové okná, režim `safe`/`fast`, polia `Folder`/`Name`, prepínač vlákien a dátumy posledných exportov kanálov. Obnovuje sa voči kanálom z cache, ID, ktoré tam nie sú, zahodí. Ukladá sa až po načítaní uloženého stavu účtu (skorší zápis by ho prepísal predvolenými hodnotami). Zlyhanie disku TUI nezhodí (varovanie v logu). Zápis nie je oneskorený (debounce): beží pri každej zmene výberu alebo formulára.
- **Prepínač Threads:** vo formulári exportu umožňuje zapnúť alebo vypnúť sťahovanie vlákien vybraných kanálov (premieta sa do ekvivalentného príkazu v spodnej lište).
- **Profily v TUI:** `P` (veľké) otvorí modálne okno na uloženie aktuálneho výberu, časového okna a režimu ako profilu, `p` (malé) otvorí modálne okno na načítanie uloženého profilu. `L` s profilmi nesúvisí, načíta kanály všetkých serverov. Profily sú v rovnakom `profiles.json` ako profily z CLI. Ručne upravený profil so zlými typmi hodnôt TUI toleruje.
- **Otvorenie priečinka exportu:** klávesová skratka `o` otvorí priečinok posledného exportu (pri zipe priečinok, v ktorom zip leží) v predvolenom prieskumníkovi systému (`os.startfile` na Windows, `xdg-open` na Linuxe, `open` na macOS). Je aktívna po dokončenom exporte a nie počas behu úlohy. Náhľad nič neukladá, preto sa nepočíta.
- **Prípony riadkov kanálov v strome:** každý kanál má stlmenú príponu zarovnanú doprava: čas od poslednej aktivity (`now`, `5m`, `3h`, `2d`, `4mo`, `1y`, z `Channel.last_message_id`) a pri kanáli, ktorý sa z tohto účtu už exportoval, dátum posledného exportu (`exp 11-03`, miestny dátum, s rokom, ak je z iného roka). V úzkom riadku vypadne najprv dátum exportu, potom aktivita, názov kanála sa nikdy nekráti. Obnovujú sa po exporte, po obnovení uloženého stavu a každých 60 s. Dátum exportu sa pri náhľade nezapisuje. Funkcie `format_activity` a `format_last_exported` sú v `tuistate.py`, vykreslenie v `ChannelTree` (`widgets.py`).
- **Progres s percentami a ETA:** počas sťahovania sa zobrazujú percentá dokončenia a odhad zostávajúceho času podľa snowflake ID (`progress.py`).
- Kanálu možno nastaviť vlastné časové okno (`e`); kanál sa tým aj vyberie. Kanály s rovnakým oknom tvoria jednu úlohu; pri viacerých úlohách sa výstupy ukladajú do podpriečinkov (`cieľ/01-7d/`, ...) alebo očíslovaných archívov (`cieľ-01-7d.zip`).
- Zhrnutie behu uvádza kanály, správy, preskočené, orezané a stav príloh. Po prerušení alebo čiastočnom výsledku zafixuje názov exportu v poli `Name`, takže stlačenie `F5` automaticky nadviaže na rozpracovaný export.

**Dialógy a Help:**
- Help (`F1` / `?`): ovládanie podľa ADR 0014 a živý výpis `discoop --help` vrátane podpríkazov z Typer aplikácie. Settings (`F2`), Login (`F3`, QR alebo token), Preview a časové okno majú rovnaký vzhľad ako hlavná obrazovka. Token sa ukladá až po overení.

**Fóra a media kanály v TUI (2026-11-04):** vyberajú sa ako ostatné kanály (výber berie `MESSAGE_TYPES` aj `FORUM_TYPES`; kategória sa nevyberá, jej výber vyberie jej kanály). Ich príspevky sú vlákna, preto pri Threads = no a vybranom fóre formulár ukáže varovanie a `F5` štart odmietne hláškou ešte pred prvým volaním Discordu (služba by to odmietla s kódom 8). Overené len testami s falošným Discordom (`tests/test_tui_forums.py`).

**Známe obmedzenia:** TUI nemá `--since-last` ani `--max-tokens`; Esc počas bežiacej HTTP požiadavky zaberie až po jej skončení (timeout 20 s); pauzy pri opakovaní sťahovania príloh sa nedajú prerušiť hneď; v šírke 80 stĺpcov sa Footer nezmestí celý; CLI príkaz má vždy `--delay` z configu. Beh v skutočnom termináli a na reálnom účte zatiaľ neoverený.

### 4.9 `doctor`

```
discoop doctor
```

Diagnostický príkaz na overenie behového prostredia, spojenia a priečinka exportov:
- **Kontroluje 6 bodov:**
  - `login`: prihlásenie cez `GET /users/@me` (`api.get_me()`),
  - `network`: dostupnosť Discord API (rozlíši sieťovú chybu od neplatného tokenu; ak používateľ nie je prihlásený, je `skipped`),
  - `export_dir`: zapisovateľnosť priečinka exportov (`export-dir` z configu, inak aktuálny priečinok) cez `os.access` na najbližšieho existujúceho rodiča (nič nevytvára),
  - `disk_space`: voľné miesto cez `shutil.disk_usage` (FAIL pod 100 MB, inak OK s veľkosťou v MB),
  - `cache`: vek cache (`servers`),
  - `version`: verzia nástroja (`__version__`).
- **Výstup:**
  - v human režime Rich tabuľka (`check`, `status`, `detail`),
  - v plain režime (`--plain`) riadky oddelené tabulátorom `check<TAB>OK|FAIL<TAB>detail`.
- **Exit kód:** exit kód prvého zlyhaného bodu (`AUTH_REQUIRED` 2, `NETWORK` 7, inak `ERROR` 1), pri úspechu 0.

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

**Chýbajúce meno:** ak sa meno v cache nenájde, nástroj raz automaticky obnoví zoznam a skúsi to znova. Ak sa nenájde ani potom (chyba `NotFoundError`), nástroj cez `difflib.get_close_matches(..., n=3, cutoff=0.6)` navrhne až 3 najbližšie podobné názvy do nápovedy v chybovej správe (`Did you mean: ...?`).

## 6. Výstupy

### 6.1 Režimy

| | `--human` | `--plain` (Plain mode) |
|---|---|---|
| Kedy | predvolený v termináli | `--plain`, `--agent`, `DISCOOP_PLAIN=1`, `DISCOOP_AGENT=1`, alebo keď stdout nie je terminál |
| Farby, tabuľky, stromy | áno (Rich) | nie (čistý text bez farieb a grafiky) |
| Progress | progress bary | nič; s `--verbose` jednoduché riadky na stderr |
| Chyby | farebný panel s radou | `ERROR <KÓD>: <správa>` + `HINT: <čo robiť>` na stderr |
| Interaktívne otázky | len pri `login` | nikdy |

**Dáta idú vždy na stdout, všetko ostatné na stderr.** Skript alebo agent si teda môže výstup bezpečne presmerovať.

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
| (nič) / `--print` | konzola | len názov a URL (URL vyprší o 12 až 24 h; pri exporte lokálna cesta) |
| `--out DIR` | priečinok | stiahnuté (vypnúť cez `--no-files`) |
| `--zip FILE` | zip | stiahnuté (vypnúť cez `--no-files`) |

**Štruktúra exportu** (rovnaká pre priečinok aj zip):
```
vutfit_2026-11-03_1200/
  manifest.json            parametre behu, čas, počty, verzia nástroja, truncated, zoznam príloh so stavom
  messages.md              všetky kanály pre človeka/AI (sekcia na kanál, vlákna vnorené)
  messages.jsonl           štruktúrované dáta (jedno JSON posolstvo na riadok)
  channels/
    isc-public.md          ten istý obsah rozdelený po kanáloch
  files/
    isc-public/<attachment_id>_<filename>
  parts/
    part-001.md            len s --max-tokens N: messages.md rozdelený na časti (nie sú v manifeste)
```
Cesty k prílohám v `.md` a `.jsonl` sú relatívne (`files/...`). V `channels/*.md` majú predponu `../files/...`.

**Pravidlá exportu a zvolené defaulty (krok 3):**
- **Ochrana cieľa:** cieľový priečinok alebo zip nesmie prepísať existujúce súbory, ktoré nepochádzajú z discoop exportu (kontrola prítomnosti `manifest.json` s `"tool": "discoop"`). Neplatný cieľ skončí kódom `8` ešte pred dotazom na Discord.
- **Opakovaný export:** do existujúceho priečinka alebo zipu sa súbory so zhodným `attachment_id` a veľkosťou znova nesťahujú (`present`).
- **Atomický zápis po kanáloch a staging priečinok `<cieľ>.partial` ([ADR 0017](rozhodnutia/0017-spolahlivy-export-a-ciastocny-uspech.md)):**
  - `ExportWriter` zapisuje správy a súbory priebežne kanál po kanáli priamo do `<cieľ>.partial` (pri zipe `<názov>.zip.partial`).
  - Publikovanie do cieľového priečinka alebo súboru prebehne atomicky až pri `close(complete=True)`. Starší hotový export sa nikdy neprepíše ani nepoškodí prerušeným behom.
  - Súbory z CDN sa sťahujú s príponou `.part` a premenujú sa po úspešnom stiahnutí.
- **Automatická obnova (resume):**
  - Ak pri spustení exportu existuje rozpracovaný `<cieľ>.partial` a jeho odtlačok (`request_fingerprint`) zodpovedá požiadavke, príkaz automaticky preskočí hotové kanály a ich prílohy a pokračuje v sťahovaní zvyšných kanálov. Odtlačok zahŕňa aj `threads` a `since_last`: prerušený export s vláknami nepokračuje beh s `--no-threads` a normálny beh nenadviaže na `--since-last` (a opačne), začne odznova. Režim sťahovania a `--max-tokens` odtlačok nemenia.
  - Relatívne okná sa počítajú od pôvodného času vzniku behu (`Resume.created`).
  - Prepínač `--print` v kombinácii s obnovou je odmietnutý ešte pred sťahovaním správ.
- **Kompresia zipu:** texty (`manifest.json`, `*.md`, `messages.jsonl`) sú komprimované (`ZIP_DEFLATED`), kým prílohy v `files/` sú nekomprimované (`ZIP_STORED`), keďže väčšina médií (obrázky, videá, PDF) je už komprimovaná.

## 7. Prílohy

- Sťahujú sa **hneď po načítaní stránky správ**, lebo podpísané URL platia len 12 až 24 h (analýza, sekcia 5).
- **Obnova URL:** URL s expiráciou (`ex`) do 60 sekúnd sa pred stiahnutím obnovia cez `POST /attachments/refresh-urls` v dávkach po najviac 50 URL. Ak CDN vráti `403`, `404` alebo `410`, nástroj URL obnoví cez `refresh-urls` a pokúsi sa o stiahnutie ešte raz.
- **Bezpečnosť:** na CDN netreba token. Sťahuje sa samostatným klientom bez `Authorization` hlavičky. `DiscordAPI` odmietne iné ako API cesty.
- **Bezpečné mená:**
  - Pomenovanie `<attachment_id>_<filename>` je unikátne.
  - Meno súboru sa skracuje na max 100 znakov a 200 UTF-8 bajtov (so zachovaním prípony do 16 znakov).
  - Priečinky kanálov majú max 50 znakov, pri kolízii bez ohľadu na veľkosť písmen sa pridá `_<channel_id>`.
  - Zakázané znaky a oddeľovače sa nahradia `_`, koncové bodky a medzery sa orežú. Rezervované názvy Windows (`CON`, `NUL`, `COM1`, …) dostanú prefix `_`.
- **Deduplikácia:** ide podľa `attachment_id` a veľkosti súboru.
- **Čo sa sťahuje:**
  - áno: prílohy (`attachments[]`),
  - nie: embedy (GIF, link preview, YouTube); zapíšu sa len ako `[link]`,
  - voliteľne: obrázky z embedov typu `image` (`--embed-images`).
- `--max-file-size` (predvolene 50 MB, `0` = bez limitu) chráni pred obrovskými videami.
- **Odolnosť voči chybám:** chyba pri sťahovaní jednotlivej prílohy nezastaví export celého kanála. Príloha sa označí ako `failed` v manifeste a súhrn chýb sa vypíše na stderr.

## 8. Vlákna a fóra ([ADR 0019](rozhodnutia/0019-vlakna.md))

Podrobné overenie správania Discord API na používateľskom účte popisuje [docs/analyzy/probe-vlakien-2026-11-04.md](analyzy/probe-vlakien-2026-11-04.md).

- **Vlákna sa sťahujú predvolene** v príkaze `discoop messages` (`request.threads = True`). Vypnúť sa dajú cez `--no-threads`.
- **Fóra (typ 15) a mediálne kanály (typ 16)** nemajú vlastné správy – ich obsahom sú výhradne vlákna. Sú plnohodnotnými cieľmi `messages` (v TUI sa vyberajú ako ostatné kanály, pri Threads = no sa štart odmietne už vo formulári). Fórum zadané s `--no-threads` je odmietnuté s kódom 8 (`BAD_ARGS`).
- **Postup načítania vlákien:**
  1. Získanie zoznamu vlákien prebieha cez `GET /channels/{id}/threads/search` s `limit=25`, `sort_by=last_message_time` a `sort_order=desc` samostatne pre aktívne (`archived=false`) aj archivované (`archived=true`) vlákna. Botovský endpoint `/guilds/{id}/threads/active` používateľský účet nemôže použiť (HTTP 403, kód 20002, `[OVERENÉ]`).
  2. Stránkovanie prebieha cez `offset` s krokom 25. Koniec stránkovania určuje výlučne prázdna alebo neúplná strana (< 25 položiek); polia `has_more` a `total_results` sú nespoľahlivé (`[OVERENÉ]`).
  3. Zoznam vlákien sa filtruje podľa časového okna (`threads.in_window`).
  4. Vlákna sa spracovávajú zoradené chronologicky od najstaršieho. Správy každého vlákna sa sťahujú rovnakou cestou ako pre kanál (`GET /channels/{thread_id}/messages`). Štartovacia správa fórum postu má ID zhodné s ID vlákna (`[OVERENÉ]`).
- **Limity:** parametre `--max-messages` a `--last N` platia nezávisle pre rodičovský kanál aj pre každé jednotlivé vlákno.
- **Ošetrenie chýb a kód 9:** HTTP 403 alebo 404 na jednotlivom vlákne vlákno preskočí s varovaním a beh pokračuje s výsledkom kód 9 (`ExitCode.PARTIAL`). Problém s načítaním zoznamu vlákien vyvolá varovanie a výsledok je čiastočný (kód 9).
- **Výstup a export:**
  - V texte a markdowne má každé vlákno vlastnú sekciu za správami kanála s tagmi a názvom.
  - V JSON/JSONL sú správy vlákien súčasťou plochého zoznamu správ s atribútom `"thread"`.
  - Prílohy vlákien smerujú do `files/<rodič>/` s unikátnymi menami.

## 9. Sťahovanie: stránkovanie, rate limit, chyby

**Časové okno:** dátumy sa prevedú na syntetické snowflake (`(ms − 1420070400000) << 22`).
- Bežné okno: od `--to` dozadu cez `before=<najstaršie_id>&limit=100` **[OVERENÉ: max 100]**, kým ID nie je staršie
  ako `--from`.
- `--since-last` ([ADR 0020](rozhodnutia/0020-since-last.md)):
  - Prírastkové sťahovanie, ktoré sťahuje správy s ID väčším ako uložené ID (`Window.min_id = int(saved_id) + 1`, exkluzívna hranica zamedzujúca duplikátom).
  - Stav synchronizácie sa ukladá do `sync-state.json` v `paths.data_dir()`, kľúčovaný ID používateľského účtu (jedno volanie `GET /users/@me`). Nezávislý od SQLite cache (prežije `clear_cache()`).
  - Pre kanál bez stavu sa použije predvolené 24-hodinové okno s informačnou poznámkou.
  - Stav sa posunie až po úplnom a úspešnom dokončení kanála (nie pri prerušení, chybe, ani pri `truncated`).
  - Preskakovanie neaktívnych kanálov: ak má kanál `Channel.last_message_id <= saved_id`, kanál bez podpory vlákien (alebo akýkoľvek kanál pri `--no-threads`) sa preskočí úplne (0 requestov). Textový alebo oznamovací kanál so zapnutými vláknami nesťahuje vlastné správy, ale jeho vlákna sa čítajú ďalej. Fórum a media kanál sa nepreskakujú nikdy. `[PREDPOKLAD]` `last_message_id` je spoľahlivé a nové odpovede vo vláknach ho v rodičovskom kanáli neposúvajú (potvrdené len na malej vzorke z probe vlákien).
  - Po prerušenom a obnovenom behu si kanály uložené prerušeným behom ponechajú starý stav a nabudúce sa stiahnu znova (duplicity, nič sa nestratí).
  - Kontrola voľného miesta na disku: pred stiahnutím príloh každého kanála sa spočíta, čo sa naozaj stiahne (`ExportWriter.bytes_to_download`), a porovná s voľným miestom cez `shutil.disk_usage`. Ak nezostáva aspoň 50 MB bezpečnostná rezerva, beh zlyhá s kódom 1 pred požiadavkami na CDN.

**Tempo a sťahovanie CDN:**
- Nástroj podporuje dva režimy sťahovania:
  - **`safe` (predvolený):** bezpečné tempo imitujúce správanie používateľa vo webovom klientovi. Stránkovanie prebieha po 25 správach (`limit=25`). Medzi API requestami je náhodná pauza (jitter) 2.0 až 4.5 s. Po každých 5 až 8 requestoch sa zaradí dlhšia čítacia pauza (8.0 až 15.0 s). Pri prepnutí na ďalší kanál je pauza 3.0 až 6.0 s a medzi sťahovaním jednotlivých príloh z CDN pauza 1.0 až 3.0 s.
  - **`fast`:** rýchle tempo pre dávkový export. Stránkovanie po 100 správach (`limit=100`), sekvenčné API requesty s pauzou `--delay` (alebo podľa `config set delay`, predvolene 1.0 s). Žiadne čítacie pauzy ani pauzy medzi kanálmi či súbormi.
- Discord neposiela rate-limit hlavičky (analýza, sekcia 10), preto tempo riadi výhradne nástroj.
- CDN sťahovanie beží sekvenčne s timeoutom 60 s (20 s na spojenie) a hlavičkou `Accept-Encoding: identity`.

**Chyby:**
- `429`: počká `retry_after` z tela odpovede a pokračuje **[PROTOTYP: tvar]**.
  Opakovaný `429` predĺži `delay` na dvojnásobok.
- `5xx` a sieťové chyby: 3 pokusy s backoffom (pri CDN pauzy 1 s a 2 s).
- `401`: koniec s kódom `2` (treba login).
- `403` na kanál s kódom `50001` (Missing Access) alebo `50013` (Missing Permissions): kanál sa preskočí
  s varovaním. Pri jedinom zadanom kanáli koniec s kódom `5`.
- `403` s iným kódom (`10008` z anti-abuse systému, `40333` z Cloudflare, …) **nie je „bez prístupu“**: koniec
  s kódom `1`, hláška obsahuje `message` z odpovede a rada je počkať a zvýšiť `delay`.
- `404` (`10003` Unknown Channel): kód `4` a rada `discoop channels --refresh`.
- `200 []` môže znamenať aj chýbajúce `READ_MESSAGE_HISTORY`. Odlíšiť sa to dá až výpočtom prístupu (rozhodnutie 9, odložené).
- `403` pri kanáli bez `VIEW_CHANNEL` je **[OVERENÉ]** 2026-11-03: `discoop messages` na kanáli
  `1549737445002584094` skončil `NO_ACCESS` (kód `5`). Presný kód (`50001` alebo `50013`) výstup neukazuje.
- Ostatné kódy chýb sú **[PREDPOKLAD]** podľa [analyzy/pristup-ku-kanalom.md](analyzy/pristup-ku-kanalom.md), sekcia 7.

**Rozsah volaní:** nástroj nikdy nevolá `ack`, `science`, `metrics` ani nič, čo zapisuje.

## 9.1 Diagnostické logovanie ([ADR 0018](rozhodnutia/0018-logovanie.md))

Diagnostické logovanie slúži na detailné sledovanie sieťových požiadaviek, stránkovania a sťahovania príloh pri riešení problémov (rate limity HTTP 429, chyby siete alebo CDN).

- **Predvolene vypnuté:** bez prepínača `--debug` alebo `--log FILE` sa nevytvárajú žiadne handlery a do konzoly ani do súboru sa nezapisujú žiadne správy. Logger `discoop` má `propagate = False`.
- **Zapnutie:**
  - `--debug` (alebo `DISCOOP_DEBUG=1`): štruktúrovaný log na `sys.stderr`. Zároveň vypne Rich animovaný spinner, aby nedochádzalo k poškodeniu rozhrania.
  - `--log FILE` (alebo `DISCOOP_LOG=cesta`): zápis do súboru (append mód, kódovanie UTF-8).
  - V príkaze `discoop ui` je `--debug` odmietnuté (kód 8), povolené je `--log FILE`.
- **Hlavička logu:** pri inicializácii sa zapíše hlavička s verziou nástroja (`discoop.__version__`), operačným systémom, verziou Pythonu a varovaním:
  `IDs in this log identify private servers and channels. Do not publish it.`
- **Čo sa loguje:**
  - `discoop.api`: HTTP metóda, cesta bez query parametrov (`path.split("?", 1)[0]`), názvy parametrov a hodnoty iba pre bezpečný allowlist (`before`, `after`, `limit`, `archived`, `offset`, `with_counts`), číslo pokusu (`attempt`), HTTP stavový kód, latencia v milisekundách meraná cez `time.perf_counter()`, dĺžka odpovede v bajtoch a prípadne počet položiek (`items`). Pri 429 sa loguje `retry_after`, `global` a predĺžený delay; dĺžka a dôvod všetkých čakaní (reading pause, jitter, between channels, between files); pri opakovaniach backoff; pri chybách top-level `code` a `message` a typ transportnej chyby (`type(e).__name__`).
  - `discoop.scrape`: jeden riadok na stranu správ: ID kanála, počet správ, ID najstaršej a najnovšej správy, príznak `last`.
  - `discoop.attachments`: iba v `_download` a `_fetch`: ID prílohy, veľkosť, stav, číslo pokusu, zapísané bajty a výhradne host z URL.
- **Čo sa NIKDY neloguje (prísny bezpečnostný filter):**
  - Hlavičky requestu ani response (ani `Authorization` token).
  - Dodatočné argumenty `kwargs` volaní `request()` (tickety, JSON telá).
  - Celé telá odpovedí (`response.text`, `response.json()`).
  - Texty správ a mená používateľov.
  - Mená súborov, cesty súborov a query parametre podpisov CDN URL (`ex`, `is`, `hm`).
  - Názvy kanálov a serverov (vždy len číselné ID).
  - Reprezentácie dataclassov (`FileJob`, `Attachment`, `Message`, `StoredToken` atď.).
- Knižnice tretích strán (`httpx`, `httpcore`, `websockets`) sú explicitne stíšené na úroveň `WARNING`.
- Po dokončení príkazu volá CLI `teardown_logging()`, ktoré korektne zatvorí a odpojí všetky handlery.

## 10. Lokálne dáta

Adresáre určí `platformdirs` podľa OS:

| OS | Dáta (cache) | Konfigurácia |
|---|---|---|
| Windows | `%LOCALAPPDATA%\discoop\` | to isté |
| macOS | `~/Library/Application Support/discoop/` | to isté |
| Linux | `~/.local/share/discoop/` | `~/.config/discoop/` |

Obsah:
- `config.toml`: nastavenia (`default-server`, `delay`, `export-dir`, `mode`).
- `profiles.json` (konfiguračný adresár): pomenované profily nastavení (`server`, `channels`, `from`, `to`, `last`, `mode`), spoločné pre CLI aj TUI.
- `tui-state.json` (konfiguračný adresár): stav TUI podľa ID účtu (výber, časové okná, režim, `Folder`/`Name`, vlákna, dátumy posledných exportov kanálov).
- `sync-state.json` (dátový adresár): stav `--since-last` podľa ID účtu, pre každý kanál a vlákno `last_message_id` a čas `updated` ([ADR 0020](rozhodnutia/0020-since-last.md)). Je oddelený od `cache.db`, aby prežil jej zmazanie.
- `cache.db`: SQLite s tabuľkami (schéma 2):
  - **teraz:** `servers`, `channels` (typ, kategória, pozícia, téma, `last_message_id`, tagy fóra), `threads`, `thread_lists` (od kedy je zoznam vlákien kanála načítaný) a `fetched` (kedy sa čo obnovilo).
    Normalizované mená sa počítajú v Pythone, kanálov je pár stoviek.
  - **neskôr** (v2, lokálny archív správ): `users` (z `author` a `mentions`, na preklad `<@id>`).
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
  discoop [--plain] <command> [options]

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
| 9 | čiastočný výsledok (PARTIAL: preskočený kanál, zlyhaná príloha, problém s vláknom) | run the same command again to continue |

## 13. Štruktúra projektu

```
Scoop/
  pyproject.toml
  src/discoop/
    cli.py            Typer app, príkazy, globálne prepínače, výber režimu
    service.py        servisná vrstva: zjednotená biznis logika pre CLI aj TUI
    auth.py           QR login (remote auth gateway), keyring, záložný login
    api.py            HTTP klient: tempo, retry, 429, chyby → exit kódy
    snowflake.py      čas ↔ snowflake, parsovanie --from/--to
    cache.py          SQLite: servery, kanály, vlákna, users, sync_state
    resolve.py        normalizácia mien, zhoda, globy, nejednoznačnosť
    scrape.py         stránkovanie správ, vlákna, časové okno
    attachments.py    sťahovanie, obnova URL, bezpečné mená súborov
    models.py         normalizované dataclasses (Message, Attachment, Server, Channel...)
    normalize.py      normalizácia správ z API, mentions
    render/
      text.py         text pre agentov, farebný human výstup, markdown (md)
      jsonout.py      json a jsonl
    export.py         priečinok + zip + manifest, kontrola cieľa a opätovné použitie
    logs.py           diagnostické logovanie (setup_logging, teardown_logging, formátovač)
    progress.py       výpočet percent a ETA podľa snowflake
    profiles.py       správa profilov nastavení v profiles.json
    tokens.py         odhad počtu tokenov a formátovanie
    syncstate.py      správa synchronizačného stavu pre --since-last (sync-state.json)
    split.py          delenie markdownu na časti podľa tokenov (split_markdown)
    agent_guide.py    generovanie nestylovanej príručky a referencie pre AI agentov
    tui/              interaktívne terminálové rozhranie (Textual)
      tuistate.py     perzistentný stav TUI v tui-state.json a formátovanie aktivity
      app.py          hlavná Textual aplikácia, responzívny layout, event handling
      state.py        stav TUI (výber kanálov, nastavenia, plánovanie úloh)
      bridge.py       mostík medzi TUI a service.py / API (CancelToken, udalosti)
      widgets.py      ovládacie prvky (ChannelTree, FormPanel, ChoiceRow, TextView, ...)
      modals.py       modálne dialógy (Help, Settings, Login, Preview, TimeWindow)
      discoop.tcss    CSS štýly komponentov rozhrania
  tests/
    fixtures/         anonymizované JSON z analýzy
  docs/
```

**Stav 2026-11-03 (po kroku 3 a pridaní safe/fast režimov):**
- `api.py`: podpora dvoch režimov sťahovania (`safe` a `fast`), jitter 2.0–4.5s, čítacie pauzy 8–15s, pauzy medzi kanálmi (3–6s) a súbormi (1–3s), zdvojnásobenie delay pri 429,
- `scrape.py`: podpora dynamickej veľkosti stránky (`limit=25` pre safe, `limit=100` pre fast),
- `attachments.py`: sťahovanie samostatným klientom bez tokenu, obnova podpisov cez `refresh-urls`, bezpečné mená súborov,
- `export.py`: zostavenie priečinka alebo zipu, `manifest.json`, opätovné použitie súborov pri opakovanom behu,
- `render/text.py`: formáty `text` a `md` (Markdown pre správy a kanály),
- `render/jsonout.py`: formáty `json` a `jsonl`,
- `service.py`: spoločná servisná vrstva pre orchestráciu načítania serverov, kanálov a sťahovania správ,
- `tui/`: interaktívne terminálové rozhranie Textual (`discoop ui`, jeden strom ovládaný klávesnicou podľa ADR 0014, panel Export, náhľad, live CLI bar, Help s `--help`).
- **Pridané 2026-11-04 (Antigravity kolo 1):**
  - `logs.py`: voliteľné diagnostické logovanie na stderr (`--debug`) alebo do súboru (`--log FILE`), ochrana pred únikom citlivých údajov ([ADR 0018](rozhodnutia/0018-logovanie.md)),
  - `progress.py`: kalkulácie percent a odhadu času (ETA) pre sťahovanie správ podľa snowflake ID,
  - `profiles.py`: správa profilov v `profiles.json` s atomickým ukladaním,
  - `tokens.py`: odhad počtu tokenov a ich formátovanie,
  - `resolve.py`: fuzzy návrhy pri preklepoch v názvoch kanálov a serverov (`Did you mean: ...?`),
  - `output.py`: unifikovaný výstup `Output.json()` pre strojové spracovanie,
  - `cli.py`: diagnostický príkaz `discoop doctor`, prepínač `--progress-json` pre `messages`, prepínač `--format text|json` pre `servers`, `channels`, `status` a `config list`.
- **Pridané 2026-11-04 (Antigravity kolo 2 a kontrola hlavným Claudom):**
  - `export.py`: `ExportWriter` (zápis po kanáloch do `<cieľ>.partial`, obnova, kód 9, časti pre `--max-tokens` v staging priečinku, `bytes_to_download` pre kontrolu disku) a `request_fingerprint` aj s `threads` a `since_last` ([ADR 0017](rozhodnutia/0017-spolahlivy-export-a-ciastocny-uspech.md)),
  - `threads.py`, `models.py` (`Thread`, `ChannelMessages.threads`), `cache.py` (schéma 2) a `render/*`: vlákna a fóra ([ADR 0019](rozhodnutia/0019-vlakna.md)),
  - `service.py`: `run_messages` je rozdelená na malé funkcie (trieda `_Run` s krokmi `open_export`, `fetch_channels`, `fetch_channel`, `finish` a ďalšie, správanie sa nezmenilo), `--since-last` a `_check_disk_space`,
  - `syncstate.py` ([ADR 0020](rozhodnutia/0020-since-last.md)), `split.py` (`split_markdown`), `agent_guide.py` a `tui/tuistate.py`.

## 14. Postup implementácie

0. **Spike / prototyp** (2026-11-03: **hotové**. Login aj probe prešli, výsledky v analýzach):
   QR `login` + malý skript, ktorý overí body [PROTOTYP]:
   - QR login: či gateway vyžaduje `Origin`, či `remote-auth/login` pýta captchu, reálne rámce po naskenovaní,
   - `GET /users/@me/guilds` a `GET /guilds/{id}/channels` s user tokenom,
   - `limit=100`,
   - REST cesta k aktívnym vláknam,
   - tvar `429` a `refresh-urls`.

   Spúšťa ho používateľ, pretože beží na jeho účte. Výsledky sa zapíšu do analýzy.
1. **Jadro:** config, cache, API klient, `servers`, `channels`, `resolve`, `status` (2026-11-03: **hotové**).
2. **`messages`** → `text`/`json` do konzoly, časové okno, `--last` (2026-11-03: **hotové**, otestované na účte).
3. **Prílohy** + `--out` / `--zip` + manifest (2026-11-03: **hotové**, čaká na test používateľa).
4. **Vlákna a fóra**, `threads` (2026-11-04: **hotové**, ADR 0019).
5. **Human režim** (Rich), `agent-guide`, help texty, TUI vylepšenia (2026-11-04: **hotové**).
6. **`--since-last`**, delenie na tokeny, profily v CLI (2026-11-04: **hotové**, ADR 0020).

Kroky 4 až 6 a odolný export (ADR 0017) sú overené len testami s falošným Discordom (`httpx.MockTransport`). Test na reálnom účte (fórum, vlákna, `--since-last`, Ctrl+C a obnova, `--max-tokens` so zipom, `discoop ui`) ešte chýba.

**Testy:** unit testy (snowflake, parsovanie času, resolve, renderery, sťahovanie, export) nad anonymizovanými fixtures a MockTransport, bez živého API.

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
