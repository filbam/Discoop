import json
import subprocess
import sys
import warnings
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
import pytest
import httpx

from discoop import cli, tokens
from discoop.api import DiscordAPI
from discoop.models import ChannelMessages, Message
from discoop.render import text as text_render
from discoop.split import split_markdown
from discoop.tokenstore import TokenStore
from export_helpers import AUTHOR, GENERAL, QUERY, SERVER, Lab
from fake_messages import CET, FIT, NOW, FakeChannel, FakeDiscord, message


def at(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 11, 3, hour, minute, tzinfo=CET).astimezone(UTC)


SAMPLE_MD = """\
# VUT FIT / #2bit-general
range: 2026-11-02 12:00 .. 2026-11-03 12:00 (UTC+01:00) | messages: 3 | files: 1

[2026-11-03 09:15] Student A (@student_a)
Kedy je deadline na #2bit-terminy?

[2026-11-03 10:00] Student B (@student_b)
Do piatku 2026-11-06 23:59.
- [file] zadanie.pdf 412KB https://cdn.discordapp.com/attachments/1.pdf
- [reactions] ✅3

[2026-11-03 11:30] Student C (@student_c)
Diky moc!
"""


def test_split_empty_and_invalid():
    assert split_markdown("", 100) == []
    assert split_markdown("   \n\n \t ", 100) == []
    with pytest.raises(ValueError, match="at least 1"):
        split_markdown("some text", 0)
    with pytest.raises(ValueError, match="at least 1"):
        split_markdown("some text", -10)


def test_split_boundaries_and_headers():
    parts = split_markdown(SAMPLE_MD, max_tokens=65)
    assert len(parts) >= 2
    for idx, part in enumerate(parts, 1):
        assert part.startswith(f"<!-- discoop part {idx} of {len(parts)} -->\n")
        assert tokens.estimate_tokens(part) <= 65

    # Check that message boundaries are preserved
    full = "".join(p.split("\n", 1)[1] for p in parts)
    assert "[2026-11-03 09:15] Student A (@student_a)" in full
    assert "[2026-11-03 10:00] Student B (@student_b)" in full
    assert "[2026-11-03 11:30] Student C (@student_c)" in full


def test_split_multiline_and_blank_lines_inside_message():
    text = """\
# VUT FIT / #discussion
range: all | messages: 2 | files: 0

[2026-11-03 10:00] Student A (@student_a)
First paragraph of a multiline message.

Second paragraph after an empty line.

Third paragraph with more details.
- [reactions] 👍2

[2026-11-03 10:30] Student B (@student_b)
Short reply.
"""
    parts = split_markdown(text, max_tokens=70)
    # The multiline message with empty lines must not be split across parts
    found_student_a_parts = [p for p in parts if "First paragraph" in p]
    assert len(found_student_a_parts) == 1
    p = found_student_a_parts[0]
    assert "First paragraph of a multiline message." in p
    assert "Second paragraph after an empty line." in p
    assert "Third paragraph with more details." in p
    assert "- [reactions] 👍2" in p


def test_split_oversized_message_alone_and_warning():
    huge_body = "word " * 300  # 1500 chars -> ~375 tokens
    text = f"""\
# VUT FIT / #general
range: all | messages: 3 | files: 0

[2026-11-03 09:00] User A (@user_a)
Normal message 1

[2026-11-03 09:30] User B (@user_b)
{huge_body}

[2026-11-03 10:00] User C (@user_c)
Normal message 2
"""
    warnings_caught = []

    def on_warn(w: str) -> None:
        warnings_caught.append(w)

    with warnings.catch_warnings():
        warnings.simplefilter("error")  # no Python warning: the callback (and the log) carry it
        parts = split_markdown(text, max_tokens=50, on_warning=on_warn)

    assert len(warnings_caught) >= 1
    assert all("exceeds max_tokens" in w for w in warnings_caught)
    # Check that huge message is alone in its part
    huge_parts = [p for p in parts if huge_body in p]
    assert len(huge_parts) == 1
    huge_part = huge_parts[0]
    assert "Normal message 1" not in huge_part
    assert "Normal message 2" not in huge_part


def run_cli(capsys, *args):
    with pytest.raises(SystemExit) as e:
        cli.main(["--agent", *args])
    captured = capsys.readouterr()
    return e.value.code, captured.out, captured.err


@pytest.fixture
def offline_discord(monkeypatch):
    TokenStore.default().save("tok")
    monkeypatch.setattr(cli, "utc_now", lambda: NOW)
    monkeypatch.setattr(cli, "LOCAL_ZONE", CET)
    msg1 = message(at(10), "Prva sprava")
    msg2 = message(at(11), "Druga sprava")
    fake = FakeDiscord({"200": FakeChannel([msg1, msg2])})

    def handle(request: httpx.Request) -> httpx.Response:
        if "/threads/search" in request.url.path:
            return httpx.Response(200, json={"threads": [], "has_more": False, "total_results": 0})
        return fake.handle(request)

    transport = httpx.MockTransport(handle)
    monkeypatch.setattr(cli, "DiscordAPI", lambda token, **kw: DiscordAPI(token, transport=transport))
    return fake


def test_cli_max_tokens_validation_before_api(capsys, monkeypatch):
    api_called = False

    def boom(*args, **kwargs):
        nonlocal api_called
        api_called = True
        raise AssertionError("Discord API must not be called!")

    monkeypatch.setattr(cli, "DiscordAPI", boom)

    # --max-tokens without --out
    code, _, err = run_cli(capsys, "messages", "-s", FIT, "-c", "200", "--max-tokens", "100")
    assert code == 8
    assert "--max-tokens only works with --out" in err
    assert not api_called

    # --max-tokens < 1 with --zip: --zip itself is no longer refused (it gets the parts too), the value still is
    code, _, err = run_cli(capsys, "messages", "-s", FIT, "-c", "200", "--zip", "exp.zip", "--max-tokens", "0")
    assert code == 8
    assert "--max-tokens must be at least 1" in err
    assert not api_called

    # --max-tokens < 1
    code, _, err = run_cli(capsys, "messages", "-s", FIT, "-c", "200", "--out", "out_dir", "--max-tokens", "0")
    assert code == 8
    assert "--max-tokens must be at least 1" in err
    assert not api_called


def test_cli_out_with_max_tokens_creates_parts(capsys, offline_discord, tmp_path):
    out_dir = tmp_path / "export"

    # First run: export with --max-tokens 40
    code, out, err = run_cli(
        capsys, "messages", "-s", FIT, "-c", "200", "--out", str(out_dir), "--max-tokens", "40"
    )
    assert code == 0, f"code is {code}, out={out!r}, err={err!r}"

    parts_dir = out_dir / "parts"
    assert parts_dir.is_dir()
    part_files = sorted(parts_dir.glob("part-*.md"))
    assert len(part_files) >= 2
    assert part_files[0].name == "part-001.md"
    assert part_files[1].name == "part-002.md"

    for idx, pf in enumerate(part_files, 1):
        content = pf.read_text(encoding="utf-8")
        assert content.startswith(f"<!-- discoop part {idx} of {len(part_files)} -->\n")

    # Verify manifest does NOT contain parts
    manifest_data = json.loads((out_dir / "manifest.json").read_text(encoding="utf-8"))
    assert "parts" not in manifest_data
    for ch in manifest_data.get("channels", []):
        assert "parts" not in ch

    # Place an old dummy part file in parts/
    old_dummy = parts_dir / "part-999.md"
    old_dummy.write_text("old part", encoding="utf-8")
    assert old_dummy.exists()

    # Re-run export
    code, _, _ = run_cli(
        capsys, "messages", "-s", FIT, "-c", "200", "--out", str(out_dir), "--max-tokens", "40"
    )
    assert code == 0
    assert not old_dummy.exists()


def test_export_summary_shows_token_estimate(capsys, offline_discord, tmp_path):
    out_dir = tmp_path / "export_summary"

    code, out, err = run_cli(capsys, "messages", "-s", FIT, "-c", "200", "--out", str(out_dir))
    assert code == 0
    assert "tokens" in out
    assert "(estimate, about 4 characters per token)" in out
    assert "~" in out

    # Test with --print (summary in stderr note)
    out_dir2 = tmp_path / "export_print"
    code, out, err = run_cli(capsys, "messages", "-s", FIT, "-c", "200", "--out", str(out_dir2), "--print", "--verbose")
    assert code == 0
    assert "tokens: ~" in err

    # Test zip export
    zip_path = tmp_path / "export.zip"
    code, out, err = run_cli(capsys, "messages", "-s", FIT, "-c", "200", "--zip", str(zip_path))
    assert code == 0
    assert "tokens" in out
    assert "(estimate, about 4 characters per token)" in out


# --- boundaries: message texts that look like headings --------------------------------------------------


def _channel(*texts: str) -> ChannelMessages:
    messages = tuple(
        Message(f"{GENERAL.id}{n:03d}", 0, NOW - timedelta(minutes=30 - n), None, AUTHOR, line)
        for n, line in enumerate(texts)
    )
    return ChannelMessages(SERVER, GENERAL, messages)


def _assert_whole(result: ChannelMessages, limits: tuple[int, ...] = (1, 40, 70, 120, 300, 100_000)) -> None:
    """Whatever the limit: the parts give the text back and no message text is cut between two parts."""
    markdown = text_render.markdown([result], QUERY, CET) + "\n"
    for limit in limits:
        parts = split_markdown(markdown, limit, on_warning=lambda _: None)
        assert "".join(part.split("\n", 1)[1] for part in parts) == markdown
        for message in result.messages:
            assert sum(message.text in part for part in parts) == 1, (limit, message.text)


def test_message_text_that_looks_like_a_heading_stays_whole():
    _assert_whole(
        _channel(
            "alpha first\n# Heading\nsecond line",
            "beta text\n\n# Heading\nrange: foo\nmore text",  # even a blank line before it, and `range:` after it
            "# Heading at the start of the gamma text",
            "delta",
        )
    )


def test_message_text_with_a_thread_heading_stays_whole():
    _assert_whole(_channel('before\n\n## thread "x"\nnot a thread header line\nafter', '## thread "y"', "plain text"))


def test_message_text_with_a_timestamp_line_after_text_stays_whole():
    _assert_whole(_channel("note\n[2026-01-01 10:00] x\nmore", "other text"))


def test_multiline_message_with_blank_lines_stays_whole():
    _assert_whole(_channel("one\n\ntwo\n\n\nthree\n\n- a list\n- of items", "short", "four\n\nfive"))


def test_every_block_of_the_real_renderer_is_a_boundary():
    """With a limit of 1 token each block is a part of its own: the heading of every channel and thread and every
    message. This ties the boundaries to the layout of `render/text.py`: a change there shows up here."""
    results = Lab().threaded_results()
    markdown = text_render.markdown(results, QUERY, CET) + "\n"
    channels = len(results)
    threads = sum(len(r.threads) for r in results)
    messages = sum(r.total_messages for r in results)
    parts = split_markdown(markdown, 1, on_warning=lambda _: None)
    assert len(parts) == channels + threads + messages
    firsts = [part.split("\n", 2)[1] for part in parts]
    assert sum(line.startswith("# ") for line in firsts) == channels
    assert sum(line.startswith("## thread ") for line in firsts) == threads
    assert sum(line.startswith("[") for line in firsts) == messages


def test_oversized_message_is_logged_without_a_python_warning(caplog):
    text = "# s / #c\nrange: all .. 2026-11-03 12:00 (UTC+01:00) | messages: 1 | files: 0\n\n"
    text += "[2026-11-03 09:00] User A (@user_a)\n" + "word " * 300 + "\n"
    with caplog.at_level("WARNING", logger="discoop.split"), warnings.catch_warnings():
        warnings.simplefilter("error")
        parts = split_markdown(text, 50)
    assert len(parts) >= 1
    assert any("exceeds max_tokens" in record.getMessage() for record in caplog.records)



def test_oversized_message_prints_nothing_to_stderr_by_itself(tmp_path):
    """No Python `UserWarning` and no bare log line from `logging.lastResort`: only `on_warning` tells the user."""
    code = (
        "from discoop.split import split_markdown\n"
        "text = '[2026-11-03 09:00] User A (@user_a)' + chr(10) + 'word ' * 300 + chr(10)\n"
        "print(len(split_markdown(text, 50)))\n"
    )
    done = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=tmp_path, check=True)
    assert done.stdout.strip() == "1"
    assert done.stderr == ""


def test_cli_zip_with_max_tokens_has_the_parts_in_the_zip(capsys, offline_discord, tmp_path):
    zip_path = tmp_path / "export.zip"
    code, out, err = run_cli(
        capsys, "messages", "-s", FIT, "-c", "200", "--zip", str(zip_path), "--max-tokens", "40"
    )
    assert code == 0, f"code is {code}, out={out!r}, err={err!r}"
    with zipfile.ZipFile(zip_path) as archive:
        names = archive.namelist()
        parts = {name: archive.read(name).decode("utf-8") for name in names if name.startswith("parts/")}
        manifest = json.loads(archive.read("manifest.json"))
    assert len(parts) >= 2
    assert sorted(parts) == [f"parts/part-{number:03d}.md" for number in range(1, len(parts) + 1)]
    for number, name in enumerate(sorted(parts), 1):
        assert parts[name].startswith(f"<!-- discoop part {number} of {len(parts)} -->\n")
    assert "part-0" not in json.dumps(manifest)

    folder = tmp_path / "folder"  # the same request into a folder gives the same parts
    code, _, _ = run_cli(capsys, "messages", "-s", FIT, "-c", "200", "--out", str(folder), "--max-tokens", "40")
    assert code == 0
    assert {f"parts/{p.name}": p.read_text(encoding="utf-8") for p in (folder / "parts").glob("part-*.md")} == parts


def test_cli_max_tokens_help_mentions_both_targets(capsys):
    with pytest.raises(SystemExit):
        cli.main(["messages", "--help"])
    text = " ".join(capsys.readouterr().out.split())
    assert "--max-tokens" in text and "--out/--zip" in text
    assert "parts/part-NNN.md" in text
