# 0018: Voliteľné diagnostické logovanie (--debug, --log)

- **Stav:** Prijaté
- **Dátum:** 2026-11-04
- **Rozhodol:** používateľ

## Kontext

Pri sťahovaní veľkých objemov správ a príloh dochádza k rôznym hraničným stavom (rate limity HTTP 429, prechodné chyby siete alebo 5xx, expirované podpísané CDN URL, odmietnutie prístupu 403). Doteraz nástroj buď ticho čakal, alebo vyhodil chybu bez detailného záznamu časovania a priebehu. Používateľ aj vývojár potrebujú diagnostický záznam na odladenie problémov.

Zároveň však Discoop pracuje s citlivými údajmi: Discord autentifikačný token, podpísané URL príloh s expiračnými tokenmi a kryptografickými podpismi (`ex`, `is`, `hm`), súkromné texty správ a mená používateľov či kanálov. Akékoľvek logovanie musí garantovať, že tieto údaje nikdy neuniknú do logov.

## Možnosti

1. **Použiť štandardné `logging.basicConfig` na root logger.** Zamietnuté: knižnice tretieho rádu (`httpx`, `httpcore`, `websockets`) by na úrovni DEBUG logovali celé požiadavky vrátane hlavičiek `Authorization` a kompletných URL s podpismi príloh.
2. **Logovať všetko vrátane tiel odpovedí.** Zamietnuté: v tele odpovedí sa nachádzajú citlivé texty správ, mená používateľov a tokeny.
3. **Štruktúrované diagnostické logovanie s prísnym allowlistom polí.** Zvolené: logger `discoop` je predvolene vypnutý (`propagate = False`), zapína sa explicitne cez `--debug` (stderr) alebo `--log FILE`. Logujú sa iba bezpečné diagnostické metadáta.

## Rozhodnutie

- Logovanie je **predvolene vypnuté**. Ak nie je zadané `--debug` ani `--log FILE`, nepripájajú sa žiadne handlery a nič sa nezapisuje ani nevypisuje.
- Spustenie a ukončenie riadia funkcie `setup_logging(debug: bool, log_file: Path | None)` a `teardown_logging()` v `src/discoop/logs.py`.
- Handlery sa pripájajú výhradne na logger `logging.getLogger("discoop")` s `propagate = False` a úrovňou `DEBUG`. Root logger ani `logging.basicConfig` sa nepoužívajú.
- `--debug` pridá `StreamHandler(sys.stderr)`. `--log FILE` pridá `FileHandler` v režime append s kódovaním UTF-8 (s automatickým vytvorením nadradených priečinkov).
- Loggery tretích strán (`httpx`, `httpcore`, `websockets`) sa v `setup_logging` explicitne stíšia na úroveň `WARNING`.
- `teardown_logging()` je idempotentné: zatvorí a odstráni všetky vytvorené handlery a vráti stav loggerov do pôvodného stavu.
- **Hlavička logu:** pri inicializácii s aktívnym handlerom sa zapíše hlavička s verziou nástroja (`discoop.__version__`), OS, verziou Pythonu a povinným bezpečnostným upozornením:
  `IDs in this log identify private servers and channels. Do not publish it.`
- **Formát riadkov:** ISO 8601 čas s milisekundami v UTC, úroveň, skrátený názov loggera (`api`, `scrape`, `attachments`, `discoop`), správa s kľúč=hodnota pármi:
  - `discoop.api`: metóda, cesta bez query reťazca (`path.split("?", 1)[0]`), názvy parametrov (`params=...`) a hodnoty výhradne pre povolené kľúče (`before`, `after`, `limit`, `archived`, `offset`, `with_counts`), číslo pokusu `attempt` (od 1), HTTP status kód, trvanie v milisekundách merané cez `time.perf_counter()`, dĺžka odpovede v bajtoch a prípadne počet položiek `items`. Pri 429 sa loguje `retry_after`, `global` a zdvojnásobený delay; pri pauzách sekundy a dôvod; pri tichých opakovaniach backoff a dôvod. Chyby >= 400 logujú top-level `code` a `message` (nie podobjekt `errors`). Transportné chyby logujú iba `type(e).__name__`, nikdy `str(e)`.
  - `discoop.scrape`: jeden riadok na stranu správ: ID kanála (`channel_id`), počet správ na strane, ID najstaršej a najnovšej správy a príznak `last=True/False`.
  - `discoop.attachments`: iba v `_download` a `_fetch`: ID prílohy, veľkosť, status, číslo pokusu, počet zapísaných bajtov a iba host z URL (`httpx.URL(url).host`).
- **Prísne zakázané (nikdy sa neloguje):**
  - Hlavičky requestu ani response (`Authorization` token).
  - Všetky ostatné `kwargs` z `request()` (napr. JSON body, tickety).
  - Celé telá odpovedí (`response.text`, `response.json()`).
  - Texty správ a mená používateľov.
  - Mená súborov, cesty súborov a query parametre podpísaných CDN URL (`ex`, `is`, `hm`).
  - Názvy kanálov a serverov (iba číselné ID).
  - Reprezentácie dataclassov (`FileJob`, `Attachment`, `Message`, `ChannelMessages`, `StoredToken`).

## Dôsledky

- `[OVERENÉ]` Diagnostické logovanie neovplyvňuje predvolený chod CLI ani existujúce správanie `DiscordAPI`.
- `[OVERENÉ]` Testy v `tests/test_logs.py` overujú, že token, podpisy príloh, mená súborov, parametre expirácie, texty správ ani názvy kanálov sa v logu nenachádzajú ani pri chybových stavoch (429, 500, 403).
- `[OVERENÉ]` Z logu je odstránený query reťazec URL, čím sa zabránilo úniku jednorazových podpisov.
- Záznam logu obsahuje číselné identifikátory (snowflake ID) serverov, kanálov a správ. Hoci neobsahuje texty správ, samotné ID identifikujú privátne servery a štruktúru kanálov, preto log nesmie byť zverejňovaný (na čo explicitne upozorňuje hlavička každého logu).
