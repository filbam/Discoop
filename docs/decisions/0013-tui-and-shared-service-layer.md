# 0013: Interaktívne terminálové rozhranie (TUI) a spoločná servisná vrstva

- **Stav:** Prijaté, rozloženie TUI nahradené ADR 0014
- **Dátum:** 2026-11-03
- **Rozhodol:** používateľ

> **Poznámka (2026-11-03):** Spoločná servisná vrstva (`service.py`), lazy import Textualu, spúšťanie a zoskupovanie úloh
> ostávajú platné. Rozloženie TUI (tri stĺpce, záložky), ovládanie a Help sa riadia
> [ADR 0014](0014-tui-keyboard-one-tree.md).

## Kontext

Nástroj `discoop` disponuje bohatým príkazovým rozhraním (CLI) s podporou `--human` a `--plain` režimov. Používateľ však pre `--human` režim chcel vizuálne prostredie v termináli ovládané klávesnicou (šípky, Enter, Space) v štýle Discordu / prieskumníka, s:
- tlačidlami na načítanie serverov a kanálov (jednotlivo aj všetkých naraz s bezpečným tempovaním a možnosťou prerušenia),
- výberom kanálov na export naprieč rôznymi servermi,
- nastavením časového okna (globálne pre všetky kanály aj individuálne per-kanál),
- voľbou režimu sťahovania (`safe` / `fast`) a cieľa exportu (priečinok alebo ZIP archív),
- responzívnym layoutom pri zmene veľkosti okna terminálu,
- vstavanou obrazovkou Help (kláves `F1` / `?`), ktorá okrem vysvetlenia ovládania TUI obsahuje aj kompletný živý výpis `discoop --help` vrátane podpríkazov.

Zároveň bolo kľúčovou požiadavkou, aby TUI nevytváralo duplicitu v aplikačnej logike a bolo postavené ako tenká nadstavba nad jadrom nástroja.

## Rozhodnutie

1. **Knižnica `Textual`:**
   - Pre TUI bola zvolená knižnica `Textual` (od autorov `Rich`), ktorá poskytuje moderný reaktívny komponentový model, flexbox/grid layout, CSS štýlovanie (`discoop.tcss`), responzívny layout (3 stĺpce v širokom okne, záložkový systém v úzkom okne), stromové komponenty (`Tree`), formuláre a background workery pre asynchrónne operácie bez zamŕzania používateľského rozhrania.
   - Textual sa načítava výhradne pri spustení TUI (`lazy import`), aby nepredlžoval štart bežných CLI príkazov.

2. **Spúšťanie:**
   - TUI sa spúšťa príkazom `discoop ui` alebo prepínačom `discoop --ui`.
   - Samotné spustenie `discoop` bez argumentov naďalej vypisuje nápovedu (`--help`), čím sa zachováva predvídateľné CLI správanie.
   - V `--plain` režime alebo pri spustení v prostredí bez interaktívneho terminálu (`not sys.stdout.isatty()`) príkaz `discoop ui` skončí s chybou a návratovým kódom `8` (`BAD_ARGS`).

3. **Spoločná servisná vrstva (`service.py`):**
   - Orchestrácia biznis logiky nástroja (`list_servers`, `list_channels`, `load_all`, `run_messages`) je vyčlenená do samostatného modulu `src/discoop/service.py`.
   - CLI aj TUI volajú tie isté funkcie a zdieľajú rovnaké dátové štruktúry, validácie a prácu s cache/API.
   - Každá naplánovaná úloha v TUI priamo zodpovedá jednému CLI príkazu `discoop messages ...`. Tento ekvivalentný príkaz sa naživo zobrazuje v spodnej lište TUI, čím používateľa učí používať aj priame CLI rozhranie.

4. **Zoskupovanie úloh podľa časového okna:**
   - Kanály so zhodným časovým oknom tvoria jednu exportnú úlohu (jedno volanie sťahovania).
   - Ak existuje len jedna úloha, export sa uloží priamo do zvolenej cieľovej cesty (priečinok alebo ZIP).
   - Ak je úloh viac (napr. niektoré vybrané kanály majú nastavené vlastné časové okno), každá úloha sa exportuje do očíslovaného podpriečinka (`cieľ/01-7d/`, `cieľ/02-...`) alebo samostatného ZIP archívu (`cieľ-01-7d.zip`), aby nedochádzalo ku kolíziám manifestov a dát.

5. **Vstavaný Help:**
   - Stlačenie `F1` alebo `?` otvorí modálne okno s pomocníkom.
   - Okno obsahuje dve záložky:
     1. *Ovládanie TUI:* prehľad klávesových skratiek, navigácie v stromoch a formulároch, význam ikon a stavov.
     2. *CLI referencia (`discoop --help`):* dynamicky generovaný výstup hlavného helpu a helpu všetkých podpríkazov priamo z Typer aplikácie, zhodný s výstupom v konzole.

## Dôsledky

- **Čistá architektúra:** Servisná vrstva `service.py` oddeľuje prezentačnú logiku (CLI formátovače, TUI widgety) od práce s Discord API, SQLite cache a exportným subsystémom.
- **Nulová duplicita:** CLI aj TUI používajú rovnaké funkcie pre načítanie serverov, kanálov aj samotné sťahovanie správ.
- **Rýchly štart CLI:** Vďaka lazy importu `Textual` nie je bežné volanie `discoop` zaťažené réžiou inicializácie TUI frameworku.
- **Vysoký používateľský komfort:** Používateľ nemusí manuálne kopírovať alebo hľadať ID kanálov v konzole – v TUI stačí vybrať servery a kanály interaktívne, nakonfigurovať parametre a spustiť export s prehľadným živým progressom.
