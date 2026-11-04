# 0001: Record everything and version it in git

- **Status:** Accepted
- **Date:** 2026-11-03
- **Decided by:** the user (requirement P12)

> **Note (2026-11-04):** The documentation language is now English ([ADR 0021](0021-english-only-repository.md)).

## Context

The project is starting through brainstorming, analyses, and proposals in conversation with AI. Without recording them, findings, decisions, and their rationale would be lost. In the next session, AI would have to rediscover them from scratch.

## Decision

Everything essential is recorded in the repository and versioned in git:

| What | Where |
|---|---|
| Requirements | `docs/requirements.md` |
| Design | `docs/design.md` |
| Analyses | `docs/analyses/<topic>.md` |
| Decisions (ADR) | `docs/decisions/NNNN-name.md` |
| Project changes | `CHANGELOG.md` |
| Work progress and incidents | `docs/journal.md` |

Rules for AI are in `CLAUDE.md`, which is loaded in every session in this repo.

## Consequences

- The record is updated in the same step as the change itself.
- Documents must not contain tokens, cookies, or names and message contents of other people.
- The Discord analysis was moved to `docs/analyses/`.
