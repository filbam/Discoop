# 0010: Work through agents

- **Status:** Accepted
- **Date:** 2026-11-03
- **Decided by:** the user

## Context

The main conversation ran out of context during implementation and had to be summarized ([journal 2026-11-03](../journal.md#2026-11-03)).
The user wants the work to be done by agents (subagents) and managed by the main Claude.

## Decision

**The main Claude (orchestrator):**
- talks to the user and asks for decisions,
- breaks down work into steps,
- writes separate briefs for agents: what is completed, which files, what the expected output is, how to verify it,
- checks the result personally (diff, `uv run pytest`), because an agent's report is not proof,
- commits after checking; pushes only on user instruction,
- does not write code or documents directly and sends errors back to the agent. Exception: trivial fix during verification, e.g. a typo.

**Agents:**
- perform the entire step including tests and records according to `CLAUDE.md` (CHANGELOG, design, analyses, ADR, journal),
- do not commit and do not push,
- return a concise report at the end: what they changed, how they verified it, what remains open.

**Concurrency:**
- Agents that only read (research, inspection) can run simultaneously.
- Agents that write never modify the same files. If they would overlap, they run sequentially.
- The journal is written by only one agent at a time in a given work block.

**Discord:** rules from `CLAUDE.md` apply equally to agents:
- Discord API is only called by the tool or a prototype run by the user (exception: `login --handshake-only`).
- An agent in the user's browser may only work according to [ADR 0003](0003-rules-for-agents-in-the-users-browser.md) and only when the user requests it.

## Consequences

- The main conversation saves context.
- Work takes longer and costs more tokens.
- Every step is followed by verification.
- An agent starts without conversation context. Therefore, everything essential must be recorded in the repository (`CLAUDE.md`, journal, design).
