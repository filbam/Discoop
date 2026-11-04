import os
from datetime import timedelta

import httpx
import pytest

from discoop.api import DiscordAPI
from discoop.attachments import (
    DOWNLOADED,
    FAILED,
    PRESENT,
    SKIPPED,
    Downloader,
    FileJob,
    Stored,
    channel_folders,
    cdn_client,
    file_name,
    plan,
    replace_file,
    reuse_stored,
    safe_name,
    url_expiry,
)
from discoop.models import Attachment, Author, Channel, ChannelMessages, Message, Server
from fake_messages import FIT, NOW, FakeCDN, FakeDiscord, Network, signed_url

SOON = NOW + timedelta(hours=20)


# --- file names ------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("assignment.pdf", "assignment.pdf"),
        ("chart (1).png", "chart (1).png"),
        ('a<b>c:d"e/f\\g|h?i*j.txt', "a_b_c_d_e_f_g_h_i_j.txt"),
        ("tab\there\nnew\x7f.txt", "tab_here_new_.txt"),
        ("../../etc/passwd", "_.._etc_passwd"),  # no separator survives, so the name cannot leave its folder
        ("..\\..\\boot.ini", "_.._boot.ini"),
        ("..", "fallback"),
        ("   ", "fallback"),
        ("", "fallback"),
        ("name. . .", "name"),  # Windows would drop trailing dots and spaces silently
        (" .hidden", "hidden"),
        ("CON", "_CON"),
        ("con.txt", "_con.txt"),
        ("Nul .tar.gz", "_Nul .tar.gz"),
        ("COM1", "_COM1"),
        ("lpt9.log", "_lpt9.log"),
        ("COM¹", "_COM¹"),
        ("CONIN$", "_CONIN$"),
        ("CONSOLE.txt", "CONSOLE.txt"),
        ("com10", "com10"),
        ("é.txt", "é.txt"),  # Preserves Unicode combining character / NFC sanitization, as Windows and Linux store it
        ("Zápočet 🔒.pdf", "Zápočet 🔒.pdf"),  # Preserves Unicode diacritics and emoji to verify file-name sanitization
    ],
)
def test_safe_name(name, expected):
    assert safe_name(name, "fallback") == expected


def test_long_names_are_shortened_keeping_the_extension():
    assert safe_name("a" * 300 + ".pdf", "f") == "a" * 96 + ".pdf"
    emoji = safe_name("😀" * 80 + ".png", "f")  # 4 UTF-8 bytes each: the byte limit applies first
    assert emoji == "😀" * 49 + ".png" and len(emoji.encode()) == 200
    assert safe_name("x." + "y" * 150, "f") == ("x." + "y" * 150)[:100]  # a 150-character "extension" is not one
    assert safe_name("a" * 94 + " . " + "b" * 20 + ".pdf", "f") == "a" * 94 + ".pdf"  # no " ." left before .pdf
    stored = file_name("800000000000000001", "b" * 300 + ".pdf")
    assert stored == "800000000000000001_" + "b" * 77 + ".pdf" and len(stored) == 100


def test_file_names_start_with_the_attachment_id():
    assert file_name("800000000000000001", "assignment.pdf") == "800000000000000001_assignment.pdf"
    assert file_name("800000000000000001", "CON.txt") == "800000000000000001__CON.txt"
    assert file_name("800000000000000001", "...") == "800000000000000001_file"


def test_channel_folders_avoid_collisions():
    channels = [
        Channel("1", FIT, "general", 0),
        Channel("2", FIT, "General", 0),  # the same folder on Windows and macOS
        Channel("3", FIT, "a:b", 0),
        Channel("4", FIT, "a_b", 0),
        Channel("5", FIT, "con", 0),
        Channel("6", FIT, "..", 0),
        Channel("1", FIT, "general", 0),  # the same channel twice
    ]
    assert channel_folders(channels) == {
        "1": "general", "2": "General_2", "3": "a_b", "4": "a_b_4", "5": "_con", "6": "channel-6"
    }


def test_channel_folders_keep_existing_names():
    first = [Channel("1", FIT, "general", 0), Channel("2", FIT, "General", 0)]
    folders = channel_folders(first)
    later = Channel("3", FIT, "GENERAL", 0)  # turns up later and must not take a name that is used
    assert channel_folders([later, first[0]], existing=folders) == {**folders, "3": "GENERAL_3"}
    assert channel_folders([], existing=folders) == folders and folders == {"1": "general", "2": "General_2"}


def test_url_expiry():
    assert url_expiry(signed_url("1", "2", "f.png", expires=NOW)) == int(NOW.timestamp())
    assert url_expiry("https://cdn.discordapp.com/emojis/827833315666558996.webp?size=48") is None
    assert url_expiry("https://cdn.discordapp.com/a?ex=zz") is None


def test_plan_saves_an_attachment_once():
    shared = Attachment("800000000000000001", "a.pdf", None, 3, "https://cdn.discordapp.com/attachments/1/2/a.pdf")
    author = Author("1", "A", "a")
    first = Message("10", 0, NOW, None, author, "", attachments=(shared,))
    forward = Message("11", 0, NOW, None, author, "", attachments=(shared,), forwarded=True)
    result = ChannelMessages(Server(FIT, "VUT FIT"), Channel("200", FIT, "x", 0), (first, forward))
    jobs = plan([result], {"200": "x"})
    assert [(job.message_id, job.path) for job in jobs] == [("10", "files/x/800000000000000001_a.pdf")]


def test_plan_carries_over_between_calls():
    author = Author("1", "A", "a")
    shared = Attachment("800000000000000001", "a.pdf", None, 3, "https://cdn.discordapp.com/attachments/1/2/a.pdf")
    own = Attachment("800000000000000002", "b.pdf", None, 3, "https://cdn.discordapp.com/attachments/1/3/b.pdf")
    anonymous = Attachment("", "c.pdf", None, 3, "https://cdn.discordapp.com/attachments/1/4/c.pdf")
    server = Server(FIT, "VUT FIT")
    first = ChannelMessages(
        server, Channel("200", FIT, "x", 0), (Message("10", 0, NOW, None, author, "", attachments=(shared,)),)
    )
    second = ChannelMessages(
        server,
        Channel("202", FIT, "y", 0),
        (Message("11", 0, NOW, None, author, "", attachments=(shared, own, anonymous)),),
    )
    folders = {"200": "x", "202": "y"}
    seen: dict[str, FileJob] = {}
    new_first = plan([first], folders, seen)
    new_second = plan([second], folders, seen)
    assert [j.path for j in new_first] == ["files/x/800000000000000001_a.pdf"]
    assert [j.path for j in new_second] == ["files/y/800000000000000002_b.pdf", "files/y/11-2_c.pdf"]  # not `shared`
    assert list(seen) == ["800000000000000001", "800000000000000002", "11-2"]
    assert plan([first, second], folders, seen) == []  # nothing new
    # the same jobs as one call for everything
    assert [j.path for j in plan([first, second], folders)] == [j.path for j in new_first + new_second]


def test_reuse_stored():
    attachment = Attachment("800000000000000001", "a.bin", None, 3, "https://cdn.discordapp.com/a")
    short, whole = "files/old/800000000000000001_a.bin", "files/x/800000000000000001_a.bin"
    job = FileJob(attachment, "10", "200", "files/new/800000000000000001_a.bin", attachment.url)
    assert reuse_stored(job, {attachment.id: [Stored(short, 2), Stored(whole, 3)]})
    assert (job.status, job.path) == (PRESENT, whole)
    other = FileJob(attachment, "10", "200", "files/new/800000000000000001_a.bin", attachment.url)
    assert not reuse_stored(other, {attachment.id: [Stored(short, 2)]})  # the size differs
    assert other.status == "pending" and not reuse_stored(other, {})


def test_replace_file_retries_after_permission_errors(tmp_path, monkeypatch):
    source, target = tmp_path / "a", tmp_path / "b"
    source.write_bytes(b"new")
    target.write_bytes(b"old")
    real = os.replace
    refused = [2]

    def flaky(src, dst):
        if refused[0]:
            refused[0] -= 1
            raise PermissionError(13, "Access is denied")
        return real(src, dst)

    monkeypatch.setattr(os, "replace", flaky)
    sleeps: list[float] = []
    replace_file(source, target, sleep=sleeps.append)
    assert target.read_bytes() == b"new" and sleeps == [0.05, 0.1]
    source.write_bytes(b"newer")
    refused[0] = 99
    sleeps.clear()
    with pytest.raises(PermissionError):
        replace_file(source, target, sleep=sleeps.append)
    assert sleeps == [0.05, 0.1, 0.2, 0.4] and target.read_bytes() == b"new"
    refused[0] = 0
    with pytest.raises(FileNotFoundError):  # only PermissionError is retried
        replace_file(tmp_path / "missing", target, sleep=pytest.fail)


# --- downloading -----------------------------------------------------------------------------------


def job(attachment_id: str, content: bytes, *, expires=SOON, name="f.bin") -> FileJob:
    url = signed_url("200", attachment_id, name, expires=expires)
    attachment = Attachment(attachment_id, name, None, len(content), url)
    return FileJob(attachment, "10", "200", f"files/x/{file_name(attachment_id, name)}", url)


@pytest.fixture
def net():
    cdn = FakeCDN()
    network = Network(FakeDiscord(), cdn)
    network.sleeps = []
    return network


def downloader(net: Network, root) -> Downloader:
    transport = httpx.MockTransport(net.handle)
    api = DiscordAPI("tok", transport=transport, sleep=lambda s: None)
    return Downloader(api, cdn_client(transport), root, now=NOW.timestamp, sleep=net.sleeps.append)


def test_download_without_token(tmp_path, net):
    item = job("800000000000000001", b"data")
    net.cdn.add(item.url, b"data")
    downloader(net, tmp_path).run([item])
    assert (item.status, item.reason) == (DOWNLOADED, None)
    assert (tmp_path / item.path).read_bytes() == b"data"
    assert [r.url.host for r in net.log] == ["cdn.discordapp.com"]
    assert "authorization" not in net.log[0].headers
    assert net.log[0].headers["accept-encoding"] == "identity"


def test_retries_after_server_errors_and_network_errors(tmp_path, net):
    flaky, broken = job("800000000000000001", b"ok"), job("800000000000000002", b"never")
    net.cdn.add(flaky.url, b"ok")
    net.cdn.flaky[httpx.URL(flaky.url).path] = 2
    net.cdn.add(broken.url, b"never")
    net.cdn.flaky[httpx.URL(broken.url).path] = 5
    downloader(net, tmp_path).run([flaky, broken])
    assert flaky.status == DOWNLOADED and (tmp_path / flaky.path).read_bytes() == b"ok"
    assert (broken.status, broken.reason) == (FAILED, "HTTP 503")
    assert net.sleeps == [1.0, 2.0, 1.0, 2.0]
    assert net.discord.refresh_batches == []  # a 503 is not an expired URL

    def offline(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    lost = job("800000000000000003", b"x")
    Downloader(None, cdn_client(httpx.MockTransport(offline)), tmp_path, now=NOW.timestamp, sleep=lambda s: None).run([lost])
    assert (lost.status, lost.reason) == (FAILED, "network error: connection refused")
    assert not list(tmp_path.rglob("*.part"))

    def loop(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"Location": str(request.url)})

    looping = job("800000000000000004", b"x")
    Downloader(None, cdn_client(httpx.MockTransport(loop)), tmp_path, now=NOW.timestamp, sleep=pytest.fail).run([looping])
    assert looping.status == FAILED and looping.reason.startswith("download error: Exceeded maximum allowed redirects")

    def bad_proto(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"Location": "ftp://example.com/file.bin"})

    wrong_proto = job("800000000000000005", b"x")
    Downloader(None, cdn_client(httpx.MockTransport(bad_proto)), tmp_path, now=NOW.timestamp, sleep=pytest.fail).run([wrong_proto])
    assert wrong_proto.status == FAILED and wrong_proto.reason.startswith("download error: ")

    bad_url_job = job("800000000000000006", b"x")
    bad_url_job.url = "https://[::1/foo"
    Downloader(None, cdn_client(httpx.MockTransport(lambda r: httpx.Response(200))), tmp_path, sleep=pytest.fail).run([bad_url_job])
    assert bad_url_job.status == FAILED and bad_url_job.reason.startswith("download error: ")


def test_refused_url_is_refreshed_once(tmp_path, net):
    revoked, gone, unchanged = (job(f"80000000000000000{n}", b"abc") for n in (1, 2, 3))
    originals = [item.url for item in (revoked, gone, unchanged)]
    for item in (revoked, gone, unchanged):
        net.cdn.add(item.url, b"abc")
    net.cdn.revoked.add("a1")  # the CDN refuses the first signatures although `ex` is still ahead
    net.cdn.missing.add(httpx.URL(gone.url).path)
    net.discord.refreshed[unchanged.url] = unchanged.url  # Discord thinks the URL is fine
    downloader(net, tmp_path).run([revoked, gone, unchanged])
    assert revoked.status == DOWNLOADED and revoked.url.endswith("hm=fresh&")
    assert (gone.status, gone.reason) == (FAILED, "HTTP 404 (also after refreshing the URL)")
    assert (unchanged.status, unchanged.reason) == (FAILED, "HTTP 403; Discord gave no new URL")
    assert net.discord.refresh_batches == [originals]  # one request for all refused URLs


def test_download_rename_is_retried(tmp_path, net, monkeypatch):
    item = job("800000000000000001", b"data")
    net.cdn.add(item.url, b"data")
    real = os.replace
    refused = [1]

    def flaky(src, dst):
        if refused[0] and str(dst).endswith(item.path.rsplit("/", 1)[1]):
            refused[0] -= 1
            raise PermissionError(13, "Access is denied")
        return real(src, dst)

    monkeypatch.setattr(os, "replace", flaky)
    downloader(net, tmp_path).run([item])
    assert item.status == DOWNLOADED and (tmp_path / item.path).read_bytes() == b"data"
    assert net.sleeps == [0.05]


def test_failing_refresh_marks_the_files_failed(tmp_path, net):
    expired = job("800000000000000001", b"abc", expires=NOW - timedelta(hours=1))
    net.cdn.add(expired.url, b"abc")
    net.discord.refresh_status = 400
    downloader(net, tmp_path).run([expired])
    assert expired.status == FAILED
    assert expired.reason.startswith("HTTP 403; refreshing the URL failed: Discord API error 400 on POST")
    assert len(net.discord.refresh_batches) == 2  # before downloading, and after the CDN refused the old URL


def test_present_skipped_and_unusable_files(tmp_path, net):
    present, big, no_url = job("800000000000000001", b"abc"), job("800000000000000002", b"x" * 2000), job("3", b"")
    no_url.url = ""
    (tmp_path / "files" / "old").mkdir(parents=True)
    (tmp_path / "files" / "old" / "800000000000000001_renamed.bin").write_bytes(b"abc")
    downloader(net, tmp_path).run([present, big, no_url], max_size=1000)
    assert (present.status, present.path) == (PRESENT, "files/old/800000000000000001_renamed.bin")
    assert (big.status, big.reason) == (SKIPPED, "larger than --max-file-size")
    assert (no_url.status, no_url.reason) == (FAILED, "no download URL")
    assert net.log == []


def test_unwritable_target_fails_only_that_file(tmp_path, net):
    blocked, fine = job("800000000000000001", b"abc"), job("800000000000000002", b"def")
    for item, content in ((blocked, b"abc"), (fine, b"def")):
        net.cdn.add(item.url, content)
    (tmp_path / blocked.path).mkdir(parents=True)  # a folder where the file should go
    downloader(net, tmp_path).run([blocked, fine])
    assert blocked.status == FAILED and blocked.reason.startswith("cannot save the file:")
    assert fine.status == DOWNLOADED
