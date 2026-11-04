# 0017: Resilient export and partial result

- **Status:** Accepted
- **Date:** 2026-11-04
- **Decided by:** the user

## Context

When downloading and exporting multiple Discord channels or large servers, situations arise where the process fails in the middle (network outage, unexpected error, user interruption via Ctrl+C or Cancel in TUI), some channels cannot be read (missing permissions HTTP 403, non-existent channel HTTP 404), or downloading an attachment fails.

The previous approach had several shortcomings:
1. If the process crashed, for example, on channel 30 out of 40, all preceding work was lost or left in a corrupted state, and the entire export had to be repeated from scratch.
2. Writing directly to the destination folder or overwriting an existing file could corrupt a previous finished export.
3. A missing channel or failed attachment either crashed the entire process with an error or exited with code 0 (success), which masked the incompleteness of the data from the user as well as scripts/AI agents.
4. The entire export held all downloaded messages in memory until the end, leading to high memory consumption on large servers.

## Options

1. **Manual `--resume` flag.** The user would need to know that the previous run was interrupted and pass the flag. Rejected: increases interface complexity and requires manual intervention where the user's intent is obvious.
2. **Ignore errors in individual channels and return code 0.** Rejected: code 0 declares full success; scripts and automation would treat an incomplete export as complete.
3. **Fail-fast on the first error (code 1/error).** Rejected: when exporting multiple channels, we do not want to discard the entire run just because the user lacks access to one channel.
4. **Automatic resume via temporary `<dest>.partial` folders, channel-by-channel writing, and new exit code `ExitCode.PARTIAL = 9`.** Chosen: writing flushes data channel by channel, publishes the target file/folder only upon completion, the identical command automatically picks up an in-progress export, and an incomplete outcome is clearly indicated by code 9.

## Decision

- **Channel-by-channel writing and staging folder `<dest>.partial`:**
  - The `ExportWriter` class (`src/discoop/export.py`) writes exported data channel by channel directly to disk, rather than keeping the entire history in memory.
  - All intermediate data is written to a temporary location `<dest>.partial` (for a zip archive, `<name>.zip.partial`).
  - Only after successful completion of all requested channels (`writer.close(complete=True)`) is the staging folder or zip atomically moved to the destination path. A previous finished export is never corrupted by an interrupted run.
  - The export manifest contains fields `request`, `targets`, `skipped_channels`, `interrupted`, `partial`, and `complete`.
  - When `--max-tokens N` is specified, `parts/part-NNN.md` chunks (splitting `messages.md` via `split.split_markdown`) are created only upon `close(complete=True)`, before publication, in the staging folder. They move to the destination alongside the rest of the export (in both folder and zip formats identical to `parts/part-NNN.md` entries), so a crash before completion leaves no `parts/` in the destination. When publishing to a folder containing a previous export, its old `parts/part-*.md` are replaced with new ones (or deleted if no new ones exist: they belong to the `messages.md` they were generated from). Other files in `parts/` remain. Parts are not listed in the manifest and `--max-tokens` is not part of the request fingerprint (parts are generated from finished `messages.md`).

- **Automatic resume without a new flag:**
  - If an unfinished folder `<dest>.partial` exists when starting an export and its fingerprint (`request_fingerprint`) matches the current request (matching targets, time window, export options), Discoop automatically continues where it left off.
  - The fingerprint (and identical fields in the manifest under `request`) covers servers, channel IDs in order, window, `--last`, `--max-messages`, `--include-system`, `--no-files`, `--max-file-size`, and since 2026-11-04 also `threads` (`--no-threads`) and `since_last` (`--since-last`). An interrupted export with threads therefore does not resume a run with `--no-threads` (saved channels would lack threads), and a `--since-last` run does not resume a regular one and vice versa: it restarts from scratch. Download mode (`safe`/`fast`) and `--max-tokens` do not affect the fingerprint.
  - Finished channels are skipped – neither their messages nor attachments are downloaded again.
  - The event `Events.resumed(done, total)` informs CLI and TUI of the number of resumed channels. The CLI prints a note: `Continuing an unfinished export: N of M channels are already saved.`
  - A relative time window (e.g. `--from 1d`) is calculated during resume from the creation time of the original run (`Resume.created`), preserving the window contents.
  - The `--print` option combined with resume where finished channels already exist is rejected with `ExitCode.BAD_ARGS` (code 8) before downloading messages (the channel list may load from cache or API, and under `--since-last` the account ID is resolved, but messages are not yet downloaded), because messages of finished channels are not in memory for printing.

- **Interruption of run:**
  - On interruption (user Ctrl+C, `Cancelled` in TUI, or unexpected exception), `ExportWriter` is closed with `complete=False`.
  - Event `Events.interrupted(saved, total, path)` is raised, informing the user: `Saved N of M channels in <path>.partial. Run the same command again to continue.`
  - Interruption via Ctrl+C (`KeyboardInterrupt`) is not swallowed in CLI and the application exits with standard Unix code 130.

- **Exit code `ExitCode.PARTIAL = 9`:**
  - If a run successfully finishes processing all available channels, but the outcome is not 100% complete, the CLI exits with code 9 (`ExitCode.PARTIAL`).
  - Considered a partial result:
    - A channel skipped due to missing permissions (HTTP 403 `NO_ACCESS`) or non-existence (HTTP 404 `NOT_FOUND`), if multiple targets were specified (if only one target was given, it fails immediately with that error).
    - Any attachment whose download failed (`status == FAILED`).
  - Files intentionally omitted by the user via `--no-files` or skipped for exceeding the size limit `--max-file-size` are **not** considered a partial result (in these cases CLI returns code 0).
  - On partial result, the CLI prints advice explaining what is missing and recommends re-running the command to fetch missing parts.
  - Summary after finishing a resumed export takes total channel, message, and attachment counts from the export manifest (`exported.manifest["counts"]`) and jobs (`exported.jobs`), not just from the results of the current run.

- **Support in TUI:**
  - TUI catches `resumed` and `interrupted` events and displays them in the status bar and log.
  - On partial result or interruption, TUI lists skipped channels and advises pressing `F5` to continue.
  - Function `_keep_export_name()` ensures that after an interruption or partial result, the automatically generated export name is pinned in the `Name` field, so pressing `F5` automatically picks up the in-progress `<dest>.partial` instead of creating a new name based on a new minute.

## Consequences

The `[VERIFIED]` tag in the following points denotes verification via tests against fake Discord (`httpx.MockTransport`) and the local filesystem. A real network outage was not verified in this way.

On a real account (2026-11-04, [analysis](../analyses/real-account-check-2026-11-04.md)), the following was also verified:
- Interruption by script (`KeyboardInterrupt` raised from CLI events during actual network downloading) after 2 out of 3 channels: code 130, `<dest>.partial` with manifest `complete: false, interrupted: true` and 2 channels, destination did not exist, message "Saved 2 of 3 channels in ....partial. Run the same command again to continue." The same command then downloaded only the 3rd channel, published destination (`complete: true`), deleted `.partial`, and exited with code 0.
- Interruption in the middle of the first channel when exporting a forum (during its 2nd thread): code 130, no `.partial`, no destination, no `.part` files. Re-running proceeded normally.
- Export of a forum (2 posts, 22 messages) finished with a complete manifest. Zip with `--max-tokens` (3 parts) was valid and parts were not in the manifest.
- **Actual Ctrl+C signal from console** (while waiting on network or during file download) was not tested on a real account. Observation: in both interruptions `main()` did not print the "Interrupted." line, code 130 was returned without it (the branch with `out.error(...)` appears unreachable, harmless).

- `[VERIFIED]` Export is written channel by channel directly to disk, not from a single whole in memory.
- `[ASSUMPTION]` Low memory footprint even when exporting hundreds of thousands of messages: tests did not measure it. Splitting with `--max-tokens` loads finished `messages.md` into memory all at once.
- `[VERIFIED]` A previous finished export in the destination directory or zip file is never overwritten or corrupted by an unfinished run.
- `[VERIFIED]` An interrupted run can be resumed immediately by running the same command without re-downloading already completed channels and attachments.
- `[VERIFIED]` Code 9 allows scripts and AI agents to unambiguously distinguish full success (0), partial success (9), and fatal error.
- `[VERIFIED]` Ctrl+C continues to return code 130 while preserving the staging folder `.partial` for future resumption (verified on a real account by script-induced interruption, not console signal).
