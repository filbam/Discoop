# 0014: TUI ovládané klávesnicou, jeden strom, farby terminálu

- **Stav:** Prijaté
- **Dátum:** 2026-11-03
- **Rozhodol:** používateľ

## Kontext

Používateľ 2026-11-03 vyskúšal `discoop ui` (ADR 0013) a nahlásil:
- veľa tlačidiel nemá viditeľný text,
- navigácia šípkami nefunguje,
- rozhranie zadrháva.

Príčina prázdnych tlačidiel: v CSS mali `height: 1`, ale Textual im predvolene dáva vysoký rámik. Rámik zabral celý
riadok a pre text nezostalo miesto.

Používateľ požaduje (P18, P19, P20): primárne ovládanie klávesnicou (šípky) s myšou ako doplnkom, predvolene
zbalené zoznamy kanálov a krajšie, jednoduchšie, viac terminálové a uhladené rozhranie.

## Možnosti

1. **Tri panely** (servery | kanály | export) s pevnou tmavou témou. Zamietnuté.
2. **Jeden strom** (servery, kategórie, kanály) s témou podľa farieb terminálu. Zvolil používateľ.

## Rozhodnutie

### Rozloženie
- Servery, kategórie a kanály sú v **jednom strome** ako v správcovi súborov. Všetko je predvolene zbalené.
- Vpravo je panel **Export** (zoznam výberu a formulár).
- Dole je log, pod ním riadok s ekvivalentným CLI príkazom a riadok s klávesmi (Footer, klikateľný myšou).
- V úzkom okne sa ukazuje jeden panel naraz.

### Farby a vzhľad
- Téma Textual `ansi-dark` používa farby a pozadie terminálu. Inú tému možno zvoliť cez Ctrl+P.
- Bez emoji a bez veľkých tlačidiel. Ovládacie prvky majú výšku jeden riadok.

### Klávesy

| Kláves | Kde | Akcia |
|---|---|---|
| ↑ ↓ | všade | pohyb v strome, zozname a formulári (medzi riadkami) |
| → | strom | rozbalí uzol. Na nenačítanom serveri načíta kanály. Na rozbalenom uzle skočí na prvé dieťa |
| ← | strom | zbalí uzol. Na zbalenom uzle skočí na rodiča |
| ← → | výberový riadok formulára | zmení hodnotu (`safe/fast`, `folder/zip/preview`, formát, prílohy, systémové správy, predvoľba okna) |
| Space | strom | vyberie kanál alebo všetky vyberateľné kanály kategórie |
| Enter | strom | kategória/server: rozbalí/zbalí. Kanál: vyberie |
| Enter | formulár | potvrdí pole. Na riadku Start spustí export |
| Tab / Shift+Tab, 1 2 3 | globálne | prepne panel |
| / | globálne | filter stromu |
| e | strom alebo zoznam výberu | vlastné časové okno kanála |
| x / Delete | zoznam výberu | odoberie kanál z výberu |
| a | strom | vyberie všetky zobrazené kanály servera |
| r | strom | znova načíta kanály servera z Discordu |
| R | globálne | znova načíta zoznam serverov |
| L | globálne | načíta kanály všetkých serverov (safe tempo, Esc zastaví) |
| F5 | globálne | spustí export |
| Esc | globálne | zastaví bežiacu operáciu, opustí filter, zavrie dialóg |
| c | globálne | skopíruje CLI príkaz |
| F1 / ? | globálne | Help |
| F2 | globálne | Nastavenia |
| F3 | globálne | Login |
| Ctrl+P | globálne | príkazová paleta (zmena témy) |
| q | globálne | koniec. Počas behu najprv zastaví prácu |

### Pravidlá správania
- Pohyb kurzorom nikdy nevolá Discord. Sieť volá len explicitná akcia: →/Enter na nenačítanom serveri, r, R, L a F5.
- Naraz beží najviac jedna sieťová operácia.
- Pauzy safe režimu sa dajú prerušiť cez Esc.

## Dôsledky

- ADR 0013 ostáva platné pre spoločnú servisnú vrstvu (`service.py`), lazy import, spúšťanie a zoskupovanie úloh.
  Rozloženie TUI z neho nahrádza tento ADR.
- Help v TUI (F1 / ?) sa riadi tabuľkou klávesov z tohto ADR.
- CSS musí dávať tlačidlám a ovládacím prvkom explicitne `border: none` (alebo primeranú výšku), aby text nezmizol.
- Dlhé operácie musia bežať vo workeroch a pohyb kurzorom nesmie spúšťať sieťové volania, čo rieši zadrhávanie.
