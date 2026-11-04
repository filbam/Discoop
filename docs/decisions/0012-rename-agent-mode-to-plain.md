# 0012: Rename "agent mode" to "plain mode" (`--plain`)

- **Status:** Accepted
- **Date:** 2026-11-03
- **Decided by:** the user

## Context

The `discoop` tool included two output modes from the beginning (P7):
- **Human mode:** interactive output with colours (Rich), tables, category trees, and progress bars.
- **Agent mode:** plain text output without colours, with tabs, and structured errors on stderr.

However, the naming "agent mode" (`--agent`) evoked that the mode was intended exclusively for AI agents. In reality, the same mode is needed for any other programs, scripts (bash, Python subprocess), or redirection to a file or pipe (`|`), because it strips ANSI escape codes and graphical elements.

## Decision

1. **New primary name:** The mode is renamed to **Plain mode** with the flag **`--plain`**.
   - The name clearly expresses that it is plain text without colours, terminal effects, and graphical formatting.
2. **AI agents in documentation and help:**
   - The help text still explicitly states that `--plain` is ideal for AI agents and automated scripts (fewer tokens, easy parsing).
   - The `NOTE FOR AI AGENTS` notice in the help remains and recommends agents use `--plain` (or `--agent`).
3. **Backward compatibility:**
   - The `--agent` flag remains functional as a hidden alias for `--plain`.
   - Both environment variables `DISCOOP_PLAIN` and `DISCOOP_AGENT` are supported.
   - When output is redirected outside a terminal (`not sys.stdout.isatty()`), plain mode continues to activate automatically.

## Consequences

- Clearer interface for users and developers: `--plain` is standard naming in modern CLI tools.
- Backward compatibility for existing scripts and tests that pass `--agent`.
- Code gains the alias `detect_plain_mode` and `Output(plain=...)` while preserving the attribute `Output.agent`.
