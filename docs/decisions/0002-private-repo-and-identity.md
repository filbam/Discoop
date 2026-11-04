# 0002: Private repo `filbam/Discoop` and git identity

- **Status:** Accepted, private repo superseded by ADR 0015
- **Date:** 2026-11-03
- **Decided by:** the user

> **Note (2026-11-04):** The repo is now public ([ADR 0015](0015-public-repo-and-installation.md)). The git identity
> `filbam` and GitHub login as `filbam` remain valid.

## Context

The project needs a remote repo. The documentation contains the VUT FIT server and channel IDs and descriptions of incidents.
The tool itself is a scraper that violates Discord Terms of Service.

## Decision

- **Repo:** `https://github.com/filbam/Discoop`, **private**, `main` branch.
- **Commit author:** `filbam <f.bambura@gmail.com>`, configured only locally (`git config` in the repo).
- **GitHub login:** for this repo as `filbam` (`credential.https://github.com.username = filbam`).

## Consequences

- Making it public would require a new decision and a review of documents containing IDs and incidents.
- Git Credential Manager has `FilipBambura` as its default account, which cannot see the private repo (`Repository not found`).
  Therefore, login as `filbam` is configured in the repo.
