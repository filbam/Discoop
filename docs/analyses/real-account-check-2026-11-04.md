# Overenie na reálnom účte: výsledky skúšky z 2026-11-04

Dátum: 2026-11-04. Typ: skúška nástroja `discoop` na reálnom účte používateľa (server VUT FIT). Spustil ju hlavný
Claude na výslovnú žiadosť používateľa, v režime `safe` a v malých časových oknách. Exporty išli do dočasného
priečinka, ktorý sa po behu zmazal; z obsahu exportov sa nič neuchovalo.

**Legenda:** **[OVERENÉ]** = pozorované v behoch z 2026-11-04 na reálnom účte (výstupy príkazov, súhrny, manifesty
a kontrolné skripty hlavného Claudea). **[PREDPOKLAD]** = extrapolácia alebo výklad, ktorý beh nepotvrdil.

**Metodika a súkromie:**
- Dokument neobsahuje ID používateľa, mená ľudí, texty správ ani názvy vlákien. Fórum sa tu volá „fórum (kategória
  general)“, ostatné kanály „študijné textové kanály“.
- Do tohto dokumentu sa dostali len počty, časy, kódy ukončenia a názvy polí.
- Súvisiace meranie: [thread-probe-2026-11-04.md](thread-probe-2026-11-04.md) (iba čítacie GET volania
  prototypu). Tu sa spúšťal samotný nástroj `discoop`.

---

## 1. Zhrnutie

| # | Oblasť | Výsledok v skratke |
|---|---|---|
| 1 | Diagnostika a základné príkazy | `doctor`: všetkých 6 kontrol OK. `status`, `servers` a `channels` fungujú |
| 2 | TUI | Používateľ samostatne potvrdil, že `discoop ui` funguje a že sa v ňom prihlásil (QR prihlásenie v TUI funguje) |
| 3 | `discoop threads` na fóre | `--from 3d`: 2 vlákna za 5,9 s. `--from 90d --refresh --format json`: 61 unikátnych vlákien (50 archivovaných) za 17 s, 4 stránky `threads/search`. `has_more` bolo na poslednej archivovanej strane znova `true`, koniec našlo `reached_start` |
| 4 | Export fóra | 2 príspevky, 22 správ, 11,6 s, manifest úplný. Nové zistenie: `message_count` v zozname vlákien nezahŕňa štartovaciu správu príspevku |
| 5 | Prerušenie a obnova | Kód 130, `.partial` s `interrupted: true`, opakovanie dotiahlo len chýbajúci kanál. Prerušenie signálom konzoly nebolo skúšané |
| 6 | `--since-last` | Druhý beh: nezmenené kanály nesťahovali vlastné správy (0 požiadaviek na `/messages`), vlákna sa čítali ďalej |
| 7 | `last_message_id` | V 20 z 25 čitateľných kanálov sa zhodovalo s najnovšou správou, v 4 z 25 ukazovalo na novšiu, v 1 z 25 bola najnovšia správa novšia než pole |
| 8 | Zip s `--max-tokens` | Platný zip (`testzip` čistý), 3 časti, hlavička časti 1 `<!-- discoop part 1 of 3 -->` |
| 9 | Príloha z CDN | Stiahla sa, ale pri opakovanom exporte sa stiahla znova (známe obmedzenie, sekcia 4) |
| 10 | Logy `--debug --log` | Dva skutočné logy prezreté: bez tokenu, podpísaných URL, názvov a slov zo správ |
| 11 | `--progress-json` | 4 udalosti, každý riadok platný JSON, bez názvov |
| 12 | Rýchlosť | Pauzy režimu `safe` dominujú: asi 4 až 6 s na vlákno |

---

## 2. Čo sa spustilo a ako

- **Účet a rozsah:** reálny účet používateľa, server VUT FIT. Fórum z kategórie general a študijné textové kanály.
  Okná boli malé (24 hodín, 3, 7 a 14 dní; najširšie bolo 90 dní, a to iba pri výpise vlákien).
- **Režim:** `safe` (predvolený). Žiadne `fast`.
- **Príkazy v skratke:**
  - `discoop doctor`, `status`, `servers`, `channels`,
  - `discoop threads -c <fórum> --from 3d` a `--from 90d --refresh --format json`,
  - `discoop messages -c <fórum> --from 3d --no-files --out DIR`,
  - `discoop messages` s `--out` a s `--zip --max-tokens 300 --max-file-size 1`,
  - `discoop messages --since-last` dvakrát po sebe (stavový súbor presmerovaný do dočasného súboru, takže skutočný
    `sync-state.json` používateľa sa nezmenil),
  - export s `--debug --log` a s `--progress-json`,
  - čítacia sonda na `last_message_id` (iba čítanie).
- **Prerušenie exportu:** skript, ktorý vyvolal `KeyboardInterrupt` z udalostí CLI počas skutočného sťahovania po
  sieti. Nebol to signál konzoly (skutočné Ctrl+C).
- **Čo sa uchovalo:** nič. Exporty boli v dočasnom priečinku, ktorý sa po behu zmazal.

---

## 3. Výsledky

### 3.1 Diagnostika, základné príkazy a TUI

- **[OVERENÉ]** `discoop doctor`: všetkých 6 kontrol je OK.
- **[OVERENÉ]** `status`, `servers` a `channels` fungujú.
- **[OVERENÉ]** (potvrdenie používateľa, nie meranie hlavného Claudea) `discoop ui` funguje a používateľ sa v ňom
  prihlásil. QR prihlásenie v TUI teda funguje.

### 3.2 `discoop threads` na fóre (kategória general)

| Príkaz | Výsledok |
|---|---|
| `--from 3d` | 2 vlákna za 5,9 s **[OVERENÉ]** |
| `--from 90d --refresh --format json` | 61 unikátnych vlákien, z toho 50 archivovaných, zoradené podľa poslednej aktivity zostupne, 17 s **[OVERENÉ]** |

- **[OVERENÉ]** Druhý príkaz urobil 4 požiadavky na `threads/search`: 1 strana aktívnych vlákien a 3 strany
  archivovaných vlákien (po 25).
- **[OVERENÉ]** `has_more` bolo na poslednej archivovanej strane znova `true`. Koniec našlo až okno (`reached_start`).
  Potvrdzuje to, že `has_more` nie je spoľahlivé (rovnako ako v [thread-probe-2026-11-04.md](thread-probe-2026-11-04.md),
  sekcia 7.6).
- **[OVERENÉ]** Jedno vlákno, ktoré je ešte aktívne, ale staršie než okno, vypadlo vo filtri okna.

### 3.3 Export fóra: `messages -c <fórum> --from 3d --no-files --out DIR`

- **[OVERENÉ]** 2 príspevky, 22 správ, 11,6 s, manifest je úplný (`complete`).
- **[OVERENÉ]** `messages.md` obsahuje sekcie `## thread "..."` s riadkami hlavičky: vytvorenie, posledná aktivita,
  počet správ, počet súborov a tagy.
- **[OVERENÉ]** Správy v `messages.jsonl` majú pole `thread: {id, name, parent_id, tags}`. Tagy sú názvy tagov fóra.
- **[OVERENÉ]** Počty v manifeste: `messages` 0, `threads` 2, `thread_messages` 22. Fórum nemá vlastné správy, čo
  zodpovedá [ADR 0019](../decisions/0019-threads.md).
- **[OVERENÉ]** **Nové zistenie:** `message_count`, ktorý ukazuje zoznam vlákien (výpis `discoop threads`),
  nezahŕňa štartovaciu správu príspevku fóra. Zoznam ukázal 9 a 11, stiahnutie vrátilo 10 a 12 správ. Pozorované na týchto
  dvoch príspevkoch (spolu 22 správ).

### 3.4 Prerušený export a obnova (skutočná sieť, prerušenie skriptom)

Prerušenie vyvolal skript výnimkou `KeyboardInterrupt` z udalostí CLI. Signál konzoly sa nepoužil.

- **(a) Po 2. z 3 kanálov:**
  - **[OVERENÉ]** Kód ukončenia 130. Vznikol `<cieľ>.partial` s manifestom `complete: false, interrupted: true`
    a 2 kanálmi. Cieľ neexistoval.
  - **[OVERENÉ]** Hláška: „Saved 2 of 3 channels in ....partial. Run the same command again to continue.“
  - **[OVERENÉ]** Ten istý príkaz znova stiahol iba 3. kanál, publikoval cieľ (`complete: true`), zmazal `.partial`
    a skončil s kódom 0.
- **(b) Uprostred prvého kanála exportu jedného fóra (počas jeho 2. vlákna):**
  - **[OVERENÉ]** Kód ukončenia 130, žiadny `.partial`, žiadny cieľ, žiadne súbory `.part`. Opakovanie prebehlo
    normálne.
  - Je to v súlade s [ADR 0019](../decisions/0019-threads.md): kanál a jeho vlákna sú nedeliteľná jednotka a
    ukladajú sa spolu, preto nebolo čo uložiť do `.partial`.
- **Pozorovanie:** v oboch prípadoch `main()` nevypísal riadok „Interrupted.“, hoci kód má na to `out.error(...)`.
  Kód 130 vyšiel aj bez neho. Pozri sekciu 5.
- **Neskúšané:** skutočné Ctrl+C z konzoly počas čakania na sieť alebo počas sťahovania súboru.

### 3.5 `--since-last` (stavový súbor presmerovaný do dočasného súboru)

- **Dva študijné textové kanály:**
  - **[OVERENÉ]** 1. beh (bez stavu): stiahli sa posledné 24 hodiny s poznámkou „No previous sync state ...“.
  - **[OVERENÉ]** 2. beh: oba kanály ohlásili „its own messages are unchanged since last sync, fetching only its
    threads“. 0 správ. `threads/search` sa volalo dvakrát na kanál (aktívne + archivované), `/messages` kanála vôbec.
- **Dve fóra:**
  - **[OVERENÉ]** 1. beh: stiahlo sa 1 vlákno s 1 správou (posledných 24 hodín) a uložili sa 3 záznamy stavu
    (2 fóra + 1 vlákno).
  - **[OVERENÉ]** 2. beh: 0 správ.
- **Nevidené:** vlákno, ktoré medzi dvoma behmi dostane novú odpoveď.

### 3.6 Spoľahlivosť `last_message_id` (iba čítanie, dva behy)

Vzorka: spolu 28 textových a oznamovacích kanálov (najaktívnejšie a náhodné staršie). 25 bolo čitateľných, 3 vrátili
403.

| Výsledok | Počet z 25 čitateľných |
|---|---|
| Pole sa rovnalo najnovšej dostupnej správe | 20 |
| Pole ukazovalo na novšiu správu, než je najnovšia dostupná | 4 |
| Najnovšia správa bola novšia než pole | 1 |

- **[OVERENÉ]** Čísla z tabuľky.
- **[PREDPOKLAD]** Štyri prípady „pole novšie“ sú pravdepodobne zmazaná správa. Je to bezpečný smer pre pravidlo
  preskakovania pri `--since-last`.
- **[PREDPOKLAD]** Jeden prípad „správa novšia než pole“ (kanál aktívny v ten deň) je pravdepodobne správa, ktorá
  prišla počas asi 2 minút vzorkovania. Nedokázané.
- **Vlákna:** 3 vlákna v 7-dňovom okne vzorkovaných kanálov nemali správu novšiu než `last_message_id` rodiča. To je
  nepreukazné pre otázku, či odpovede vo vláknach posúvajú `last_message_id` rodiča. Ostáva **[PREDPOKLAD]** a kód
  ostáva opatrný: vlákna sa čítajú ďalej.

### 3.7 Zip s delením na tokeny

`--zip --max-tokens 300 --max-file-size 1` na 3 študijných textových kanáloch za 7 dní:

- **[OVERENÉ]** 16 správ, 43,5 s.
- **[OVERENÉ]** Zip je platný (`testzip` bez chýb). Záznamy: `channels/`, `manifest.json`, `messages.jsonl`,
  `messages.md`, `parts/part-001.md` až `parts/part-003.md`.
- **[OVERENÉ]** Časti nie sú v manifeste (zodpovedá [ADR 0017](../decisions/0017-reliable-export-and-partial-success.md)).
- **[OVERENÉ]** Prvý riadok časti 1 je `<!-- discoop part 1 of 3 -->`. Súhrn ukázal `tokens: ~742`.

### 3.8 Príloha z CDN

- **[OVERENÉ]** V exporte fóra sa stiahol 1 súbor (PNG, 36731 B), po behu nezostal žiadny súbor `.part`.
- Opakovaný export do toho istého priečinka stiahol súbor znova. Pozri sekciu 4.
- V 14 dňoch dvoch fór sa našla iba jedna príloha, takže ide o jednu vzorku.

### 3.9 Logy `--debug --log`

- **[OVERENÉ]** Prezreli sa dva skutočné logy (13 a 30 riadkov). Neobsahujú token, `Authorization` ani `Bearer`,
  parametre podpísaných URL (`ex`, `is`, `hm`), názvy serverov ani kanálov, ani žiadne zo 102 rôznych slov vybraných
  z exportovaných správ.
- **[OVERENÉ]** Logy obsahujú ID kanálov a vlákien (hlavička logu na to upozorňuje).

### 3.10 `--progress-json` na exporte fóra

- **[OVERENÉ]** 4 udalosti: `channel_start`, 2x `thread`, `channel_done`. Každý riadok je platný JSON, bez názvov.
- **[OVERENÉ]** Kľúče: `event, index, total, channel_id, thread_id, messages, files, truncated`.
- Udalosť `page` sa v tomto behu neobjavila (fórum nemá vlastné správy). Či stránky správ vlákien udalosť `page`
  emitujú, sa nezisťovalo. Pozri sekciu 5.

### 3.11 Rýchlosť

- **[OVERENÉ]** Pauzy režimu `safe` dominujú: v behoch vyššie asi 4 až 6 s na vlákno vrátane podielu na výpise vlákien.
- **[PREDPOKLAD]** Extrapolácia: úplné stiahnutie fóra s asi 1800 príspevkami trvá v režime `safe` zhruba 2 až 3
  hodiny. Nemerané.

---

## 4. Známe obmedzenie: príloha, ktorú API popíše inak, sa sťahuje pri každom behu znova

**Stav: otvorené, neopravené.**

- **[OVERENÉ]** Export fóra do toho istého priečinka druhýkrát stiahol tú istú prílohu znova
  (`downloaded: 1, already_present: 0`).
- **[OVERENÉ]** Príčina v pozorovaných údajoch: API pri prílohe uviedlo `size` 25238 a `content_type` `image/webp`
  (názov súboru končil na `.png`), no CDN poslalo platný PNG s rovnakými rozmermi v pixeloch (375x468) a veľkosťou
  36731 B.
- **[PREDPOKLAD]** Preto opätovné použitie podľa ID prílohy a veľkosti (`attachments.reuse_stored`, rovnako opätovné
  použitie v zipe a `bytes_to_download`) takúto prílohu nepozná. Pozorované bolo len správanie (stiahne sa znova);
  že za tým je práve porovnanie veľkosti, je výklad z kódu.
- **Dopad:** neškodný. Prevedený obrázok sa pri každom behu stiahne znova. Pozorované na jedinej prílohe (jedna
  vzorka).
- **Možná oprava neskôr (nezaradená, nerobí sa):** uvoľniť kontrolu veľkosti alebo ukladať do manifestu skutočnú
  veľkosť.

---

## 5. Otvorené pozorovania

- **Chýbajúci riadok „Interrupted.“:** kód v `main()` má `out.error(... "Interrupted.")`, no pri oboch
  prerušeniach (3.4) sa riadok nevypísal a kód 130 vyšiel aj tak. Vetva vyzerá nedosiahnuteľná. **[PREDPOKLAD]**
  `click`/`typer` skončí s kódom 130 skôr. Neškodné, treba sa na to pozrieť neskôr.
- **Udalosť `page` pri vláknach:** nezistilo sa, či stránky správ vlákien emitujú v `--progress-json` udalosť `page`
  (v behu 3.10 sa neobjavila žiadna).

---

## 6. Čo ostáva neoverené

- Skutočný signál Ctrl+C z konzoly (počas čakania na sieť aj počas sťahovania súboru).
- Ctrl+C v TUI.
- Výber fór a prepínač Threads v TUI na reálnom účte.
- Export fóra so stovkami príspevkov od začiatku do konca.
- Vlákno, ktoré medzi dvoma behmi `--since-last` dostane novú odpoveď.
- Súkromné vlákna (typ 12) a HTTP 202 (neobjavili sa).
- Export s množstvom príloh (videná len 1 príloha).
- Linux a macOS.

---

## 7. Dopad na dokumentáciu

Záznamy, ktoré tvrdili, že nič z kola 2 nebolo overené na reálnom účte, boli opravené: `CLAUDE.md`,
[denník](../journal.md), [odovzdanie stavu](../handover.md), [požiadavky P26 až P30](../requirements.md),
[návrh nástroja](../design.md), [ADR 0017](../decisions/0017-reliable-export-and-partial-success.md),
[ADR 0019](../decisions/0019-threads.md), [ADR 0020](../decisions/0020-since-last.md) a
[CHANGELOG](../../CHANGELOG.md).
