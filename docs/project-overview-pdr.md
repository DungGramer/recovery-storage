# Project Overview and PDR

Sources: `plans/20261019-1726-recovery-storage-skill/requirements.md` (verbatim spec in Vietnamese, settled decisions, verified facts), `plan.md`, `amendment-01-operator-console-and-mapfile-coverage.md`, `amendment-02-review-round-2.md`.

## Product

`recovery-storage` is a Claude Code skill (`recovery-storage/`) that diagnoses and recovers storage devices: USB flash, SD/microSD, HDD, SATA/NVMe SSD, external drives, USB bridges and controller-based flash. Goals per session: data recovery, device recovery, diagnosis only, authenticity check, health assessment, forensic preservation.

It orchestrates; it does not replace specialised tools. Python scripts only detect devices, normalise output, orchestrate the workflow, store results and manage state. Imaging (ddrescue), partition and file recovery (TestDisk, PhotoRec), capacity tests (F3, H2testw) and controller tools (MPTool) are run by the operator, and the skill ingests their output.

Done criteria from the spec: classify device and fault without repairing; never run a destructive action on its own; know when to move from software to hardware diagnosis; prefer existing tools; stop when evidence is insufficient or risk too high; never treat a successful format as a successful recovery; every conclusion carries evidence, a verification criterion and a final status.

## Scope

In scope: R0 evidence collection on Windows and Linux, risk-based triage, gated risky actions, data-first state, evidence-based verdicts, per-device reports, case history and comparison across sessions.

Out of scope: running imaging, repair, flashing or capacity writes inside the CLI; fetching or running firmware; reimplementing SMART parsing or NAND decoding; cloud storage, databases, git history.

## Business rules

### R0-R3 risk levels

| Level | Meaning |
|---|---|
| R0 | Read-only evidence: smartctl, OS inventory, event logs. No gate. |
| R1 | Non-destructive but changes device or OS state (self-tests, offline, read-only attribute, imaging read, WSL bare mount). |
| R2 | Writes the source (format, partition write, F3/H2testw write tests, clear, filesystem repair, firmware, MPTool). One live R2 gate globally. |
| R3 | Hardware / lab hand-over. |

Each session has a risk ceiling (default R0) the operator raises deliberately; an action above it is refused (`risk-above-ceiling`). The action catalog is `rslib/actions.py`.

### Gates

Every R1+ action goes through `gate open` -> operator `gate confirm` -> action by the operator -> `gate close`. `open` lists every failing reason at once. `confirm` is typed by the operator at an interactive console, re-resolves the device and prints the only OS path to use. A gate covers one device; a second live gate on it is refused (`device-busy`). Nothing runs inside the CLI.

Triage `STOP_UNSAFE` (mechanical noise, not spinning) allows only the R3 hardware-lab action. A forensic-preservation goal never writes the source. Boot and system disks are refused.

### Operator console (amendment 01)

`gate confirm`, `data-state waived`, `data-state secured --attested`, `data-state not-needed`, `ingest attested` and `device link` need a human at an interactive console, which the agent's tool calls do not have. Without one: exit 3 `operator-console-required` with the exact command for the operator's own terminal, store unchanged. Answers other than the required phrase or `YES`: `wrong-phrase` / `operator-declined`. The phrase is shown by `gate open`; the operator reads it there. Known leak: an injected operator in a script that imports the library, or a pseudo-terminal wrapper.

### Data-first across sessions with last write (amendment 02)

- Data-first is a state per session and device: `none`, `secured`, `waived`, `not-needed`.
- A write gate on a device that any session must preserve is refused (`data-not-secured`) unless `secured` or `waived` was recorded after the device's last write (`last_write_ts`, across all sessions, including confirmed-then-aborted write gates).
- `not-needed` is allowed only when the session does not preserve data.

### Full-coverage image under an image-ddrescue gate

`secured --evidence` needs (amendment 01) a ddrescue mapfile that starts at 0, is contiguous, ends exactly at the device byte count, is finished and has no bad, non-tried, non-trimmed or non-scraped bytes. Reasons: `image-incomplete`, `image-not-contiguous`, `image-does-not-cover-device`. Amendment 02 adds a closed, successful `image-ddrescue` gate on that device in the same session, confirmed before the evidence was ingested (`image-gate-missing`). Hand-written mapfiles therefore cannot secure data. The alternative is an operator `waived --reason`.

### Identity changed only by the operator

Device ids bind to multi-attribute fingerprints, never to Disk Number, drive letter or `/dev` path. `gate close` never changes a fingerprint; a device not found exactly closes the gate with `identity_drift` and a `drift_reason`. `device link <observation> <device>` or `--new` is operator-only; a link to different hardware is refused (`hardware-mismatch`); a valid link clears drift on earlier closed gates. Unresolved drift blocks PASS. A smartctl answer is attached to a device only when its identity matches (`identity-conflict` otherwise). SD cards in a reader without an on-media id are `weak`: allowed at a gate only when no lookalike is attached, with the exact byte count as the phrase.

### Triage (Phase 1)

First matching rule wins: STOP_UNSAFE; HARDWARE_DIAGNOSIS_REQUIRED (isolated "not detected", irreplaceable data with low risk tolerance, or media counters rising within the session); CONTROLLER_RECOVERY_CANDIDATE; SOFTWARE_RECOVERY_CANDIDATE (failing-but-readable HDD means image first by default); UNDETERMINED. Session fields `--data-value` and `--risk-tolerance` (default `medium`) drive it. Rule ids and parameters: `rs.py rules`.

### Verdict matrix

Statuses: PASS, PASS_LIMITED, FAIL, REPAIR_REQUIRED, UNRESOLVED, RETIRED. PASS needs evidence gathered after the window start (later of session start and last write): replug and stable observations, a classified device, and per class: flash capacity verification (attested H2testw counts, labelled ATTESTED; f3read at coverage); HDD health, non-rising counters and a self-test inside the window; SSD health, counters, critical warning clear and read verify. Missing items are all listed. PASS_LIMITED requires a limitation and is not for unique or important data. A successful format is never evidence. Details in [system-architecture.md](system-architecture.md).

### Guard hook and its leaks

A skill-scoped PreToolUse hook denies matched destructive Bash/PowerShell commands unless a gate is open. It is a second barrier. It does not stop obfuscation, script files, GUI tools, unknown tools, non-shell tools, or anything run outside Claude; any open gate unlocks all matched commands on all devices; it reads only the default home; it is active only after the skill is invoked.

### Reports

Per-device report with the spec section 7 headings (Vietnamese in the code), every statement tagged `[VERIFIED]`, `[ATTESTED]`, `[INFERRED]` or `[UNDETERMINED]`; `--check` flags unfilled sections; `--redact` masks serials and user/host names.

## Non-functional requirements

- Stdlib-only Python >= 3.10; no network access; no subprocess outside the runner; argv allow-list.
- Case store outside the repo (serials); evidence has sha256 in the database.
- No tracebacks to the user; fixed exit codes; one JSON object with `--json`.
- Fixtures are real captures or single-field derivations, redacted.
- Evidence beats assertion: SMART-clean is never proof of health (healthy is capped at medium confidence).

## Acceptance

The frozen spec-first suite (`.claude/frozen-tests.json`, `tests/CONTRACT.md`) is the acceptance record. Criteria that cannot be automated (live device smoke, real console, trigger evaluation, hook enforcement in bypass-permissions mode) are listed under `uncovered` in the manifest. Status and history: [project-roadmap.md](project-roadmap.md), [project-changelog.md](project-changelog.md).

## Settled decisions

Scope GĐ 1-4 built in full; Python >= 3.10 stdlib only, smartctl as single collector; Windows via PowerShell 5.1 scripts, Linux via lsblk and sysfs; SQLite store with per-session evidence; operator-attested H2testw counts for PASS; risk-based triage; guard hook as a leaky second barrier; suite run on Python 3.10 and 3.12.
