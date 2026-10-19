# Plan: recovery-storage skill (GĐ 1-4)

Status: Done - 2026-10-19 (review amendments: [01](amendment-01-operator-console-and-mapfile-coverage.md), [02](amendment-02-review-round-2.md), [03](amendment-03-real-run-card-reader.md), [04](amendment-04-verification-gate-window.md), [05](amendment-05-report-fixes.md), [06](amendment-06-f3-ingest-real-outputs.md), [07](amendment-07-f3read-after-replug.md))
Spec: [requirements.md](requirements.md) (verbatim spec, settled decisions, verified facts). Research: `research/researcher-0{1..5}-*.md`. Fixtures (built): `recovery-storage/scripts/tests/fixtures/SOURCES.md`.

## Goal
Claude Code skill `./recovery-storage/` that orchestrates storage diagnosis and recovery. It detects devices, collects R0 evidence, triages, and puts every risky action behind an identity re-check plus human confirmation (the gate). It records cases in SQLite, refuses PASS without evidence and renders the §7 report. It never images, repairs, flashes or tests capacity itself: it drives and reads smartctl / OS tools and ingests ddrescue / F3 output.

## Architecture (one paragraph)
`scripts/rs.py` -> `rslib/cli.py` (argparse, `--json`, `--home`). Every external process goes through `rslib/runner.py`, the only module allowed to import `subprocess`. Before spawning, it checks argv against `rslib/allowlist.py`; it then applies a timeout and records tool/version/argv/exit. PowerShell runs only the shipped `rslib/ps/*.ps1` scripts (sha256-frozen, `-EncodedCommand`, validated env parameters). Store: `<home>/rs.sqlite` + `<home>/sessions/<id>/evidence/*.json` (sha256 in DB). Rules are pure functions over normalised records, so tests replay recorded real outputs through an in-process `RecordedRunner`; production has no replay switch. A skill-scoped PreToolUse hook (phase 08) is a second, leaky barrier against ungated destructive shell commands.

## Phases (sequential, single implementer)
| # | Phase | Goal | Status |
|---|---|---|---|
| 01 | [foundation](phase-01-foundation-runner-store-session.md) | CLI skeleton, guarded runner, SQLite store, sessions (incl. data value, risk tolerance) | Done |
| 02 | [identity + collection](phase-02-device-identity-and-collection.md) | Windows/Linux parsers, smartctl normaliser, fingerprint match (exact/probable/weak/ambiguous), `inventory`, `collect`, `ingest smartctl` | Done |
| 03 | [evidence interpretation](phase-03-health-triage-hypotheses-ingest.md) | health verdict, delta, risk-based triage, hypotheses, ddrescue/F3 parsers, `assess`, `ingest` | Done |
| 04 | [gate + verdict](phase-04-gate-and-verdict.md) | action catalog, gate open/confirm/close/abort, R2 lock, data-rescue state, `verdict` evidence rules | Done |
| 05 | [report + fleet](phase-05-report-and-fleet-history.md) | §7 report + `--check`, `device list/show`, `compare` (GĐ3) | Done |
| 06 | [SKILL.md + references](phase-06-skill-md-and-references.md) | lean orchestrator + playbooks (5 fields per method), `rs.py rules` | Done |
| 07 | [GĐ4 scenarios + install](phase-07-scenarios-hardening-install.md) | cross-phase scenarios, live R0 smoke (NVMe + USB + SD), junction, py3.10 + 3.12 | Done, live checks pending |
| 08 | [guard hook](phase-08-guard-hook.md) | PreToolUse deny of matched destructive commands unless a gate is `open`; spike-gated | Done, leaky by design |

Dependencies: strictly 01 -> 08. Each phase's acceptance criteria are the frozen spec for its tests; phase 07 adds only cross-phase scenarios. Phase 08 is separate from 07: it adds a new mechanism with its own corpus and a live test whose outcome (deny enforced in bypassPermissions?) can cancel it.

## Decisions 2026-10-19
- Q1 hook: yes -> phase 08 (skill frontmatter `hooks:`, exit 2 deny, leaky by design, spike first).
- Q2 devices: USB stick + SD reader captured (`fixtures/windows/{usb-stick,usb-sd}`); HDD dock skipped.
- Q3 attested H2testw counts for PASS, labelled ATTESTED.
- Q4 samples git-ignored; `requirements.md` identifiers redacted (main agent).
- Q5 risk-based triage: failing-but-readable HDD -> SOFTWARE + image-first by default; HARDWARE when (irreplaceable AND tolerance low) or counters rise within the session; STOP_UNSAFE on mechanical-noise / not-spinning. New session fields `--data-value`, `--risk-tolerance` (phase 01/03).
- Q6 Python 3.10 via `uv python install 3.10`; suite runs on 3.10 and 3.12.

## Deviations from the main-agent direction (justified)
- **`gate confirm`** between open and action: re-resolves the fingerprint, requires an operator-typed phrase taken from the device, prints the OS path valid now (closes the renumber-after-replug window). Exec wrapper `gate run` rejected for v1: most R2 tools run outside this process (WSL, live Linux, GUI).
- **Ingest parsers in phase 03** with the rules that use them; phase 04 is only the control state machine.
- **Canonical identity = smartctl identity** when available; OS ids secondary (survives Windows <-> Linux/WSL).
- **`weak` match level**: SD-in-reader and blank media have no serial and no on-media id. Gate allows them only when no other attached device has the same model, size and VID/PID, and the confirmation phrase is the exact byte count.

## Over-engineering cut
- `groups`/`history` -> `device list --group-by` / `device show`. Lock -> SQLite partial unique index, no auto-expiry.
- No PhotoRec/TestDisk/H2testw log parsers (attested evidence + file hash instead); no nvme-cli; no event-ID table (only Ntfs 55); no generic-serial or VID blacklist.

## Fixtures
Real only (see `SOURCES.md`). Boundary cases are single-field mutations of a real file (`*.derived.json`). **No real sample yet:** HDD behind a USB dock on Windows; elevated `-d sat` on USB; native mmc SD; Linux USB sysfs chain; F3 full outputs; H2testw log; real ddrescue mapfile (manual example used).

## Risks (top)
- Wrong-device action -> fingerprint + confirm re-resolve + device-derived phrase; ambiguous never auto-picked.
- Agent calls tools directly -> SKILL.md rules + permission prompts + phase 08 hook (leaky: obfuscation, scripts, GUI tools; any open gate unlocks all devices).
- Hook not enforced in bypassPermissions -> phase 08 spike decides before building.

## Decisions 2026-10-19 (round 2, main agent, reversible defaults)
- R1: `--risk-tolerance` unspecified = `medium`; SKILL.md Phase 0 asks for it.
- R2: hook decodes `powershell|pwsh -EncodedCommand|-enc|-e <b64>` and judges the decoded text; an undecodable payload is destructive-class (needs an open gate). rs.py's own PowerShell runs via subprocess, not the agent tool, so it is unaffected.
- R3: hook script missing -> fail open with visible "guard inactive" warning (exit 1), never exit 2.
- R4: SD-in-reader weak identity accepted with the gate rule in phase 04 D9b (unique model+bytes+vid/pid, phrase = exact bytes).
- R5: no elevated capture; USB SMART absence stays unverified (`needs_elevation` only) and is stated so in references.

## Unresolved questions
none
