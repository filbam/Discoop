# Decisions (ADR)

Each decision has its own file `NNNN-name.md`. A modified decision is never deleted. It is replaced by a new ADR
and the old one receives the status `Superseded by ADR NNNN`.

**Statuses:**
- `Accepted`: decided or explicitly approved by the user.
- `Proposed`: awaiting approval.
- `Superseded by ADR NNNN`: decision replaced by a newer ADR.

Decisions that are not yet resolved are in [design.md, section 15](../design.md#open-decisions).

| # | Decision | Status | Date |
|---|---|---|---|
| [0001](0001-record-everything-and-version-it.md) | Record everything and version it in git | Accepted | 2026-11-03 |
| [0002](0002-private-repo-and-identity.md) | Private repo `filbam/Discoop` and git identity | Accepted, private repo superseded by ADR 0015 | 2026-11-03 |
| [0003](0003-rules-for-agents-in-the-users-browser.md) | Rules for agents in the user's browser | Accepted | 2026-11-03 |
| [0004](0004-name-discoop.md) | Tool name `discoop` | Accepted | 2026-11-03 |
| [0005](0005-qr-login-without-a-browser.md) | QR login in the terminal without a browser | Accepted, browser rejection superseded by ADR 0022 | 2026-11-03 |
| [0006](0006-python.md) | Implementation in Python (uv, Typer, Rich, …) | Accepted | 2026-11-03 |
| [0007](0007-english-in-the-tool.md) | English help and tool messages | Superseded by ADR 0021 | 2026-11-03 |
| [0008](0008-fallback-login-token.md) | Fallback login `discoop login --token` | Accepted, browser option and captcha hint superseded by ADR 0022 | 2026-11-03 |
| [0009](0009-login-in-agent-mode.md) | `login` refuses in agent mode | Accepted, agent-mode refusal amended by ADR 0022 | 2026-11-03 |
| [0010](0010-work-through-agents.md) | Work through agents, managed by the main Claude | Accepted | 2026-11-03 |
| [0011](0011-default-behaviour-of-messages.md) | Default behaviour of `messages`: threads enabled, 24 h window, `text` format | Accepted | 2026-11-03 |
| [0012](0012-rename-agent-mode-to-plain.md) | Rename "agent mode" to "plain mode" (`--plain`) | Accepted | 2026-11-03 |
| [0013](0013-tui-and-shared-service-layer.md) | Interactive terminal user interface (TUI) and shared service layer | Accepted, TUI layout superseded by ADR 0014 | 2026-11-03 |
| [0014](0014-tui-keyboard-one-tree.md) | TUI: keyboard navigation, single tree, terminal colours | Accepted | 2026-11-03 |
| [0015](0015-public-repo-and-installation.md) | Public repo and installation via `uv tool` | Superseded by ADR 0024 | 2026-11-04 |
| [0016](0016-default-export-folder-in-tui.md) | Default export folder in TUI: `Documents/discoop` | Accepted | 2026-11-04 |
| [0017](0017-reliable-export-and-partial-success.md) | Resilient export and partial result | Accepted | 2026-11-04 |
| [0018](0018-logging.md) | Optional diagnostic logging (`--debug`, `--log`) | Accepted | 2026-11-04 |
| [0019](0019-threads.md) | Threads and forum posts (basis: [probe](../analyses/thread-probe-2026-11-04.md)) | Accepted | 2026-11-04 |
| [0020](0020-since-last.md) | Incremental download (`--since-last`) | Accepted | 2026-11-04 |
| [0021](0021-english-only-repository.md) | English-only repository | Accepted | 2026-11-04 |
| [0022](0022-browser-login.md) | Browser login `discoop login --browser` | Accepted | 2026-11-10 |
| [0023](0023-version-and-single-source.md) | Version 1.0.0 and single source of truth | Accepted | 2026-11-10 |
| [0024](0024-releases-tags-and-stable-branch.md) | Releases, tags, and the `stable` branch | Accepted | 2026-11-12 |
| [0025](0025-update-notifier.md) | Update notifier | Accepted | 2026-11-12 |

## Template

```markdown
# NNNN: Decision title

- **Status:** Proposed | Accepted | Superseded by ADR NNNN
- **Date:** YYYY-MM-DD
- **Decided by:** the user | Claude's proposal

## Context
Why the decision was needed.

## Options
Alternatives considered.

## Decision
What was decided.

## Consequences
What follows from this.
```
