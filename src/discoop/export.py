"""Exports: a folder or a zip with the messages, their files and a manifest (docs/navrh-nastroja.md, section 6.3).

    manifest.json         what was asked for, counts, and every attachment with its status
    messages.md           all channels, for people and AI
    messages.jsonl        one JSON message per line
    channels/<name>.md    the same Markdown, one file per channel
    files/<name>/<attachment id>_<file name>
    parts/part-NNN.md     only with `max_tokens`: messages.md split into parts (not in the manifest)

Paths in messages.md and messages.jsonl are relative to the export folder, in channels/*.md to that file (`../files/…`).

Threads (forum posts, threads of text channels) are nested in the result of their channel (`ChannelMessages.threads`)
and stay with it: channels/<name>.md has a section per thread after the channel's own messages, messages.md the same,
messages.jsonl is flat (the messages of the channel, then those of each thread; see `render.jsonout`). The files of a
thread are saved in the folder of its channel. A channel and its threads are ONE unit: `ExportWriter.add_channel`
writes, commits and resumes them together, and the manifest entry of the channel counts the threads (`threads`,
`thread_messages`, only when there are some) and their files (`files`). There are no folders and no entries of their own
for threads.

With `max_tokens` the parts of messages.md (`split.split_markdown`) are made when the export is finished, into the
staging folder, and published with everything else, in a folder and in a zip alike. So a crash leaves no `parts/` in the
target, and publishing into a folder that holds an earlier export replaces its `parts/part-*.md` (they belong to the
messages.md they were made from, so they go also when the new run has no `max_tokens`).

A folder can be exported into again: saved files are reused (`present`), new ones downloaded, and the other files
are written anew for this run. A zip has the same content; files from an older zip are reused as well. A folder or
file that is not an export is never overwritten.

Crash safety (`ExportWriter`)
-----------------------------
An export is written channel by channel, never into the target itself. All of it goes to a staging folder next to the
target: `<target>.partial` (for `fit.zip` that is `fit.zip.partial`). Only `ExportWriter.close(complete=True)` publishes
it, so an earlier COMPLETE export in the target stays exactly as it was until a run has finished:

- folder: the files of the new run are moved into the target (renames on one volume, no copying), then
  channels/*.md, messages.md and messages.jsonl are replaced and manifest.json goes last. If the target does not exist
  or is empty, the staging folder is renamed to the target in one step instead.
- zip: the zip is built in the staging folder and replaces the old zip in one `os.replace`.

After a crash or an error only the staging folder is left. Its manifest says `complete: false`; it holds the channels
finished so far and their files. `find_unfinished` finds it, and a run with the same request (same fingerprint)
continues there: finished channels are neither fetched nor downloaded again. A staging folder of another request is
deleted when a new run starts; a folder that is not a discoop staging folder is never touched (`check_target`).

`messages.md` and `messages.jsonl` grow by one channel at a time. The manifest records how many bytes of each are
committed (`offsets`), so a half-written channel after a crash is cut off when the run continues.
Every file that is rewritten (manifest, channels/*.md) is written as `<name>.part` and renamed, with a few retries,
because Windows may refuse a rename while an antivirus scanner looks at the file for a moment.
"""

import contextlib
import hashlib
import json
import os
import shutil
import time
import zipfile
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime, tzinfo
from pathlib import Path, PurePosixPath
from types import TracebackType
from typing import Any

import httpx

from discoop import __version__
from discoop.api import DiscordAPI
from discoop.attachments import (
    DOWNLOADED,
    FAILED,
    FILES_DIR,
    NO_FILES,
    PART,
    PENDING,
    PRESENT,
    REPLACE_WAITS,
    SKIPPED,
    STORED_NAME,
    Downloader,
    FileJob,
    Progress,
    Stored,
    channel_folders,
    plan,
    replace_file,
    reuse_stored,
    stored_files,
)
from discoop.errors import DiscoopError, ExitCode
from discoop.models import Attachment, Channel, ChannelMessages
from discoop.render import Query, jsonout, text
from discoop.split import split_markdown

MANIFEST = "manifest.json"
MESSAGES_MD = "messages.md"
MESSAGES_JSONL = "messages.jsonl"
CHANNELS_DIR = "channels"
PARTS_DIR = "parts"
TOOL = "discoop"
STATUSES = (DOWNLOADED, PRESENT, FAILED, SKIPPED)
SAVED = (DOWNLOADED, PRESENT)  # statuses of a file that is in the export
STAGING_SUFFIX = ".partial"

# Why a channel was left out. Codes, not messages: the manifest holds no free text.
SKIP_NO_ACCESS = "no_access"
SKIP_NOT_FOUND = "not_found"
SKIP_REASONS = (SKIP_NO_ACCESS, SKIP_NOT_FOUND)


@dataclass(frozen=True)
class Options:
    files: bool = True  # False: --no-files
    max_file_size: int | None = None  # bytes; None: no limit
    threads: bool = True  # False: --no-threads; part of the request, so it is part of the resume fingerprint
    since_last: bool = False  # True: --since-last; likewise, a normal run must not continue it (or the reverse)


@dataclass(frozen=True)
class SkippedChannel:
    id: str
    reason: str  # one of SKIP_REASONS


@dataclass(frozen=True)
class ChannelDone:
    """A finished channel as the manifest of an unfinished export records it.

    `messages` are those posted in the channel itself, `files` include the files of its threads and `truncated` is
    true if the channel or one of its threads was cut short; `threads` and `thread_messages` are 0 without threads.
    """

    messages: int
    files: int
    truncated: bool
    threads: int = 0
    thread_messages: int = 0


@dataclass(frozen=True)
class Resume:
    """An unfinished export that a run with the same request can continue (see `find_unfinished`)."""

    staging: Path
    fingerprint: str
    created: datetime  # `created` of the first run: use it as "now" so a relative window (`--from 1d`) is the same
    done: Mapping[str, ChannelDone]  # finished channels by ID, in export order: do not fetch these again
    skipped: Mapping[str, str]  # channels the first run skipped (ID -> reason code); a new run may try them again
    manifest: Mapping[str, Any] = field(repr=False)  # the manifest as stored


@dataclass(frozen=True)
class Exported:
    """The outcome of an export (a finished one or, after `close(complete=False)`, an unfinished one).

    `path` is where the data is: the target after a finished export, else the staging folder (the target itself when
    nothing worth keeping was written). `results` are the channels added by this run, with the paths of their files;
    `jobs` all attachments of the export, also those of channels finished by an earlier run.
    `manifest` has the totals for the whole export.
    """

    path: Path
    results: list[ChannelMessages]  # attachments carry the path of their saved file
    jobs: list[FileJob]
    complete: bool = True
    interrupted: bool = False
    skipped: tuple[SkippedChannel, ...] = ()
    manifest: Mapping[str, Any] = field(default_factory=dict, repr=False)
    target: Path | None = None

    def count(self, status: str) -> int:
        return sum(1 for job in self.jobs if job.status == status)

    @property
    def partial(self) -> bool:
        """True if something asked for is missing (exit code `ExitCode.PARTIAL`); see `is_partial`."""
        return is_partial(self.skipped, self.jobs)


def is_partial(skipped: Iterable[SkippedChannel], jobs: Iterable[FileJob]) -> bool:
    """True if an export lacks something it was asked for: a channel left out for missing access or because it was
    not found, or a file that could not be downloaded (`failed`). Files left out on purpose (`--max-file-size`,
    `--no-files`) do not count."""
    return any(item.reason in SKIP_REASONS for item in skipped) or any(job.status == FAILED for job in jobs)


def skip_reason(code: ExitCode) -> str:
    """The manifest code for the error that made `messages` skip a channel."""
    if code == ExitCode.NO_ACCESS:
        return SKIP_NO_ACCESS
    if code == ExitCode.NOT_FOUND:
        return SKIP_NOT_FOUND
    raise ValueError(f"{code.name} is not a reason to skip a channel")


# --- the request -----------------------------------------------------------------------------------


def request_summary(
    targets: Iterable[Channel], query: Query, options: Options, tz: tzinfo | None = None
) -> dict[str, Any]:
    """What an export asks for: servers, channel IDs in order, the window and the options that change the data.

    No names and no message text. The download `mode` is left out: it only changes the pace, not the result.
    """
    channels = list({channel.id: channel for channel in targets}.values())
    head = jsonout.header([], query, tz)
    return {
        "servers": sorted({channel.server_id for channel in channels}),
        "channels": [channel.id for channel in channels],
        "from": head["from"],
        "to": head["to"],
        "last": query.last,
        "max_messages": query.max_messages,
        "include_system": query.include_system,
        "files": options.files,
        "max_file_size": options.max_file_size,
        "threads": options.threads,
        "since_last": options.since_last,
    }


def request_fingerprint(
    targets: Iterable[Channel], query: Query, options: Options, tz: tzinfo | None = None
) -> str:
    """A hash of the request, to tell whether an unfinished export belongs to the run that wants to continue it.

    It also covers the folder names of the channels, so a channel renamed in between does not get its files into
    another folder than the channels finished before. A relative window ends at "now": continue with
    `Resume.created` as "now", or the fingerprints differ.
    """
    channels = list({channel.id: channel for channel in targets}.values())
    return _digest(request_summary(channels, query, options, tz), channel_folders(channels))


def _digest(request: Mapping[str, Any], folders: Mapping[str, str]) -> str:
    material = json.dumps({"request": request, "folders": folders}, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


# --- staging and resuming ------------------------------------------------------------------------------


def staging_path(target: Path) -> Path:
    """Where an export to `target` is written until it is finished: `<target>.partial`."""
    return target.with_name(target.name + STAGING_SUFFIX)


def find_unfinished(target: Path, fingerprint: str | None = None) -> Resume | None:
    """The unfinished export (manifest `complete: false`) that an export to `target` left behind.

    With `fingerprint` (see `request_fingerprint`) only one of the same request is returned; without, any, which
    is how a caller reads `Resume.created` before it can build the request. None if there is none, it belongs to
    another request, or it is damaged (a file is missing or shorter than its manifest says).
    """
    staging = staging_path(target)
    data = _read_manifest(staging / MANIFEST)
    if data is None or data.get("complete") is not False:
        return None
    try:
        found = data["request"]["fingerprint"]
        if fingerprint is not None and found != fingerprint:
            return None
        created = datetime.fromisoformat(data["created"])
        offsets = {name: int(data["offsets"][name]) for name in (MESSAGES_MD, MESSAGES_JSONL)}
        done = {
            item["channel"]["id"]: ChannelDone(
                int(item["messages"]),
                int(item["files"]),
                bool(item["truncated"]),
                int(item.get("threads", 0)),
                int(item.get("thread_messages", 0)),
            )
            for item in data["channels"]
        }
        skipped = {item["id"]: item["reason"] for item in data["skipped_channels"]}
        markdown = [item["markdown"] for item in data["channels"]]
        saved = [
            entry["path"] for entry in data["attachments"] if entry["status"] in SAVED and entry["path"]
        ]
    except (KeyError, TypeError, ValueError):
        return None
    for name, size in offsets.items():
        with contextlib.suppress(OSError):
            if (staging / name).stat().st_size >= size:
                continue
        return None
    if not all((staging / name).is_file() for name in markdown):
        return None
    if not all((staging / name).is_file() or (target / name).is_file() for name in saved):
        return None
    return Resume(staging, found, created, done, skipped, data)


def check_target(path: Path, as_zip: bool) -> None:
    """Refuse a target that would overwrite something that is not a discoop export. Called before any API request."""
    if as_zip:
        if path.is_dir():
            raise DiscoopError(
                ExitCode.BAD_ARGS, f"{path} is a folder.", "Give --zip a file name such as export.zip, or use --out."
            )
        if path.exists() and not _is_export_zip(path):
            raise DiscoopError(
                ExitCode.BAD_ARGS,
                f"{path} exists and is not a discoop export.",
                "Choose another file name, or delete the file first.",
            )
    elif path.exists():
        if not path.is_dir():
            raise DiscoopError(ExitCode.BAD_ARGS, f"{path} is a file.", "Give --out a folder, or use --zip for a zip.")
        if any(path.iterdir()) and not _is_manifest(path / MANIFEST):
            raise DiscoopError(
                ExitCode.BAD_ARGS,
                f"{path} is not empty and is not a discoop export.",
                "Choose a new or empty folder, or the folder of an earlier export.",
            )
    staging = staging_path(path)
    if staging.exists() and not _is_staging(staging):
        raise DiscoopError(
            ExitCode.BAD_ARGS,
            f"{staging} exists and is not an unfinished discoop export.",
            "Move or delete it, or choose another target.",
        )


# --- writing ---------------------------------------------------------------------------------------


class ExportWriter:
    """Writes an export one channel at a time, so that a crash loses at most the channel being written.

        writer = ExportWriter(path, as_zip, query=query, options=options, api=api, cdn=cdn, created=now, tz=tz)
        resume = find_unfinished(path, request_fingerprint(channels, query, options, tz))
        with writer:
            writer.open(channels, resume)  # all channels of the export, in order
            for channel in channels:
                if resume and channel.id in resume.done:
                    continue  # finished by the run that was interrupted
                try:
                    result = fetch(channel)
                except DiscoopError as e:  # no access, not found
                    writer.add_skipped(channel, skip_reason(e.code))
                    continue
                writer.add_channel(result)  # downloads its files, appends it, saves the manifest
            exported = writer.close(complete=True)  # publishes the export; exported.partial: exit code PARTIAL

    Leaving the `with` block by an exception closes the writer with `complete=False`: the staging folder stays for
    the next run. Nothing but `close(complete=True)` touches the target. See the module docstring.

    `max_tokens` makes `close(complete=True)` also write `parts/part-NNN.md` (messages.md in parts of at most that many
    estimated tokens, no message split); `on_warning` is told about a message that is larger than that.

    Methods raise DiscoopError when they cannot write (ExitCode.ERROR), ValueError for a misuse.
    """

    def __init__(
        self,
        target: Path,
        as_zip: bool,
        *,
        query: Query,
        options: Options,
        api: DiscordAPI,
        cdn: httpx.Client,
        created: datetime,
        tz: tzinfo | None = None,
        now: Callable[[], float] = time.time,
        sleep: Callable[[float], None] = time.sleep,
        progress: Progress | None = None,
        max_tokens: int | None = None,
        on_warning: Callable[[str], None] | None = None,
    ) -> None:
        if max_tokens is not None and max_tokens < 1:
            raise ValueError(f"max_tokens must be at least 1, got {max_tokens}")
        self.target = target
        self.as_zip = as_zip
        self.max_tokens = max_tokens
        self.staging = staging_path(target)
        self.query = query
        self.options = options
        self.tz = tz
        self._api = api
        self._cdn = cdn
        self._now = now
        self._sleep = sleep  # pauses between attempts to rename a file; also the downloader's pauses
        self._progress = progress
        self._on_warning = on_warning
        self._parts: list[str] = []  # the parts of the finished export, relative to its root
        self._created = jsonout.iso_time(created, tz)
        self._opened = False
        self._closed = False
        self._resumed = False
        self._result: Exported | None = None
        self._request: dict[str, Any] = {}
        self._fingerprint = ""
        self._folders: dict[str, str] = {}
        self._target_ids: list[str] = []
        self._summaries: dict[str, dict[str, Any]] = {}  # channel ID -> its entry in the manifest, in export order
        self._skipped: dict[str, str] = {}
        self._seen: dict[str, FileJob] = {}
        self._saved: list[ChannelMessages] = []
        self._offsets = {MESSAGES_MD: 0, MESSAGES_JSONL: 0}
        self._in_target: dict[str, list[Stored]] | None = None
        self._in_zip: dict[str, list[int]] | None = None

    # -- state

    @property
    def fingerprint(self) -> str:
        return self._fingerprint

    @property
    def done(self) -> list[str]:
        """IDs of the finished channels, in export order (also those of an earlier run)."""
        return list(self._summaries)

    @property
    def pending(self) -> list[str]:
        """IDs of the targets that are neither finished nor skipped yet."""
        return [i for i in self._target_ids if i not in self._summaries and i not in self._skipped]

    @property
    def jobs(self) -> list[FileJob]:
        """All attachments of the finished channels."""
        return [job for job in self._seen.values() if job.channel_id in self._summaries]

    def __enter__(self) -> "ExportWriter":
        return self

    def __exit__(
        self, exc_type: type[BaseException] | None, exc: BaseException | None, tb: TracebackType | None
    ) -> None:
        if self._opened and not self._closed:
            try:
                self.close(complete=False)
            except (OSError, DiscoopError):
                if exc is None:
                    raise

    # -- steps

    def open(self, targets: Sequence[Channel], resume: Resume | None = None) -> None:
        """Start the export of `targets`, all of them, in export order.

        Folder names come from all of them, not from the order their messages arrive in. Without `resume`
        the staging folder is made anew (one left by an earlier run is deleted); with the `Resume` that
        `find_unfinished` returned for this request, the finished channels are taken over.
        """
        if self._opened:
            raise RuntimeError("The export is already open.")
        channels = list({channel.id: channel for channel in targets}.values())
        self._folders = channel_folders(channels)
        self._target_ids = [channel.id for channel in channels]
        self._request = request_summary(channels, self.query, self.options, self.tz)
        self._fingerprint = _digest(self._request, self._folders)
        with self._io():
            if resume is None:
                self._start()
            else:
                self._resume(resume)
        self._opened = True

    def fetch_files(self, results: Sequence[ChannelMessages]) -> None:
        """Download the files of several channels in one go (one progress bar for all), before `add_channel`.

        Optional: `add_channel` downloads the files of a channel that were not fetched yet.
        """
        self._require_open()
        with self._io():
            for result in results:
                self._register(result.channel)
            self._fetch(plan(results, self._folders, self._seen))

    def add_channel(self, result: ChannelMessages) -> list[FileJob]:
        """Download the files of a channel, append it to messages.md and messages.jsonl, write channels/<name>.md
        and save the manifest. Returns the jobs of the files first seen in this channel.

        A channel that is not one of the targets is accepted and added to them. The threads of the channel are part
        of `result` (`ChannelMessages.threads`): they are downloaded, written and recorded together with it, as one
        unit, and are never added on their own.
        """
        self._require_open()
        channel = result.channel
        if channel.id in self._summaries:
            raise ValueError(f"Channel {channel.id} is already in the export.")
        with self._io():
            self._register(channel)
            self._skipped.pop(channel.id, None)
            plan([result], self._folders, self._seen)
            self._fetch([job for job in self._seen.values() if job.status == PENDING and job.channel_id == channel.id])
            folder = self._folders[channel.id]
            saved = with_paths([result], list(self._seen.values()))[0]
            _atomic_write(
                self.staging / CHANNELS_DIR / f"{folder}.md",
                text.markdown([saved], self.query, self.tz, link_prefix="../") + "\n",
                self._sleep,
            )
            markdown = text.markdown([saved], self.query, self.tz) + "\n"
            if self._summaries:
                markdown = "\n" + markdown  # a blank line between channels, as one `text.markdown` call has it
            lines = "".join(line + "\n" for line in jsonout.lines([saved], self.tz))
            self._offsets = {
                MESSAGES_MD: self._append(MESSAGES_MD, markdown),
                MESSAGES_JSONL: self._append(MESSAGES_JSONL, lines),
            }
            self._summaries[channel.id] = jsonout.header([result], self.query, self.tz)["channels"][0] | {
                "markdown": f"{CHANNELS_DIR}/{folder}.md",
                "folder": f"{FILES_DIR}/{folder}",
            }
            self._saved.append(saved)
            self._commit()
        return [job for job in self._seen.values() if job.channel_id == channel.id]

    def add_skipped(self, channel: Channel, reason: str) -> None:
        """Record that a channel was left out (`SKIP_NO_ACCESS`, `SKIP_NOT_FOUND`; see `skip_reason`)."""
        self._require_open()
        if reason not in SKIP_REASONS:
            raise ValueError(f"Unknown reason {reason!r}; use one of {', '.join(SKIP_REASONS)}.")
        if channel.id in self._summaries:
            raise ValueError(f"Channel {channel.id} is already in the export.")
        self._register(channel)
        self._skipped[channel.id] = reason
        with self._io():
            self._commit()

    def bytes_to_download(self, result: ChannelMessages) -> int:
        """The bytes `add_channel(result)` would still have to download, by the sizes Discord gives.

        Left out are what is not downloaded: attachments already seen in this export (also those of a channel
        finished by an earlier run), saved files that are reused (in the staging folder, in the target folder or in
        the old zip, found by attachment ID and size), files over `max_file_size`, files without a download URL, and
        everything with `--no-files`. An attachment that is in the channel and in its thread counts once.
        """
        if not self.options.files:
            return 0
        in_staging = stored_files(self.staging) if self.staging.is_dir() else {}
        in_target = self._stored_in_target()
        in_zip = self._stored_in_zip()
        counted: set[str] = set()
        needed = 0
        for part in result.parts():
            for message in part.messages:
                for number, attachment in enumerate(message.attachments):
                    key = attachment.id or f"{message.id}-{number}"
                    if key in counted or key in self._seen:
                        continue
                    counted.add(key)
                    if self.options.max_file_size is not None and attachment.size > self.options.max_file_size:
                        continue
                    if not attachment.url.startswith("https://"):
                        continue
                    job = FileJob(attachment, message.id, result.channel.id, "", attachment.url)
                    if reuse_stored(job, in_staging) or reuse_stored(job, in_target):
                        continue
                    if any(attachment.size <= 0 or size == attachment.size for size in in_zip.get(attachment.id, [])):
                        continue
                    needed += max(attachment.size, 0)
        return needed

    def close(self, complete: bool) -> Exported:
        """End the export. `complete=True` publishes it (every target must be added or skipped, else ValueError);
        `complete=False` keeps the staging folder with `interrupted: true` in its manifest, to continue later.
        Calling it again returns the first result."""
        if self._closed:
            assert self._result is not None
            return self._result
        self._require_open()
        if complete and self.pending:
            raise ValueError(f"{len(self.pending)} channels were neither added nor skipped; close(complete=False).")
        with self._io():
            self._result = self._finish() if complete else self._abandon()
        self._closed = True
        return self._result

    # -- internals

    @contextlib.contextmanager
    def _io(self) -> Iterator[None]:
        try:
            yield
        except (OSError, zipfile.BadZipFile) as e:
            raise DiscoopError(
                ExitCode.ERROR,
                f"Cannot write the export {self.target}: {e}",
                "Check the path, its permissions and free space.",
            ) from e

    def _require_open(self) -> None:
        if not self._opened or self._closed:
            raise RuntimeError("The export is not open.")

    def _start(self) -> None:
        if self.staging.exists():
            if not _is_staging(self.staging):
                raise DiscoopError(
                    ExitCode.BAD_ARGS,
                    f"{self.staging} exists and is not an unfinished discoop export.",
                    "Move or delete it, or choose another target.",
                )
            _remove_tree(self.staging, self._sleep, strict=True)
        self.staging.mkdir(parents=True)
        self._commit()

    def _resume(self, resume: Resume) -> None:
        if resume.fingerprint != self._fingerprint or resume.staging != self.staging:
            raise ValueError("This unfinished export is of another request.")
        fresh = find_unfinished(self.target, self._fingerprint)
        if fresh is None:
            raise DiscoopError(
                ExitCode.ERROR,
                f"The unfinished export {self.staging} cannot be continued any more.",
                "Run the export again; it starts from the beginning.",
            )
        data = fresh.manifest
        self._created = data["created"]
        self._offsets = {name: int(data["offsets"][name]) for name in (MESSAGES_MD, MESSAGES_JSONL)}
        for name, size in self._offsets.items():  # cut off what a crash left after the last finished channel
            with (self.staging / name).open("r+b") as file:
                file.truncate(size)
        self._summaries = {item["channel"]["id"]: item for item in data["channels"]}
        for channel_id in data["targets"]:  # channels that turned up while the first run fetched
            if channel_id not in self._folders and channel_id in self._summaries:
                self._folders[channel_id] = self._summaries[channel_id]["folder"].split("/", 1)[1]
                self._target_ids.append(channel_id)
        for number, entry in enumerate(data["attachments"]):
            attachment = Attachment(entry["id"], entry["filename"], None, entry["size"], "")
            path = entry["path"] or ""
            job = FileJob(
                attachment, entry["message_id"], entry["channel_id"], path, "", entry["status"], entry["reason"]
            )
            self._seen[entry["id"] or f"{entry['message_id']}-resumed-{number}"] = job
        self._resumed = True
        self._commit()

    def _register(self, channel: Channel) -> None:
        if channel.id not in self._folders:
            self._folders = channel_folders([channel], existing=self._folders)
        if channel.id not in self._target_ids:
            self._target_ids.append(channel.id)

    def _stored_in_target(self) -> dict[str, list[Stored]]:
        """The files of an earlier export in the target folder, by attachment ID (read once: the target does not
        change before the export is published). None for a zip."""
        if self._in_target is None:
            self._in_target = stored_files(self.target) if not self.as_zip and self.target.is_dir() else {}
        return self._in_target

    def _stored_in_zip(self) -> dict[str, list[int]]:
        """The sizes of the files in the old zip at the target, by attachment ID (read once, in one pass)."""
        if self._in_zip is None:
            self._in_zip = _zip_files(self.target) if self.as_zip and self.target.is_file() else {}
        return self._in_zip

    def _fetch(self, jobs: list[FileJob]) -> None:
        """Get the files into the staging folder: reuse the saved ones, download the rest."""
        if not jobs:
            return
        if not self.options.files:
            for job in jobs:
                job.status, job.reason = SKIPPED, NO_FILES
            return
        if self.as_zip:
            if self.target.is_file():
                _reuse_zip(self.target, self.staging, jobs)
        else:
            in_target = self._stored_in_target()
            for job in jobs:
                reuse_stored(job, in_target)  # files of an earlier export stay where they are
        todo = [job for job in jobs if job.status == PENDING]
        downloader = Downloader(
            self._api, self._cdn, self.staging, now=self._now, sleep=self._sleep, progress=self._progress
        )
        downloader.run(todo, self.options.max_file_size)

    def _append(self, name: str, data: str) -> int:
        """Write `data` after the committed part of `name`; returns the new length. A torn tail is overwritten."""
        path = self.staging / name
        raw = data.encode("utf-8")
        with path.open("r+b" if path.exists() else "wb") as file:
            file.seek(self._offsets[name])
            file.truncate()
            file.write(raw)
            file.flush()
            os.fsync(file.fileno())
        return self._offsets[name] + len(raw)

    def _commit(self, *, interrupted: bool = False) -> None:
        """Save the progress: the manifest of the unfinished export, written atomically.

        `interrupted` is true only in the manifest `close(complete=False)` leaves. A staging folder whose manifest says
        `complete: false, interrupted: false` was left by a run that died without closing the writer.
        """
        data = self._manifest(complete=False, interrupted=interrupted, offsets=True)
        _atomic_write(self.staging / MANIFEST, _dumps(data), self._sleep)

    def _manifest(self, *, complete: bool, interrupted: bool, offsets: bool) -> dict[str, Any]:
        jobs = self.jobs
        channels = list(self._summaries.values())
        skipped = [SkippedChannel(i, reason) for i, reason in self._skipped.items()]
        head = jsonout.header([], self.query, self.tz)
        data: dict[str, Any] = {
            "tool": TOOL,
            "version": __version__,
            "complete": complete,
            "interrupted": interrupted,
            "partial": is_partial(skipped, jobs),
            "created": self._created,
            "request": {"fingerprint": self._fingerprint} | self._request,
            "query": {
                "from": head["from"],
                "to": head["to"],
                "last": self.query.last,
                "max_messages": self.query.max_messages,
                "include_system": self.query.include_system,
                "mode": getattr(self.query, "mode", "safe"),
                "files": self.options.files,
                "max_file_size": self.options.max_file_size,
            },
            "targets": list(self._target_ids),
            "skipped_channels": [{"id": item.id, "reason": item.reason} for item in skipped],
            "truncated": any(item["truncated"] for item in channels),
            "counts": self._counts(channels, jobs),
            "channels": channels,
            "attachments": [
                {
                    "id": job.attachment.id,
                    "message_id": job.message_id,
                    "channel_id": job.channel_id,
                    "filename": job.attachment.filename,
                    "size": job.attachment.size,
                    "status": job.status,
                    "path": job.path if job.status in SAVED else None,
                    "reason": job.reason,
                }
                for job in jobs
            ],
        }
        if offsets:
            data["offsets"] = dict(self._offsets)  # bytes of messages.md and messages.jsonl that are finished channels
        return data

    @staticmethod
    def _counts(channels: Sequence[Mapping[str, Any]], jobs: Sequence[FileJob]) -> dict[str, Any]:
        """Totals for the manifest. `threads` and `thread_messages` appear only if some channel has threads, so an
        export without them has exactly the counts it had before threads existed."""
        counts: dict[str, Any] = {
            "channels": len(channels),
            "messages": sum(item["messages"] for item in channels),
        }
        threads = sum(item.get("threads", 0) for item in channels)
        if threads:
            counts["threads"] = threads
            counts["thread_messages"] = sum(item.get("thread_messages", 0) for item in channels)
        counts["files"] = len(jobs)
        return counts | {status: sum(1 for job in jobs if job.status == status) for status in STATUSES}

    def _abandon(self) -> Exported:
        keep = bool(self._summaries or self._skipped or self._resumed)
        if keep:
            self._commit(interrupted=True)
        else:  # nothing worth continuing from
            _remove_tree(self.staging, self._sleep, strict=False)
        data = self._manifest(complete=False, interrupted=True, offsets=True)
        return self._exported(self.staging if keep else self.target, data, complete=False)

    def _finish(self) -> Exported:
        if not self._summaries:  # an export without channels still has its files
            self._offsets = {
                MESSAGES_MD: self._append(MESSAGES_MD, "\n"),
                MESSAGES_JSONL: self._append(MESSAGES_JSONL, ""),
            }
        self._parts = self._write_parts()
        data = self._manifest(complete=True, interrupted=False, offsets=False)
        final = _dumps(data)
        keep = self._keep()
        if self.as_zip:
            self._publish_zip(keep, final)
        else:
            self._publish_folder(keep, final)
        return self._exported(self.target, data, complete=True)

    def _exported(self, path: Path, data: dict[str, Any], *, complete: bool) -> Exported:
        return Exported(
            path,
            list(self._saved),
            self.jobs,
            complete=complete,
            interrupted=not complete,
            skipped=tuple(SkippedChannel(i, reason) for i, reason in self._skipped.items()),
            manifest=data,
            target=self.target,
        )

    def _keep(self) -> set[str]:
        """The files of the finished export, relative to its root. The rest of the staging folder is not published."""
        keep = {MANIFEST, MESSAGES_MD, MESSAGES_JSONL}
        keep.update(item["markdown"] for item in self._summaries.values())
        keep.update(job.path for job in self.jobs if job.status in SAVED)
        keep.update(self._parts)
        return keep

    def _write_parts(self) -> list[str]:
        """Split the finished messages.md into parts in the staging folder; returns their paths. Parts that an earlier
        attempt to finish left there are deleted first, so no part of another split stays."""
        folder = self.staging / PARTS_DIR
        for old in folder.glob("part-*.md") if folder.is_dir() else ():
            old.unlink()
        if self.max_tokens is None:
            return []
        markdown = (self.staging / MESSAGES_MD).read_bytes().decode("utf-8")
        names = []
        for number, part in enumerate(split_markdown(markdown, self.max_tokens, on_warning=self._on_warning), 1):
            name = f"{PARTS_DIR}/part-{number:03d}.md"
            folder.mkdir(exist_ok=True)
            (self.staging / name).write_bytes(part.encode("utf-8"))
            names.append(name)
        return names

    def _publish_zip(self, keep: set[str], final: str) -> None:
        """Build the zip in the staging folder and put it in place with one rename."""
        temp = self.staging / (self.target.name + PART)
        try:
            with zipfile.ZipFile(temp, "w") as archive:
                for name in sorted(keep):
                    # Attachments are mostly compressed already (images, PDFs, videos).
                    method = zipfile.ZIP_STORED if name.startswith(f"{FILES_DIR}/") else zipfile.ZIP_DEFLATED
                    if name == MANIFEST:
                        archive.writestr(name, final.encode("utf-8"), compress_type=method)
                    else:
                        archive.write(self.staging / name, name, compress_type=method)
            replace_file(temp, self.target, sleep=self._sleep)
        finally:
            with contextlib.suppress(OSError):
                temp.unlink(missing_ok=True)
        self._discard_staging(final)

    def _publish_folder(self, keep: set[str], final: str) -> None:
        target = self.target
        if not target.exists() or (target.is_dir() and not any(target.iterdir())):
            _prune(self.staging, keep)  # a new folder: the staging folder becomes the export in one rename
            _atomic_write(self.staging / MANIFEST, final, self._sleep)
            if target.exists():
                target.rmdir()
            replace_file(self.staging, target, sleep=self._sleep)
            return
        # An earlier export is there: add what this run has, the manifest last.
        for job in self.jobs:
            source = self.staging / job.path
            if job.status in SAVED and source.is_file():
                destination = target / job.path
                destination.parent.mkdir(parents=True, exist_ok=True)
                with contextlib.suppress(OSError):  # an unfinished download of this file from an older run
                    destination.with_name(destination.name + PART).unlink(missing_ok=True)
                replace_file(source, destination, sleep=self._sleep)
        folder = target / CHANNELS_DIR
        folder.mkdir(exist_ok=True)
        written: set[str] = set()
        for item in self._summaries.values():
            name = PurePosixPath(item["markdown"]).name
            replace_file(self.staging / item["markdown"], folder / name, sleep=self._sleep)
            written.add(name.casefold())
        for old in folder.glob("*.md"):  # channels of an earlier run that this one does not have
            if old.name.casefold() not in written:
                old.unlink()
        replace_file(self.staging / MESSAGES_MD, target / MESSAGES_MD, sleep=self._sleep)
        replace_file(self.staging / MESSAGES_JSONL, target / MESSAGES_JSONL, sleep=self._sleep)
        self._publish_parts()
        _atomic_write(target / MANIFEST, final, self._sleep)
        self._discard_staging(final)

    def _publish_parts(self) -> None:
        """Replace the `parts/part-*.md` of an earlier export in the target by the parts of this one (or by none)."""
        folder = self.target / PARTS_DIR
        names = {PurePosixPath(name).name for name in self._parts}
        if names:
            folder.mkdir(exist_ok=True)
        for name in sorted(names):
            replace_file(self.staging / PARTS_DIR / name, folder / name, sleep=self._sleep)
        if folder.is_dir():
            for old in folder.glob("part-*.md"):
                if old.name not in names:
                    old.unlink()
            with contextlib.suppress(OSError):
                folder.rmdir()  # only an empty folder goes

    def _discard_staging(self, final: str) -> None:
        """Delete the staging folder of a published export. If Windows will not let it go, the leftover says so."""
        with contextlib.suppress(OSError):
            _atomic_write(self.staging / MANIFEST, final, self._sleep)  # `complete: true`: nobody resumes this
        _remove_tree(self.staging, self._sleep, strict=False)


# --- the whole export in one call ------------------------------------------------------------------


def export(
    target: Path,
    as_zip: bool,
    results: Sequence[ChannelMessages],
    query: Query,
    *,
    api: DiscordAPI,
    cdn: httpx.Client,
    options: Options,
    created: datetime,
    tz: tzinfo | None = None,
    now: Callable[[], float] = time.time,
    progress: Progress | None = None,
) -> Exported:
    """Write the export of channels that are all fetched. A file that cannot be downloaded is recorded as failed; only
    a write error is raised. Unlike `ExportWriter` this never continues an unfinished export: it starts anew."""
    writer = ExportWriter(
        target,
        as_zip,
        query=query,
        options=options,
        api=api,
        cdn=cdn,
        created=created,
        tz=tz,
        now=now,
        progress=progress,
    )
    with writer:
        writer.open([result.channel for result in results])
        writer.fetch_files(results)
        for result in results:
            writer.add_channel(result)
        return writer.close(complete=True)


def with_paths(results: Sequence[ChannelMessages], jobs: Sequence[FileJob]) -> list[ChannelMessages]:
    """The messages, also those of the threads, with `path` set on every attachment that is saved."""
    paths = {job.attachment.id: job.path for job in jobs if job.status in SAVED and job.attachment.id}
    return [_with_paths(result, paths) for result in results]


def _with_paths(result: ChannelMessages, paths: Mapping[str, str]) -> ChannelMessages:
    messages = tuple(
        replace(m, attachments=tuple(replace(a, path=paths.get(a.id)) for a in m.attachments))
        if m.attachments
        else m
        for m in result.messages
    )
    return replace(result, messages=messages, threads=tuple(_with_paths(t, paths) for t in result.threads))


# --- helpers ---------------------------------------------------------------------------------------


def _zip_files(path: Path) -> dict[str, list[int]]:
    """The saved files in a zip (`files/<folder>/<attachment id>_<name>`) as their sizes by attachment ID. A zip that
    cannot be read has none."""
    found: dict[str, list[int]] = {}
    try:
        with zipfile.ZipFile(path) as archive:
            for info in archive.infolist():
                parts = PurePosixPath(info.filename).parts
                match = STORED_NAME.match(parts[-1]) if len(parts) >= 3 and parts[0] == FILES_DIR else None
                if match and not info.is_dir():
                    found.setdefault(match.group(1), []).append(info.file_size)
    except (zipfile.BadZipFile, OSError):
        return {}
    return found


def _reuse_zip(old: Path, staging: Path, jobs: Sequence[FileJob]) -> None:
    """Copy the files of an older zip that these jobs need into the staging folder, at their old paths."""
    sizes = {job.attachment.id: job.attachment.size for job in jobs if job.attachment.id}
    root = staging.resolve()
    with zipfile.ZipFile(old) as archive:
        for info in archive.infolist():
            parts = PurePosixPath(info.filename).parts
            match = STORED_NAME.match(parts[-1]) if len(parts) >= 3 and parts[0] == FILES_DIR else None
            if info.is_dir() or match is None or match.group(1) not in sizes or ".." in parts:
                continue
            size = sizes[match.group(1)]
            target = staging.joinpath(*parts)
            if (size > 0 and info.file_size != size) or not target.resolve().is_relative_to(root):
                continue
            if target.is_file() and target.stat().st_size == info.file_size:
                continue  # taken over by an earlier run into this staging folder
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(info) as source, target.open("wb") as copy:
                shutil.copyfileobj(source, copy)


def _prune(root: Path, keep: set[str]) -> None:
    """Delete everything under `root` that is not in `keep` (paths relative to `root`), and the empty folders."""
    for path in sorted(root.rglob("*"), reverse=True):
        if path.is_dir():
            with contextlib.suppress(OSError):
                path.rmdir()  # only an empty one goes
        elif path.relative_to(root).as_posix() not in keep:
            path.unlink()


def _remove_tree(path: Path, sleep: Callable[[float], None], *, strict: bool) -> None:
    """Delete a folder, trying again when Windows holds a file. `strict`: raise if it will not go."""
    for wait in (*REPLACE_WAITS, None):
        try:
            shutil.rmtree(path)
            return
        except FileNotFoundError:
            return
        except OSError:
            if wait is None:
                if strict:
                    raise
                return
            sleep(wait)


def _is_staging(path: Path) -> bool:
    """A folder that may be deleted as a staging folder: empty, or with a discoop manifest."""
    return path.is_dir() and (not any(path.iterdir()) or _is_manifest(path / MANIFEST))


def _read_manifest(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_bytes())
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) and data.get("tool") == TOOL else None


def _is_manifest(path: Path) -> bool:
    try:
        return _is_manifest_data(path.read_bytes())
    except OSError:
        return False


def _is_export_zip(path: Path) -> bool:
    try:
        with zipfile.ZipFile(path) as archive:
            return _is_manifest_data(archive.read(MANIFEST))
    except (zipfile.BadZipFile, KeyError, OSError):
        return False


def _is_manifest_data(raw: bytes) -> bool:
    try:
        data = json.loads(raw)
    except ValueError:
        return False
    return isinstance(data, dict) and data.get("tool") == TOOL


def _dumps(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2) + "\n"


def _atomic_write(path: Path, content: str, sleep: Callable[[float], None] = time.sleep) -> None:
    """UTF-8 with `\\n` line ends on every OS, so a folder and a zip are the same everywhere.

    Written to `<name>.part` and renamed, so the file is either the old one or the new one, never half of it.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + PART)
    try:
        with temp.open("wb") as file:
            file.write(content.encode("utf-8"))
            file.flush()
            os.fsync(file.fileno())
        replace_file(temp, path, sleep=sleep)
    finally:
        with contextlib.suppress(OSError):
            temp.unlink(missing_ok=True)
