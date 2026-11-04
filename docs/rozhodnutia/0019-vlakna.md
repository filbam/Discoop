# 0019: Vlákna a príspevky na fórach

- **Stav:** Prijaté
- **Dátum:** 2026-11-04
- **Rozhodol:** používateľ

## Kontext

V Discorde existujú dva hlavné druhy kanálov obsahujúcich diskusie:
1. Bežné kanály (textové typ 0, oznamovacie typ 5), ktoré obsahujú vlastný lineárny prúd správ a popri tom voliteľné nadväzujúce vlákna (threads).
2. Fórumové kanály (typ 15) a mediálne kanály (typ 16), ktoré nemajú vlastný prúd správ – všetok ich obsah je organizovaný výhradne do príspevkov (threads), pričom každý príspevok je samostatným vláknom so štartovacou správou a prípadnými odpoveďami.

V pôvodnej verzii Discoop nepodporoval čítanie vlákien; fóra a media kanály boli odmietané ako nečitateľné (hláška „threads come in a later version“). Na serveroch ako VUT FIT je však veľká časť kľúčových študijných informácií, otázok a odpovedí sústredená práve v príspevkoch na fórach a vo vláknach kanálov.

ADR 0011 stanovilo, že vlákna sa majú sťahovať predvolene. Merania cez probe skript (`docs/analyzy/probe-vlakien-2026-11-04.md`) overili správanie Discord API pre používateľský účet:
- Botovský endpoint `GET /guilds/{id}/threads/active` používateľský účet nemôže použiť (403, kód 20002).
- Kanálový endpoint `GET /channels/{id}/threads/search` funguje pre používateľský účet na fórach aj v bežných textových kanáloch s `limit=25`.
- Správy jednotlivých vlákien sa čítajú štandardnou cestou `GET /channels/{thread_id}/messages`.

Bolo potrebné dobudovať plnú podporu sťahovania vlákien do servisnej vrstvy (`service.py`), do príkazu `discoop messages`, pridať samostatný prehľadový príkaz `discoop threads` a doriešiť ošetrenie chýb pri výpadku prístupu k vláknam.

## Možnosti

1. **Nestahovať vlákna vôbec alebo ich vyžadovať explicitným prepínačom `--threads`.**
   Zamietnuté: Podľa ADR 0011 majú byť vlákna prirodzenou súčasťou exportovanej histórie, aby používateľ neprišiel o dôležitý kontext.
2. **Považovať fórum za obyčajný kanál a volať `fetch_messages` na ID fóra.**
   Zamietnuté: Fórum nemá vlastné správy; volanie na jeho ID zbytočne plytvá HTTP požiadavkami a môže zlyhať. Fórum sťahuje výlučne svoje vlákna.
3. **Zastaviť celý export pri chybe jedného vlákna (fail-fast).**
   Zamietnuté: Ak jedno vlákno vráti 403 (napr. súkromné vlákno) alebo 404, nie je dôvod zahodiť správy celého kanála ani ostatných vlákien. Riešením je čiastočný úspech (kód 9) podľa ADR 0017.

## Rozhodnutie

- **Sťahovanie vlákien v `messages` a prepínač `--threads / --no-threads`:**
  - V súlade s ADR 0011 sú vlákna predvolene zapnuté (`request.threads = True`).
  - Používateľ a skripty môžu vlákna vypnúť prepínačom `--no-threads`. V popise príkazu a prepínača je uvedené upozornenie, že vlákna generujú dodatočné požiadavky a pri rozsiahlych fórach (stovky príspevkov) v režime `safe` trvá sťahovanie dlhšie.
  - Pre bežné kanály (textové typ 0, oznamovacie typ 5) sa najprv stiahnu správy samotného kanála a následne vlákna.
  - Pre fóra (typ 15) a mediálne kanály (typ 16) sa sťahujú výlučne vlákna (`items = ()`, žiadne volanie `fetch_messages` na samotný kanál).
  - Ak používateľ zadá fórum alebo media kanál spolu s `--no-threads`, Discoop to odmietne s `ExitCode.BAD_ARGS` (kód 8) a radou: *"A forum only has threads: drop --no-threads."*.

- **Časové okno a poradie vlákien:**
  - Sťahujú sa aktívne aj archivované vlákna (`threads.fetch_all_threads`), ktorých existencia zasahuje do zadaného časového okna (`threads.in_window`).
  - Vlákna sa spracovávajú a ukladajú zoradené chronologicky od najstaršieho (podľa `thread.created` a číselného `thread.id`).
  - Vlákno, ktoré v danom časovom okne nemá žiadne správy, sa do výsledku nezaraďuje.

- **Limity správ (`--max-messages`, `--last`):**
  - Parametre `--max-messages` a `--last N` platia nezávisle pre každý kanál aj pre každé jedno vlákno (každé vlákno dostane rovnaký limit).
  - Pri orezaní vlákna limitom sa zaznamená `truncated = True` a vyvolá sa varovanie `events.warning(...)`.

- **Jednotka ukladania a export:**
  - Kanál a jeho vlákna tvoria nedeliteľnú jednotku: `ChannelMessages(..., threads=tuple(nested_threads))`.
  - Do `writer.add_channel(...)` a `events.channel_done(...)` vstupujú spoločne.
  - Nastavenie vlákien je súčasťou odtlačku požiadavky, podľa ktorého sa prerušený export obnovuje (ADR 0017): export prerušený s vláknami nepokračuje beh s `--no-threads` (uložené kanály by vlákna nemali) ani opačne, takýto beh začne odznova.
  - V textovom a markdown exporte má každé vlákno vlastnú sekciu za správami kanála (`--- thread "názov" ---` v čistom texte, `## thread "názov"` v markdowne). V JSON/JSONL exporte sú správy vlákien súčasťou plochého zoznamu správ s vyplneným atribútom `"thread"`.

- **Nový príkaz `discoop threads`:**
  - Poskytuje rýchly zoznam vlákien kanála bez nutnosti sťahovať správy.
  - Signatúra: `discoop threads -s SERVER -c CHANNEL [--from ...] [--to ...] [--refresh] [--format text|json]`.
  - Predvolené časové okno pre zoznam vlákien je 30 dní (`--from 30d`). Celá história sa vypíše cez `--from all`.
  - Ak zadaný kanál nepodporuje vlákna (`not threads.is_thread_container(channel)`), príkaz skončí s `ExitCode.BAD_ARGS` (kód 8).
  - Podporuje režimy `human` (Rich tabuľka: id, archived, messages, last_activity, tags, name), `plain` (TSV formát s hlavičkou) a `--format json` (strojovo čitateľný JSON so zoznamom tagov).

- **Ošetrenie chýb a kód `ExitCode.PARTIAL = 9`:**
  - Chyba HTTP 403 (`NO_ACCESS`) alebo HTTP 404 (`NOT_FOUND`) pri sťahovaní správ jedného vlákna vlákno preskočí s varovaním (`events.warning(...)`). Kanál a ostatné vlákna sa uložia a celkový výsledok je čiastočný (`partial = True`, kód 9).
  - Chyba pri načítaní zoznamu vlákien kanála (403/404) alebo neúplný zoznam (`FetchedThreads.problem` nie je `None`, napr. pri HTTP 202 neindexovaných vláknach) vyvolá varovanie a výsledok je čiastočný (kód 9). Správy samotného kanála ostanú zachované.
  - `MessagesOutcome.partial` aj `ExportWriter` zohľadňujú chyby vlákien (`thread_problems > 0`) a CLI v záverečnej rade (`_partial_advice`) presne informuje používateľa o problémoch s vláknami.

- **Súkromie v priebehu (`Events.thread`):**
  - Pri `--progress-json` udalosť `thread` emituje výlučne technické identifikátory (`channel_id`, `thread_id`) a počty (`index`, `total`). Žiadne názvy kanálov, názvy vlákien ani texty správ sa v strojovom JSON progress výstupe neobjavujú.

## Vzťah k zisteniam z probe (`docs/analyzy/probe-vlakien-2026-11-04.md`)

- **[OVERENÉ]**
  - Používateľský účet nemôže pristupovať na `/guilds/{id}/threads/active` (403, kód 20002). Aktívne vlákna sa preto získavajú cez kanálový endpoint `/channels/{id}/threads/search?archived=false`.
  - Stránkovanie `threads/search` akceptuje `limit=25`; limit 50 Discord odmieta kódom 400 (`Invalid Form Body`).
  - Polia `has_more` a `total_results` na `threads/search` sú nespoľahlivé (falošné `has_more: true` na poslednej strane, nezrovnalosti v `total_results`). Koniec stránkovania preto spoľahlivo určuje iba prázdna alebo neúplná strana (< 25 položiek).
  - Správy vlákien sa čítajú štandardným volaním `GET /channels/{thread_id}/messages`. Štartovacia správa fórumového postu má ID zhodné s ID vlákna.
  - Kanály a vlákna bez oprávnení vracajú HTTP 403 `Missing Access`. Discoop ich zachytáva a bezpečne hlási ako čiastočný výsledok (kód 9).
  - Na reálnom účte (2026-11-04, [analýza](../analyzy/overenie-na-realnom-ucte-2026-11-04.md)): `discoop threads` na fóre vypísalo pri `--from 3d` 2 vlákna (5,9 s) a pri `--from 90d --refresh --format json` 61 unikátnych vlákien (50 archivovaných) zoradených podľa poslednej aktivity zostupne, na 4 stránky `threads/search` (1 aktívna + 3 archivované po 25), za 17 s. `has_more` bolo na poslednej archivovanej strane znova `true`, koniec našlo okno (`reached_start`), čo potvrdzuje nespoľahlivosť `has_more`. Vlákno, ktoré je ešte aktívne, ale staršie než okno, vypadlo vo filtri okna.
  - Na reálnom účte (2026-11-04): export fóra (`messages -c <fórum> --from 3d --no-files --out DIR`) dal 2 príspevky a 22 správ za 11,6 s s úplným manifestom (`messages 0, threads 2, thread_messages 22`). Markdown má sekcie `## thread "..."` s riadkami hlavičky (vytvorenie, posledná aktivita, správy, súbory, tagy) a správy v `messages.jsonl` majú pole `thread: {id, name, parent_id, tags}` s názvami tagov fóra.
  - Na reálnom účte (2026-11-04): `message_count` v zozname vlákien nezahŕňa štartovaciu správu príspevku fóra. Zoznam ukázal 9 a 11, stiahnutie vrátilo 10 a 12 správ (pozorované na 2 príspevkoch).

- **[PREDPOKLAD]**
  - Predpokladá sa, že všetky bežné textové kanály (typ 0) a oznamovacie kanály (typ 5) podporujú `threads/search` pre používateľský účet rovnako ako fórum a skúmaný vzorový textový kanál.
  - Pri neindexovaných vláknach môže nastať stavový kód HTTP 202 (na reálnom účte 2026-11-04 sa neobjavil, rovnako ako súkromné vlákna typu 12). Implementácia naň reaguje zaznamenaním problému `Stop.NOT_INDEXED` a čiastočným úspechom (kód 9).

## Dôsledky

- Používatelia a AI agenti majú plný prístup k obsahu fór a vlákien bez manuálnych zásahov.
- Výpadok prístupu k jednému vláknu nezničí celý export (kód 9 zaručuje transparentnosť a bezpečnosť automatizácií).
- Príkaz `discoop threads` poskytuje rýchlu a prehľadnú orientáciu v obsahu kanálov bez zbytočného sťahovania správ.
