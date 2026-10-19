# Phase 07 - GĐ4 scenario suite, live R0 smoke, install

## Context Links
- Spec §6 GĐ4 (test cases per error group, wrong device, disconnect, tool errors, confirmation cannot be bypassed, confidence and report completeness), §8 done criteria: [requirements.md](requirements.md)
- Settled: junction `~/.claude/skills/recovery-storage` -> `./recovery-storage/`
- Phases 01-06 acceptance criteria (unit level; not repeated here)

## Overview
- Priority: P1. Status: Todo. Depends on 01-06.
- Cross-phase scenarios driven through `rslib.cli.main(argv, runner=RecordedRunner(...))` with a temp home; one live R0 smoke on this machine; the install junction.

## Key Insights
- Unit criteria already freeze each component; this phase proves the whole flow per spec §8 and catches seams (e.g. collect -> assess -> gate -> verdict -> report).
- Scenario inputs are recorded real outputs (+ documented derived mutations); a scenario that needs an output class with no real sample is marked `structural` and listed, not faked.
- Live smoke is R0 only (inventory, collect, assess, report) on this machine's NVMe disks, non-admin: proves the real runner, PowerShell scripts and smartctl paths work outside fixtures.

## Requirements
Scenario suite `tests/scenarios/` (each scenario = session script + recorded runner outputs + expected end state):
- One per spec §2.3 cause group: connection-cable-power-bridge (199 CRC), partition-or-filesystem (Ntfs 55 event + healthy SMART), bad-sectors-io (`scrutiny-usbjmicron-hdd-failing`), controller-or-firmware (S11 derived / bytes 0), nand-degradation (f3probe 101 or NVMe media_errors), fake-capacity-or-counterfeit (f3probe 103), write-locked (NVMe critical_warning 8), encryption-or-protection (symptom encrypted-locked + bridge), physical-hardware (mechanical-noise symptom).
- One per triage class (five), each reached from recorded evidence + session facts.
- Wrong device: two USB sticks, same model and size, serial absent -> `ambiguous`, gate refused, `device link` by operator resolves. Built from `windows/usb-stick` captures with the second disk a documented derived duplicate.
- Real USB paths: `windows/usb-stick` (no SMART, `needs_elevation`, `fs_unrecognised`) and `windows/usb-sd` (weak identity, FAT32) run end to end: inventory -> collect -> assess -> gate (f3write-f3read after data-state) -> attested/f3 evidence -> verdict -> report.
- Q5 branches end to end: failing HDD default -> SOFTWARE + constraints; irreplaceable + tolerance low -> HARDWARE; counters rising within session -> HARDWARE; not-spinning -> STOP_UNSAFE.
- Disconnect: device disappears between gate open and confirm; between confirm and close; during collect (tool returns open failure).
- Tool failure matrix for smartctl, PowerShell, lsblk: missing, timeout, non-zero exit, malformed JSON, empty stdout -> collection status recorded, no traceback, exit 4 where the command's purpose failed, assessment `unknown`/`UNDETERMINED`.
- Bypass: every CLI flag that reaches the runner fuzzed with forbidden values (`--dtype "sat,x"`, device path with `;`, extra args) -> refused before spawn; no CLI command writes a verdict PASS without the matrix; gate state machine has no transition skipping `confirm`.
- Confidence: across all scenarios, no `healthy` with high confidence; every high-confidence conclusion has at least one STRONG evidence item; every hypothesis has alternative + next test.
- Report completeness: every finished scenario (with verdict) passes `report --check`; unfinished ones fail it naming the missing sections.
- Full data-recovery flow: data-recovery + device-recovery goals on a failing HDD -> format gate refused until a complete mapfile is ingested and data-state secured -> format gate -> f3/verify not applicable (HDD) -> self-test evidence -> PASS or refusal per matrix.
Live smoke (manual run, recorded in the phase review with date, command, exit code): `inventory`, `collect`, `assess`, `report --redact --check` against this machine, with the USB stick and SD reader plugged in; expected: both NVMe disks identified with exact UniqueId<->eui64 join, health healthy/medium, boot/system disk flagged; USB stick and SD card listed with serial absent, SMART `needs_elevation` (non-admin), triage SOFTWARE_RECOVERY_CANDIDATE.
Install: `recovery-storage/scripts/install_junction.py` (or documented one-liner) creating `~/.claude/skills/recovery-storage` as a junction to the repo folder; idempotent; refuses if the target exists and is not a junction to this folder.
Python floor (decision Q6): main agent installs 3.10 with `uv python install 3.10`; the full suite runs on 3.10 and 3.12.

## Architecture
```
recovery-storage/scripts/tests/scenarios/<name>/{script.json, outputs/*.json|txt, expected.json}
recovery-storage/scripts/tests/test_scenarios.py   parametrised over scenario dirs
recovery-storage/scripts/install_junction.py       stdlib only; filesystem call, no subprocess
```
Install note: junction creation is a filesystem operation, not a device tool; implement with `_winapi.CreateJunction` (stdlib, CPython on Windows) to avoid adding `cmd.exe` to the runner allow-list; POSIX: `os.symlink`. This keeps A18 (no subprocess outside runner) intact.

## Related Code Files
Create: `tests/scenarios/**`, `tests/test_scenarios.py`, `tests/test_bypass.py`, `tests/test_tool_failures.py`, `recovery-storage/scripts/install_junction.py`.
Modify: `fixtures/SOURCES.md` (scenario-specific derived files), SKILL.md (one-line install pointer).

## Implementation Steps
1. Scenario format + runner; port each cause-group/triage scenario.
2. Wrong-device, disconnect, tool-failure, bypass scenarios.
3. Confidence + report-completeness properties across all scenarios.
4. Python 3.10 run.
5. Live R0 smoke on this machine; record results in the phase review (not in the skill).
6. Install junction; verify Claude Code lists the skill.

## Todo List
- [ ] scenario harness
- [ ] cause-group + triage scenarios
- [ ] wrong-device / disconnect / tool-failure / bypass
- [ ] confidence + completeness properties
- [ ] py3.10 + py3.12 runs
- [ ] live R0 smoke
- [ ] junction install

## Acceptance Criteria (observable)
- G1 Each of the nine cause groups has a scenario whose assessment contains a hypothesis of that category with >= 1 evidence item; scenarios lacking a real sample are labelled `structural` in their `script.json` and listed in the phase review.
- G2 Each of the five triage classes is the final class of at least one scenario.
- G3 Wrong-device scenario: no gate reaches `open`; after `device link` the gate opens for the linked device only.
- G4 Disconnect scenarios: open->confirm disappearance ends `aborted(device-changed)`; confirm->close swap ends `identity_drift=true` and PASS refused; collect open failure stores `collection_failed`, exit 4.
- G5 Tool-failure matrix: every cell ends with a stored run row, a defined collection status, no Python traceback on stderr, exit code per phase 01 table.
- G6 Bypass: all fuzzed forbidden inputs refused before spawn (RecordedRunner records zero spawns for them); grep over `rslib/` confirms A18 still holds.
- G7 Properties: zero `healthy/high`; every high-confidence item has a STRONG evidence item; every hypothesis complete.
- G8 Every scenario with a verdict passes `report --check`; every scenario without one fails it, naming section 9.
- G9 Full data-recovery flow reaches the expected end state at every step (refusal codes and order as specified).
- G10 Suite exit code 0 on Python 3.10 (uv-managed interpreter) and on 3.12; both runs recorded with interpreter path and version.
- G11 Live smoke: commands exit 0; report `--check` exit 0 except section 9 (no verdict) which is expected; result recorded with date, interpreter, smartctl version.
- G12 After install, `~/.claude/skills/recovery-storage/SKILL.md` resolves to the repo file; re-running the installer is a no-op exit 0; a pre-existing non-junction target -> exit 3 untouched.

## Pros / cons vs alternative
Chosen: data-driven scenario directories replayed in-process.
- Pros: scenarios readable by humans, extendable with new real captures without code; no device or admin needed; same code path as production except the runner.
- Cons: in-process runner injection does not exercise process spawning (covered by live smoke G11).
Alternative: end-to-end against virtual block devices (loop devices / VHD) on a real OS.
- Pros: exercises real tools. Cons: smartctl has no SMART on virtual disks, needs admin/root, Linux-only for loop devices; does not reproduce failing hardware. Rejected for the suite; live smoke covers spawning.

## Not Worth Doing If
- A scenario is not worth adding if its end state is already asserted by a unit criterion with the same inputs (check phases 01-05 criteria lists before adding).

## Risk Assessment
- `_winapi.CreateJunction` is a CPython-private API -> fallback documented: operator runs `New-Item -ItemType Junction` manually; installer prints the command when the API is missing.
- uv-managed 3.10 lacks a stdlib module used here (e.g. `_winapi` is CPython-Windows only, present in uv builds) -> the 3.10 run catches it.
- Live smoke reveals PowerShell output shape differences -> fix parsers + add the capture as a fixture (real data, redacted).

## Security Considerations
- Live smoke output stays under home; the phase review records only redacted values.
- Installer never deletes an existing target.

## Next Steps
- Phase 08 (guard hook) needs the junction installed by this phase for its live test.
- Structural scenarios stay structural until real captures exist (HDD dock, elevated `-d sat`, Linux USB sysfs, native mmc, F3/H2testw outputs).
