# 0020: Prírastkové sťahovanie (`--since-last`)

- **Stav:** Prijaté
- **Dátum:** 2026-11-04
- **Rozhodol:** používateľ

## Kontext

Pri pravidelnom alebo opakovanom sťahovaní správ a exportovaní serverov (napr. na dennej báze) bolo doteraz potrebné manuálne špecifikovať časové okno (napr. `--from 24h` alebo `--from 7d`). To malo dve nevýhody:
1. Ak používateľ spustil nástroj po dlhšom čase než 24 hodín, prišiel o správy z medziobdobia. Ak naopak použil príliš široké okno, sťahoval duplicitné správy a zbytočne zaťažoval Discord API a lokálny disk.
2. Pri exportoch s prílohami mohol používateľ zaplniť lokálny disk bez predchádzajúceho varovania uprostred sťahovania dávky súborov.

Bolo potrebné zaviesť mechanizmus prírastkového (inkrementálneho) sťahovania správ cez prepínač `--since-last`, ktorý nadviaže presne na posledný úspešný export každého kanála a vlákna, a doplniť preventívnu kontrolu voľného miesta na disku s bezpečnou rezervou.

## Možnosti

1. **Ukladať stav synchronizácie do SQLite cache (`cache.db`).**
   Zamietnuté: Cache je podľa návrhu zahoditeľná (`cache.clear_cache()` pri odhlásení alebo zmene schémy) a slúži iba na rýchle vyhľadávanie názvov serverov, kanálov a vlákien. Stav synchronizácie musí prežiť zmazanie cache.
2. **Inkluzívna hranica `lowest = saved_id`.**
   Zamietnuté: Keďže `scrape.fetch_messages` filtruje `int(m["id"]) >= lowest`, inkluzívna hranica by opakovane stiahla a zduplikovala poslednú už videnú správu. Exkluzívna hranica `min_id = int(saved_id) + 1` zaručuje, že správa s uloženým ID sa už nezopakuje.
3. **Priebežné posúvanie stavu po každej prečítanej správe.**
   Zamietnuté: Ak export zlyhá uprostred behu (napr. chyba siete, rate limit, prerušenie používateľom, pád na ďalšom kanáli), stav by sa posunul a neuložené správy by sa pri ďalšom behu vynechali.
4. **Preskakovať všetky kanály s `Channel.last_message_id <= saved_id`, aj s ich vláknami.**
   Zamietnuté: Podľa analýzy probe vlákien (`docs/analyses/thread-probe-2026-11-04.md`, sekcie 6 a 11) ukazuje `last_message_id` na fórach na posledný vytvorený post a nové odpovede vo vláknach bežných textových kanálov sa pravdepodobne nepremietajú do `last_message_id` rodičovského kanála `[PREDPOKLAD]`. Preto by preskočenie textového kanála so zapnutými vláknami alebo fóra znamenalo stratu nových odpovedí vo vláknach. Prijatá je užšia verzia: textový alebo oznamovací kanál preskočí len svoje vlastné správy a jeho vlákna sa čítajú ďalej (sekcia Rozhodnutie).

## Rozhodnutie

- **Samostatný JSON súbor `sync-state.json` viazaný na ID účtu:**
  - Súbor je uložený v `paths.data_dir() / "sync-state.json"`, oddelene od `cache.db`, takže ho `clear_cache()` nezmaže.
  - Zápis je atomický (cez dočasný súbor `.tmp` a `os.replace` podľa vzoru `profiles.py`).
  - Pri poškodení súboru (neplatný JSON, neplatná štruktúra) nástroj nezlyhá výnimkou, ale vráti prázdny stav a vydá varovanie.
  - Presný formát:
    ```json
    {
      "version": 1,
      "accounts": {
        "<user_id>": {
          "channels": {
            "<channel_id>": {
              "last_message_id": "...",
              "updated": "<ISO UTC>"
            }
          }
        }
      }
    }
    ```
  - `user_id` sa zistí jedným volaním `GET /users/@me` pri použití `--since-last`.

- **Správanie `--since-last` a časové okná:**
  - Prepínač `--since-last` sa vzájomne vylučuje s `--from`, `--to` a `--last`. Ak sú zadané súčasne, vyhodí sa `ExitCode.BAD_ARGS` (kód 8) ešte pred volaním API.
  - Pre kanál so zaznamenaným stavom je okno od `saved_id + 1` po teraz (`current_now`). `Window.min_id = int(saved_id) + 1` definuje exkluzívnu spodnú hranicu, zatiaľ čo `Window.start = to_time(int(saved_id))` poskytuje zmysluplný čas pre hlavičku a kontrolu aktivity vlákien.
  - Pre kanál bez predchádzajúceho stavu sa použije predvolené 24-hodinové okno (`DEFAULT_SPAN`) a vypíše sa poznámka (`events.note`).
  - Pre vlákna: okno vlákna začína od jeho vlastného `thread_saved_id + 1` (ak má vlastný záznam v `channels`), inak od času `updated` rodičovského kanála (ak mal rodič stav), inak od 24 hodín.

- **Posunutie stavu až po úplnom a úspešnom behu:**
  - Stav sa aktualizuje až po `writer.close(complete=True)` pri exporte, resp. po úspešnom dokončení všetkých kanálov pri konzolovom výstupe.
  - Pri akejkoľvek výnimke (prerušenie, chyba) sa stav neposunie.
  - Stav sa aktualizuje iba pre kanály, ktoré neboli orezané limitom (`not truncated`), neboli preskočené (`not skipped`), nemali problém so zoznamom vlákien ani zlyhané vlákno, a žiadna ich príloha neskončila v stave `failed`.
  - Ak nepribudli nové správy, zachová sa predchádzajúce `last_message_id` (alebo `target.last_message_id`, ak je väčšie) a aktualizuje sa čas `updated` na `current_now`. Stav sa teda nikdy nevráti dozadu. Pre prázdny kanál pri prvom behu sa uloží syntetický snowflake pre `current_now`.
  - **Známe obmedzenie po obnove prerušeného behu:** ak sa prerušený export `--since-last` obnoví (ten istý príkaz pokračuje v `<cieľ>.partial`, ADR 0017), stav synchronizácie kanálov, ktoré uložil prerušený beh, sa neposunie. Obnovený beh ich nesťahuje znova, takže pre ne nemá čo zapísať. Najbližší `--since-last` ich stiahne znova od starého stavu: v ďalšom exporte budú správy, ktoré už predchádzajúci export obsahuje (duplicity), ale žiadna správa sa nestratí. `run_messages` na to pri obnove upozorní poznámkou (`events.note`: „The channels saved by the interrupted run keep their old sync state, ...“).
  - Odtlačok požiadavky, podľa ktorého sa export obnovuje (ADR 0017), zahŕňa aj `since_last`: beh `--since-last` nepokračuje v prerušenom normálnom behu a opačne.

- **Preskakovanie neaktívnych kanálov:**
  - Zoznam kanálov servera sa pri `--since-last` občerství (`refresh=True`), aby obsahoval aktuálne `Channel.last_message_id`.
  - Ak má kanál uložený stav, jeho `Channel.last_message_id` nie je prázdne a platí `Channel.last_message_id <= saved_id`, v kanáli samotnom nepribudla nová správa. Čo sa vtedy stane, závisí od druhu kanála:
    - **Kanál, ktorý nemôže mať vlákna (napr. hlasový), alebo beh s `--no-threads`:** kanál sa preskočí úplne, bez akýchkoľvek požiadaviek, a započíta sa do `outcome.unchanged` (poznámka „is unchanged since last sync: skipping.“).
    - **Textový (typ 0) alebo oznamovací (typ 5) kanál so zapnutými vláknami:** jeho vlastné správy sa nesťahujú (žiadna požiadavka na `/channels/{id}/messages`, `items = ()`), ale zoznam jeho vlákien sa načíta a vlákna sa stiahnu ako pri každom inom behu (vlákno od svojho uloženého ID, inak od času `updated` rodiča). `events.note` povie, že vlastné správy kanála sú nezmenené. Kanál sa nepočíta do `outcome.unchanged`, je vo výsledku (len bez vlastných správ). Jeho stav sa zachová (nikdy nejde dozadu) a posunie sa len čas `updated` a stavy vlákien.
    - **Fórum (typ 15) a media kanál (typ 16)** sa nepreskakujú nikdy ani sčasti: nemajú vlastné správy a ich `last_message_id` ukazuje na najnovší príspevok, takže nič nehovorí o novej odpovedi vo vlákne.
  - `[PREDPOKLAD]` `last_message_id` textového kanála je spoľahlivý: posunie sa s každou novou správou v kanáli. Probe vlákien to potvrdil na dvoch čitateľných vzorkách (`docs/analyses/thread-probe-2026-11-04.md`). Kontrola na reálnom účte 2026-11-04 ([analýza](../analyses/real-account-check-2026-11-04.md), iba čítanie, 25 čitateľných z 28 vzorkovaných textových a oznamovacích kanálov): pole sa rovnalo najnovšej dostupnej správe v 20 z 25 kanálov, v 4 z 25 ukazovalo na novšiu správu, než je najnovšia dostupná (pravdepodobne zmazaná správa, bezpečný smer pre pravidlo preskakovania), a v 1 z 25 (kanál aktívny v ten deň) bola najnovšia správa novšia než pole (pravdepodobne správa, ktorá prišla počas asi 2 minút vzorkovania, nedokázané). Stále ide o vzorku, nie o dôkaz. Ak by ho Discord niekedy oneskoroval, nová vlastná správa kanála by sa v behu mohla vynechať. Keďže okno ďalšieho behu začína od uloženého ID, objaví sa najskôr pri najbližšom `--since-last` po tom, čo v kanáli pribudne ďalšia správa a `last_message_id` sa posunie.
  - `[PREDPOKLAD]` Nové odpovede vo vláknach nemenia `last_message_id` rodiča (preto sa vlákna čítajú ďalej a fóra sa nepreskakujú). Kontrola z 2026-11-04 to nerozhodla: 3 vlákna v 7-dňovom okne vzorkovaných kanálov nemali správu novšiu než `last_message_id` rodiča (nepreukazné). Preto pravidlo ostáva opatrné: vlákna sa čítajú ďalej a fóra sa nepreskakujú.
  - `[OVERENÉ]` Na reálnom účte (2026-11-04) 2. beh `--since-last` na dvoch študijných textových kanáloch ohlásil, že vlastné správy kanála sú nezmenené, stiahol 0 správ, zavolal `threads/search` dvakrát na kanál (aktívne + archivované) a `/messages` kanála vôbec. Na dvoch fórach 1. beh stiahol 1 vlákno s 1 správou a uložil 3 záznamy stavu (2 fóra + 1 vlákno), 2. beh 0 správ. Stavový súbor bol presmerovaný do dočasného súboru. Nevidené: vlákno, ktoré medzi dvoma behmi dostane novú odpoveď.

- **Kontrola voľného miesta na disku:**
  - Pred každým stiahnutím príloh kanála (`writer.add_channel`) sa spočíta skutočná veľkosť sťahovaných súborov (`ExportWriter.bytes_to_download`): vynechajú sa súbory pri `--no-files`, súbory nad `--max-file-size`, súbory bez URL, príloha videná už skôr v exporte (aj príloha v kanáli a v jeho vlákne sa počíta raz) a súbory, ktoré už existujú v staging priečinku, v cieľovom priečinku alebo v starom zipe (`present`). Starý zip sa číta najviac raz.
  - Porovná sa potrebné miesto s voľným miestom na disku (`shutil.disk_usage`).
  - Ak nezostáva aspoň 50 MB bezpečnostná rezerva (`free_bytes - needed_bytes < 50 MB`), operácia sa odmietne s `ExitCode.ERROR` (kód 1) pred odoslaním požiadaviek na CDN.
