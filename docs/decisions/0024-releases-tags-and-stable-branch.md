# 0024: Releases, tags, and the `stable` branch

- **Status:** Accepted
- **Date:** 2026-11-12
- **Decided by:** the user

## Context

Previously ([ADR 0015](0015-public-repo-and-installation.md)), users installed Discoop directly from the repository's default branch (`uv tool install git+https://github.com/filbam/Discoop`, tracking `main`). That exposes users running `uv tool upgrade discoop` to unreleased commits and work in progress between releases.

[ADR 0023](0023-version-and-single-source.md) established Semantic Versioning (`project.version` in `pyproject.toml` as the single source of truth) and version `1.0.0`, while noting that no git tags existed yet. Together with the update notifier ([ADR 0025](0025-update-notifier.md)), which checks GitHub Releases and tells users to run `uv tool upgrade discoop`, Discoop needs a repeatable release flow backed by SemVer git tags, cross-platform test verification, GitHub Releases with extracted changelog notes, and a dedicated `stable` branch for user installations.

## Options

1. **PyPI.** Rejected: requires an account, availability of the name `discoop` is unknown, and it would publicly list a tool that violates Discord's Terms of Service.
2. **The `stable` branch driven by a tag-triggered GitHub Actions workflow.** Chosen: users install from `@stable` and continue upgrading with `uv tool upgrade discoop`, while `stable` only moves forward after automated tests pass and the release workflow creates the GitHub Release.
3. **Installs pinned directly to tags.** Rejected: every upgrade requires typing the new tag by hand instead of running `uv tool upgrade discoop`.

## Decision

1. **Single source of truth and release tags:**
   - `project.version` in `pyproject.toml` remains the single source of truth ([ADR 0023](0023-version-and-single-source.md)).
   - A release is the annotated SemVer tag `vX.Y.Z` on the release commit.

2. **Owner's release steps (manual preparation and push):**
   - Bump `project.version` in `pyproject.toml`.
   - Run `uv lock` and `uv sync` (following the lockfile rule in [ADR 0023](0023-version-and-single-source.md)).
   - Rename `[Unreleased]` in `CHANGELOG.md` to `## [X.Y.Z] - YYYY-MM-DD`, with a fresh empty `## [Unreleased]` heading above it.
   - Add an entry in `docs/journal.md`.
   - Commit the release changes on `main`.
   - Create the annotated tag: `git tag -a vX.Y.Z -m "discoop X.Y.Z"`.
   - Push the commit and tag: `git push origin main vX.Y.Z`. Tags and pushes happen only on the user's explicit instruction.

3. **Release workflow (`.github/workflows/release.yml`):**
   - Triggered only by pushed tags matching `v[0-9]+.[0-9]+.[0-9]+`.
   - Top-level `permissions: contents: read`.
   - Uses only `actions/checkout` and `astral-sh/setup-uv` (pinned to released versions); no other third-party actions.
   - **Job `test`:** runs on a matrix of `ubuntu-latest`, `windows-latest`, and `macos-latest`; runs `uv sync --locked` and `uv run pytest`.
   - **Job `release`:** requires `needs: test`, runs on `ubuntu-latest`, sets `permissions: contents: write`, and checks out with `fetch-depth: 0`. Executes in order:
     1. `scripts/release_notes.py --tag "$GITHUB_REF_NAME" --out notes.md` (a standalone Python stdlib-only script, not part of the installed package; fails if the tag does not match `project.version` or if the matching `CHANGELOG.md` section is missing or empty).
     2. `uv build` (builds distributions into `dist/`).
     3. Move `stable`: `git push origin "$GITHUB_SHA:refs/heads/stable"` without `--force` (creates `stable` the first time and refuses non-fast-forward updates so `stable` can never move backwards).
     4. Create the GitHub Release: `gh release create "$GITHUB_REF_NAME" dist/* --verify-tag --title "discoop X.Y.Z" --notes-file notes.md` with `GH_TOKEN: ${{ github.token }}`.

4. **User installation and upgrade:**
   - Installation becomes `uv tool install git+https://github.com/filbam/Discoop@stable`.
   - Upgrade stays `uv tool upgrade discoop`.
   - Existing installations (from `main`) move once with `uv tool install --force git+https://github.com/filbam/Discoop@stable`.

## Consequences

- Supersedes [ADR 0015](0015-public-repo-and-installation.md) (the repository stays public, `uv tool` remains the distribution method, `uv run` stays for development, and the git identity from [ADR 0002](0002-private-repo-and-identity.md) is unchanged; user installations now target `@stable` instead of the default branch).
- Existing users moving from `main` perform a one-time reinstall with `uv tool install --force git+https://github.com/filbam/Discoop@stable`.
- `1.0.0` (commit `4788d98`) predates the workflow: the owner tags it `v1.0.0` and creates its GitHub Release by hand later.
- `1.1.0` will be the first workflow-driven release (containing the release workflow and the update notifier).
- Tags and pushes happen only on the user's explicit instruction; CI workflows for ordinary pushes or pull requests and PyPI publishing remain out of scope.
- `scripts/release_notes.py` uses only the Python standard library and lives outside `src/`, adding no runtime dependencies or package files.
- `[ASSUMPTION]` The cross-platform `test` matrix (`ubuntu-latest`, `windows-latest`, `macos-latest`), fast-forward `stable` push, and GitHub Release creation will be exercised live when `v1.1.0` is pushed.
