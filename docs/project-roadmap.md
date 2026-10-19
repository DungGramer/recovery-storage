# Project roadmap: recovery-storage skill

Last updated: 2026-10-19 (HEAD f32e84f). Changelog: [project-changelog.md](project-changelog.md).
Plan: [plans/20261019-1726-recovery-storage-skill/plan.md](../plans/20261019-1726-recovery-storage-skill/plan.md).
Architecture: [system-architecture.md](system-architecture.md).

## Goal

Claude Code skill `recovery-storage/` that detects storage devices, collects R0 evidence, triages, puts every risky action behind an identity re-check plus human confirmation (the gate), refuses PASS without evidence and renders the report. It never images, repairs, flashes or tests capacity itself.

## Phase status

Acceptance for phases 01-08: frozen test suite green on Python 3.12, exit 0, verified 2026-10-19.

| # | Phase | Status | Delivered in |
|---|---|---|---|
| 01 | Foundation: CLI, guarded runner, SQLite store, sessions | Done | d8990a5 |
| 02 | Device identity and collection | Done | d8990a5 |
| 03 | Evidence interpretation: health, triage, hypotheses, ingest | Done | d8990a5 |
| 04 | Gate and verdict | Done | d8990a5 |
| 05 | Report and fleet history | Done | d8990a5 |
| 06 | SKILL.md and references | Done | d8990a5 |
| 07 | Scenarios, hardening, install | Done (live checks pending, see M3) | d8990a5 |
| 08 | Guard hook | Done (leaky by design) | d8990a5 |

Review amendments applied on top (f32e84f):

| Amendment | Scope | Status |
|---|---|---|
| [01](../plans/20261019-1726-recovery-storage-skill/amendment-01-operator-console-and-mapfile-coverage.md) | Operator console for confirmations; full-coverage mapfiles | Done |
| [02](../plans/20261019-1726-recovery-storage-skill/amendment-02-review-round-2.md) | Identity by operator, last write, image gate, snapshot identity, self-test wrap, SSD coverage, unsafe characters, guard tokenizer | Done |

## Next milestones (open)

### M1. Operator console verification

- Operator must run `gate confirm` at a real console: PowerShell and Windows Terminal.
- Git Bash (mintty) isatty behaviour is unverified; treat as unsupported until tested.
- Same check applies to the other console-gated commands (`session data-state`, `ingest attested`, `device link`).

### M2. Missing real captures

Fixtures are real captures only; these are absent:

- HDD behind a USB dock (Windows).
- smartctl standby output.
- f3read output with numbers (unblocks 5 skipped tests).
- Elevated USB SAT capture (`-d sat`).
- Native mmc SD.
- Linux USB sysfs chain.

Until the USB SAT capture exists, USB SMART absence stays unverified (`needs_elevation` only) and references say so.

### M3. Live checks pending (`test_live.py`)

- G10: run on Python 3.10 and 3.12.
- G11: live R0 smoke.
- WSL bare-mount identity spike.
- F7: reviewer pass.
- F9: trigger eval.

### M4. Known low findings left open

- Guard pattern list is not exhaustive (for example `Invoke-Expression` with a variable, `New-Volume`, `sdelete`, `dcfldd`). The hook stays a leaky second barrier.
- Device-type free text is not validated.
- `ingest smartctl` has no input size limit.
- Open gate TTL is enforced only in the hook.
- `gate open` on a drifting device is not refused.

## Risks

- Wrong-device action: mitigated by fingerprint, confirm re-resolve, device-derived phrase, operator-only identity changes.
- Agent bypassing the CLI: mitigated by SKILL.md rules, permission prompts and the guard hook; leaks are obfuscation, scripts, GUI tools, an injected operator or a pseudo-terminal wrapper, and any open gate unlocks all devices in the hook.
- Console confirmation is untested on real terminals (M1).
