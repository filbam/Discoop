# Release Process and `@stable` Verification

Date: 2026-11-12. Subject: automated GitHub release workflow (`.github/workflows/release.yml`), changelog release-note generator (`scripts/release_notes.py`), and `uv tool` installation/upgrade behaviour against the `@stable` branch.

**Legend:** **[VERIFIED]** = directly observed on 2026-11-12 in isolated local runs on Windows (`uv 0.13.7`, Python `3.12.10`, local `git` clone and bare remote) or via `uv run pytest`; exact commands, outputs, and timings are stated. **[ASSUMPTION]** = behaviour inferred from documentation, general GitHub Actions / `uv` knowledge, or cross-platform expectations that could not be executed locally (no live GitHub, GitHub Actions, Linux, or macOS runs were performed).

**Scope and privacy:** All local checks used a disposable temporary clone of `<repo>` (the local repository) and isolated `UV_TOOL_DIR` / `UV_TOOL_BIN_DIR` paths under `%TEMP%`, which were deleted afterwards. No tokens, personal data, Discord API calls, or GitHub API calls were made.

---

## 1. Release Workflow Architecture

The release pipeline splits into two components owned in the repository **[VERIFIED]** (2026-11-12, file contents):

1. **`scripts/release_notes.py`** (standard library only: `argparse`, `pathlib`, `re`, `sys`, `tomllib`) **[VERIFIED]** (2026-11-12, file contents):
   - Validates that the release tag matches `vX.Y.Z` strictly with ASCII digits (`\Av([0-9]+\.[0-9]+\.[0-9]+)\Z`). **[VERIFIED]** (2026-11-12, file contents)
   - Reads `project.version` from `pyproject.toml` and fails with a non-zero exit code if the tag version differs. **[VERIFIED]** (2026-11-12, file contents)
   - Extracts the body between `## [X.Y.Z] - <date>` and the next `## [` heading (or EOF) in `CHANGELOG.md`, failing if the section is missing or its trimmed body is empty. **[VERIFIED]** (2026-11-12, file contents)
   - Writes the extracted markdown with LF (`\n`) line endings to `--out`. **[VERIFIED]** (2026-11-12, file contents)
2. **`.github/workflows/release.yml`**:
   - **Trigger:** `on: push: tags: ['v[0-9]+.[0-9]+.[0-9]+']` only. **[VERIFIED]** (2026-11-12, file contents)
   - **Permissions:** top-level `contents: read`; elevated to `contents: write` only on the `release` job. **[VERIFIED]** (2026-11-12, file contents)
   - **Actions:** uses only `actions/checkout@v6` and `astral-sh/setup-uv@v10.3.3` (no other third-party actions). **[VERIFIED]** (2026-11-12, file contents)
     - `astral-sh/setup-uv` stopped publishing floating major tags (`@v8+`), so pinning to an explicit release tag (`@v10.3.3`) rather than a moving `@v10` tag is required **[ASSUMPTION]** (based on action release documentation; live GitHub Action resolution is unverified locally).
   - **`test` job:** matrix `[ubuntu-latest, windows-latest, macos-latest]`, runs `uv sync --locked` then `uv run pytest`. **[VERIFIED]** (2026-11-12, file contents)
   - **`release` job (`needs: test`, `ubuntu-latest`):** checks out full git history (`fetch-depth: 0`), sets up `uv`, and runs in strict order **[VERIFIED]** (2026-11-12, file contents):
     1. `uv run --no-sync python scripts/release_notes.py --tag "$GITHUB_REF_NAME" --out "$RUNNER_TEMP/notes.md"` (validates tag, `pyproject.toml`, and `CHANGELOG.md` before building or pushing). The output path was `notes.md` in the repository root until the review fix on 2026-11-12 (see V3).
     2. `uv build` (builds wheel and source distribution into `dist/`).
     3. `git push origin "$GITHUB_SHA:refs/heads/stable"` without `--force` (creates `stable` on first push and rejects any non-fast-forward move backwards; the push behaviour itself is checked in T4).
     4. `gh release create "$GITHUB_REF_NAME" dist/* --verify-tag --title "discoop ${GITHUB_REF_NAME#v}" --notes-file "$RUNNER_TEMP/notes.md"` with `GH_TOKEN: ${{ github.token }}`.

---

## 2. Verification Results

### 2.1 Offline Script, Workflow, and Suite Checks

| # | Check | Result | Status |
|---|---|---|---|
| V1 | `uv run pytest tests/test_release_notes.py -v` (22 tests) | 22 passed: `tag_to_version` strict ASCII digit validation, CLI `notes.md` LF output, subprocess CLI entrypoint, mismatch/invalid-tag/missing-section/empty-section failures, missing `project.version`, extracting the real `1.0.0` section from `CHANGELOG.md` (`307` lines in `notes.md`), and stdlib YAML parsing/structural checks on `.github/workflows/release.yml`. Note (2026-11-12): commit `ed0edbb` (CRLF normalisation) later raised the file to 24 tests, and the review fixes on 2026-11-12 may add more. | **[VERIFIED]** (2026-11-12, Windows) |
| V2 | `uv run --no-sync python scripts/release_notes.py --tag v1.0.0 --out notes.md` inside a clean clone without `.venv` | Exit code `0`. `uv` created `.venv` using `CPython 3.12.10` (satisfying `requires-python = ">=3.12"`) without installing dependencies, and wrote `notes.md` (`307` lines). | **[VERIFIED]** (2026-11-12, Windows, `uv 0.13.7`) |
| V3 | `uv build` after generating `notes.md` in the clean clone | Produced `dist/discoop-1.0.0-py3-none-any.whl` (`179,994` bytes, `54` entries, no `notes.md`), `dist/discoop-1.0.0.tar.gz` (`624,990` bytes, `158` entries), and `dist/.gitignore` (`1` byte). Because `notes.md` is in the repository root and not in `.gitignore`, Hatchling included `notes.md` in the `.tar.gz` sdist (the wheel is unaffected). Fixed on 2026-11-12 in the review: the workflow now writes the notes to `$RUNNER_TEMP/notes.md`, outside the checkout, so `uv build` no longer picks them up (**[ASSUMPTION]**: follows from the path; not rebuilt on a runner). | **[VERIFIED]** (2026-11-12, Windows, `uv 0.13.7`) |
| V4 | Line endings of `.github/workflows/release.yml`, `scripts/release_notes.py`, and `tests/test_release_notes.py` | All three use LF (`\n`) with zero CRLF (`\r\n`) bytes. | **[VERIFIED]** (2026-11-12, Python byte check) |

### 2.2 Isolated `uv tool` Install, Upgrade, and `@stable` Switching

Performed in `%TEMP%\discoop-a1-test-<random>` against a local `--no-hardlinks` clone of `<repo>` (`HEAD` at `4788d98a6427e08d7138d99f3154f839d44de845`, default branch `feature/releases-and-update-notifier`) with `UV_TOOL_DIR` and `UV_TOOL_BIN_DIR` pointed at temporary folders. Before and after the run, the owner's real `uv tool list` was `discoop v1.0.0` (`- discoop`), completely unchanged.

| # | Action | Observed output & timing | Status |
|---|---|---|---|
| T1 | Created local branch `stable` at `4788d98` (`1.0.0`), ran `uv tool install "git+file:///<clone>@stable"` | Built `discoop==1.0.0` (`4788d98`), installed 35 packages and 1 executable (`discoop`) in `3.58 s` (resolved 35 packages in `17 ms`, prepared 1 package in `1.13 s`, installed in `222 ms`; warm uv cache). `discoop.exe --version` printed `discoop 1.0.0`; isolated `uv tool list` showed `discoop v1.0.0`. | **[VERIFIED]** (2026-11-12, Windows, `uv 0.13.7`) |
| T2 | Committed a `pyproject.toml` bump to `1.0.1` on `stable` (`f5f6299`), switched `HEAD` back to `4788d98`, ran `uv tool upgrade discoop` | Detected commit `f5f6299` on `stable`, rebuilt `discoop`, and reported `Updated discoop v1.0.0 -> v1.0.1` in `3.04 s`. `discoop.exe --version` printed `discoop 1.0.1`; isolated `uv tool list` showed `discoop v1.0.1`. | **[VERIFIED]** (2026-11-12, Windows, `uv 0.13.7`) |
| T3 | Uninstalled `discoop`, installed from default branch without `@stable` (`uv tool install "git+file:///<clone>"`), then switched with `uv tool install --force "git+file:///<clone>@stable"` | Default-branch install resolved `4788d98` in `0.76 s` and `discoop.exe --version` printed `discoop 1.0.0`. Switching with `--force ...@stable` replaced it with `f5f6299` in `1.01 s`, and `discoop.exe --version` printed `discoop 1.0.1`. | **[VERIFIED]** (2026-11-12, Windows, `uv 0.13.7`) |
| T4 | Tested `git push` to a local bare remote without `--force`: initial push (`4788d98` -> `refs/heads/stable`), fast-forward push (`f5f6299` -> `refs/heads/stable`), and backwards push (`4788d98` -> `refs/heads/stable`) | Initial push created `stable` (`exit 0`); fast-forward push advanced `4788d98..f5f6299` (`exit 0`); backwards push was rejected with `! [rejected] ... -> stable (non-fast-forward)` (`exit 1`). | **[VERIFIED]** (2026-11-12, Windows, Git) |
| T5 | Deleted `%TEMP%\discoop-a1-test-<random>` and unset `UV_TOOL_DIR` / `UV_TOOL_BIN_DIR` | Temporary directory removed (`Test-Path` = `False`); real `uv tool list` remained `discoop v1.0.0` / `- discoop`. | **[VERIFIED]** (2026-11-12) |

### 2.3 What Could Not Be Verified Locally

All items below remain **[ASSUMPTION]** until the first workflow-driven release runs on GitHub:

- **GitHub Actions execution:** runner provisioning, `actions/checkout@v6` credential handling with `fetch-depth: 0` and `permissions: contents: write`, and `astral-sh/setup-uv@v10.3.3` on `ubuntu-latest`, `windows-latest`, and `macos-latest`.
- **Cross-platform test matrix:** running `uv sync --locked` and `uv run pytest` on Linux (`ubuntu-latest`) and macOS (`macos-latest`).
- **Remote `stable` push on GitHub:** `git push origin "$GITHUB_SHA:refs/heads/stable"` using `GITHUB_TOKEN` (including annotated-tag dereferencing of `$GITHUB_SHA` by GitHub Actions and branch protection rules, if any are enabled later).
- **GitHub Release creation:** `gh release create "$GITHUB_REF_NAME" dist/* --verify-tag --title "discoop ${GITHUB_REF_NAME#v}" --notes-file "$RUNNER_TEMP/notes.md"` with `GH_TOKEN: ${{ github.token }}`, and relying on bash's default `dist/*` glob (with `dotglob` off) to skip `dist/.gitignore` while uploading `.whl` and `.tar.gz`.
- **HTTPS installation and upgrades from GitHub:** `uv tool install git+https://github.com/filbam/Discoop@stable` and `uv tool upgrade discoop` over HTTPS across Windows, Linux, and macOS.

---

## 3. Planned Owner Release Workflow

1. **Manual `v1.0.0` release on `4788d98`:**
   - Commit `4788d98` contains no `.github/` or `scripts/` files **[VERIFIED]** (2026-11-12, `git ls-tree -r 4788d98`), so pushing tag `v1.0.0` at `4788d98` will not trigger the workflow **[ASSUMPTION]** (GitHub reads the workflow from the tagged commit; not tried).
   - The owner creates the `v1.0.0` tag and GitHub Release manually on `4788d98` (using the `1.0.0` body from `CHANGELOG.md` and, if desired, pointing `stable` at `4788d98`). Not done yet as of 2026-11-12 **[VERIFIED]** (2026-11-12, `git tag -l` in the local repository is empty).
2. **First workflow-driven release (`1.1.0`):**
   - Once the release pipeline and update notifier changes are merged to `main`, releasing `1.1.0` follows [ADR 0024](../decisions/0024-releases-tags-and-stable-branch.md) **[VERIFIED]** (2026-11-12, file contents of ADR 0024):
     1. Bump `project.version` to `"1.1.0"` in `pyproject.toml` and refresh `uv.lock` (`uv lock`) and `.venv` (`uv sync`).
     2. In `CHANGELOG.md`, rename `[Unreleased]` (or add `## [1.1.0] - YYYY-MM-DD` below an empty `## [Unreleased]`) with non-empty release notes, and update `docs/journal.md`.
     3. Verify `uv run pytest` passes locally.
     4. Commit on `main`, create the tag with `git tag -a v1.1.0 -m "discoop 1.1.0"`, and push both together with `git push origin main v1.1.0`, only on the user's instruction. Pushing them together matters: the README on `main` points users at `@stable`, and `stable` does not exist on GitHub until the workflow creates it (unless it was created by hand first). **[VERIFIED]** (2026-11-12, no `origin/stable` among the local remote-tracking branches; not re-fetched, so **[ASSUMPTION]** for the live GitHub state)
   - Pushing `v1.1.0` triggers `.github/workflows/release.yml`, which runs the 3-OS test matrix, generates `$RUNNER_TEMP/notes.md` via `scripts/release_notes.py`, builds distributions, fast-forwards `stable` to the tagged commit, and publishes the GitHub Release `discoop 1.1.0` **[ASSUMPTION]** (follows from the workflow file contents, **[VERIFIED]** 2026-11-12; the workflow has never run on GitHub).
