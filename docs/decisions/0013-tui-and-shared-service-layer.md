# 0013: Interactive terminal user interface (TUI) and shared service layer

- **Status:** Accepted, TUI layout superseded by ADR 0014
- **Date:** 2026-11-03
- **Decided by:** the user

> **Note (2026-11-03):** The shared service layer (`service.py`), lazy import of Textual, job launching and grouping
> remain valid. TUI layout (three columns, tabs), controls, and Help are governed by
> [ADR 0014](0014-tui-keyboard-one-tree.md).

## Context

The `discoop` tool has a rich command-line interface (CLI) with support for `--human` and `--plain` modes. For `--human` mode, however, the user wanted a visual environment in the terminal controlled by keyboard (arrows, Enter, Space) in the style of Discord / file explorer, with:
- buttons to load servers and channels (individually as well as all at once with safe pacing and cancellation support),
- channel selection for export across different servers,
- time window configuration (globally for all channels and individually per channel),
- choice of download mode (`safe` / `fast`) and export target (folder or ZIP archive),
- responsive layout when resizing the terminal window,
- built-in Help screen (`F1` / `?` key), which in addition to explaining TUI controls also contains complete live `discoop --help` output including subcommands.

At the same time, a key requirement was that the TUI should not duplicate application logic and should be built as a thin layer on top of the tool's core.

## Decision

1. **`Textual` library:**
   - The `Textual` library (from the authors of `Rich`) was chosen for the TUI, providing a modern reactive component model, flexbox/grid layout, CSS styling (`discoop.tcss`), responsive layout (3 columns in wide window, tab system in narrow window), tree widgets (`Tree`), forms, and background workers for asynchronous operations without freezing the user interface.
   - Textual is loaded strictly upon launching the TUI (`lazy import`), so that it does not slow down the startup of standard CLI commands.

2. **Invocation:**
   - The TUI is launched with the command `discoop ui` or the flag `discoop --ui`.
   - Running `discoop` by itself without arguments continues to display help (`--help`), preserving predictable CLI behaviour.
   - In `--plain` mode or when launched in an environment without an interactive terminal (`not sys.stdout.isatty()`), the command `discoop ui` exits with an error and exit code `8` (`BAD_ARGS`).

3. **Shared service layer (`service.py`):**
   - Orchestration of the tool's business logic (`list_servers`, `list_channels`, `load_all`, `run_messages`) is factored out into a dedicated module `src/discoop/service.py`.
   - Both CLI and TUI call the same functions and share the same data structures, validations, and cache/API handling.
   - Every scheduled job in the TUI corresponds directly to one CLI command `discoop messages ...`. This equivalent command is displayed live in the TUI bottom bar, teaching the user how to use the direct CLI interface.

4. **Grouping jobs by time window:**
   - Channels with identical time windows form a single export job (one download call).
   - If there is only one job, the export is saved directly into the chosen destination path (folder or ZIP).
   - If there are multiple jobs (e.g. some selected channels have custom time windows configured), each job is exported into a numbered subfolder (`dest/01-7d/`, `dest/02-...`) or separate ZIP archive (`dest-01-7d.zip`), preventing collisions of manifests and data.

5. **Built-in Help:**
   - Pressing `F1` or `?` opens a modal dialog with help.
   - The window contains two tabs:
     1. *TUI Controls:* overview of keyboard shortcuts, navigation in trees and forms, meaning of icons and states.
     2. *CLI Reference (`discoop --help`):* dynamically generated output of the main help and all subcommand helps directly from the Typer application, identical to console output.

## Consequences

- **Clean architecture:** The service layer `service.py` separates presentation logic (CLI formatters, TUI widgets) from Discord API interactions, SQLite cache, and the export subsystem.
- **Zero duplication:** CLI and TUI use the same functions for fetching servers, channels, and downloading messages.
- **Fast CLI startup:** Thanks to the lazy import of `Textual`, standard `discoop` invocations carry no overhead from TUI framework initialisation.
- **High user convenience:** The user does not need to manually copy or search for channel IDs in the console – in the TUI they simply select servers and channels interactively, configure parameters, and launch export with clear live progress.
