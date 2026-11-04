# 0010: Práca cez agentov

- **Stav:** Prijaté
- **Dátum:** 2026-11-03
- **Rozhodol:** používateľ

## Kontext

Hlavná konverzácia pri implementácii minula kontext a musela sa zhrnúť ([denník 2026-11-03](../journal.md)).
Používateľ chce, aby prácu robili agenti (subagenti) a hlavný Claude ich riadil.

## Rozhodnutie

**Hlavný Claude (orchestrátor):**
- hovorí s používateľom a pýta sa ho na rozhodnutia,
- delí prácu na kroky,
- píše agentom samostatné zadania: čo je hotové, ktoré súbory, čo má byť výsledkom, ako to overiť,
- výsledok kontroluje sám (diff, `uv run pytest`), lebo správa agenta nie je dôkaz,
- po kontrole commituje, pushuje len na pokyn používateľa.
- Sám nepíše kód ani dokumenty a chyby vracia agentovi. Výnimka: triviálna oprava pri kontrole, napr. preklep.

**Agenti:**
- robia celý krok vrátane testov a záznamov podľa `CLAUDE.md` (CHANGELOG, návrh, analýzy, ADR, denník),
- necommitujú a nepushujú,
- na konci vrátia stručnú správu: čo zmenili, ako to overili, čo ostalo otvorené.

**Súbežnosť:**
- Agenti, ktorí iba čítajú (prieskum, kontrola), môžu bežať naraz.
- Agenti, ktorí píšu, nikdy nemenia rovnaké súbory. Keď by sa prekrývali, idú za sebou.
- Denník v jednom bloku práce píše vždy len jeden agent.

**Discord:** pravidlá z `CLAUDE.md` platia pre agentov rovnako:
- Discord API volá len nástroj alebo prototyp, ktorý spúšťa používateľ (výnimka `login --handshake-only`).
- Agent v prehliadači používateľa smie pracovať len podľa [ADR 0003](0003-rules-for-agents-in-the-users-browser.md)
  a len keď o to používateľ požiada.

## Dôsledky

- Hlavná konverzácia šetrí kontext.
- Práca trvá dlhšie a stojí viac tokenov.
- Po každom kroku je kontrola.
- Agent začína bez kontextu konverzácie. Všetko podstatné preto musí byť zapísané v repe
  (`CLAUDE.md`, denník, návrh).
