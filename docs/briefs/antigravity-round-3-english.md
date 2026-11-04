# Brief for Antigravity, round 3: the whole repository in English

This brief is self-contained: you do not need the conversation it came from. Rounds 1 and 2 are done and committed
(`docs/briefs/antigravity-round-1.md`, `docs/briefs/antigravity-round-2.md`). This round changes **no behaviour**. It is a translation
and consistency job: afterwards everything in the repository is English, and the repository says so.

## 0. For the coordinator (Argon): how to proceed

You coordinate. Give each package from section 5 to **one** Gemini Flash agent and run them **in parallel** (all packages T1 to T11 at once; if the
platform limits how many agents run at the same time, run them in waves in the order of the table, but never two agents on the same file).

1. **First, yourself** (no delegation): read `CLAUDE.md` (still Slovak, the rules in it hold), this brief, run `git status`, `git log --oneline -3`,
   and the full `uv run pytest`. Write the starting state (tests passed or failed) into the report (section 8).
2. Start all agents with: the translation rules (section 4), the glossary (section 4.2), their own file list and their package text from section 5.
   An agent changes **only** the files of its package. If it needs a change elsewhere, it writes that into its report and leaves it.
3. **Git is yours alone.** The user allowed commits in this round, so: **sub-agents never run any git command**. When an agent finishes, you check
   its diff (`git diff -- <its files>`) and commit exactly its files (section 7). This is how the work gets committed continuously, package by package.
4. After all packages are committed, do the final checks (section 6), fix what they find (or send it back to the agent that owns the file), commit.
5. If something is unclear, choose the **simplest solution that satisfies the text of this brief** and write it into the report under "Decisions".
   Stop a package only if continuing would break a hard rule (section 3).

## 1. The new rule and why

The owner decided on 2026-11-04: **the repository is English only, always.** Documentation, code, comments, identifiers, commit messages, tests,
fixtures, file and folder names, tool texts: all English. The owner talks to the agents in Slovak, but nothing Slovak goes into the repository.
The rule is recorded as ADR 0021 (package T8) and stated at the top of `CLAUDE.md` and `AGENTS.md` (package T1).

## 2. State of the repository at the start

- The Slovak doc files and folders were **already renamed** to English names in commit `c3a174b`, and every path reference was updated. Content is still Slovak.
  The new names (use them everywhere):

| Old (Slovak) | New (English) |
|---|---|
| `docs/poziadavky.md` | `docs/requirements.md` |
| `docs/navrh-nastroja.md` | `docs/design.md` |
| `docs/dennik.md` | `docs/journal.md` |
| `docs/odovzdanie-stavu.md` | `docs/handover.md` |
| `docs/rozhodnutia/` (ADRs) | `docs/decisions/` |
| `docs/analyzy/` | `docs/analyses/` |
| `docs/zadania/` | `docs/briefs/` |

  The ADR files are now `docs/decisions/0001-record-everything-and-version-it.md` and so on (`ls docs/decisions`).
- Tool texts (help, messages, errors) are already English (ADR 0007). Code is mostly English already. Slovak is in: all of `docs/`, `CLAUDE.md`, `README.md`,
  `CHANGELOG.md`, `prototype/README.md`, a few comments and the evidence markers `[OVERENÉ]` / `[PREDPOKLAD]` in `src/`, and sample message texts in `tests/`.
- The project folder on disk is still called `Scoop` while you work (do not rename it, do not move it). The owner renames it to `Discoop` on 2026-11-04, right after this round.
  The docs must already say that the local folder is `Discoop` (see T3 and T8). Work in the folder you were opened in.
- Conventions you must keep: uv (`export PATH="$PATH:/c/Users/Filip/AppData/Local/Microsoft/WinGet/Packages/astral-sh.uv_Microsoft.Winget.Source_8wekyb3d8bbwe"` if
  `uv` is missing in Git Bash), `uv run pytest` (about 3 minutes), `.py` files with LF line endings, git has `core.autocrlf=true` so markdown line endings do not matter
  (do not mix them inside one file if you can avoid it).

## 3. Hard rules

1. **Git:** only the coordinator runs git, only `git add <explicit paths>` and `git commit`. No `push`, no `checkout`, `reset`, `stash`, `rebase`, `commit --amend`, `add -A`/`add .`.
2. **Discord:** never call the Discord API or CDN, never run `discoop` commands that do (allowed: `uv run pytest`, `uv run discoop --help`, `uv run discoop agent-guide`).
3. **Do not read, copy or commit** anything from `Temp/`, `exports/`, `prototype/out/`, `.venv/`, `uv.lock` contents beyond what a tool needs. Do not edit `uv.lock`.
4. **No behaviour change.** In `src/` you may change comments, docstrings and the evidence markers only. In `tests/` you may change **data strings** (sample texts, names) and comments, and the
   matching expected values, nothing else. Do not weaken or remove an assertion, no `skip`/`xfail`, do not rename or delete a test. All tests must pass at the end.
5. **No new dependencies**, do not touch `pyproject.toml` except for text that is Slovak (there is none now: check).
   Do not run `uvx`, `pip`, `npm` or anything that downloads.
6. **No secrets, no real people.** No token, cookie, user ID, real names or real message texts anywhere. If you meet one in an existing file, replace it with a made-up value and write it into the report.
7. **Translate, do not rewrite** (section 4). Do not delete content, do not add content except what a package lists, do not "improve" facts. If the Slovak original looks wrong or outdated,
   translate it as it is and note it in the report.
8. Never delete `*.partial` folders or anything outside the repository.

## 4. Translation rules

### 4.1 General

- Natural, plain technical English. Short sentences. Keep the author's structure: same headings in the same order, same **section numbers** (code comments cite them, for example
  `docs/design.md, section 6.2`), same tables, lists, code blocks and links. Keep anchors working: when a heading is translated, fix every `#anchor` link that points at it (GitHub slug rules:
  lowercase, spaces to `-`, punctuation dropped).
- Do not translate: code, identifiers, command lines and their output, file and folder names, option names, JSON keys, exit-code names, URLs, error codes, numbers, ISO dates (`2026-11-04`).
  Slovak dates such as `3. 11. 2026` become ISO dates.
- Texts that quote the tool's own English output stay as they are. Slovak sentences inside code blocks, tables or comments are translated.
- Discord content quoted in analyses (message texts, thread titles, channel names in Czech or Slovak): replace with made-up English examples that show the same thing, or write a neutral placeholder
  (`<text>`). Real server names that are public proper nouns (VUT FIT, FIT, IZP) can stay.
- Frontmatter-like labels and ADR structure are translated with the glossary below, the file structure stays.

### 4.2 Glossary (use exactly these, so that parallel agents agree)

| Slovak | English |
|---|---|
| `[OVERENÉ]` | `[VERIFIED]` |
| `[PREDPOKLAD]` | `[ASSUMPTION]` |
| Overené / Neoverené | Verified / Unverified |
| Stav: Prijaté / Navrhnuté / Nahradené ADR NNNN | Status: Accepted / Proposed / Superseded by ADR NNNN |
| Rozhodol: používateľ / návrh Claude | Decided by: the user / Claude's proposal |
| Kontext / Možnosti / Rozhodnutie / Dôsledky | Context / Options / Decision / Consequences |
| Ďalej (the next-steps block of a journal section) | Next |
| požiadavky / návrh / denník / odovzdanie stavu | requirements / design / journal / handover |
| rozhodnutia (ADR) / analýzy / zadania | decisions (ADR) / analyses / briefs |
| používateľ | the user |
| hlavný Claude | the main Claude |
| agent, koordinátor | agent, coordinator |
| kolo / balík / fáza / zadanie | round / package / phase / brief |
| kanál / vlákno / fórum / správa / príloha | channel / thread / forum / message / attachment |
| odolný export, obnova (resume), čiastočný výsledok | resilient export, resume, partial result |
| nerozbalený/hotový export, staging priečinok | finished export, staging folder |
| bez farieb (plain), safe / fast režim | plain mode (no colours), safe / fast mode |
| falošný Discord (testy) | fake Discord |
| reálny účet | real account |

Where the glossary has no entry, pick a natural term and use it consistently inside your package.

## 5. Packages (disjoint files; T11 is the only one that may touch code)

| Package | Files |
|---|---|
| **T1** | `CLAUDE.md` (translate and extend), new `AGENTS.md`, `README.md`, check `.gitignore` and `pyproject.toml` for Slovak text |
| **T2** | `CHANGELOG.md` |
| **T3** | `docs/design.md` |
| **T4** | `docs/journal.md` |
| **T5** | `docs/handover.md`, `docs/requirements.md` |
| **T6** | `docs/analyses/discord-analysis.md`, `docs/analyses/discord-login.md` |
| **T7** | `docs/analyses/channel-access.md`, `docs/analyses/thread-probe-2026-11-04.md`, `docs/analyses/real-account-check-2026-11-04.md` |
| **T8** | `docs/decisions/README.md` (index and template), ADRs 0001 to 0010, new ADR 0021 |
| **T9** | ADRs 0011 to 0020 in `docs/decisions/` |
| **T10** | `docs/briefs/antigravity-round-1.md`, `docs/briefs/antigravity-round-2.md` (this brief stays as it is), `prototype/README.md`, `prototype/probe.py`, `prototype/probe_threads.py` |
| **T11** | `src/`, `tests/` (and nothing else) |

### T1: CLAUDE.md, AGENTS.md, README.md
- `CLAUDE.md`: translate everything, then (a) put a new section **"Language: the repository is English only"** right after the intro: everything that is committed is English (docs, code, comments,
  identifiers, commit messages, tests and fixtures, file and folder names, tool texts); the conversation with the user may be in Slovak or any language but nothing of it enters the repository;
  quoted Discord content in tests and docs is made up and English, except small fixtures that test Unicode handling (accents, emoji, normalisation), which say so in a comment; reference ADR 0021.
  (b) Replace the old language bullet ("documents in Slovak") by that rule. (c) Evidence markers are `[VERIFIED]` and `[ASSUMPTION]`. (d) The project folder is `Discoop`.
  (e) The "Next" block of the journal replaces the "Ďalej" block. Everything else is translated faithfully, rules unchanged (agent workflow of ADR 0010, git rules, Discord rules).
  Update the status line only for names (do not invent new facts).
- New `AGENTS.md` (the shared instruction file for any coding agent, for example Antigravity/Gemini; at most about 120 lines): purpose of the project in 3 lines; **the English-only rule first**;
  commands (`uv sync`, `uv run pytest`, `uv run discoop ...`, the uv PATH hint); hard rules (no Discord or CDN calls from agents, tests are offline with fakes, no secrets or other people's data, no new
  dependencies without asking, `.py` files LF, do not touch `Temp/`, `exports/`, `prototype/out/`); git rules (commit only when the task says so, explicit paths, English messages, never push unless the user says so);
  documentation map (the table from `CLAUDE.md`), evidence markers, absolute ISO dates; a pointer: "`CLAUDE.md` has the Claude-specific orchestration workflow (ADR 0010). Keep `AGENTS.md` and `CLAUDE.md` consistent."
- `README.md`: translate (keep install and usage examples exactly).

### T2 to T7, T9, T10: documents
Translate per section 4. Package specifics:
- **T3 `docs/design.md`**: keep the section numbering exactly (code cites "section 5", "6.2", "6.3", "11", "12", ...). Section "Otvorené rozhodnutia" becomes "Open decisions" and its anchors are fixed.
  The sentence that the local folder may stay `Scoop` and the folder tree `Scoop/` in section 13 become `Discoop` ("the local folder is `Discoop`, renamed from `Scoop` on 2026-11-04").
- **T4 `docs/journal.md`**: every `**Ďalej:**` block becomes `**Next:**` (and `Ďalej (nahradené ...)` becomes `Next (superseded by ...)`). Slovak dates become ISO dates.
- **T6, T7**: replace real Czech or Slovak Discord content by made-up English examples (section 4.1). Keep every number, ID format, JSON shape and the `[VERIFIED]`/`[ASSUMPTION]` split.
  Do not add or remove facts.
- **T10**: `prototype/*.py`: comments, docstrings and printed texts to English; do not change behaviour. The old briefs are historical: translate them, keep their structure.

### T8: ADRs 0001 to 0010, index, ADR 0021
- Translate the ADRs (glossary for the fixed headings). ADR 0004 (name `discoop`): add a dated line at the end of its Decision: "2026-11-04: the local project folder was renamed from `Scoop` to `Discoop`."
- `docs/decisions/README.md`: translate the explanation, the status list, the index table (titles in English, statuses `Accepted` / `Proposed` / `Superseded by ADR NNNN`), the template.
- **New ADR 0021 "English-only repository"**: Status Accepted, Date 2026-11-04, Decided by the user. Context: the docs were Slovak (ADR 0001, ADR 0007), the repository is public, agents and
  other contributors work in English. Options: keep Slovak docs; bilingual docs; English only (chosen). Decision: everything in the repository is English (list as in T1), file and folder names too;
  the conversation with the user is free; sample Discord content is made up and English except Unicode-handling fixtures; evidence markers `[VERIFIED]` / `[ASSUMPTION]`.
  Consequences: ADR 0007 gets the status `Superseded by ADR 0021` (only its "documentation in Slovak" part: tool texts stay English); ADR 0001 gets a one-line note that the documentation language is now
  English (ADR 0021); all existing documents were translated on 2026-11-04 (round 3) and the doc files were renamed; `CLAUDE.md` and `AGENTS.md` state the rule. Add the row to the index.

### T11: code and tests
- `src/`: the markers `[OVERENÉ]`/`[PREDPOKLAD]` in comments and docstrings become `[VERIFIED]`/`[ASSUMPTION]`; the Slovak sample in the docstring of `src/discoop/render/text.py` becomes an English sample
  (and is consistent with the rendering it describes); search for any other Slovak (`git grep -nP "[áäčďéíĺľňóôŕšťúýžÁČĎÉÍĽŇÓŠŤÚÝŽ]" -- src tests`) and for comments that cite old Slovak words.
  Arrows, box characters and similar symbols are fine.
- `tests/`: sample message texts, author names, thread titles, embed titles, file names and similar **data** that are Slovak or Czech become simple English, and the expected values next to them change in
  the same way. Keep, with an English comment saying why, only fixtures that test Unicode handling: file-name sanitising (`é.txt`, `Zápočet 🔒.pdf`), name normalisation in `tests/test_resolve.py`
  (for example `Bakalářka – státnice`), emoji, fancy-font names. In `tests/test_resolve.py` replace the real-looking fancy-font display name by a made-up fancy-font word (it must still normalise to
  the plain word the test expects, adjust that expected word). Server and channel names that are made up but Slovak (`IZP – cvičenia`) become English (`IZP – exercises`).
  After each file run its tests, at the end the full `uv run pytest` must be green and the number of tests must be the same as at the start.

## 6. Final checks (coordinator, after all packages are committed)

1. **Links:** every relative markdown link resolves (script below), and every `#anchor` link points at an existing heading (check with a small script of your own using the GitHub slug rule).
2. **Slovak left:** `git grep -nP "[áäčďéíĺľňóôŕšťúýžÁČĎÉÍĽŇÓŠŤÚÝŽ]" -- . ':!uv.lock' ':!docs/briefs/antigravity-round-3-english.md'` must only show the documented Unicode fixtures in `tests/` and made-up
   emoji or symbol uses; list each remaining hit with the reason in the report. Also check for common Slovak words:
   `git grep -nwiE "(ako|alebo|ktorý|ktoré|nie je|sú|bola|bolo|všetky|používateľ|kanál|správa|súbor|ďalej|zatiaľ|pretože|však|keď)" -- . ':!uv.lock' ':!docs/briefs/antigravity-round-3-english.md'` must be empty (or justified).
   This brief itself is excluded on purpose: its glossary and its search patterns are Slovak, because they describe the translation. Do not translate or shorten them.
3. **Names:** `git ls-files` shows only English, ASCII file and folder names. `git grep -n "OVERENÉ\|PREDPOKLAD\|rozhodnutia/\|analyzy/\|zadania/\|Ďalej" -- . ':!docs/briefs/antigravity-round-3-english.md'` is empty.
4. **Tests:** the full `uv run pytest` is green with the same test count as at the start; `uv run discoop --help` and `uv run discoop agent-guide` run.
5. **Language rule present:** `CLAUDE.md`, `AGENTS.md`, ADR 0021 and `docs/decisions/README.md` state it; the index lists ADR 0021.
6. **Status line numbers** in `CLAUDE.md` (test count) match the real test count.

Link check script (save it outside the repository, for example in your scratch folder, and run it from the repository root):

```python
import re, subprocess
from pathlib import Path
files = subprocess.run(["git", "ls-files", "*.md"], capture_output=True, text=True, encoding="utf-8").stdout.split()
bad = []
for f in files:
    for m in re.finditer(r"\]\(([^)\s]+)\)", Path(f).read_text(encoding="utf-8")):
        t = m.group(1)
        if re.match(r"[a-z]+:", t) or t.startswith("#"):
            continue
        path = t.split("#")[0]
        if path and not (Path(f).parent / path).exists():
            bad.append((f, t))
print(len(bad), "broken links")
for f, t in bad:
    print(" ", f, "->", t)
```

(Placeholders such as `cesta` or `files/...` that appear as examples inside documentation tables are not real links: after translation they read `path` and `files/...`; make sure they are
written as code, not as links, so the check is clean.)

## 7. Commits (continuous, by the coordinator)

- One commit per finished package, right after you checked its diff: `git add <explicit file list>` then `git commit -m "Translate <what> to English"`
  (T1: "Translate CLAUDE.md and README to English and add AGENTS.md", T8: "Translate the early ADRs and add ADR 0021: English-only repository", T11: "Translate code comments and test data to English", and so on).
- English messages, imperative mood, no attribution or co-author lines, **no push**.
- If a commit fails (for example `index.lock` because of a running process), wait a moment and retry; never delete lock files you did not create.
- Before every commit run `git status --short`: only the files of that package may be in it. Final state: `git status` clean.

## 8. Report

Write `prototype/out/antigravity-round-3-report.md` (git ignores it) as you go, after each package: files changed, commit hash, anything odd in the Slovak original (wrong or outdated statements you
translated as they were), decisions you made, the remaining Slovak hits with reasons, the test result (count passed and failed) and the final state of the checks of section 6.
If something stops you in the middle (usage limit, error), the report must tell the owner where you got to.
