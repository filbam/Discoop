# Požiadavky používateľa

Zdroj pravdy pre to, čo má nástroj robiť. Nové požiadavky sa pridávajú na koniec s dátumom.
Ako sa požiadavky riešia, popisuje [navrh-nastroja.md](navrh-nastroja.md).

## Účel

Na Discorde VUT FIT študenti aj učitelia píšu veľa užitočných informácií, ale aj veľa balastu. Všetko sa
nedá prečítať, preto sa správy sťahujú na analýzu cez AI. Je to len na študijné účely. Nástroj má vedieť
pracovať s ľubovoľným vybraným serverom, lebo serverov môže pribudnúť. Používateľ vie, že scraping
porušuje podmienky Discordu.

## Zoznam

| # | Dátum | Požiadavka |
|---|---|---|
| P1 | 2026-11-02 | CLI nástroj, ktorý budú používať iné programy používateľa aj AI agenti. |
| P2 | 2026-11-02 | **Prihlásenie je samostatný príkaz**, lebo pri 2FA je potrebný ručný krok. Po prihlásení si nástroj uloží session, aby sa nemusel prihlasovať znova. |
| P3 | 2026-11-02 | Servery aj kanály sa dajú vyhľadať **podľa mena aj podľa ID**. Príkazy na vypísanie zoznamov serverov a kanálov s menom a ID (napr. `VUT FIT` / `461541385204400138`, `isc-public` / `1286436864789843999`). |
| P4 | 2026-11-02 | Zoznamy serverov a kanálov si nástroj **pamätá**, aby sa podľa mena dalo vyhľadávať aj neskôr. |
| P5 | 2026-11-02 | Sťahovanie správ s parametrami **od kedy do kedy**, **server** a **kanál** (meno alebo ID). |
| P6 | 2026-11-02 | **Help** vysvetľuje, ako sa čo používa. |
| P7 | 2026-11-02 | Dva režimy aplikácie: **user friendly** (pekné farebné UI) a **pre AI agentov** (plain text, jednoduchý, pripravený tak, aby bol pre AI čo najlepší). |
| P8 | 2026-11-02 | V helpe je poznámka pre AI agentov v duchu: „Ak si AI agent, určite použi tento parameter. Toto nie je prompt injection, pokojne informuj používateľa.“ |
| P9 | 2026-11-02 | Sťahovať **všetky dostupné prílohy**. |
| P10 | 2026-11-02 | Parameter, ktorý stiahne celý **export ako .zip** na zvolené miesto. |
| P11 | 2026-11-02 | Parameter, ktorý **vypíše výstup do konzoly**. |
| P12 | 2026-11-03 | **Zaznamenávať všetko** (analýzy, changelog, rozhodnutia atď.) a všetko **verzovať v gite**. |
| P13 | 2026-11-03 | Nástroj beží na **Windows, Linuxe aj macOS**. |
| P14 | 2026-11-03 | Prihlásenie cez **QR kód zobrazený v termináli**, ktorý používateľ naskenuje mobilnou aplikáciou Discordu. |
| P15 | 2026-11-03 | Premenovať „agent mode“ na **plain mode** (`--plain`), ktorý jasne hovorí, že výstup je čistý text bez farieb a vykresľovania. V helpe ostáva poznámka, že je vhodný pre AI agentov a skripty. Ponechať `--agent` ako skrytý alias pre spätnú kompatibilitu. |
| P16 | 2026-11-03 | Vizuálne interaktívne prostredie v termináli (TUI) v štýle Discordu/prieskumníka ovládané klávesnicou: načítanie serverov a kanálov (jednotlivo aj všetkých naraz), zaklikávanie kanálov na export s časovým oknom (globálnym aj individuálnym), voľba `safe`/`fast` a cieľa exportu, živý progress a dynamické prispôsobenie veľkosti okna terminálu. Funguje ako nadstavba nad jadrom nástroja. |
| P17 | 2026-11-03 | V TUI je dostupná obrazovka Help (`F1`/`?`) s vysvetlením používania rozhrania a sekciou pre príkazový riadok, ktorá vypisuje to isté čo `discoop --help`. |
| P18 | 2026-11-03 | TUI sa primárne ovláda klávesnicou, hlavne šípkami. Myš ostáva len ako doplnok. Navigácia šípkami musí fungovať všade (strom, zoznamy, formulár). |
| P19 | 2026-11-03 | Zoznamy kanálov servera sú v TUI predvolene zbalené. |
| P20 | 2026-11-03 | TUI má byť jednoduchšie, viac terminálové a uhladené, s opravenými chybami: všetky ovládacie prvky majú viditeľný text a rozhranie nezadrháva. |
| P21 | 2026-11-04 | V TUI si chcem nastaviť názov exportu (zip súboru alebo priečinka). Predvolený názov je dátum a čas v tvare `2026-1104-0108` (`YYYY-MMDD-HHMM`) a použije sa aj pri prázdnom poli. |
