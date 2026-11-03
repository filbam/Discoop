# 0012: Premenovanie „agent mode“ na „plain mode“ (`--plain`)

- **Stav:** Prijaté
- **Dátum:** 2026-11-03
- **Rozhodol:** používateľ

## Kontext

Nástroj `discoop` od začiatku obsahoval dva režimy výstupu (P7):
- **Human mode:** interaktívny výstup s farbami (Rich), tabuľkami, stromami kategórií a progress barmi.
- **Agent mode:** textový výstup bez farieb, s tabulátormi a štruktúrovanými chybami na stderr.

Pomenovanie „agent mode“ (`--agent`) však evokovalo, že režim je určený výlučne pre AI agentov. V skutočnosti je rovnaký režim potrebný pre akékoľvek iné programy, skripty (bash, Python subprocess) alebo presmerovanie do súboru či rúry (`|`), pretože odstraňuje ANSI escape kódy a grafické prvky.

## Rozhodnutie

1. **Nový primárny názov:** Režim sa premenúva na **Plain mode** s prepínačom **`--plain`**.
   - Názov jasne vyjadruje, že ide o prostý text bez farieb, terminálových efektov a grafického formátovania.
2. **AI agenti v dokumentácii a helpe:**
   - V texte helpu ostáva explicitne uvedené, že `--plain` je ideálny pre AI agentov a automatizované skripty (menej tokenov, jednoduchý parsing).
   - Poznámka `NOTE FOR AI AGENTS` v helpe zostáva a odporúča agentom použiť `--plain` (alebo `--agent`).
3. **Spätná kompatibilita:**
   - Prepínač `--agent` zostáva funkčný ako skrytý alias pre `--plain`.
   - Podporované sú premenné prostredia `DISCOOP_PLAIN` aj `DISCOOP_AGENT`.
   - Pri presmerovaní výstupu mimo terminálu (`not sys.stdout.isatty()`) sa plain mode naďalej aktivuje automaticky.

## Dôsledky

- Zrozumiteľnejšie rozhranie pre používateľov aj programátorov: `--plain` je štandardné pomenovanie v moderných CLI nástrojoch.
- Spätná kompatibilita pre existujúce skripty a testy, ktoré odovzdávajú `--agent`.
- V kóde vzniká alias `detect_plain_mode` a `Output(plain=...)` so zachovaním atribútu `Output.agent`.
