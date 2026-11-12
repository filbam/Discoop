"""Tests for scripts/release_notes.py and .github/workflows/release.yml."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import re
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "release_notes.py"
WORKFLOW = ROOT / ".github" / "workflows" / "release.yml"


def _load_release_notes_module():
    spec = importlib.util.spec_from_file_location("_discoop_release_notes", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _parse_yaml_scalar(raw: str) -> object:
    value = raw.strip()
    if not value:
        return ""
    if (value.startswith("'") and value.endswith("'")) or (
        value.startswith('"') and value.endswith('"')
    ):
        return value[1:-1]
    if value.startswith("[") and value.endswith("]"):
        inner = value[1:-1].strip()
        if not inner:
            return []
        return [_parse_yaml_scalar(item) for item in inner.split(",")]
    if value == "true":
        return True
    if value == "false":
        return False
    if re.fullmatch(r"-?[0-9]+", value):
        return int(value)
    return value


def _strip_yaml_comment(line: str) -> str:
    in_single = False
    in_double = False
    for index, ch in enumerate(line):
        if ch == "'" and not in_double:
            in_single = not in_single
        elif ch == '"' and not in_single:
            in_double = not in_double
        elif ch == "#" and not in_single and not in_double:
            if index == 0 or line[index - 1].isspace():
                return line[:index].rstrip()
    return line.rstrip()


def _decode_workflow_bytes(raw: bytes) -> str:
    """Normalize CRLF line endings to LF before validating and decoding workflow YAML."""
    normalized = raw.replace(b"\r\n", b"\n")
    assert b"\r" not in normalized, "Workflow YAML must not contain bare CR characters."
    assert b"\t" not in normalized, "Workflow YAML must not contain tabs."
    assert normalized.endswith(b"\n"), "Workflow YAML must end with a newline."
    return normalized.decode("utf-8")


def _parse_workflow_yaml(text: str) -> dict[str, object]:
    """Parse a clean indentation-based subset of YAML used by workflow files."""
    assert "\t" not in text, "Workflow YAML must not contain tab characters."
    tokens: list[tuple[int, str]] = []
    for lineno, raw_line in enumerate(text.splitlines(), start=1):
        stripped = _strip_yaml_comment(raw_line)
        if not stripped.strip():
            continue
        indent = len(stripped) - len(stripped.lstrip(" "))
        assert indent % 2 == 0, f"Line {lineno} has non-even indentation: {raw_line!r}"
        tokens.append((indent, stripped.strip()))

    def parse_block(idx: int, min_indent: int) -> tuple[object, int]:
        assert idx < len(tokens)
        indent, content = tokens[idx]
        assert indent >= min_indent
        if content.startswith("- "):
            return parse_seq(idx, indent)
        return parse_map(idx, indent)

    def parse_seq(idx: int, seq_indent: int) -> tuple[list[object], int]:
        items: list[object] = []
        while idx < len(tokens):
            indent, content = tokens[idx]
            if indent < seq_indent:
                break
            assert indent == seq_indent and content.startswith("- "), (
                f"Expected sequence item at indent {seq_indent}, got {content!r}"
            )
            rest = content[2:].strip()
            idx += 1
            if not rest:
                child, idx = parse_block(idx, seq_indent + 2)
                items.append(child)
                continue
            if ":" in rest and not (rest.startswith("'") or rest.startswith('"')):
                key, raw_val = rest.split(":", 1)
                item_map: dict[str, object] = {}
                key = key.strip()
                raw_val = raw_val.strip()
                if raw_val:
                    item_map[key] = _parse_yaml_scalar(raw_val)
                else:
                    child, idx = parse_block(idx, seq_indent + 4)
                    item_map[key] = child
                if idx < len(tokens) and tokens[idx][0] == seq_indent + 2 and not tokens[idx][1].startswith("- "):
                    extra, idx = parse_map(idx, seq_indent + 2)
                    item_map.update(extra)
                items.append(item_map)
            else:
                items.append(_parse_yaml_scalar(rest))
        return items, idx

    def parse_map(idx: int, map_indent: int) -> tuple[dict[str, object], int]:
        mapping: dict[str, object] = {}
        while idx < len(tokens):
            indent, content = tokens[idx]
            if indent < map_indent:
                break
            assert indent == map_indent and not content.startswith("- "), (
                f"Expected mapping entry at indent {map_indent}, got {content!r}"
            )
            assert ":" in content, f"Invalid mapping line: {content!r}"
            key, raw_val = content.split(":", 1)
            key = key.strip()
            assert key not in mapping, f"Duplicate YAML key {key!r}"
            raw_val = raw_val.strip()
            idx += 1
            if raw_val:
                mapping[key] = _parse_yaml_scalar(raw_val)
            else:
                assert idx < len(tokens) and tokens[idx][0] > map_indent, (
                    f"Missing block under YAML key {key!r}"
                )
                child, idx = parse_block(idx, tokens[idx][0])
                mapping[key] = child
        return mapping, idx

    parsed, next_idx = parse_map(0, 0)
    assert next_idx == len(tokens)
    return parsed


def test_tag_to_version_accepts_strict_digits() -> None:
    mod = _load_release_notes_module()
    assert mod.tag_to_version("v1.0.0") == "1.0.0"
    assert mod.tag_to_version("v0.12.345") == "0.12.345"


@pytest.mark.parametrize(
    "bad_tag",
    [
        "",
        "1.0.0",
        "V1.0.0",
        "v1.0",
        "v1.0.0.0",
        "v1.0.0-rc1",
        "v1.0.0+build1",
        "refs/tags/v1.0.0",
        "v1.0.0\n",
        "v\u0661.0.0",
    ],
)
def test_tag_to_version_rejects_invalid_tags(bad_tag: str) -> None:
    mod = _load_release_notes_module()
    with pytest.raises(ValueError, match="Invalid release tag"):
        mod.tag_to_version(bad_tag)


def test_cli_writes_notes_when_tag_matches_pyproject(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    mod = _load_release_notes_module()
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text('[project]\nname = "discoop"\nversion = "1.2.3"\n', encoding="utf-8")

    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text(
        "# Changelog\r\n\r\n"
        "## [Unreleased]\r\n\r\n"
        "## [1.2.3] - 2026-11-12\r\n\r\n"
        "Release summary.\r\n\r\n"
        "### Added\r\n"
        "- New feature.\r\n\r\n"
        "## [1.2.2] - 2026-11-01\r\n\r\n"
        "- Older entry.\r\n",
        encoding="utf-8",
        newline="\n",
    )
    out = tmp_path / "dist" / "notes.md"

    rc = mod.main(
        [
            "--tag",
            "v1.2.3",
            "--out",
            str(out),
            "--pyproject",
            str(pyproject),
            "--changelog",
            str(changelog),
        ]
    )
    captured = capsys.readouterr()

    assert rc == 0
    assert captured.err == ""
    raw = out.read_bytes()
    assert b"\r\n" not in raw
    text = raw.decode("utf-8")
    assert text == "Release summary.\n\n### Added\n- New feature.\n"
    assert "## [1.2.3]" not in text
    assert "Older entry." not in text
    assert "[Unreleased]" not in text


def test_cli_subprocess_entrypoint(tmp_path: Path) -> None:
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text('[project]\nname = "discoop"\nversion = "2.0.1"\n', encoding="utf-8")
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text("## [2.0.1] - 2026-11-12\n\n- Works via CLI.\n", encoding="utf-8")
    out = tmp_path / "notes.md"

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--tag",
            "v2.0.1",
            "--out",
            str(out),
            "--pyproject",
            str(pyproject),
            "--changelog",
            str(changelog),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )

    assert result.returncode == 0
    assert result.stderr == ""
    assert out.read_text(encoding="utf-8") == "- Works via CLI.\n"


def test_cli_fails_on_pyproject_mismatch(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    mod = _load_release_notes_module()
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text('[project]\nname = "discoop"\nversion = "1.2.3"\n', encoding="utf-8")
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text("## [1.2.4] - 2026-11-12\n\n- Entry.\n", encoding="utf-8")
    out = tmp_path / "notes.md"

    rc = mod.main(
        [
            "--tag",
            "v1.2.4",
            "--out",
            str(out),
            "--pyproject",
            str(pyproject),
            "--changelog",
            str(changelog),
        ]
    )
    captured = capsys.readouterr()

    assert rc != 0
    assert "does not match pyproject.toml version" in captured.err
    assert not out.exists()


def test_cli_fails_on_invalid_tag(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    mod = _load_release_notes_module()
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text('[project]\nname = "discoop"\nversion = "1.2.3"\n', encoding="utf-8")
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text("## [1.2.3] - 2026-11-12\n\n- Entry.\n", encoding="utf-8")
    out = tmp_path / "notes.md"

    rc = mod.main(
        [
            "--tag",
            "1.2.3",
            "--out",
            str(out),
            "--pyproject",
            str(pyproject),
            "--changelog",
            str(changelog),
        ]
    )
    captured = capsys.readouterr()

    assert rc != 0
    assert "Invalid release tag" in captured.err
    assert not out.exists()


def test_cli_fails_on_missing_changelog_section(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    mod = _load_release_notes_module()
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text('[project]\nname = "discoop"\nversion = "1.2.3"\n', encoding="utf-8")
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text("## [Unreleased]\n\n## [1.2.2] - 2026-11-01\n\n- Old.\n", encoding="utf-8")
    out = tmp_path / "notes.md"

    rc = mod.main(
        [
            "--tag",
            "v1.2.3",
            "--out",
            str(out),
            "--pyproject",
            str(pyproject),
            "--changelog",
            str(changelog),
        ]
    )
    captured = capsys.readouterr()

    assert rc != 0
    assert "not found" in captured.err
    assert not out.exists()


@pytest.mark.parametrize(
    "changelog_body",
    [
        "## [1.2.3] - 2026-11-12\n\n   \n## [1.2.2] - 2026-11-01\n\n- Old.\n",
        "## [1.2.3] - 2026-11-12\n   \n\t\n",
    ],
)
def test_cli_fails_on_empty_changelog_section(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], changelog_body: str
) -> None:
    mod = _load_release_notes_module()
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text('[project]\nname = "discoop"\nversion = "1.2.3"\n', encoding="utf-8")
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text(changelog_body, encoding="utf-8")
    out = tmp_path / "notes.md"

    rc = mod.main(
        [
            "--tag",
            "v1.2.3",
            "--out",
            str(out),
            "--pyproject",
            str(pyproject),
            "--changelog",
            str(changelog),
        ]
    )
    captured = capsys.readouterr()

    assert rc != 0
    assert "is empty" in captured.err
    assert not out.exists()


@pytest.mark.parametrize("newline", ["\n", "\r\n"])
def test_extract_ignores_similar_headings_and_stops_at_next_section(newline: str) -> None:
    mod = _load_release_notes_module()
    changelog = (
        "## [Unreleased]\n\n"
        "## [1.2.3-rc1] - 2026-11-11\n\n- Pre-release.\n\n"
        "## [1.2.3] - 2026-11-12\n\n- Final release.\n\n"
        "## [1.2.2]\n\n- Older.\n"
    ).replace("\n", newline)
    notes = mod.extract_changelog_section(changelog, "1.2.3")
    assert "\r" not in notes
    assert notes == "- Final release.\n"


def test_cli_fails_when_pyproject_missing_version(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    mod = _load_release_notes_module()
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text('[project]\nname = "discoop"\n', encoding="utf-8")
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text("## [1.2.3] - 2026-11-12\n\n- Entry.\n", encoding="utf-8")
    out = tmp_path / "notes.md"

    rc = mod.main(
        [
            "--tag",
            "v1.2.3",
            "--out",
            str(out),
            "--pyproject",
            str(pyproject),
            "--changelog",
            str(changelog),
        ]
    )
    captured = capsys.readouterr()

    assert rc != 0
    assert "project.version" in captured.err
    assert not out.exists()


def test_extract_real_repo_1_0_0_changelog() -> None:
    mod = _load_release_notes_module()
    changelog_text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    notes = mod.extract_changelog_section(changelog_text, "1.0.0")

    assert "\r" not in notes
    assert notes.startswith("First `1.x` release;")
    assert "### Added" in notes
    assert "### Changed" in notes
    assert "### Fixed" in notes
    assert "## [Unreleased]" not in notes
    assert "## [1.0.0]" not in notes

    crlf_changelog = changelog_text.replace("\n", "\r\n")
    assert mod.extract_changelog_section(crlf_changelog, "1.0.0") == notes

    pyproject_ver = mod.read_pyproject_version(ROOT / "pyproject.toml")
    assert re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", pyproject_ver)


def test_workflow_yaml_normalization_handles_lf_and_crlf() -> None:
    sample_lf = (
        "name: Release\n"
        "\n"
        "on:\n"
        "  push:\n"
        "    tags:\n"
        "      - 'v[0-9]+.[0-9]+.[0-9]+'\n"
        "jobs:\n"
        "  test:\n"
        "    steps:\n"
        "      - run: uv run pytest\n"
    ).encode("utf-8")
    sample_crlf = sample_lf.replace(b"\n", b"\r\n")

    decoded_lf = _decode_workflow_bytes(sample_lf)
    decoded_crlf = _decode_workflow_bytes(sample_crlf)
    assert decoded_crlf == decoded_lf

    expected = {
        "name": "Release",
        "on": {"push": {"tags": ["v[0-9]+.[0-9]+.[0-9]+"]}},
        "jobs": {"test": {"steps": [{"run": "uv run pytest"}]}},
    }
    assert _parse_workflow_yaml(decoded_crlf) == expected
    assert _parse_workflow_yaml(sample_crlf.decode("utf-8")) == expected

    with pytest.raises(AssertionError, match="tabs"):
        _decode_workflow_bytes(b"name: Release\r\n\ton:\r\n")
    with pytest.raises(AssertionError, match="end with a newline"):
        _decode_workflow_bytes(b"name: Release\r\non: push")

    real_lf = WORKFLOW.read_bytes().replace(b"\r\n", b"\n")
    real_crlf = real_lf.replace(b"\n", b"\r\n")
    assert _parse_workflow_yaml(_decode_workflow_bytes(real_crlf)) == _parse_workflow_yaml(
        _decode_workflow_bytes(real_lf)
    )


def test_release_workflow_yaml_structure() -> None:
    workflow = _parse_workflow_yaml(_decode_workflow_bytes(WORKFLOW.read_bytes()))
    assert workflow["on"] == {"push": {"tags": ["v[0-9]+.[0-9]+.[0-9]+"]}}
    assert workflow["permissions"] == {"contents": "read"}

    jobs = workflow["jobs"]
    assert isinstance(jobs, dict)
    assert set(jobs) == {"test", "release"}

    test_job = jobs["test"]
    assert isinstance(test_job, dict)
    assert test_job["strategy"] == {"matrix": {"os": ["ubuntu-latest", "windows-latest", "macos-latest"]}}
    assert test_job["runs-on"] == "${{ matrix.os }}"
    test_steps = test_job["steps"]
    assert isinstance(test_steps, list)
    assert len(test_steps) == 4
    assert test_steps[0]["uses"].startswith("actions/checkout@")
    assert test_steps[1]["uses"].startswith("astral-sh/setup-uv@")
    assert test_steps[2]["run"] == "uv sync --locked"
    assert test_steps[3]["run"] == "uv run pytest"

    release_job = jobs["release"]
    assert isinstance(release_job, dict)
    assert release_job["needs"] == "test"
    assert release_job["runs-on"] == "ubuntu-latest"
    assert release_job["permissions"] == {"contents": "write"}

    release_steps = release_job["steps"]
    assert isinstance(release_steps, list)
    assert len(release_steps) == 6
    assert release_steps[0]["uses"].startswith("actions/checkout@")
    assert release_steps[0]["with"] == {"fetch-depth": 0}
    assert release_steps[1]["uses"].startswith("astral-sh/setup-uv@")

    # Verify step order and exact commands in release job.
    assert "scripts/release_notes.py" in release_steps[2]["run"]
    assert '--tag "$GITHUB_REF_NAME"' in release_steps[2]["run"]
    assert "--out notes.md" in release_steps[2]["run"]
    assert release_steps[3]["run"] == "uv build"
    assert release_steps[4]["run"] == 'git push origin "$GITHUB_SHA:refs/heads/stable"'
    assert "--force" not in release_steps[4]["run"]
    assert "gh release create" in release_steps[5]["run"]
    assert '"$GITHUB_REF_NAME"' in release_steps[5]["run"]
    assert "dist/*" in release_steps[5]["run"]
    assert "--verify-tag" in release_steps[5]["run"]
    assert '--title "discoop ${GITHUB_REF_NAME#v}"' in release_steps[5]["run"]
    assert "--notes-file notes.md" in release_steps[5]["run"]
    assert release_steps[5]["env"] == {"GH_TOKEN": "${{ github.token }}"}

    # Restrict third-party actions strictly to actions/checkout and astral-sh/setup-uv.
    for job in jobs.values():
        assert isinstance(job, dict)
        for step in job["steps"]:
            assert isinstance(step, dict)
            if "uses" in step:
                uses = step["uses"]
                assert isinstance(uses, str)
                assert uses.startswith(("actions/checkout@", "astral-sh/setup-uv@"))
                assert "@" in uses and uses.split("@", 1)[1].startswith("v")
