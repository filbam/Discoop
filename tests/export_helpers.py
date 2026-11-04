"""Offline helpers for the export writer tests: ready-made channels, and a fake Discord and CDN on one transport.

Names, texts and files are made up. Nothing here talks to the real Discord or its CDN.
"""

from collections import Counter
from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path

import httpx

from discoop import export as export_module
from discoop.api import DiscordAPI
from discoop.attachments import PART, Progress, cdn_client, channel_folders, plan
from discoop.models import Attachment, Author, Channel, ChannelMessages, Message, Server
from discoop.render import Query, jsonout, text
from discoop.snowflake import Window
from fake_messages import CET, FIT, NOW, FakeCDN, FakeDiscord, Network, signed_url

SOON = NOW + timedelta(hours=20)
SERVER = Server(FIT, "VUT FIT")
AUTHOR = Author("900000000000000001", "Student A", "student_a")
QUERY = Query(Window(NOW - timedelta(days=1), NOW), None, 5000, False)
OPTIONS = export_module.Options(files=True, max_file_size=None)

GENERAL = Channel("200", FIT, "2bit-general", 0)
TERMINY = Channel("202", FIT, "2bit-terminy", 0)
INFO = Channel("203", FIT, "2bit-info", 0)
CHANNELS = [GENERAL, TERMINY, INFO]

# Attachment IDs and file names per channel. SHARED is posted in two channels (e.g. forwarded) and saved once.
SHARED = "800000000000000003"
FILES = {
    "200": [("800000000000000001", "zadanie.pdf"), (SHARED, "graf (1).png")],
    "202": [("800000000000000002", "CON.txt")],
    "203": [(SHARED, "graf (1).png"), ("800000000000000004", "../../evil:name?.sh")],
}


def content(attachment_id: str) -> bytes:
    return f"test file {attachment_id}\n".encode() * 8


def tree(root: Path) -> dict[str, bytes]:
    """Every file under `root` by relative POSIX path."""
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


class Boom(Exception):
    """A crash in the code that uses the writer (a network error between two channels, say)."""


class Lab:
    """A fake Discord API and CDN behind one transport, and builders for channels whose files the CDN serves."""

    def __init__(self) -> None:
        self.discord = FakeDiscord()
        self.cdn = FakeCDN()
        self.network = Network(self.discord, self.cdn)
        self.transport = httpx.MockTransport(self.network.handle)
        self.sleeps: list[float] = []

    def file(self, attachment_id: str, name: str, data: bytes | None = None) -> Attachment:
        """An attachment the CDN serves (`data` or the default content)."""
        data = content(attachment_id) if data is None else data
        url = signed_url("200", attachment_id, "file.bin", expires=SOON)
        self.cdn.add(url, data)
        return Attachment(attachment_id, name, "application/octet-stream", len(data), url)

    def result(
        self, channel: Channel, files: list[tuple[str, str]] | None = None, *, texts: tuple[str, ...] = ("hello",)
    ) -> ChannelMessages:
        """A channel with a message per text and one message with all `files`."""
        messages = [
            Message(f"{channel.id}{n:03d}", 0, NOW - timedelta(minutes=30 - n), None, AUTHOR, line)
            for n, line in enumerate(texts)
        ]
        if files:
            attachments = tuple(self.file(attachment_id, name) for attachment_id, name in files)
            when = NOW - timedelta(minutes=10)
            messages.append(Message(f"{channel.id}900", 0, when, None, AUTHOR, "files", attachments=attachments))
        return ChannelMessages(SERVER, channel, tuple(messages))

    def results(self, channels: list[Channel] | None = None) -> list[ChannelMessages]:
        return [self.result(c, FILES.get(c.id), texts=(f"text of {c.name}",)) for c in channels or CHANNELS]

    def api(self) -> DiscordAPI:
        return DiscordAPI("tok", transport=self.transport, sleep=lambda s: None)

    def writer(
        self,
        target: Path,
        as_zip: bool = False,
        *,
        options: export_module.Options = OPTIONS,
        query: Query = QUERY,
        sleep: Callable[[float], None] | None = None,
        progress: Progress | None = None,
        created: datetime = NOW,
    ) -> export_module.ExportWriter:
        return export_module.ExportWriter(
            target,
            as_zip,
            query=query,
            options=options,
            api=self.api(),
            cdn=cdn_client(self.transport),
            created=created,
            tz=CET,
            now=NOW.timestamp,
            sleep=sleep or self.sleeps.append,
            progress=progress,
        )

    def export_all(self, target: Path, as_zip: bool, results: list[ChannelMessages], **kw) -> export_module.Exported:
        """The single-pass `export()` of finished channels."""
        return export_module.export(
            target,
            as_zip,
            results,
            kw.pop("query", QUERY),
            api=self.api(),
            cdn=cdn_client(self.transport),
            options=kw.pop("options", OPTIONS),
            created=NOW,
            tz=CET,
            now=NOW.timestamp,
            **kw,
        )

    @property
    def downloads(self) -> Counter:
        """CDN requests by URL path: how often each file was fetched."""
        return Counter(r.url.path for r in self.cdn.requests)


def stream(writer: export_module.ExportWriter, results: list[ChannelMessages], *, stop_after: int | None = None) -> None:
    """Open a writer for the channels of `results` and add them in order, as a caller that fetches them one by one.
    With `stop_after`, raise `Boom` after that many channels, like a crash while fetching the next one."""
    writer.open([r.channel for r in results])
    for number, result in enumerate(results):
        if stop_after is not None and number == stop_after:
            raise Boom("crash while fetching a channel")
        writer.add_channel(result)


def reference(results: list[ChannelMessages], query: Query = QUERY) -> dict[str, bytes]:
    """The expected files of an export of `results`, rendered in ONE pass as the old `export()` did, with every file
    downloaded: messages.md, messages.jsonl and channels/*.md."""
    folders = channel_folders(r.channel for r in results)
    jobs = plan(results, folders)
    for job in jobs:
        job.status = "downloaded"
    saved = export_module.with_paths(results, jobs)
    expected = {
        "messages.md": (text.markdown(saved, query, CET) + "\n").encode(),
        "messages.jsonl": "".join(line + "\n" for line in jsonout.lines(saved, CET)).encode(),
    }
    for item in saved:
        name = f"channels/{folders[item.channel.id]}.md"
        expected[name] = (text.markdown([item], query, CET, link_prefix="../") + "\n").encode()
    for job in jobs:
        expected[job.path] = content(job.attachment.id)
    return expected


def debris(root: Path) -> list[str]:
    """Temporary files (`*.part`) anywhere under `root`."""
    return sorted(p.relative_to(root).as_posix() for p in root.rglob("*") if p.name.endswith(PART))
