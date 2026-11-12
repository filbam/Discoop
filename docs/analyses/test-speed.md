# Test suite speed and parallel runs

Date: 2026-11-12. Subject: how long `uv run pytest` takes serially and in parallel with pytest-xdist, as the basis for [ADR 0026](../decisions/0026-parallel-tests.md) (requirement P36 in [requirements.md](../requirements.md)).

**Legend:** **[VERIFIED]** = measured on 2026-11-12 on the owner's Windows 10 machine (16 logical cores, `uv 0.13.7`, CPython `3.12.10`, pytest `9.2.0`, pytest-asyncio `1.4.1.post1`, pytest-xdist `3.8.0`, execnet `2.1.2`); the command and the result are stated. Times are the `in N s` figure that pytest prints unless a row says "wall", which is the shell `time` of the whole `uv run pytest` command. **[ASSUMPTION]** = inferred, not measured.

**Conditions:** The machine was not idle. During the first set of measurements another agent was busy on the same machine; during the second set other agent sessions may have been active as well (not controlled). Single runs vary by a few seconds, so the numbers are indicative, not benchmarks. All tests are offline (fake Discord and CDP, `httpx.MockTransport`, in-memory keyring); no Discord or GitHub call was made.

---

## 1. Summary

| # | Finding | Status |
|---|---|---|
| 1 | Serially the full suite takes about 3:46 (226.6 s for 1190 tests). | [VERIFIED] |
| 2 | About 82% of the serial time is in the TUI test files (Textual Pilot tests). | [VERIFIED] |
| 3 | With `-n auto` (16 workers) the full suite takes about 35 s, about 6 to 6.5 times faster (226.6 s against 34.9 to 36.5 s for 1190 tests; 212.37 s against 34.50 to 35.09 s for 1254 tests), with no change to the tests. Every test that passes serially also passes in parallel. | [VERIFIED] |
| 4 | `--dist worksteal` is slightly faster than the default `--dist load` (34.9 s against 36.2 s and 36.5 s). | [VERIFIED] (one run, within the noise) |
| 5 | Worker start-up costs a few seconds, so a single small file is faster with `-n0`. | [VERIFIED] |
| 6 | Without the TUI test files the parallel run takes about 17 to 18 s. | [VERIFIED] |
| 7 | GitHub runners have fewer cores, so the speed-up in the release workflow is smaller. | [ASSUMPTION] |

---

## 2. Owner's measurements (copy of `main` at `4788d98`, before the change)

Run on 2026-11-12 in a copy of `main` at `4788d98`, with pytest-xdist installed but no `addopts`, while another agent was busy on the same machine.

### 2.1 Serial run

| # | Measurement | Result | Status |
|---|---|---|---|
| S1 | `uv run pytest` (serial) | 1190 passed, 1 skipped in 226.6 s (about 3:46) | [VERIFIED] (2026-11-12) |
| S2 | Time per TUI test file | `tests/test_tui_modals.py` 74.4 s, `tests/test_tui_app.py` 67.5 s, `tests/test_tui_forums.py` 15.0 s, `tests/test_tui_r4g.py` 11.2 s, `tests/test_tui_tree_suffix.py` 9.4 s; together about 82% of the run | [VERIFIED] (2026-11-12) |
| S3 | Slowest single test | `tests/test_tui_app.py::test_cli_and_service_export_equivalence` 7.7 s | [VERIFIED] (2026-11-12) |
| S4 | Distribution of test durations | 1 test at 5 s or more, 49 tests 1 to 5 s, 176 tests 0.3 to 1 s, 376 tests 0.005 to 0.3 s (the rest faster) | [VERIFIED] (2026-11-12) |

### 2.2 Parallel runs

| # | Command | Result | Status |
|---|---|---|---|
| X1 | `uv run pytest -n auto` | 1190 passed in 36.5 s and 36.2 s (two runs) | [VERIFIED] (2026-11-12) |
| X2 | `uv run pytest -n 8` | 1190 passed in 40.8 s | [VERIFIED] (2026-11-12) |
| X3 | `uv run pytest -n auto --dist worksteal` | 1190 passed in 34.9 s | [VERIFIED] (2026-11-12) |
| X4 | `uv run pytest -n auto --ignore-glob=tests/test_tui_*.py` | 916 passed in 17.8 s (serially 41.2 s) | [VERIFIED] (2026-11-12) |
| X5 | `tests/test_config.py` alone | 4.2 s with `-n auto` (worker start-up), 0.9 s with `-n0` | [VERIFIED] (2026-11-12) |
| X6 | Isolation | Every parallel run passed completely; tests already use `tmp_path`, an in-memory keyring and ephemeral ports (`127.0.0.1:0`) | [VERIFIED] (2026-11-12) |

---

## 3. Fresh measurements with the new default (branch `chore/parallel-tests`)

Run on 2026-11-12 in a separate git worktree on branch `chore/parallel-tests`, based on `e76423a` (the release workflow and update-check work, so the suite has more tests than in section 2), after `uv add --dev pytest-xdist` and with `addopts = ["-n", "auto", "--dist", "worksteal"]` in `pyproject.toml`. pytest printed `created: 16/16 workers` and `plugins: ... xdist-3.8.0`.

| # | Command | Result | Status |
|---|---|---|---|
| F1 | `uv run pytest` (run 1) | 1252 passed, 1 skipped, 1 failed in 34.50 s | [VERIFIED] (2026-11-12) |
| F2 | `uv run pytest` (run 2) | 1252 passed, 1 skipped, 1 failed in 35.09 s (wall 36.6 s) | [VERIFIED] (2026-11-12) |
| F3 | `uv run pytest -n0 --durations=3` (serial, for comparison) | 1252 passed, 1 skipped, 1 failed in 212.37 s (wall 3:34.8); slowest tests `tests/test_tui_app.py::test_cli_and_service_export_equivalence` 6.14 s, `tests/test_tui_modals.py::test_preview_scroll_keys_work_from_the_format_row` 4.08 s, `tests/test_tui_app.py::test_tab_walks_panels_not_fields` 2.92 s | [VERIFIED] (2026-11-12) |
| F4 | `uv run pytest --ignore-glob="tests/test_tui_*.py"` | 978 passed, 1 skipped, 1 failed in 16.61 s (wall 18.1 s) | [VERIFIED] (2026-11-12) |
| F5 | `uv run pytest tests/test_config.py` (default, parallel) | 12 passed in 5.26 s (wall 6.7 s), `created: 16/16 workers` | [VERIFIED] (2026-11-12) |
| F6 | `uv run pytest -n0 tests/test_config.py` | 12 passed in 0.35 s (wall 1.7 s), `collected 12 items`, no workers started | [VERIFIED] (2026-11-12) |

**The one failure is not caused by the parallel run.** `tests/test_release_notes.py::test_release_workflow_yaml_structure` checks that `.github/workflows/release.yml` has no CRLF bytes. The worktree was checked out with `core.autocrlf=true`, so git wrote that file (and every other text file) with CRLF in the working copy, while the committed blob has LF (`git ls-files --eol`: `i/lf w/crlf`). The test fails the same way with `-n0` (`uv run pytest -n0 tests/test_release_notes.py`: 1 failed, 21 passed). [VERIFIED] (2026-11-12). It would fail in any fresh Windows checkout with `core.autocrlf=true`; it does not fail in a checkout where the file was written with LF. [ASSUMPTION] (follows from the check reading the working copy bytes; only this worktree was tried). Resolved later on 2026-11-12 by CRLF normalisation in the test (commit `ed0edbb`). [VERIFIED] (2026-11-12, commit contents)

The `--ignore-glob="tests/test_tui_*.py"` run skips six files: the five Pilot files of section 2.1 and `tests/test_tui_state.py`, which tests the TUI state module without the Pilot. [VERIFIED] (2026-11-12, file listing).

---

## 4. How xdist picks the number of workers

- `-n auto` asks the hook `pytest_xdist_auto_num_workers`. In pytest-xdist `3.8.0` it returns `PYTEST_XDIST_AUTO_NUM_WORKERS` when that environment variable is set, otherwise the core count from `psutil` when it is installed, otherwise `len(os.sched_getaffinity(0))` where available (Linux) and `os.cpu_count()` elsewhere. [VERIFIED] (2026-11-12, source of the installed `xdist/plugin.py`)
- `psutil` is not installed in the project environment, so on the owner's machine `-n auto` started 16 workers, one per logical core. [VERIFIED] (2026-11-12, `created: 16/16 workers`)
- `PYTEST_XDIST_AUTO_NUM_WORKERS=4 uv run pytest` would cap the run at four workers, for example when several agents run the suite at the same time. [VERIFIED] (2026-11-12, `PYTEST_XDIST_AUTO_NUM_WORKERS=4 uv run pytest tests/test_config.py`: `created: 4/4 workers`, 12 passed in 2.16 s)
- `--dist worksteal` first splits the tests evenly between the workers and then lets a worker that runs out of tests take tests from a busy one, which suits a suite where a few TUI tests take seconds and most take milliseconds. [ASSUMPTION] (pytest-xdist documentation; the gain measured in X3 is small)

---

## 5. Why the parallel run does not get much faster

- The parallel run cannot be shorter than the slowest single test (7.7 s, S3) plus the worker start-up (about 3 to 4 s, X5 and F5). With 16 workers and about 230 s of serial work, an even split gives about 14 s per worker, so the measured 35 s is more than twice that ideal. [ASSUMPTION] (arithmetic from the measurements, not profiled)
- Likely reasons: Textual Pilot tests are CPU-heavy, 16 worker processes compete with each other and with other work on the machine, and every worker imports Textual and the package again. [ASSUMPTION] (not profiled)
- This is why speeding up the TUI tests themselves was put aside in [ADR 0026](../decisions/0026-parallel-tests.md): a large effort for a small gain while the slowest test bounds the run. [ASSUMPTION]

---

## 6. GitHub runners (release workflow)

- The `test` job of [`.github/workflows/release.yml`](../../.github/workflows/release.yml) runs `uv sync --locked` (which installs the `dev` group with pytest-xdist) and `uv run pytest` on `ubuntu-latest`, `windows-latest` and `macos-latest`, so it gets the parallel default without a change to the workflow. [VERIFIED] (2026-11-12, workflow file)
- Standard GitHub-hosted runners have far fewer cores than the owner's machine (for a public repository about 4 on Linux and Windows and 3 on macOS), so `-n auto` starts only a few workers and the run takes at best about a quarter of the serial time instead of about a sixth. [ASSUMPTION] (not measured; no workflow run exists yet, and runner cores may also be slower)
- On Linux the worker count follows the CPU affinity of the process (`os.sched_getaffinity`), not a container CPU quota, so a quota-limited container may start more workers than it has CPU time for. [ASSUMPTION] (follows from the code in section 4, not tried on a runner)

---

## 7. Tests that were flaky in parallel

- During the review on 2026-11-12, 2 of 5 full parallel runs failed `tests/test_tui_r4g.py::test_footer_lists_p_and_o_and_not_the_ctrl_keys` and 1 of 5 failed `tests/test_tui_app.py::test_footer_key_runs_the_binding`. Each passed every time on its own (5 serial runs of the first, 3 parallel runs of its file). [VERIFIED]
- Cause: both read the footer after a single `pilot.pause()`. When 16 workers share the CPU, the footer is not yet composed (no `FooterKey`) or not yet refreshed after `refresh_bindings()`, or the help screen is not yet open after a click. [ASSUMPTION] (inferred from the failures and the fix, not traced inside Textual)
- Fix: both tests now wait for the condition with the existing helper `wait_until` from `tests/test_tui_app.py` instead of a single pause. After the fix, 6 full parallel runs in a row passed (apart from the line-ending failure of `test_release_workflow_yaml_structure`, which happens only in this worktree because it was checked out with `core.autocrlf=true`). [VERIFIED]
- Rule for new TUI tests: wait for the state with `wait_until`, never assume that one `pilot.pause()` is enough.
