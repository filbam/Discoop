# 0016: Default export folder in TUI

- **Status:** Accepted
- **Date:** 2026-11-04
- **Decided by:** the user

## Context

Without `export-dir` in config, export from TUI went into an `exports` directory in the current working directory. Where the export ended up depended
on where the user launched the terminal, which was unpredictable. In addition, the form row `Name` (P21) combined name
and path in a single field. The user wants (P23) separate fields `Folder` and `Name`, default name
`discord-export-<date and time>`, and a default folder that is at the same predictable location on every OS.

## Options

1. **Current directory** (previous `exports`). Rejected: outcome depends on where the terminal was launched.
2. **Downloads directory.** Rejected: an export is not a downloaded file and the folder is cluttered with other things.
3. **Application data directory** (`AppData\Local\discoop`, `~/.local/share/discoop`). Rejected: it is hidden and the user
   would struggle to find the export. `cache.db` is also stored there.
4. **Home directory.** Rejected: exports would clutter the home directory.
5. **`discoop` in user Documents.** Chosen.

## Decision

- The default export folder in TUI is `discoop` in the user's Documents. It is located by `platformdirs.user_documents_dir()`
  (`paths.default_export_dir()`), using identical code on Windows, Linux, and macOS. Discovery creates nothing; the folder
  is created on first export.
- Config `export-dir`, if set, takes precedence. In Settings (`F2`, row `Export folder`) the folder is changed permanently;
  in the `Folder` field only for that single export.
- The form has two fields: `Folder` and `Name`.
  - Empty `Folder` means the default directory. A path with `~` or an absolute path is used as-is. A relative path is resolved
    inside the default directory.
  - Empty `Name` produces `discord-export-<date and time>` (`discord-export-2026-1104-0108`). A provided `Name` is always just a name,
    never a path: it is sanitized via `safe_name` (slashes and invalid characters replaced with `_`).
  - Collision within the same minute (`-2`, `-3`) is handled only for automatically generated names. A specified name is not modified; a repeated export
    continues into it.
- Paths in the `--out` and `--zip` line of the TUI are absolute and use slashes (`/`). Windows accepts them and the CLI command line
  does not require quoting.
- CLI is unchanged. `discoop messages --out/--zip` remains relative to the current directory or `export-dir`.
  The new default folder applies only in the TUI.

## Consequences

- `[VERIFIED]` on Windows (platformdirs 4.14.3): `user_documents_dir()` returns `C:\Users\Filip\Documents`, so the default
  directory is `C:\Users\Filip\Documents\discoop`.
- `[ASSUMPTION]`: Linux and macOS according to `platformdirs` documentation (Linux reads XDG `XDG_DOCUMENTS_DIR`, otherwise `~/Documents`;
  macOS `~/Documents`). Untested. On Linux without a Documents folder, `platformdirs` returns `~/Documents` anyway,
  and export creates it (`export.py` also creates parent directories).
- `[ASSUMPTION]`: Documents redirected to OneDrive. Windows reports the redirected path and export will go to OneDrive,
  which may sync to the cloud. Users who do not want this can set `Export folder` in Settings.
- Export contains other people's messages. The folder in Documents is outside the repo, so git does not track it.
- Saving a preview (`Save` in Preview) keeps existing behaviour (`export-dir`, otherwise `exports` in current directory).
  Any change is out of scope for this decision.
- Tests mock `paths.documents_dir()` to a directory in `tmp_path`, so they never touch real Documents.
