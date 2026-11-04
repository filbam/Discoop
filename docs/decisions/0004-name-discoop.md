# 0004: Tool name `discoop`

- **Status:** Accepted
- **Date:** 2026-11-03
- **Decided by:** the user (named the repo `Discoop`)

## Context

The working title of the project was `Scoop`. However, the `scoop` command collides with the widespread Windows package manager Scoop (scoop.sh). If it were installed, the commands would clash.

## Options

- `scoop`: collides.
- `fitseeker`: name of the old script, but tied to FIT, whereas the tool must work for any server.
- `discoop` (Discord + scoop): no collision, builds on the original name.

## Decision

The tool, Python package, and command are called **`discoop`**. The GitHub repo is `filbam/Discoop`.
The local project folder can remain `Scoop`.

2026-11-04: the local project folder was renamed from `Scoop` to `Discoop`.

## Consequences

- Environment variable for agent mode: `DISCOOP_AGENT`.
- Local data: `discoop` directory in the OS data directory (see design, section 10).
- Key in keyring: `discoop`.
