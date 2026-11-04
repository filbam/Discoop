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
| X | zoznam výberu | vymaže celý výber |
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

Kláves `X` bol doplnený 2026-11-04 po kontrole, lebo hromadné zrušenie výberu zmizlo spolu s tlačidlami.

### Pravidlá správania
- Pohyb kurzorom nikdy nevolá Discord. Sieť volá len explicitná akcia: →/Enter na nenačítanom serveri, r, R, L a F5.
- Naraz beží najviac jedna sieťová operácia.
- Pauzy safe režimu sa dajú prerušiť cez Esc.

## Dôsledky

- ADR 0013 ostáva platné pre spoločnú servisnú vrstvu (`service.py`), lazy import, spúšťanie a zoskupovanie úloh.
  Rozloženie TUI z neho nahrádza tento ADR.
- Help v TUI (F1 / ?) sa riadi tabuľkou klávesov z tohto ADR.
- Ovládacie prvky sa robia cez `compact=True` (bez rámika, výška jeden riadok), nie cez `height: 1`, aby text nezmizol.
- Dlhé operácie musia bežať vo workeroch a pohyb kurzorom nesmie spúšťať sieťové volania, čo rieši zadrhávanie.

## Doplnenie 2026-11-04

Pôvodné rozhodnutie sa nemení. Doplnenie opisuje, čo pribudlo v 2. kole (P30) popri tabuľke klávesov vyššie. Tabuľka v Helpe (`GUIDE_KEYS` v `tui/modals.py`) tieto klávesy už obsahuje.

### Ďalšie klávesy

| Kláves | Kde | Akcia |
|---|---|---|
| P | globálne | uloží aktuálny výber, časové okno a režim ako pomenovaný profil (`profiles.json` v konfiguračnom priečinku, rovnaký súbor ako `discoop messages --save-profile`) |
| p | globálne | načíta uložený profil: nahradí výber, časové okno a režim. Ručne upravený profil so zlými typmi hodnôt TUI toleruje |
| o | globálne | otvorí priečinok posledného exportu v správcovi súborov (pri zipe priečinok, v ktorom leží). Je aktívny až po dokončenom exporte a nie počas behu úlohy. Náhľad (Target=preview) nič neukladá, preto nie je „posledným exportom“ |

- `L` ostáva „načíta kanály všetkých serverov“. Na profily nie je.
- `P`, `p` a `o` nevolajú Discord, pravidlá správania vyššie sa nemenia.

### Pripony riadkov kanálov v strome

- Každý riadok kanála má stlmenú príponu zarovnanú doprava: čas od poslednej aktivity (`now`, `5m`, `3h`, `2d`, `4mo`, `1y`, podľa `Channel.last_message_id`) a pri kanáli, ktorý sa z tohto účtu už exportoval, dátum posledného exportu (`exp 11-03`, miestny dátum, s rokom, ak je z iného roka). Kategórie a servery ju nemajú (server má vpravo počet kanálov, `not loaded` alebo `no access`).
- Ak je riadok príliš úzky, vypadne najprv dátum exportu, potom aj aktivita. Názov kanála sa kvôli prípone nikdy nekráti.
- Pripony sa obnovia po exporte, po obnovení uloženého stavu a každých 60 s. Dátum posledného exportu sa ukladá v `tui-state.json` (podľa ID kanála a účtu) a pri náhľade sa nezapisuje.
