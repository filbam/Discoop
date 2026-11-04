# 0018: Optional diagnostic logging (`--debug`, `--log`)

- **Status:** Accepted
- **Date:** 2026-11-04
- **Decided by:** the user

## Context

When downloading large volumes of messages and attachments, various edge cases occur (HTTP 429 rate limits, transient network or 5xx errors, expired signed CDN URLs, 403 access denied). Until now, the tool either waited silently or threw an error without a detailed trace of timing and progress. Both the user and developer need a diagnostic log to debug issues.

At the same time, Discoop handles sensitive data: Discord authentication token, signed attachment URLs with expiration tokens and cryptographic signatures (`ex`, `is`, `hm`), private message texts, and user or channel names. Any logging must guarantee that these data points never leak into logs.

## Options

1. **Use standard `logging.basicConfig` on the root logger.** Rejected: third-party libraries (`httpx`, `httpcore`, `websockets`) at DEBUG level would log full requests including `Authorization` headers and complete URLs with attachment signatures.
2. **Log everything including response bodies.** Rejected: response bodies contain sensitive message texts, user names, and tokens.
3. **Structured diagnostic logging with a strict field allowlist.** Chosen: the `discoop` logger is disabled by default (`propagate = False`), explicitly enabled via `--debug` (stderr) or `--log FILE`. Only safe diagnostic metadata is logged.

## Decision

- Logging is **disabled by default**. If neither `--debug` nor `--log FILE` is provided, no handlers are attached and nothing is written or printed.
- Startup and teardown are controlled by `setup_logging(debug: bool, log_file: Path | None)` and `teardown_logging()` functions in `src/discoop/logs.py`.
- Handlers are attached exclusively to the logger `logging.getLogger("discoop")` with `propagate = False` and `DEBUG` level. The root logger and `logging.basicConfig` are not used.
- `--debug` attaches a `StreamHandler(sys.stderr)`. `--log FILE` attaches a `FileHandler` in append mode with UTF-8 encoding (automatically creating parent directories).
- Third-party loggers (`httpx`, `httpcore`, `websockets`) are explicitly quieted to `WARNING` level in `setup_logging`.
- `teardown_logging()` is idempotent: it closes and removes all created handlers and resets loggers to their original state.
- **Log header:** on initialisation with an active handler, a header is written with the tool version (`discoop.__version__`), OS, Python version, and a mandatory security notice:
  `IDs in this log identify private servers and channels. Do not publish it.`
- **Line format:** ISO 8601 timestamp with milliseconds in UTC, level, shortened logger name (`api`, `scrape`, `attachments`, `discoop`), message with key=value pairs:
  - `discoop.api`: method, path without query string (`path.split("?", 1)[0]`), parameter names (`params=...`) and values strictly for allowed keys (`before`, `after`, `limit`, `archived`, `offset`, `with_counts`), attempt number `attempt` (from 1), HTTP status code, duration in milliseconds measured via `time.perf_counter()`, response length in bytes, and optional item count `items`. On 429 it logs `retry_after`, `global`, and doubled delay; on pauses seconds and reason; on silent retries backoff and reason. Errors >= 400 log top-level `code` and `message` (not the nested `errors` object). Transport errors log only `type(e).__name__`, never `str(e)`.
  - `discoop.scrape`: one line per message page: channel ID (`channel_id`), message count on the page, ID of oldest and newest message, and flag `last=True/False`.
  - `discoop.attachments`: only in `_download` and `_fetch`: attachment ID, size, status, attempt number, written byte count, and only the host from the URL (`httpx.URL(url).host`).
- **Strictly forbidden (never logged):**
  - Request and response headers (`Authorization` token).
  - All other `kwargs` from `request()` (e.g. JSON bodies, tickets).
  - Full response bodies (`response.text`, `response.json()`).
  - Message texts and user names.
  - File names, file paths, and query parameters of signed CDN URLs (`ex`, `is`, `hm`).
  - Channel and server names (only numeric IDs).
  - Dataclass representations (`FileJob`, `Attachment`, `Message`, `ChannelMessages`, `StoredToken`).

## Consequences

- `[VERIFIED]` Diagnostic logging does not affect default CLI execution or existing `DiscordAPI` behaviour.
- `[VERIFIED]` Tests in `tests/test_logs.py` verify that token, attachment signatures, file names, expiration parameters, message texts, and channel names are absent from the log even during error conditions (429, 500, 403).
- `[VERIFIED]` The URL query string is stripped from the log, preventing leakage of single-use signatures.
- The log contains numeric identifiers (snowflake IDs) of servers, channels, and messages. Although it contains no message texts, the IDs themselves identify private servers and channel structure; therefore, the log must not be published (as explicitly warned in the header of each log).
