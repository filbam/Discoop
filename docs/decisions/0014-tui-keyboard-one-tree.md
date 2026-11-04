# 0014: Keyboard-driven TUI, single tree, terminal colours

- **Status:** Accepted
- **Date:** 2026-11-03
- **Decided by:** the user

## Context

The user tested `discoop ui` on 2026-11-03 (ADR 0013) and reported:
- many buttons have no visible text,
- arrow key navigation does not work,
- the interface stutters.

The cause of empty buttons: in CSS they had `height: 1`, but Textual gives them a tall border by default. The border consumed the entire
row and left no room for text.

The user requests (P18, P19, P20): primary keyboard navigation (arrows) with mouse as a secondary option, channels
collapsed by default, and a prettier, simpler, more terminal-like and polished interface.

## Options

1. **Three panels** (servers | channels | export) with a fixed dark theme. Rejected.
2. **Single tree** (servers, categories, channels) with a theme based on terminal colours. Chosen by the user.

## Decision

### Layout
- Servers, categories, and channels are in a **single tree** like in a file manager. Everything is collapsed by default.
- On the right is the **Export** panel (selection list and form).
- At the bottom is the log, below it a line with the equivalent CLI command and a row with keybindings (Footer, clickable by mouse).
- In a narrow window, only one panel is shown at a time.

### Colours and appearance
- Textual's `ansi-dark` theme uses the terminal's colours and background. Another theme can be selected via Ctrl+P.
- No emojis and no large buttons. Controls have a height of one line.

### Keybindings

| Key | Where | Action |
|---|---|---|
| ↑ ↓ | everywhere | move in tree, list, and form (between rows) |
| → | tree | expand node. On an unloaded server loads channels. On an expanded node jumps to first child |
| ← | tree | collapse node. On a collapsed node jumps to parent |
| ← → | form select row | change value (`safe/fast`, `folder/zip/preview`, format, attachments, system messages, window preset) |
| Space | tree | select channel or all selectable channels in category |
| Enter | tree | category/server: expand/collapse. Channel: select |
| Enter | form | confirm field. On Start row launches export |
| Tab / Shift+Tab, 1 2 3 | global | switch panel |
| / | global | filter tree |
| e | tree or selection list | custom channel time window |
| x / Delete | selection list | remove channel from selection |
| X | selection list | clear entire selection |
| a | tree | select all visible channels of the server |
| r | tree | reload server channels from Discord |
| R | global | reload server list |
| L | global | load channels of all servers (safe pacing, Esc cancels) |
| F5 | global | launch export |
| Esc | global | cancel running operation, leave filter, close dialog |
| c | global | copy CLI command |
| F1 / ? | global | Help |
| F2 | global | Settings |
| F3 | global | Login |
| Ctrl+P | global | command palette (change theme) |
| q | global | quit. During execution, stops work first |

Key `X` was added 2026-11-04 after a review, because clearing the entire selection disappeared along with the buttons.

### Behavioural rules
- Cursor navigation never calls Discord. Network calls are triggered only by explicit actions: →/Enter on an unloaded server, r, R, L, and F5.
- At most one network operation runs at a time.
- Safe mode pauses can be cancelled with Esc.

## Consequences

- ADR 0013 remains valid for the shared service layer (`service.py`), lazy import, job launching and grouping.
  TUI layout from it is superseded by this ADR.
- TUI Help (F1 / ?) is governed by the keybinding table from this ADR.
- Controls are implemented with `compact=True` (no border, height of one line), not via `height: 1`, so text does not disappear.
- Long operations must run in background workers and cursor movement must not trigger network calls, resolving UI stutter.

## Addendum 2026-11-04

The original decision does not change. The addendum describes additions in round 2 (P30) alongside the keybinding table above. The table in Help (`GUIDE_KEYS` in `tui/modals.py`) already contains these keys.

### Additional keybindings

| Key | Where | Action |
|---|---|---|
| P | global | save current selection, time window, and mode as a named profile (`profiles.json` in config folder, same file as `discoop messages --save-profile`) |
| p | global | load saved profile: replaces selection, time window, and mode. TUI tolerates manually edited profiles with invalid value types |
| o | global | open folder of last export in file manager (for zip, folder containing it). Active only after a finished export and not during running task. Preview (Target=preview) saves nothing, thus is not a "last export" |

- `L` remains "load channels of all servers". Not used for profiles.
- `P`, `p`, and `o` do not call Discord; behavioural rules above remain unchanged.

### Channel row suffixes in tree

- Every channel row has a dimmed suffix aligned to the right: time since last activity (`now`, `5m`, `3h`, `2d`, `4mo`, `1y`, according to `Channel.last_message_id`) and for a channel already exported from this account, date of last export (`exp 11-03`, local date, with year if from another year). Categories and servers do not have it (server has channel count on the right, `not loaded` or `no access`).
- If the row is too narrow, the export date is dropped first, then activity. The channel name is never truncated for the suffix.
- Suffixes refresh after export, after restoring saved state, and every 60 s. Date of last export is saved in `tui-state.json` (keyed by channel ID and account) and is not written for preview.
