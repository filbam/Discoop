# Prototyp: QR login a overenie API

Jednorazové overenie otvorených bodov z [docs/analyzy/](../docs/analyzy/). Všetko spúšťaš ty, lebo to beží
na tvojom Discord účte. Výstupy idú do `prototype/out/`, ktorý git ignoruje.

## 1. Prihlásenie

V termináli (Windows Terminal alebo PowerShell) v koreni projektu spusti:

```
uv run discoop login --trace prototype/out/login-trace.jsonl
```

1. Zobrazí sa QR kód s odpočtom. V mobilnej aplikácii Discord ho naskenuj cez **Settings → Scan QR Code**.
2. Terminál ukáže, kto sa prihlasuje. Prihlásenie potvrď na telefóne.
3. Nástroj vypíše `Logged in as …`. Token je uložený vo Windows Credential Manager.

Kontrola prihlásenia:

```
uv run discoop status
```

**Ak by QR kód nešiel naskenovať,** napríklad pri nečitateľnom vykreslení, daj mi vedieť a priblíž
terminál (`Ctrl` + `-`/`+`).

**Ak Discord vypýta captchu** alebo login zlyhá inak, pošli mi výpis a `prototype/out/login-trace.jsonl`.
Náhradná cesta je `uv run discoop login --token`.

## 2. Probe

```
uv run python prototype/probe.py
```

**Čo probe robí:**
- Pošle približne 20 requestov, jeden za sekundu, na VUT FIT a #2bit-general. Fórum `help-center` si nájde sám.
- Nič nezapisuje: žiadne správy, `ack` ani reakcie. Jediný POST je `/attachments/refresh-urls`, ktorý iba vráti nový odkaz.
- Z CDN prečíta prvý 1 KB jednej prílohy, aby overil, že netreba token. Nič neukladá.

**Výstup:**
- súhrnná tabuľka v konzole,
- report `prototype/out/probe-<čas>.json`. Je v ňom len štruktúra: žiadny token, mená, texty správ, ID
  používateľov ani URL príloh.

Ciele sa dajú zmeniť cez `--guild`, `--channel`, `--forum` a tempo cez `--delay`.

## 3. Potom

Napíš mi, že je hotovo. Prečítam `prototype/out/*` a výsledky zapíšem do analýz a denníka.

Na odhlásenie slúži `uv run discoop logout`. Reláciu v Discorde zrušíš v **Settings → Devices**.

## 4. Probe vlákien

```
uv run python prototype/probe_threads.py
```

**Čo probe vlákien robí:**
- Zameriava sa na správanie API pri vláknach a fórach: veľkosti strán pri vyhľadávaní vlákien (`limit` 25 vs 50), dostupnosť stránkovania cez `offset` (0, 25, 100, 500 a koniec), kontrolu prípadnej 202 Accepted („not indexed“) odpovede, prítomnosť a atribúty súkromných vlákien (typ 12), porovnanie `total_results` so skutočným počtom vrátených a unikátnych vlákien naprieč stránkami, a kontrolu `last_message_id` v kanáloch servera.
- Posiela výhradne GET requesty v tempe 1 request za sekundu (`--delay 1.0`). Nič nezapisuje ani nemení.
- Všetko spúšťa používateľ na svojom účte.

**Výstup:**
- súhrnná tabuľka v konzole,
- report `prototype/out/probe-threads-<čas>.json`. Obsahuje iba štruktúru: typy, počty, názvy polí a stavové kódy. Žiadny token, mená kanálov či vlákien, texty správ, ID používateľov ani URL.

Ciele sa dajú prispôsobiť cez prepínače `--guild`, `--forum`, `--channel` a tempo cez `--delay`.

