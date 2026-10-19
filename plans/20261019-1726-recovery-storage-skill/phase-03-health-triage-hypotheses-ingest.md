# Phase 03 - Evidence interpretation: health, triage, hypotheses, ingest parsers

## Context Links
- Spec Phase 1 triage classes, §2.2 health, §2.3 cause groups + "confidence, evidence, alternative, next test", §2.4 authenticity: [requirements.md](requirements.md)
- Verdict design, strong/medium/weak signals, wear whitelist, delta rules: [researcher-05](research/researcher-05-health-rules.md) §1-§6
- NVMe critical_warning bits: [researcher-01](research/researcher-01-smartctl-nvme-json.md) §5
- F3 exit codes and line formats: [researcher-03](research/researcher-03-flash-counterfeit-controller.md) §1
- ddrescue mapfile format (verbatim 1.30 example): [researcher-04](research/researcher-04-imaging-recovery.md) §1
- SATAFIRM S11 safe-mode identity (vendor-lab sources): researcher-04 §4
- Fixture names and origins: `recovery-storage/scripts/tests/fixtures/SOURCES.md`; session fields `--data-value`, `--risk-tolerance`, symptom `not-spinning`: phase 01

## Overview
- Priority: P0. Status: Todo. Depends on 01, 02.
- Commands: `assess <session> <device>`, `ingest ddrescue|f3probe|f3write|f3read|attested ...`.
- Pure, deterministic functions: same inputs -> same output, rule version stored with each assessment.

## Key Insights
- Missing field skips the rule; it never defaults to 0/false. Missing everything -> `unknown` / `UNDETERMINED`.
- A clean SMART report is not proof of health (Backblaze: 23.3% of failed drives showed none of the five stats) -> `healthy` confidence is capped at `medium`, always with a next test.
- 199 CRC is a link/cable/bridge signal, never a media verdict.
- Growth between two valid snapshots outranks absolute counts.
- Triage class answers "may the software path continue, and under which constraints"; health answers "how bad". Decision Q5 (2026-10-19, risk-based): a failing-but-readable disk without mechanical symptoms is a software (imaging) candidate with image-first constraints by default; it becomes `HARDWARE_DIAGNOSIS_REQUIRED` when the effective data value is irreplaceable AND risk tolerance is low, or when media counters rise between snapshots within the session; mechanical-noise / not-spinning -> `STOP_UNSAFE`.
- Environment facts (`needs_elevation`, `unsupported_bridge`) are not device evidence: they never lower health below `unknown` and never raise a hardware hypothesis.
- Counterfeit is concluded only from write/read evidence (F3), never from identity strings alone; identity inconsistency gives a low-confidence hypothesis.
- Unverified research items ([M]/[K]/[UNVERIFIED]: HDD temperature bands, Seagate packed raws, event ids, generic serials, "assumed" wear rows) are NOT rules here; they go to references labelled.

## Requirements
Health verdict per snapshot: `healthy | watch | degraded | failing | unknown`, with `confidence low|medium|high`, `evidence[]` (snapshot id + JSON path + value), `missing[]` (fields that would have been needed).
Rules (first match wins; each declares required fields):
1. failing / high: overall status FAILED; any pre-fail attribute VALUE <= THRESH (or `when_failed == "now"`); NVMe critical_warning bit 0 (spare), bit 3 (media read-only); available_spare < available_spare_threshold; self-test log entry with read failure; delta: two or more of {5,187,197,198,media_errors} rising.
2. degraded / medium: raw > 0 on 5, 187, 197 or 198; media_errors > 0; critical_warning bit 2, 4 or 5; percentage_used >= 100 or devstat Percentage Used Endurance Indicator >= 100; one of {5,187,197,198,media_errors} rising.
3. watch / low-medium: percentage_used or devstat endurance in [80, 100); temperature.current >= device-reported `op_limit_max` (only when reported); 199 or 188 raw > 0; num_err_log_entries > 0; exit bits 5-7 set.
4. healthy / medium (cap): collection ok, overall status PASSED present, all rule-1/2 required fields present for the protocol and clean.
5. unknown: collection failed/timeout/tool_missing/malformed, SMART not exposed, protocol without rules (SCSI in v1), or overall status absent.
Parameters (named constants with rationale comment): endurance watch 80, degraded 100 (100 = rated endurance consumed, smartmontools/NVMe semantics).
SATA SSD wear: devstat "Percentage Used Endurance Indicator" first; else attribute rows whose smartctl name states "remaining"/"left" (169 Remaining_Lifetime_Perc, 173/202/231 Percent_Lifetime_Remain, 231 SSD_Life_Left, 231 Life_Remaining_Percent, 233 Remaining_Lifetime_Perc, 177 Lifetime_Remaining%) -> remaining = normalised VALUE, confidence low. Any other wear row (e.g. 177 Wear_Leveling_Count, 233 Media_Wearout_Indicator) -> wear `unknown`.
Host writes: NVMe data_units_written x 512000 bytes; SATA devstat Logical Sectors Written x logical block size; no TBW-remaining unless operator supplies rated TBW.
Delta engine `delta(a, b)`: valid only if same canonical identity, power_on_hours non-decreasing, and counters non-decreasing except 197. Fields 5, 187, 197, 198, 199, media_errors, percentage_used, num_err_log_entries, power_on_hours. Absent on either side -> `n/a`.
Triage class (first match wins):
1. `STOP_UNSAFE`: session symptom in {mechanical-noise, not-spinning, burning-smell, physical-damage, liquid-damage, overheating}; or temperature.current >= device-reported `critical_limit_max`.
2. `HARDWARE_DIAGNOSIS_REQUIRED`, any of: (a) symptom `not-detected` or `disconnects-repeatedly` AND at least two isolation facts recorded (`--tried other-port|other-cable|other-host|other-os`) AND device absent / disappearing in observations; (b) health `failing` or `degraded`, identity readable, effective data value `irreplaceable` AND session risk tolerance `low`; (c) a valid delta within this session shows any of 5, 187, 197, 198, media_errors rising (active degradation while being handled).
3. `CONTROLLER_RECOVERY_CANDIDATE`: identity readable and bytes == 0 or bytes < 0.5 x nominal (gross mismatch; parameter); NVMe critical_warning bit 3; model string in the sourced safe-mode identity list (v1: `SATAFIRM S11`, source cited in code).
4. `SOFTWARE_RECOVERY_CANDIDATE`: identity readable (model or vid/pid, and bytes > 0) and none of the above; SMART status may be ok, `not_exposed`, `unsupported_bridge` or `needs_elevation` when OS identity is present (health then `unknown`, next_test names the elevated re-collect or the class-specific verify).
5. `UNDETERMINED`: everything else, incl. not-detected without isolation tests (next test = the missing isolation facts).
Constraints attached to triage (list): health failing/degraded or preserve=yes -> `image-before-any-write`, `no-fs-repair-on-source`; health failing -> `minimise-power-on`, `stop-if-read-rate-collapses`; bridge present -> `keep-original-enclosure` when symptom `encrypted-locked` or bridge-encryption suspected.
Hypotheses: `{category, confidence, evidence[], alternative, next_test}`; category in the nine spec groups: `connection-cable-power-bridge, partition-or-filesystem, bad-sectors-io, controller-or-firmware, nand-degradation, fake-capacity-or-counterfeit, write-locked, encryption-or-protection, physical-hardware`. A hypothesis is never emitted without at least one evidence item; `alternative` and `next_test` never empty. Observation fact `fs_unrecognised` (phase 02) -> `partition-or-filesystem` (medium). VID/PID values are never rule inputs (the "no-name VID ABCD" association is unverified and lives only in references as a weak hint).
Ingest parsers:
- ddrescue mapfile: comments (`#` at line start or after whitespace), first non-comment line = status line, then `pos size status`; integers in C++ syntax (hex `0x`, octal leading `0`, decimal). Output: total, rescued(`+`), bad(`-`), non_tried(`?`), non_trimmed(`*`), non_scraped(`/`), rescued_pct, finished (status line char `+`).
- f3probe: exit code (operator-provided `--exit-code`) + stdout text. 0 good; 101 damaged; 102 limbo; 103 wraparound; 104 chain; other non-zero -> `inconclusive` (tool error). Text `Bad news: ... counterfeit of type X` must agree with the code, else `inconclusive`. Parse `*Usable* size:` / `Announced size:` when present.
- f3write: `Free space:`, `No space!`, `Write failure:`; f3read: `Data OK:`, `Data LOST:`, `Corrupted:`, `Slightly changed:`, `Overwritten:`, exit code (0 pass, 1 bad).
- attested: `ingest attested --tool h2testw|other --result pass|fail --file <log-or-screenshot>`: stores sha256 of the attached file + operator text; evidence level `attested` (not `parsed`).
Each ingested record links to (session, device) and stores file sha256; ingesting the same file twice is idempotent (same sha256 -> same evidence id).

## Architecture
```
rslib/health.py     verdict(SmartRecord, prev: SmartRecord|None) -> HealthVerdict
rslib/delta.py      delta(a, b) -> DeltaResult{valid, reason, fields}
rslib/wear.py       wear whitelist table (id, name) -> remaining%
rslib/triage.py     triage(session, observations, verdict, ingested) -> TriageResult{class, constraints, hypotheses}
rslib/ingest.py     parse_mapfile, parse_f3probe, parse_f3write, parse_f3read, attested
rslib/assess.py     CLI orchestration; stores assessment row (rules_version, inputs ids)
```
Fixture to expected-result map is the test-designer's core table (below).

## Related Code Files
Create: `rslib/{health,delta,wear,triage,ingest,assess}.py`; tests `test_health_rules.py, test_delta.py, test_wear.py, test_triage.py, test_hypotheses.py, test_ingest_mapfile.py, test_ingest_f3.py, test_assess_cli.py`; fixtures `fixtures/smartctl/*.derived.json`, `fixtures/ingest/ddrescue-manual-1.30.map` (verbatim researcher-04), `fixtures/ingest/f3*.txt` (sourced from F3 docs sample outputs; fetch during this phase, cite URL in SOURCES.md).
Modify: `rslib/cli.py`, `fixtures/SOURCES.md`.

## Implementation Steps
1. Derived fixtures (single-field mutations, documented): NVMe sda with critical_warning 8; with critical_warning 1; available_spare 5 (< 10); percentage_used 79 / 80 / 99 / 100; temperature.current 85 (== critical_limit_max); a second NVMe snapshot with media_errors 0 -> 3 and power_on_hours +10; a pair with power_on_hours decreasing; from `scrutiny-usbjmicron-hdd-failing`, a second snapshot with attribute 197 raw 8 -> 12 and power_on_hours +1 (C16c).
2. F3 samples: fetch F3 docs usage page, copy example outputs verbatim into fixtures with URL; if a format is absent there, the parser for it is tested only on lines quoted in researcher-03 and marked so.
3. health, wear, delta (pure); then triage + hypotheses; then ingest parsers; then `assess` / `ingest` CLI.

## Todo List
- [ ] derived fixtures + SOURCES.md entries
- [ ] F3 sample outputs sourced
- [ ] health + wear + delta
- [ ] triage + constraints + hypotheses
- [ ] ingest parsers + CLI
- [ ] assess CLI storing assessments

## Acceptance Criteria (observable)
Health (fixture -> verdict / confidence / must-include evidence)
- C1 `scrutiny-usbjmicron-hdd-failing` -> failing / high; evidence includes overall FAILED, attribute 5 VALUE 1 <= THRESH 5 (`when_failed` now), 197 raw 8, self-test "Completed: read failure".
- C2 `scrutiny-nvme-media-errors` -> degraded / medium; evidence media_errors 7; num_err_log_entries 62 listed as weak; hypothesis `bad-sectors-io` with alternative "historical errors, now stable" and next_test "re-collect after a full read, compare media_errors delta".
- C3 `scrutiny-ata-ssd-crc199` (199 raw 108) -> watch, NOT degraded/failing; hypothesis `connection-cable-power-bridge`, next_test mentions changing cable/port and comparing 199 delta; wear `unknown` (177 Wear_Leveling_Count not whitelisted).
- C4 `scrutiny-ata-hdd-healthy` (WD 14TB clean) -> healthy / medium (never high); next_test = extended self-test or full surface read.
- C5 `scrutiny-ata-ssd-healthy` (860 EVO) -> healthy / medium; wear from devstat endurance 19 (used), source `devstat`.
- C6 `nvme-990pro-x` -> healthy / medium; percentage_used 6, spare 100 > 10; host writes = 74494327 x 512000 bytes.
- C7 `scrutiny-sat-partial` -> unknown; `missing` contains overall status and capacity; attribute values listed as evidence.
- C8 `scrutiny-scsi-no-smartctl-block` -> unknown (protocol without rules); `smart_status.passed` reported as evidence only.
- C9 `scrutiny-open-failed` -> unknown, reason `needs_elevation`, next_test "re-run collect from an elevated shell"; `missing-device` -> unknown, reason collection failed, next_test mentions checking connection / device path. Neither yields any hypothesis of category `physical-hardware` or `controller-or-firmware`.
- C10 Derived boundaries: percentage_used 79 -> healthy; 80 -> watch; 99 -> watch; 100 -> degraded. critical_warning 1 -> failing; 8 -> failing; available_spare 5 < 10 -> failing.
- C11 No verdict of `healthy` ever has confidence `high` across all fixtures (property test).
Delta
- C12 media_errors 0 -> 3 with power_on_hours +10 -> valid, `media_errors +3`, health at least degraded with "rising" evidence. Pair with power_on_hours decreasing -> `invalid: power-on hours went backwards`, no delta used. Different serials -> `invalid: identity differs`. 197 falling while 5 rising -> valid (197 exempt), counted as rising 5. Field absent on one side -> `n/a`, not 0.
Triage
- C13 Any fixture + session symptom `mechanical-noise` or `not-spinning` -> `STOP_UNSAFE` regardless of SMART. Derived temperature 85 with critical_limit_max 85 -> `STOP_UNSAFE`.
- C14 Symptom `not-detected`, device absent, isolation facts other-port + other-cable -> `HARDWARE_DIAGNOSIS_REQUIRED`. Same with zero or one isolation fact -> `UNDETERMINED`, next_test lists the missing isolation steps.
- C15 Observation with model `SATAFIRM S11` (derived) or bytes 0 with identity readable -> `CONTROLLER_RECOVERY_CANDIDATE`; constraints include `image-before-any-write`; hypothesis `controller-or-firmware`. NVMe critical_warning 8 -> `CONTROLLER_RECOVERY_CANDIDATE` + hypothesis `write-locked`.
- C16 `scrutiny-usbjmicron-hdd-failing` + preserve=yes, data-value unknown (effective irreplaceable), risk-tolerance default `medium` -> `SOFTWARE_RECOVERY_CANDIDATE` with constraints {image-before-any-write, no-fs-repair-on-source, minimise-power-on, stop-if-read-rate-collapses}.
- C16b Same + `--risk-tolerance low` -> `HARDWARE_DIAGNOSIS_REQUIRED`, rule id of branch (b) in evidence. Same + `--data-value replaceable --risk-tolerance low` -> `SOFTWARE_RECOVERY_CANDIDATE`. Same + preserve=no + data-value unknown (effective replaceable) + tolerance low -> `SOFTWARE_RECOVERY_CANDIDATE`.
- C16c Two snapshots of one device in the same session, derived pair with 197 raw 8 -> 12 and power_on_hours +1 -> `HARDWARE_DIAGNOSIS_REQUIRED` (branch c) even with tolerance `high`. The same pair split across two different sessions -> branch (c) does not fire (within-session only); health still reflects the delta.
- C16d `scrutiny-ata-hdd-healthy` + tolerance low + irreplaceable -> `SOFTWARE_RECOVERY_CANDIDATE` (branch b needs failing/degraded health).
- C17 `scrutiny-open-failed` (no OS identity) -> `UNDETERMINED`.
- C17b `windows/usb-stick` Disk 2 (OS identity, SMART `needs_elevation`, `fs_unrecognised=true`) -> triage `SOFTWARE_RECOVERY_CANDIDATE`, health `unknown`; hypothesis `partition-or-filesystem` (evidence: partition MbrType 7 without a recognised volume) with alternative "controller returns garbage / fake-capacity wrap corrupted the FS" and next_test "image or read-only inspect, then capacity verify after data is secured"; no hypothesis `fake-capacity-or-counterfeit` above low (VID/PID is never a rule input).
- C17c `windows/usb-sd` Disk 3 (FAT32 volume, SMART `needs_elevation`) -> `SOFTWARE_RECOVERY_CANDIDATE`, health `unknown`, no `partition-or-filesystem` hypothesis unless a symptom or event supports it.
- C18 Every hypothesis in every fixture run has >= 1 evidence item, non-empty alternative and next_test (property test).
- C19 No fixture produces hypothesis `fake-capacity-or-counterfeit` with confidence above low unless an f3 record is ingested.
Ingest
- C20 Verbatim 1.30 mapfile -> total 1474560, rescued 1142784, bad 512, non_scraped 4096, non_trimmed 32256, non_tried 294912, rescued_pct 77.5 (rounded to 1 dp), finished false.
- C21 Number syntax: `0x200` = 512, `512` = 512, `010` = 8 (octal), `0o10` rejected as malformed line, negative or non-numeric -> malformed with line number; empty file -> malformed.
- C22 f3probe exit 0 + "Good news" text -> `good`; 103 + "counterfeit of type wraparound" -> `fake/wraparound` -> hypothesis `fake-capacity-or-counterfeit` high; 101 -> `damaged` -> hypothesis `nand-degradation` medium; exit 1 -> `inconclusive`; exit 103 with "Good news" text -> `inconclusive (code/text disagree)`.
- C23 f3read exit 0 with Data LOST zero -> `pass`; exit 1 with non-zero Overwritten -> `fail`, hypothesis fake-capacity medium; f3write `No space!` -> `inconclusive (nothing written)`.
- C24 Same file ingested twice -> one evidence id. `ingest attested` without `--file` -> exit 2.
- C25 `assess` stores an assessment with rules_version and the snapshot/evidence ids used; running it twice with no new inputs yields identical output.

## Pros / cons vs alternative
Chosen: hand-written first-match rule list with declared required fields.
- Pros: deterministic, explainable per evidence item, each rule maps to a cited research line, trivially testable from fixtures.
- Cons: rule order is a design decision that must be justified; new device behaviours need code edits.
Alternative: weighted score (sum of signal weights -> verdict band).
- Pros: smoother handling of mixed signals. Cons: weights would be invented numbers without sources, verdicts become hard to explain and to freeze in tests. Rejected.

## Not Worth Doing If
- The F3 sample-output step is not worth doing if F3 docs contain no example output for a tool; then that parser ships tested only on researcher-03 quoted lines (state it in SOURCES.md) instead of hunting other sites.

## Risk Assessment
- Rule order wrong for a mixed case -> C1-C17c freeze the intended order (Q5 decided 2026-10-19).
- Default `--risk-tolerance medium` decides the common case; SKILL.md Phase 0 must ask the operator for data value and risk tolerance (see plan.md open question).
- Wear direction inferred from names -> confidence low, devstat preferred.
- F3 output format drift between versions -> exit code is the primary signal; text only cross-checks.

## Security Considerations
- Parsers treat input files as untrusted: size limit parameter, no eval, line-oriented parsing, malformed -> error with line number.

## Next Steps
- Phase 04 uses triage class, constraints, health and ingested evidence for gate and verdict decisions.
