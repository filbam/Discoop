# ADR 0021: English-only repository

- **Status:** Accepted
- **Date:** 2026-11-04
- **Decided by:** the user

## Context

The docs were originally Slovak ([ADR 0001](0001-record-everything-and-version-it.md), [ADR 0007](0007-english-in-the-tool.md)), the repository is public ([ADR 0015](0015-public-repo-and-installation.md)), and agents and other contributors work in English.

## Options

- **Keep Slovak docs:** original setup, but limits external contributors and requires agents to translate back and forth.
- **Bilingual docs:** keeps both languages, but creates heavy maintenance overhead to keep documentation in sync.
- **English only (chosen):** unified language across the entire codebase and documentation.

## Decision

Everything in the repository is English (documentation, code, comments, identifiers, commit messages, tests and fixtures, file and folder names, tool texts).

The conversation with the user is free (can be Slovak), but nothing of it enters the repository. Quoted Discord content in tests and docs is made up and English, except small fixtures that test Unicode handling (accents, emoji, normalisation), which state so in a comment.

Evidence markers are `[VERIFIED]` / `[ASSUMPTION]`.

## Consequences

- [ADR 0007](0007-english-in-the-tool.md) gets status `Superseded by ADR 0021` (its documentation part; tool texts stay English).
- [ADR 0001](0001-record-everything-and-version-it.md) gets a note that documentation language is now English.
- All existing documents were translated on 2026-11-04 (round 3) and doc files were renamed to English names.
- `CLAUDE.md` and `AGENTS.md` state the rule.
