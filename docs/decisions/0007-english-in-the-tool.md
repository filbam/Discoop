# 0007: English help and tool messages

- **Status:** Superseded by ADR 0021
- **Date:** 2026-11-03
- **Decided by:** the user

> **Note (2026-11-04):** Only the "documentation in Slovak" part is superseded by [ADR 0021](0021-english-only-repository.md); tool texts remain English.

## Context

The tool is used by AI agents and potentially other people. Project documentation was originally in Slovak ([ADR 0001](0001-record-everything-and-version-it.md)).

## Decision

- **In English:** help, messages, error codes, and tool outputs.
- **In the original language:** content of downloaded messages.
- **In Slovak:** documentation in the repo (`docs/`, `CLAUDE.md`). *(Superseded by [ADR 0021](0021-english-only-repository.md): documentation is now in English.)*

## Consequences

- The note text for AI agents in the help is in English (design, section 11).
