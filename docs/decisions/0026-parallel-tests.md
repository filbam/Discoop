# 0026: Parallel tests by default

- **Status:** Accepted
- **Date:** 2026-11-12
- **Decided by:** the user

## Context

The full test suite took about 3:46 when run serially (`uv run pytest`: 1190 passed, 1 skipped in 226.6 s on 2026-11-12 on the owner's Windows 10 machine with 16 logical cores). The user, the agents and the release workflow ([`.github/workflows/release.yml`](../../.github/workflows/release.yml), job `test`) all run the plain command `uv run pytest`, often several times per work step. About 82% of the serial time is spent in the TUI test files (Textual Pilot tests), and the slowest single test takes 7.7 s. The tests already isolate their state (`tmp_path`, an in-memory keyring, ephemeral ports on `127.0.0.1:0`), so they can run in several processes at once. The user wants faster tests and asked to run them in parallel (P36). Measurements: [test-speed.md](../analyses/test-speed.md).

## Options

1. **Keep the serial run.** Rejected: 3:46 for every full run slows down every step of the work.
2. **pytest-xdist with `-n auto --dist worksteal` by default** (`addopts` in `[tool.pytest.ini_options]` of `pyproject.toml`). Chosen: the full suite passed in about 35 s on 16 logical cores (`-n auto`: 36.2 s, `-n 8`: 40.8 s, `-n auto --dist worksteal`: 34.9 s), with no change to the tests, and plain `uv run pytest` becomes parallel for people, agents and the release workflow alike.
3. **pytest-xdist only on request** (`uv run pytest -n auto` typed by hand). Rejected: easy to forget, and agents and the release workflow run plain `uv run pytest`.
4. **Speed up the TUI tests themselves.** Not now: the slowest single test bounds the parallel run anyway, so the gain is small for a large effort. It can be revisited if the suite grows.

## Decision

1. Add `pytest-xdist` to the `dev` dependency group only (`uv add --dev pytest-xdist`, which also locks its dependency `execnet`). The runtime `dependencies` of the package do not change.
2. Set `addopts = ["-n", "auto", "--dist", "worksteal"]` in `[tool.pytest.ini_options]` of `pyproject.toml`, so `uv run pytest` runs on one worker per logical core and idle workers take tests from busy ones.
3. A serial run stays available with `-n0`, for example `uv run pytest -n0 tests/test_x.py`.
4. A quick run without the TUI test files is `uv run pytest --ignore-glob="tests/test_tui_*.py"` (about 18 s).
5. `.github/workflows/release.yml` stays unchanged; its `uv sync --locked` installs the dev group and its `uv run pytest` picks up the new default.

## Consequences

- For a single small file or for debugging with `print` or `pdb`, use `-n0`: starting the workers costs a few seconds (`tests/test_config.py`: 4.2 s with `-n auto`, 0.9 s with `-n0`), and xdist workers capture output, so `print` output and `pdb` need the serial run.
- Tests must stay independent of their order and of the process they run in: no shared files outside `tmp_path`, no fixed ports, no global state carried from one test to another. A test that only passes serially is a bug in the test.
- Several agents running the full suite at the same time on the same machine each start one worker per logical core and compete for the CPU; the run gets slower, but it still passes.
- New dev dependency `pytest-xdist` (with `execnet`) in `uv.lock`, approved by the user on 2026-11-12. It is not installed for users of the tool.
- On GitHub runners with fewer cores the speed-up is smaller (not measured, see [test-speed.md](../analyses/test-speed.md)).
