"""Attachments of an export: safe file names, signed CDN URLs, downloading without the token.

Verified (docs/analyzy/discord-analyza.md, sections 5 and 15):
- attachment URLs are signed, `?ex=<expiry>&is=<issued>&hm=<signature>&` with hex unix seconds; a freshly fetched
  URL stays valid for 12 to 24 more hours,
- the CDN needs no token. Files are downloaded by a separate HTTP client without an Authorization header,
  so the token only ever goes to the API (DiscordAPI refuses anything but API paths),
- `POST /attachments/refresh-urls` takes `{"attachment_urls": [...]}` and answers
  `{"refreshed_urls": [{"original": ..., "refreshed": ...}]}`; a URL that is still valid comes back unchanged.

Assumed: at most 50 URLs per refresh request, the CDN answers an expired URL with 403 or 404, and an attachment's
`size` is the number of bytes the CDN sends.

A file is saved as `files/<channel folder>/<attachment id>_<file name>`. It is written as `<name>.part` and renamed
when the download is complete, so a file under its final name is whole. A rerun into the same folder finds files
by attachment ID and size and does not download them again.
"""

import contextlib
import logging
import os
import re
import time
import unicodedata
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

import httpx

from discoop.api import USER_AGENT, DiscordAPI, raise_for_status
from discoop.errors import DiscoopError, ExitCode
from discoop.models import Attachment, Channel, ChannelMessages

logger = logging.getLogger("discoop.attachments")

FILES_DIR = "files"
PART = ".part"
REFRESH_BATCH = 50  # URLs per refresh-urls request (assumed limit)
EXPIRY_MARGIN = 60  # seconds: a URL that expires sooner is refreshed before the download
REFRESHABLE = {403, 404, 410}  # CDN answers that can mean an expired URL
RETRY_WAITS = (1.0, 2.0)  # pauses before the 2nd and 3rd attempt after a network error, 429 or 5xx
_RETRY_STATUSES = {429, 500, 502, 503, 504}
CHUNK = 64 * 1024

# Name limits: NTFS allows 255 UTF-16 units and ext4/APFS 255 UTF-8 bytes per name, Windows 260 characters per path
# unless long paths are on. Short names leave room for the export folder's own path.
MAX_FILE_CHARS = 100
MAX_DIR_CHARS = 50
MAX_NAME_BYTES = 200
_MAX_EXTENSION = 16

DOWNLOADED, PRESENT, FAILED, SKIPPED, PENDING = "downloaded", "present", "failed", "skipped", "pending"
NO_FILES = "--no-files"
TOO_LARGE = "larger than --max-file-size"

_FORBIDDEN = re.compile(r'[<>:"/\\|?*\x00-\x1f\x7f]')
_DEVICE_DIGITS = "0123456789¹²³"
_RESERVED = {"CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$"} | {
    f"{device}{digit}" for device in ("COM", "LPT") for digit in _DEVICE_DIGITS
}
STORED_NAME = re.compile(r"(\d+)_.")  # a saved file: attachment ID, `_`, file name


def safe_name(
    name: str, fallback: str, max_chars: int = MAX_FILE_CHARS, max_bytes: int = MAX_NAME_BYTES
) -> str:
    """`name` as one path component that works on Windows, macOS and Linux and cannot leave its folder.

    - Characters Windows forbids (`<>:"/\\|?*`) and control characters become `_`, so there are no separators.
    - Dots and spaces at both ends go: Windows drops trailing ones silently, `..` would be the parent folder
      and a leading dot hides a file on Linux and macOS.
    - A reserved device name (`CON`, `nul.txt`, `COM1`, ...) gets a `_` in front.
    - A long name is shortened to `max_chars` characters and `max_bytes` UTF-8 bytes, keeping the extension.
    - Nothing left gives `fallback`.
    """
    text = _FORBIDDEN.sub("_", unicodedata.normalize("NFC", name)).strip(" .")
    text = _shorten(text, max_chars, max_bytes).strip(" .") or fallback
    if text.split(".")[0].rstrip(" ").upper() in _RESERVED:
        text = _shorten("_" + text, max_chars, max_bytes)
    return text


def _shorten(text: str, max_chars: int, max_bytes: int) -> str:
    def fits(candidate: str) -> bool:
        return len(candidate) <= max_chars and len(candidate.encode("utf-8")) <= max_bytes

    if fits(text):
        return text
    stem, dot, extension = text.rpartition(".")
    if dot and stem and len(extension) <= _MAX_EXTENSION:
        base, suffix = stem, dot + extension
    else:
        base, suffix = text, ""
    base = base[: max(max_chars - len(suffix), 0)]
    while base and not fits(base + suffix):
        base = base[:-1]
    return base.rstrip(" .") + suffix


def file_name(attachment_id: str, filename: str) -> str:
    """`<attachment id>_<safe file name>`: unique in an export, as attachment IDs are."""
    prefix = f"{attachment_id}_"
    return prefix + safe_name(filename, "file", MAX_FILE_CHARS - len(prefix), MAX_NAME_BYTES - len(prefix))


def channel_folders(channels: Iterable[Channel]) -> dict[str, str]:
    """A folder name per channel ID: the safe channel name, with `_<channel id>` when an earlier channel has it.

    Names are compared without regard to case, as Windows and macOS do.
    """
    folders: dict[str, str] = {}
    taken: set[str] = set()
    for channel in channels:
        if channel.id in folders:
            continue
        name = safe_name(channel.name, f"channel-{channel.id}", MAX_DIR_CHARS)
        while name.casefold() in taken:
            name = f"{name}_{channel.id}"
        taken.add(name.casefold())
        folders[channel.id] = name
    return folders


def url_expiry(url: str) -> int | None:
    """Unix time in the `ex` parameter (hex) of a signed CDN URL; None for an unsigned URL."""
    try:
        return int(httpx.URL(url).params["ex"], 16)
    except (KeyError, ValueError, httpx.InvalidURL):
        return None


def cdn_client(transport: httpx.BaseTransport | None = None) -> httpx.Client:
    """The HTTP client for files. Unlike DiscordAPI it has no Authorization header: the CDN needs no token.

    `Accept-Encoding: identity` keeps the bytes as they are, so sizes can be compared with Discord's.
    """
    return httpx.Client(
        headers={"User-Agent": USER_AGENT, "Accept-Encoding": "identity"},
        timeout=httpx.Timeout(60.0, connect=20.0),
        follow_redirects=True,
        transport=transport,
    )


@dataclass
class FileJob:
    """One attachment to save; `status` and `reason` record how it went."""

    attachment: Attachment
    message_id: str
    channel_id: str
    path: str  # relative to the export folder, `/` separators
    url: str  # the download URL, replaced when it is refreshed
    status: str = PENDING
    reason: str | None = None

    def fail(self, reason: str) -> None:
        self.status, self.reason = FAILED, reason


def plan(results: Sequence[ChannelMessages], folders: Mapping[str, str]) -> list[FileJob]:
    """One job per attachment, in message order. An attachment seen twice (e.g. also forwarded) is saved once."""
    jobs: dict[str, FileJob] = {}
    for result in results:
        folder = folders[result.channel.id]
        for message in result.messages:
            for number, attachment in enumerate(message.attachments):
                key = attachment.id or f"{message.id}-{number}"
                if key not in jobs:
                    path = f"{FILES_DIR}/{folder}/{file_name(key, attachment.filename)}"
                    jobs[key] = FileJob(attachment, message.id, result.channel.id, path, attachment.url)
    return list(jobs.values())


@dataclass(frozen=True)
class Stored:
    path: str  # relative to the export folder
    size: int


def stored_files(root: Path) -> dict[str, list[Stored]]:
    """Files already saved in an export folder, by attachment ID. Unfinished `.part` downloads do not count."""
    found: dict[str, list[Stored]] = {}
    base = root / FILES_DIR
    if base.is_dir():
        for path in sorted(base.rglob("*")):
            match = STORED_NAME.match(path.name)
            if match and not path.name.endswith(PART) and path.is_file():
                stored = Stored(path.relative_to(root).as_posix(), path.stat().st_size)
                found.setdefault(match.group(1), []).append(stored)
    return found


class Progress:
    """Download progress. The CLI shows a bar to humans and --verbose notes to agents; this one shows nothing."""

    def start(self, files: int, total_bytes: int) -> None: ...

    def file(self, number: int, total: int, job: FileJob) -> None: ...

    def advance(self, size: int) -> None: ...

    def finish(self) -> None: ...

    def note(self, text: str) -> None: ...


class Downloader:
    """Saves attachments under an export folder. Problems are recorded in the jobs, never raised."""

    def __init__(
        self,
        api: DiscordAPI,
        cdn: httpx.Client,
        root: Path,
        *,
        now: Callable[[], float] = time.time,
        sleep: Callable[[float], None] = time.sleep,
        progress: Progress | None = None,
    ) -> None:
        self.api = api  # only for refresh-urls; shares the pacing of the other API requests
        self.cdn = cdn
        self.root = root
        self._now = now
        self._sleep = sleep
        self.progress = progress or Progress()

    def run(self, jobs: Sequence[FileJob], max_size: int | None = None) -> None:
        """Download what is not saved yet. Expired URLs are refreshed first; a URL the CDN refuses is refreshed
        and tried once more."""
        stored = stored_files(self.root)
        todo = [job for job in jobs if self._needed(job, stored, max_size)]
        if not todo:
            return
        expired = [job for job in todo if self._expired(job.url)]
        if expired:
            self.progress.note(f"Refreshing {len(expired)} expired file URLs")
            self._refresh(expired, after_failure=False)
        self.progress.start(len(todo), sum(max(job.attachment.size, 0) for job in todo))
        try:
            refused = []
            for n, job in enumerate(todo, 1):
                if n > 1 and hasattr(self.api, "between_files"):
                    self.api.between_files()
                status = self._download(job, n, len(todo))
                if status in REFRESHABLE:
                    refused.append(job)
            if refused:
                self.progress.note(f"Refreshing {len(refused)} file URLs the CDN refused")
                renewed = self._refresh(refused, after_failure=True)
                for n, job in enumerate(renewed, 1):
                    if hasattr(self.api, "between_files"):
                        self.api.between_files()
                    self._download(job, n, len(renewed))
                    if job.status == FAILED:
                        job.reason = f"{job.reason} (also after refreshing the URL)"
        finally:
            self.progress.finish()

    def _needed(self, job: FileJob, stored: Mapping[str, list[Stored]], max_size: int | None) -> bool:
        size = job.attachment.size
        for item in stored.get(job.attachment.id, []):
            if size <= 0 or item.size == size:
                job.path, job.status, job.reason = item.path, PRESENT, None
                return False
        if max_size is not None and size > max_size:
            job.status, job.reason = SKIPPED, TOO_LARGE
            return False
        if not job.url.startswith("https://"):
            job.fail("no download URL")
            return False
        return True

    def _expired(self, url: str) -> bool:
        expiry = url_expiry(url)
        return expiry is not None and expiry <= self._now() + EXPIRY_MARGIN

    def _refresh(self, jobs: Sequence[FileJob], *, after_failure: bool) -> list[FileJob]:
        """New URLs from Discord in batches, through the API client and its pacing. Returns the jobs whose URL
        changed. When the CDN already refused a job (`after_failure`), its reason says why there is no retry."""
        renewed: list[FileJob] = []
        for start in range(0, len(jobs), REFRESH_BATCH):
            batch = jobs[start : start + REFRESH_BATCH]
            try:
                fresh = self._fresh_urls([job.url for job in batch])
            except DiscoopError as e:
                if not after_failure:
                    self.progress.note(f"Could not refresh {len(batch)} file URLs: {e.message}")
                for job in batch:
                    if after_failure:
                        job.reason = f"{job.reason}; refreshing the URL failed: {e.message}"
                continue
            for job in batch:
                new = fresh.get(job.url) or fresh.get(_url_path(job.url))
                if new and new != job.url:
                    job.url = new
                    renewed.append(job)
                elif after_failure:
                    job.reason = f"{job.reason}; Discord gave no new URL"
        return renewed

    def _fresh_urls(self, urls: list[str]) -> dict[str, str]:
        """refresh-urls for one batch: original URL (and its path, in case Discord rewrites the query) → new URL."""
        response = self.api.request("POST", "/attachments/refresh-urls", json={"attachment_urls": urls})
        raise_for_status(response)
        try:
            pairs = [(item["original"], item["refreshed"]) for item in response.json()["refreshed_urls"]]
        except (ValueError, KeyError, TypeError) as e:
            raise DiscoopError(ExitCode.ERROR, "Unexpected answer from Discord to refresh-urls.") from e
        fresh: dict[str, str] = {}
        for original, refreshed in pairs:
            if isinstance(original, str) and isinstance(refreshed, str) and refreshed.startswith("https://"):
                fresh[original] = refreshed
                fresh[_url_path(original)] = refreshed
        return fresh

    def _download(self, job: FileJob, number: int, total: int) -> int | None:
        """Download one file into place. Returns the HTTP status if the CDN refused it, else None."""
        self.progress.file(number, total, job)
        target = self.root / job.path
        part = target.with_name(target.name + PART)
        host = ""
        try:
            host = httpx.URL(job.url).host
        except Exception:
            pass
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            for attempt in range(len(RETRY_WAITS) + 1):
                attempt_num = attempt + 1
                last = attempt == len(RETRY_WAITS)
                try:
                    status = self._fetch(job.url, part, retry=not last)
                except (httpx.InvalidURL, httpx.UnsupportedProtocol) as e:
                    logger.debug(
                        "download id=%s size=%d host=%s attempt=%d error=%s bytes=0",
                        job.attachment.id,
                        job.attachment.size,
                        host,
                        attempt_num,
                        type(e).__name__,
                    )
                    job.fail(f"download error: {e or type(e).__name__}")
                    return None
                except httpx.TransportError as e:  # also a timeout or a body cut short
                    bytes_written = part.stat().st_size if part.is_file() else 0
                    logger.debug(
                        "download id=%s size=%d host=%s attempt=%d error=%s bytes=%d",
                        job.attachment.id,
                        job.attachment.size,
                        host,
                        attempt_num,
                        type(e).__name__,
                        bytes_written,
                    )
                    if last:
                        job.fail(f"network error: {e or type(e).__name__}")
                        return None
                    status = -1
                except httpx.HTTPError as e:  # e.g. too many redirects: no point in retrying
                    bytes_written = part.stat().st_size if part.is_file() else 0
                    logger.debug(
                        "download id=%s size=%d host=%s attempt=%d error=%s bytes=%d",
                        job.attachment.id,
                        job.attachment.size,
                        host,
                        attempt_num,
                        type(e).__name__,
                        bytes_written,
                    )
                    job.fail(f"download error: {e or type(e).__name__}")
                    return None

                bytes_written = part.stat().st_size if part.is_file() else 0
                logger.debug(
                    "download id=%s size=%d host=%s attempt=%d status=%d bytes=%d",
                    job.attachment.id,
                    job.attachment.size,
                    host,
                    attempt_num,
                    status,
                    bytes_written,
                )
                if status == -1:
                    self._sleep(RETRY_WAITS[attempt])
                    continue
                if status != 200:
                    job.fail(f"HTTP {status}")
                    return status
                os.replace(part, target)
                job.status, job.reason = DOWNLOADED, None
                return None
        except OSError as e:
            logger.debug(
                "download id=%s size=%d host=%s error=%s",
                job.attachment.id,
                job.attachment.size,
                host,
                type(e).__name__,
            )
            job.fail(f"cannot save the file: {e}")
        finally:
            with contextlib.suppress(OSError):
                part.unlink(missing_ok=True)
        return None

    def _fetch(self, url: str, part: Path, *, retry: bool) -> int:
        """One GET into `part`. Returns the HTTP status, or -1 for an answer worth another try."""
        with self.cdn.stream("GET", url) as response:
            if retry and response.status_code in _RETRY_STATUSES:
                return -1
            if response.status_code != 200:
                return response.status_code
            with part.open("wb") as file:
                for chunk in response.iter_bytes(CHUNK):
                    file.write(chunk)
                    self.progress.advance(len(chunk))
        return 200


def _url_path(url: str) -> str:
    try:
        return httpx.URL(url).path
    except httpx.InvalidURL:
        return url
