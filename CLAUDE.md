# CLAUDE.md

Claude Code skill `recovery-storage/`: storage diagnosis and recovery orchestration. Python >= 3.10, standard library only at runtime; pytest for tests; smartctl 7.x is the single SMART collector. Docs index: `docs/README.md`.

## Commands (PowerShell, repo root)

- Tests: `python -m pytest -q -p no:cacheprovider` (marker `live` is deselected by default).
- CLI: `python recovery-storage/scripts/rs.py --help`, `... rules`.
- Install: `python recovery-storage/scripts/install_junction.py`.
- Fixture leak check: `python -I tools/redact_fixtures.py --check`.

## Read before coding

1. `plans/20261019-1726-recovery-storage-skill/requirements.md`
2. `plans/20261019-1726-recovery-storage-skill/plan.md`, then `amendment-01-*.md`, `amendment-02-*.md`, `amendment-03-*.md`, `amendment-04-*.md`, `amendment-05-*.md`, `amendment-06-*.md`, `amendment-07-*.md`, `amendment-08-*.md` and `amendment-09-*.md`
3. `recovery-storage/scripts/tests/CONTRACT.md`
4. `recovery-storage/SKILL.md`

## Conventions

- Only `rslib/runner.py` spawns processes; every argv passes `rslib/allowlist.py`. Exit codes 0/2/3/4/5, no tracebacks, one JSON object with `--json`.
- The frozen suite (`.claude/frozen-tests.json`) is not edited to make code pass; behaviour changes go through an amendment and re-freeze. Do not touch `recovery-storage/` skill files, tests or plans from a docs task.
- Fixtures are real or single-field derivations, redacted; raw captures stay git-ignored.
- Docs describe current state only; changelog history goes to `docs/project-changelog.md`. Details: `docs/code-standards.md`.
- Comments: caveman style (short, mechanism and pointer, keep numbers and dates).

## Lessons

- Text with backslashes (Python source, regexes): write it with the Write/Edit tools, never through a Bash heredoc; on Windows always run Python with -I when the CWD is recovery-storage/scripts/rslib; frozen hashes are taken over the git blob bytes. Detail: .claude/memory/windows-and-tooling-traps.md
- Card reader medium changes size or media id mid-session: ask whether the card was swapped before concluding anything; a write gate cut by a disconnect closes `interrupted`. Detail: .claude/memory/card-swap-misread.md
- Review findings: turn the reviewer's reproductions into spec tests (test-designer, amendment + re-freeze when the contract changes) before changing code; re-review only the changed functions. Detail: .claude/memory/review-fix-regressions.md
