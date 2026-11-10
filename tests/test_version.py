"""Tests for the single-source package version in pyproject.toml (ADR 0023)."""

import ast
from importlib.metadata import PackageNotFoundError, version
import importlib.util
from pathlib import Path
import re
import subprocess
import tomllib

import pytest

import discoop

ROOT = Path(__file__).resolve().parent.parent
PYPROJECT = ROOT / "pyproject.toml"
INIT_FILE = ROOT / "src" / "discoop" / "__init__.py"
SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+$")


def _pyproject_version() -> str:
    data = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    return str(data["project"]["version"])


def _tracked_src_files() -> list[Path]:
    if (ROOT / ".git").exists():
        result = subprocess.run(
            ["git", "ls-files", "src/"], cwd=ROOT, check=True, capture_output=True, text=True, encoding="utf-8"
        )
        return [ROOT / line for line in result.stdout.splitlines() if line]
    return sorted((ROOT / "src").rglob("*.py"))


def _assigns_to_version(node: ast.AST) -> bool:
    if isinstance(node, ast.Assign):
        return any(isinstance(t, ast.Name) and t.id == "__version__" for t in node.targets)
    if isinstance(node, ast.AnnAssign):
        return isinstance(node.target, ast.Name) and node.target.id == "__version__"
    return False


def test_version_matches_installed_metadata_and_pyproject() -> None:
    expected = _pyproject_version()
    assert discoop.__version__ == version("discoop")
    assert discoop.__version__ == expected
    assert SEMVER_RE.match(discoop.__version__)


def test_init_reads_metadata_without_hardcoding_version() -> None:
    tree = ast.parse(INIT_FILE.read_text(encoding="utf-8"), filename=str(INIT_FILE))
    # Require a call to version("discoop") from importlib.metadata.
    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "version"
        and len(node.args) == 1
        and isinstance(node.args[0], ast.Constant)
        and node.args[0].value == "discoop"
    ]
    assert calls, "src/discoop/__init__.py must read the version via importlib.metadata.version('discoop')"

    # Only the except fallback branch may assign a non-SemVer fallback literal to __version__.
    except_nodes = [node for node in ast.walk(tree) if isinstance(node, ast.ExceptHandler)]
    in_except = {child for handler in except_nodes for child in ast.walk(handler)}

    for node in ast.walk(tree):
        if not _assigns_to_version(node):
            continue
        value = node.value  # type: ignore[attr-defined]
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            assert not SEMVER_RE.match(value.value), f"Hardcoded SemVer literal in __init__.py: {value.value!r}"
            assert node in in_except, f"Direct string literal assignment to __version__ outside except: {value.value!r}"


def test_version_fallback_when_package_metadata_is_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    def missing(_name: str) -> str:
        raise PackageNotFoundError(_name)

    monkeypatch.setattr("importlib.metadata.version", missing)
    spec = importlib.util.spec_from_file_location("_discoop_uninstalled", INIT_FILE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.__version__ == "0+unknown"


def test_no_source_file_hardcodes_current_version() -> None:
    current = _pyproject_version()
    quoted = (f'"{current}"', f"'{current}'")
    for path in _tracked_src_files():
        text = path.read_text(encoding="utf-8")
        assert not any(lit in text for lit in quoted), f"Hardcoded version {current!r} in {path}"
        if path.suffix == ".py":
            tree = ast.parse(text, filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Constant) and isinstance(node.value, str):
                    assert node.value != current, f"Hardcoded version string {current!r} in {path}"
