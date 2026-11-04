# 0017: Spoľahlivý export a čiastočný úspech

- **Stav:** Prijaté
- **Dátum:** 2026-11-04
- **Rozhodol:** používateľ

## Kontext

Pri sťahovaní a exportovaní viacerých Discord kanálov alebo veľkých serverov dochádza k situáciám, kedy proces zlyhá uprostred (výpadok siete, neočakávaná chyba, prerušenie používateľom cez Ctrl+C alebo Cancel v TUI), prípadne niektoré kanály nemožno prečítať (chýbajúce oprávnenia HTTP 403, neexistujúci kanál HTTP 404) alebo zlyhá stiahnutie niektorej prílohy.

Doterajší prístup mal niekoľko nedostatkov:
1. Ak proces spadol napríklad v 30. kanáli zo 40, všetka doterajšia práca sa stratila alebo ostala v poškodenom stave, a celý export sa musel opakovať od začiatku.
2. Zápis priamo do cieľového priečinka alebo prepisovanie existujúceho súboru mohlo poškodiť predchádzajúci hotový export.
3. Chýbajúci kanál alebo zlyhaná príloha buď zhodili celý proces chybou, alebo skončili s kódom 0 (úspech), čo maskovalo neúplnosť dát pred používateľom aj skriptami/AI agentmi.
4. Celý export držal všetky stiahnuté správy v pamäti až do konca, čo pri veľkých serveroch viedlo k vysokej pamäťovej náročnosti.

## Možnosti

1. **Manuálny prepínač `--resume`.** Používateľ by musel sám vedieť, že predchádzajúci beh bol prerušený, a zadať prepínač. Zamietnuté: zvyšuje zložitosť rozhrania a vyžaduje manuálny zásah tam, kde je zámer používateľa jasný.
2. **Ignorovať chyby jednotlivých kanálov a vrátiť kód 0.** Zamietnuté: kód 0 deklaruje úplný úspech; skripty a automatizácie by považovali neúplný export za kompletný.
3. **Pád na prvej chybe (kód 1/chyba).** Zamietnuté: pri exporte viacerých kanálov nechceme zahodiť celý beh len preto, že k jednému kanálu nemá používateľ prístup.
4. **Automatická obnova cez dočasné priečinky `<cieľ>.partial`, zápis po kanáloch a nový kód ukončenia `ExitCode.PARTIAL = 9`.** Zvolené: zápis priebežne ukladá dáta po kanáloch, cieľový súbor/priečinok publikuje až po dokončení, rovnaký príkaz automaticky nadviaže na rozpracovaný export a neúplný výsledok je jasne signalizovaný kódom 9.

## Rozhodnutie

- **Zápis po kanáloch a staging priečinok `<cieľ>.partial`:**
  - Trieda `ExportWriter` (`src/discoop/export.py`) zapisuje exportované dáta po jednotlivých kanáloch priamo na disk, namiesto držania celej histórie v pamäti.
  - Všetky priebežné dáta sa zapisujú do dočasného umiestnenia `<cieľ>.partial` (pri zip archíve `<názov>.zip.partial`).
  - Až po úspešnom dokončení všetkých požadovaných kanálov (`writer.close(complete=True)`) sa staging priečinok alebo zip atomicky presunie na cieľovú cestu. Predchádzajúci hotový export sa nikdy nepoškodí prerušeným behom.
  - Manifest exportu obsahuje polia `request`, `targets`, `skipped_channels`, `interrupted`, `partial` a `complete`.
  - Ak je zadané `--max-tokens N`, časti `parts/part-NNN.md` (delenie `messages.md` cez `split.split_markdown`) sa vytvoria až pri `close(complete=True)`, ešte pred publikáciou, do staging priečinka. Do cieľa idú spolu so zvyškom exportu (do priečinka aj do zipu rovnako, ako záznamy `parts/part-NNN.md`), takže pád pred koncom nenechá v cieli žiadne `parts/`. Pri publikácii do priečinka s predchádzajúcim exportom sa jeho staré `parts/part-*.md` nahradia novými (alebo zmažú, ak nové nie sú: patria k `messages.md`, z ktorého vznikli). Iné súbory v `parts/` ostanú. Časti nie sú v manifeste a `--max-tokens` nie je súčasťou odtlačku požiadavky (časti vznikajú až z hotového `messages.md`).

- **Automatická obnova (resume) bez nového prepínača:**
  - Ak pri spustení exportu existuje nedokončený priečinok `<cieľ>.partial` a jeho odtlačok (`request_fingerprint`) zodpovedá aktuálnej požiadavke (zhodné ciele, časové okno, voľby exportu), Discoop automaticky pokračuje tam, kde prestal.
  - Odtlačok (a rovnaké polia v manifeste v `request`) pokrýva servery, ID kanálov v poradí, okno, `--last`, `--max-messages`, `--include-system`, `--no-files`, `--max-file-size` a od 2026-11-04 aj `threads` (`--no-threads`) a `since_last` (`--since-last`). Prerušený export s vláknami teda nepokračuje beh s `--no-threads` (uložené kanály by vlákna nemali) a beh `--since-last` nenadviaže na normálny a opačne: začne odznova. Režim sťahovania (`safe`/`fast`) a `--max-tokens` odtlačok nemenia.
  - Hotové kanály sa preskočia – ich správy ani prílohy sa znova nesťahujú.
  - Udalosť `Events.resumed(done, total)` informuje CLI aj TUI o počte prevzatých kanálov. CLI vypíše poznámku: `Continuing an unfinished export: N of M channels are already saved.`
  - Relatívne časové okno (napr. `--from 1d`) sa pri obnove počíta od času vytvorenia pôvodného behu (`Resume.created`), aby sa nezmenil obsah okna.
  - Voľba `--print` v kombinácii s obnovou, kde už existujú hotové kanály, sa odmietne s `ExitCode.BAD_ARGS` (kód 8) ešte pred sťahovaním správ (zoznam kanálov sa môže načítať z cache alebo z API a pri `--since-last` sa zistí ID účtu, správy sa ale ešte nesťahujú), pretože správy hotových kanálov nie sú v pamäti na vytlačenie.

- **Prerušenie behu:**
  - Pri prerušení (používateľské Ctrl+C, `Cancelled` v TUI alebo neočakávaná výnimka) sa `ExportWriter` uzavrie s `complete=False`.
  - Vyvolá sa udalosť `Events.interrupted(saved, total, path)`, ktorá používateľa informuje: `Saved N of M channels in <cesta>.partial. Run the same command again to continue.`
  - Prerušenie cez Ctrl+C (`KeyboardInterrupt`) sa v CLI neprehltne a aplikácia skončí so štandardným unixovým kódom 130.

- **Kód ukončenia `ExitCode.PARTIAL = 9`:**
  - Ak beh úspešne dokončí spracovanie všetkých dostupných kanálov, ale výsledok nie je stopercentne úplný, CLI skončí s kódom 9 (`ExitCode.PARTIAL`).
  - Za čiastočný výsledok sa považuje:
    - Kanál preskočený pre chýbajúce oprávnenie (HTTP 403 `NO_ACCESS`) alebo neexistenciu (HTTP 404 `NOT_FOUND`), ak bolo zadaných viacero cieľov (ak je cieľ len jeden, zlyhá priamo s danou chybou).
    - Akákoľvek príloha, ktorej stiahnutie zlyhalo (`status == FAILED`).
  - Za čiastočný výsledok sa **nepovažujú** súbory vynechané zámerne používateľom cez `--no-files` alebo preskočené pre prekročenie limitu veľkosti `--max-file-size` (v týchto prípadoch vracia CLI kód 0).
  - Pri čiastočnom výsledku CLI vypíše radu vysvetľujúcu, čo chýba, a odporučí opätovné spustenie príkazu na dotiahnutie chýbajúcich častí.
  - Súhrn po dokončení obnoveného exportu berie celkové počty kanálov, správ a príloh z manifestu exportu (`exported.manifest["counts"]`) a úloh (`exported.jobs`), nie len z výsledkov aktuálneho behu.

- **Podpora v TUI:**
  - TUI zachytáva udalosti `resumed` a `interrupted` a zobrazuje ich v stavovom riadku a v logu.
  - Pri čiastočnom výsledku alebo prerušení TUI vypíše zoznam preskočených kanálov a radu na pokračovanie stlačením `F5`.
  - Funkcia `_keep_export_name()` zabezpečí, že po prerušení alebo čiastočnom výsledku sa automaticky generovaný názov exportu zafixuje v poli `Name`, takže stlačenie `F5` automaticky nadviaže na rozpracovaný `<cieľ>.partial` namiesto vytvorenia nového názvu podľa novej minúty.

## Dôsledky

Značka `[OVERENÉ]` pri nasledujúcich bodoch znamená overené testami proti falošnému Discordu (`httpx.MockTransport`) a lokálnemu súborovému systému. Skutočný výpadok siete takto overený nebol.

Na reálnom účte (2026-11-04, [analýza](../analyses/real-account-check-2026-11-04.md)) sa navyše overilo:
- Prerušenie skriptom (`KeyboardInterrupt` vyvolaný z udalostí CLI pri skutočnom sťahovaní po sieti) po 2. z 3 kanálov: kód 130, `<cieľ>.partial` s manifestom `complete: false, interrupted: true` a 2 kanálmi, cieľ neexistoval, hláška „Saved 2 of 3 channels in ....partial. Run the same command again to continue.“ Ten istý príkaz potom stiahol už len 3. kanál, publikoval cieľ (`complete: true`), zmazal `.partial` a skončil s kódom 0.
- Prerušenie uprostred prvého kanála exportu jedného fóra (počas jeho 2. vlákna): kód 130, žiadny `.partial`, žiadny cieľ, žiadne súbory `.part`. Opakovanie prebehlo normálne.
- Export fóra (2 príspevky, 22 správ) skončil s úplným manifestom. Zip s `--max-tokens` (3 časti) bol platný a časti neboli v manifeste.
- **Skutočný signál Ctrl+C z konzoly** (počas čakania na sieť ani počas sťahovania súboru) sa na reálnom účte neskúšal. Pozorovanie: v oboch prerušeniach `main()` nevypísal riadok „Interrupted.“, kód 130 vyšiel aj bez neho (vetva s `out.error(...)` vyzerá nedosiahnuteľná, neškodné).

- `[OVERENÉ]` Export sa zapisuje po kanáloch priamo na disk, nie z jedného celku v pamäti.
- `[PREDPOKLAD]` Nízka pamäťová stopa aj pri exportoch stoviek tisíc správ: testy ju nemerali. Delenie `--max-tokens` načíta hotový `messages.md` naraz do pamäte.
- `[OVERENÉ]` Predchádzajúci hotový export v cieľovom priečinku alebo zip súbore nie je nikdy prepísaný ani poškodený nedokončeným behom.
- `[OVERENÉ]` Prerušený beh je možné okamžite obnoviť spustením toho istého príkazu bez opätovného sťahovania už hotových kanálov a príloh.
- `[OVERENÉ]` Kód 9 umožňuje skriptom a AI agentom jednoznačne rozlíšiť úplný úspech (0), čiastočný úspech (9) a fatálnu chybu.
- `[OVERENÉ]` Ctrl+C naďalej vracia kód 130 pri zachovaní staging priečinka `.partial` pre budúcu obnovu (na reálnom účte overené prerušením vyvolaným skriptom, nie signálom konzoly).
