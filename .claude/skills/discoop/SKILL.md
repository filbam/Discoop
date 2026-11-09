---
name: discoop
description: Use when the user wants you to read, download, export or analyse data from Discord (messages, channels, threads, forum posts, attachments, a server such as VUT FIT), or mentions discoop. Explains how to use the Discoop CLI for this; start by running `discoop agent-guide`, whose output overrides this skill.
---

# Using Discoop

Discoop is a command line tool that downloads messages and attachments from Discord servers the user is a member of
and writes them in a form that is easy for an AI to analyse. It uses the user's own Discord login. Scraping violates
Discord's Terms of Service; the user knows this and accepts the risk, so treat the account as something to protect
(slow, human-like pacing; no needless requests).

This skill is only a practical summary. The tool documents itself, and that documentation is the source of truth.

## Step 0: read the tool's own guide first (always)

Before running any other Discoop command, **always run the AI agent guide first**:

```
discoop agent-guide        # inside the repo during development: uv run discoop agent-guide
```

It is generated from the code and describes the workflow, recommended flags, rules for agents, the command list and
the exit codes of the installed version.

- **If `agent-guide` does not work** (command not found, unknown command, error), the parameter may have been renamed
  or removed. Do not guess: run `discoop --help` (the "NOTE FOR AI AGENTS" block names the current agent reference),
  then `discoop <command> --help` for the commands you need, and find out whether the guide now lives under a
  different name. Use what you find.
- **If `discoop` itself is not found**, tell the user it is not installed (see the README) instead of improvising.
- **Precedence:** if the tool's output (`agent-guide`, `--help`) says something different from this skill, **the
  tool's information wins**. Follow the tool and, when relevant, tell the user that the skill is out of date.
- Re-check `agent-guide` in a new session or after the tool was upgraded; do not rely on a memory of an earlier run.

## Hard rules

1. **Always run with `--plain`** (or set `DISCOOP_PLAIN=1`). It removes colours and rich tables, uses tab-separated
   tables and prints stable machine-readable errors (`ERROR <CODE>: ...`, `HINT: ...` on stderr). `--plain` is a
   global option and goes before the command: `discoop --plain messages ...`.
2. **Never log in for the user.** If any command exits with code `2` (`AUTH_REQUIRED`), ask the user to run
   `discoop login` in their own terminal (QR code scanned with the Discord mobile app). Do not run `login`, do not
   ask for, read, store or transmit tokens or cookies, and do not use `login --token`.
3. **Only run Discoop when the user asked for Discord data.** Every download sends requests to Discord from the
   user's account. Do not explore "just to see".
4. **Keep the default `--safe` mode** for anything larger than a small window. `--fast` (100 messages per request,
   fixed delay) is only for small, quick checks and only if the user asks for it.
5. **Never call the Discord API or CDN yourself** (curl, scripts). Use the CLI only.
6. **Exports contain other people's messages.** Keep them out of git (`exports/` and `*.zip` are git-ignored in this
   repo), do not paste them into public places, and do not put real message texts or names into committed files.

## Standard workflow

Follow this order: `status` -> `servers` -> `channels` -> (`threads`) -> `messages`.

```
discoop --plain status --format json                       # exit 2 -> ask the user to run `discoop login`
discoop --plain servers --format json
discoop --plain channels -s "VUT FIT" --format json
discoop --plain channels -s "VUT FIT" --type forum --format json   # only some channel types
discoop --plain threads -s "VUT FIT" -c "forum-name" --format json
```

- Servers and channels accept a **name or a numeric ID**. Names ignore case, diacritics and emoji. A name matching
  several items is an error (exit `3`); use the ID then.
- `-c` accepts patterns such as `"isc-*"` and can be repeated for several channels.
- `--server` can be left out after `discoop config set default-server "VUT FIT"`.
- `channels` and `servers` come from a local cache; add `--refresh` to fetch fresh data from Discord.
- `channels --type` takes: `text, voice, announcement, stage, directory, forum, media`.

## Reading messages

Without `--from/--to/--last` the window is the **last 24 hours**. Messages are printed oldest first.

```
discoop --plain messages -s "VUT FIT" -c isc-public                    # last 24 h
discoop --plain messages -s "VUT FIT" -c isc-public --from 7d          # last 7 days
discoop --plain messages -s "VUT FIT" -c isc-public --from 2026-10-01 --to 2026-10-31
discoop --plain messages -s "VUT FIT" -c "isc-*" --last 20 --format json   # 20 newest per channel
discoop --plain messages -s "VUT FIT" -c isc-public --from all --max-messages 500   # whole history, capped
```

- Time values (`--from`, `--to`) are local time: a date (`2026-10-01`), date and time (`2026-10-01T14:00`), relative
  (`48h`, `7d`, `2w`), `now`, and `all` for `--from` only. A bare date in `--to` covers the whole day.
- `--last N` gives the N newest messages, from the whole history unless `--from` is given.
- `--format` is `text`, `md`, `json` or `jsonl`. Prefer `json`/`jsonl` for programmatic work, `md` for reading.
- `--max-messages N` (default 5000 per channel) protects against huge outputs. A channel truncated by the limit is
  not marked as fully synced.
- `--include-system` keeps system messages (joins, pins, boosts); they are dropped by default.
- Threads and forum posts are included by default. Use `--no-threads` to skip them (a forum cannot be exported with
  `--no-threads`; exit `8`). Large forums are slow in safe mode.
- Without `--out`/`--zip`, attachments are only listed as Discord CDN links that **expire after 12 to 24 hours**.
  Use an export if the files matter.

## Exporting (messages + attachments)

```
discoop --plain messages -s "VUT FIT" -c isc-public --from 30d --out exports/isc --progress-json
discoop --plain messages -s "VUT FIT" -c isc-public --from all --zip exports/isc.zip
discoop --plain messages -s "VUT FIT" -c "isc-*" --from 30d --out exports/isc --max-tokens 50000
discoop --plain messages -s "VUT FIT" -c isc-public --from 7d --out exports/isc --no-files          # text only
discoop --plain messages -s "VUT FIT" -c isc-public --from 7d --out exports/isc --max-file-size 10  # skip files > 10 MB
```

With `--out DIR` or `--zip FILE` the export contains:

| Path | Content |
|---|---|
| `manifest.json` | counts, request settings, status of every file, skipped channels, `partial`/`complete` flags |
| `messages.md` | all channels in one Markdown file |
| `messages.jsonl` | one JSON object per message (threads are flat, with a `thread` attribute) |
| `channels/NAME.md` | one Markdown file per channel, threads as subsections |
| `files/NAME/` | attachments as `<attachment id>_<file name>` |
| `parts/part-NNN.md` | only with `--max-tokens N`: `messages.md` split into parts of at most N estimated tokens (never splits a message) |

- Only a summary is printed; add `--print` to print the messages as well.
- A relative `DIR`/`FILE` goes to the `export-dir` setting when it is set (`discoop config set export-dir <folder>`),
  otherwise to the current directory.
- Attachments larger than `--max-file-size` (default 50 MB; `0` = no limit) are skipped.
- `--max-tokens N` needs `--out` or `--zip`. Use it to fit an export into an LLM context window (for example `50000`),
  then read `parts/part-001.md`, `part-002.md`, ... one at a time.
- To analyse an export, start with `manifest.json` (what was exported, what was skipped), then read `messages.md`
  or the parts. Attachment paths inside messages are relative to the export root.

### Resilience and resuming

- An export is written channel by channel into `<target>.partial` and moved to `<target>` only when everything is
  complete, so an earlier finished export is never damaged.
- If a run is interrupted (Ctrl+C, network failure), **run exactly the same command again**. Already saved channels and
  attachments are not downloaded again. (A changed request, for example adding `--no-threads` or `--since-last`,
  starts from scratch instead.)
- Exit code `9` (`PARTIAL`) means the run finished but some channel was skipped (no access / not found), a thread was
  skipped or an attachment failed. Check `manifest.json` (`skipped_channels`, file statuses), tell the user what was
  skipped, and do not treat it as a total failure. Files skipped on purpose (`--no-files`, `--max-file-size`) do not
  cause code `9`.
- Combining `--print` with resuming an export that already has finished channels is rejected (exit `8`).

### Incremental updates (`--since-last`)

```
discoop --plain messages -s "VUT FIT" -c "isc-*" --since-last --out exports/isc-update
```

- Downloads only messages newer than the last **successful, complete** export of each channel. State is kept in
  `sync-state.json` in Discoop's data folder, per account.
- Mutually exclusive with `--from`, `--to` and `--last`.
- A channel with no previous state uses a 24 hour window (with a note). A channel without new messages is skipped
  without requests; its threads are still checked; forums are never skipped.
- The state advances only after a complete run, and only for channels that were not truncated by `--max-messages`
  and had no failed files or threads. Use a **new output folder** per incremental run so earlier exports stay
  intact.
- A disk space check runs before downloading; low disk space fails early.

## Profiles

```
discoop --plain messages --save-profile fit-study -s "VUT FIT" -c "isc-*" --from 7d     # save and run
discoop --plain messages --profile fit-study --out exports/fit                         # load options
discoop --plain profiles                                                                # list profiles
```

A profile stores server, channels, time window and mode.

## Settings, diagnostics, output

```
discoop --plain config list --format json
discoop --plain doctor                       # login, network, export folder, disk space, cache, version
discoop --plain --debug messages ...         # diagnostic log on stderr
discoop --plain --log discoop.log messages ...
discoop --plain -v messages ...              # show progress notes in plain mode
```

- Logs never contain tokens, CDN signatures, message texts or usernames (numeric IDs only), so they are safe to
  share when reporting a problem.
- `--progress-json` writes JSON lines with percentages and ETA to stderr (events carry IDs and counts only). Use it
  for long exports and read stderr incrementally.
- `discoop ui` is an interactive terminal UI for the human. Do not run it from an agent.

## Exit codes

| Code | Name | What to do |
|---|---|---|
| 0 | OK | Done. |
| 1 | ERROR | Unexpected error. Re-run with `--debug`, read the message and hint. |
| 2 | AUTH_REQUIRED | Ask the user to run `discoop login` themselves. |
| 3 | AMBIGUOUS | Several servers/channels match the name. Use the numeric ID. |
| 4 | NOT_FOUND | Server or channel not found. Check names with `servers` / `channels --refresh`. |
| 5 | NO_ACCESS | HTTP 403: the account lacks permission for the channel. Do not retry. |
| 6 | RATE_LIMITED | Wait, then re-run the same command; consider a higher `--delay`. Never switch to `--fast`. |
| 7 | NETWORK | Network failure. Re-run the same command (exports resume). |
| 8 | BAD_ARGS | Invalid options (for example `--since-last` with `--from`, `--max-tokens` without `--out`). Fix the command. |
| 9 | PARTIAL | Finished, but something was skipped or failed. Inspect `manifest.json`, report it. |
| 130 | CANCELLED | Interrupted (Ctrl+C). Re-run the same command to resume. |

Verify the numbers with `discoop agent-guide`, which builds this table from the code (and wins if it differs).

## Typical task recipes

**"Summarise what happened this week in channel X."**
`status` -> `channels` (find X) -> `messages -c X --from 7d --format md` (add `--max-messages` for busy channels).

**"Export the whole server for study."**
`channels --format json` -> pick the channels with the user (confirm scope; it can be thousands of requests) ->
`messages -c "..." --from all --out exports/NAME --max-tokens 50000` -> on exit `9` inspect `manifest.json` ->
read `parts/part-NNN.md` in order.

**"Update my earlier export."**
`messages ... --since-last --out exports/NAME-update` -> read only the new export.

**Command exits with code 2.**
Stop and ask the user to run `discoop login`. Do not try to work around it.

## Known limits (unverified on a real account as of 2026-11-04)

Real Ctrl+C from a console, forum selection in the TUI, exporting a very large forum, and Linux/macOS have not been
verified on a real account. An attachment described differently by the API and the CDN may be re-downloaded on a
repeated export into the same folder (harmless). The `message_count` in the thread list does not include the forum
post starter message.
