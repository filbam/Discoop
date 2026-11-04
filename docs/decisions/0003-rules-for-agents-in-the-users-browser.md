# 0003: Rules for agents in the user's browser

- **Status:** Accepted
- **Date:** 2026-11-03
- **Decided by:** introduced after incidents, the user let the analysis continue under these rules

## Context

The Discord analysis was performed by an AI agent in the user's real Chrome, logged into Discord ([journal 2026-11-03](../journal.md#2026-11-03)).

1. **Sent message:** the agent was allowed to type into search. A click hit the message composer field and Enter sent a message from the user's account.
2. **Closed Chrome:** closing the agent's tab (`tabs_close_mcp`) crashed all of Chrome twice.

## Decision

An agent in the user's browser on Discord:
- **does not type and presses no keys** (not even search),
- **clicks only on navigation**: channels in the sidebar, buttons in the channel header, closing panels. Never on the message list, reactions, composer, Follow, or Join.
- **does not close tabs or windows.** Leaves the tab open and the user closes it.
- **only reads.** Prefers monitoring network requests; does not read token or cookies and does not make its own API calls.
- **stops immediately upon anything unexpected** and reports it.

## Consequences

- Things that require custom API calls (rate limits, REST endpoints, `429` responses) are verified by a prototype run by the user.
- During analysis, some channels will always be marked as read. This is a side effect of opening a channel, and the user must be warned before analysis.
- **Added 2026-11-03:** `discord.com/login` invokes passkey autofill (`navigator.credentials.get`) each time the form is rendered. The embedded browser on Windows turns this into a system Windows Security dialog. Before opening the login page, the user must be warned to dismiss the dialog.
