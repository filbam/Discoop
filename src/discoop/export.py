"""Exports: a folder or a zip with the messages, their files and a manifest (docs/navrh-nastroja.md, section 6.3).

    manifest.json         what was asked for, counts, and every attachment with its status
    messages.md           all channels, for people and AI
    messages.jsonl        one JSON message per line
    channels/<name>.md    the same Markdown, one file per channel
    files/<name>/<attachment id>_<file name>

Paths in messages.md and messages.jsonl are relative to the export folder, in channels/*.md to that file (`../files/…`).

A folder can be exported into again: saved files are reused (`present`), new ones downloaded, and the other files
are written anew for this run. A zip has the same content. It is built in a temporary folder next to it and replaces
an older zip only when complete; files from the older zip are reused as well. A folder or file that is not an export
is never overwritten.
"""

import json
import os
import shutil
import tempfile
import time
import zipfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime, tzinfo
from pathlib import Path, PurePosixPath
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
    PRESENT,
    SKIPPED,
    STORED_NAME,
    Downloader,
    FileJob,
    Progress,
    channel_folders,
    plan,
)
from discoop.errors import DiscoopError, ExitCode
from discoop.models import ChannelMessages
from discoop.render import Query, jsonout, text

MANIFEST = "manifest.json"
MESSAGES_MD = "messages.md"
MESSAGES_JSONL = "messages.jsonl"
CHANNELS_DIR = "channels"
TOOL = "discoop"
STATUSES = (DOWNLOADED, PRESENT, FAILED, SKIPPED)


@dataclass(frozen=True)
class Options:
    files: bool = True  # False: --no-files
    max_file_size: int | None = None  # bytes; None: no limit


@dataclass(frozen=True)
class Exported:
    path: Path
    results: list[ChannelMessages]  # attachments carry the path of their saved file
    jobs: list[FileJob]

    def count(self, status: str) -> int:
        return sum(1 for job in self.jobs if job.status == status)


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
    """Write the export. A file that cannot be downloaded is recorded as failed; only a write error is raised."""
    folders = channel_folders(r.channel for r in results)
    jobs = plan(results, folders)

    def build(root: Path) -> list[ChannelMessages]:
        _write(root / MANIFEST, _dumps({"tool": TOOL, "version": __version__, "complete": False}))
        if options.files:
            downloader = Downloader(api, cdn, root, now=now, progress=progress)
            downloader.run(jobs, options.max_file_size)
        else:
            for job in jobs:
                job.status, job.reason = SKIPPED, NO_FILES
        saved = with_paths(results, jobs)
        _write(root / MESSAGES_MD, text.markdown(saved, query, tz) + "\n")
        _write(root / MESSAGES_JSONL, "".join(line + "\n" for line in jsonout.lines(saved, tz)))
        _write_channels(root, saved, query, folders, tz)
        _write(root / MANIFEST, _dumps(manifest(saved, query, jobs, folders, options, created, tz)))
        return saved

    try:
        if not as_zip:
            target.mkdir(parents=True, exist_ok=True)
            return Exported(target, build(target), jobs)
        target.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix=".discoop-", dir=target.parent, ignore_cleanup_errors=True) as tmp:
            staging = Path(tmp)
            if target.exists():
                _reuse_zip(target, staging, jobs)
            saved = build(staging)
            _write_zip(staging, target)
        return Exported(target, saved, jobs)
    except OSError as e:
        raise DiscoopError(
            ExitCode.ERROR, f"Cannot write the export {target}: {e}", "Check the path, its permissions and free space."
        ) from e


def with_paths(results: Sequence[ChannelMessages], jobs: Sequence[FileJob]) -> list[ChannelMessages]:
    """The messages with `path` set on every attachment that is saved."""
    paths = {job.attachment.id: job.path for job in jobs if job.status in (DOWNLOADED, PRESENT) and job.attachment.id}
    out = []
    for result in results:
        messages = tuple(
            replace(m, attachments=tuple(replace(a, path=paths.get(a.id)) for a in m.attachments))
            if m.attachments
            else m
            for m in result.messages
        )
        out.append(replace(result, messages=messages))
    return out


def manifest(
    results: Sequence[ChannelMessages],
    query: Query,
    jobs: Sequence[FileJob],
    folders: Mapping[str, str],
    options: Options,
    created: datetime,
    tz: tzinfo | None = None,
) -> dict[str, Any]:
    head = jsonout.header(results, query, tz)
    return {
        "tool": TOOL,
        "version": __version__,
        "complete": True,
        "created": jsonout.iso_time(created, tz),
        "query": {
            "from": head["from"],
            "to": head["to"],
            "last": query.last,
            "max_messages": query.max_messages,
            "include_system": query.include_system,
            "mode": getattr(query, "mode", "safe"),
            "files": options.files,
            "max_file_size": options.max_file_size,
        },
        "truncated": head["truncated"],
        "counts": {
            "channels": len(results),
            "messages": sum(len(r.messages) for r in results),
            "files": len(jobs),
        }
        | {status: sum(1 for job in jobs if job.status == status) for status in STATUSES},
        "channels": [
            summary | {"markdown": f"{CHANNELS_DIR}/{folder}.md", "folder": f"{FILES_DIR}/{folder}"}
            for summary, folder in zip(head["channels"], (folders[r.channel.id] for r in results), strict=True)
        ],
        "attachments": [
            {
                "id": job.attachment.id,
                "message_id": job.message_id,
                "channel_id": job.channel_id,
                "filename": job.attachment.filename,
                "size": job.attachment.size,
                "status": job.status,
                "path": job.path if job.status in (DOWNLOADED, PRESENT) else None,
                "reason": job.reason,
            }
            for job in jobs
        ],
    }


def _write_channels(
    root: Path, saved: Sequence[ChannelMessages], query: Query, folders: Mapping[str, str], tz: tzinfo | None
) -> None:
    """channels/<name>.md for each channel; files of channels from an earlier run into this folder are removed."""
    folder = root / CHANNELS_DIR
    folder.mkdir(exist_ok=True)
    written: set[str] = set()
    for result in saved:
        name = f"{folders[result.channel.id]}.md"
        _write(folder / name, text.markdown([result], query, tz, link_prefix="../") + "\n")
        written.add(name.casefold())
    for old in folder.glob("*.md"):
        if old.name.casefold() not in written:
            old.unlink()


def _reuse_zip(old: Path, staging: Path, jobs: Sequence[FileJob]) -> None:
    """Copy the files of an older zip that this export needs into the staging folder, at their old paths."""
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
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(info) as source, target.open("wb") as copy:
                shutil.copyfileobj(source, copy)


def _write_zip(root: Path, target: Path) -> None:
    """Zip the staging folder into `target`, replacing it only when the new zip is complete."""
    partial = target.with_name(target.name + PART)
    try:
        with zipfile.ZipFile(partial, "w") as archive:
            for path in sorted(root.rglob("*")):
                if path.is_file() and not path.name.endswith(PART):
                    name = path.relative_to(root).as_posix()
                    # Attachments are mostly compressed already (images, PDFs, videos).
                    method = zipfile.ZIP_STORED if name.startswith(f"{FILES_DIR}/") else zipfile.ZIP_DEFLATED
                    archive.write(path, name, compress_type=method)
        os.replace(partial, target)
    finally:
        partial.unlink(missing_ok=True)


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


def _write(path: Path, content: str) -> None:
    """UTF-8 with `\\n` line ends on every OS, so a folder and a zip are the same everywhere."""
    path.write_text(content, encoding="utf-8", newline="\n")
