"""Generate GitHub release notes from CHANGELOG.md for a release tag."""

from __future__ import annotations

import argparse
from pathlib import Path
import re
import sys
import tomllib

REPO_ROOT = Path(__file__).resolve().parent.parent
TAG_RE = re.compile(r"\Av([0-9]+\.[0-9]+\.[0-9]+)\Z")
NEXT_SECTION_PREFIX = "## ["


def tag_to_version(tag: str) -> str:
    """Validate a 'vX.Y.Z' tag (ASCII digits only) and return 'X.Y.Z'."""
    match = TAG_RE.fullmatch(tag)
    if match is None:
        raise ValueError(
            f"Invalid release tag {tag!r}: expected 'vMAJOR.MINOR.PATCH' with digits only."
        )
    return match.group(1)


def read_pyproject_version(pyproject_path: Path) -> str:
    """Read and validate project.version from pyproject.toml."""
    data = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
    project = data.get("project")
    if not isinstance(project, dict):
        raise ValueError(f"Missing [project] table in {pyproject_path}.")
    version = project.get("version")
    if not isinstance(version, str) or not version.strip():
        raise ValueError(f"Missing or invalid project.version in {pyproject_path}.")
    return version


def extract_changelog_section(changelog_text: str, version: str) -> str:
    """Extract the body of '## [version] - <date>' up to the next '## [' heading or EOF."""
    normalized = changelog_text.replace("\r\n", "\n").replace("\r", "\n")
    heading_re = re.compile(rf"^## \[{re.escape(version)}\] - \S.*$")

    found = False
    collected: list[str] = []
    for line in normalized.splitlines():
        if not found:
            if heading_re.match(line):
                found = True
            continue
        if line.startswith(NEXT_SECTION_PREFIX):
            break
        collected.append(line)

    if not found:
        raise ValueError(f"CHANGELOG section for version {version!r} not found.")

    body = "\n".join(collected).strip()
    if not body:
        raise ValueError(f"CHANGELOG section for version {version!r} is empty.")

    return f"{body}\n"


def generate_release_notes(
    tag: str,
    *,
    pyproject_path: Path,
    changelog_path: Path,
) -> str:
    """Validate tag against pyproject.toml and extract matching CHANGELOG.md notes."""
    version = tag_to_version(tag)
    pyproject_version = read_pyproject_version(pyproject_path)
    if version != pyproject_version:
        raise ValueError(
            f"Tag version {version!r} does not match pyproject.toml version {pyproject_version!r}."
        )
    changelog_text = changelog_path.read_text(encoding="utf-8")
    return extract_changelog_section(changelog_text, version)


def build_parser() -> argparse.ArgumentParser:
    """Create the command-line argument parser."""
    parser = argparse.ArgumentParser(
        description="Extract release notes for a vX.Y.Z tag from CHANGELOG.md."
    )
    parser.add_argument("--tag", required=True, help="Release tag in vX.Y.Z format.")
    parser.add_argument("--out", required=True, type=Path, help="Output markdown file path.")
    parser.add_argument(
        "--pyproject",
        type=Path,
        default=REPO_ROOT / "pyproject.toml",
        help="Path to pyproject.toml (defaults to repository root).",
    )
    parser.add_argument(
        "--changelog",
        type=Path,
        default=REPO_ROOT / "CHANGELOG.md",
        help="Path to CHANGELOG.md (defaults to repository root).",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint; returns 0 on success and 1 on validation or I/O failure."""
    args = build_parser().parse_args(argv)
    try:
        notes = generate_release_notes(
            args.tag,
            pyproject_path=args.pyproject,
            changelog_path=args.changelog,
        )
        args.out.parent.mkdir(parents=True, exist_ok=True)
        with args.out.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(notes)
    except (ValueError, OSError, tomllib.TOMLDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
