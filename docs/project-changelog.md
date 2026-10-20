# Changelog: recovery-storage skill

Format: newest first. Versions are semantic and assigned retroactively (no version is declared in the skill). Roadmap: [project-roadmap.md](project-roadmap.md).

## [0.9.1] - 2026-10-21 - Amendment 10 (guard hook clock)

Spec: [amendment-10](../plans/20261019-1726-recovery-storage-skill/amendment-10-guard-hook-clock.md). Rules version unchanged.

### Fixed
- `guard_hook.py` reads time through one `_now()`; frozen tests pin it. Six guard tests built open gates on the fixed `FakeClock` date and went red 12 h later by the wall clock alone (2026-10-20 12:00Z). The 12 h open-gate limit is now specified and tested.
- Frozen files re-hashed over their git blob bytes (59 were CRLF in the working copy; manifest entry `eol-lf`).

## [0.9.0] - 2026-10-20 - Amendment 09 (event attribution by drive letter)

Spec: [amendment-09](../plans/20261019-1726-recovery-storage-skill/amendment-09-event-attribution-by-nearest-letter-holder.md). Rules version `2026.10.20-8`.

### Fixed
- An OS event naming a drive letter belongs to the device whose observation showing that letter is nearest in time (any session); a tie goes to nobody. Drive letters are reused across media: a 32 GB card's 25 Ntfs 55 events on E: were evidence on a later 4 GB card (real run 2026-10-20). Applies to assess hypotheses and report section 3.

## [0.8.0] - 2026-10-20 - Amendment 08 (f3read run time)

Spec: [amendment-08](../plans/20261019-1726-recovery-storage-skill/amendment-08-f3read-run-time.md). Rules version `2026.10.20-7`.

### Fixed
- `ingest f3read` / `f3write` record the log file's modification time (`output_mtime`); the replug rule dates the f3read by the earlier of ingest and log mtime, so a log written before the replug but ingested after it no longer passes. Rows without `output_mtime` keep the ingest time. Residual limitation: a log copied without keeping its mtime carries the copy time (playbook: write the log to the ingested path or `cp -p`).

## [0.7.0] - 2026-10-20 - Amendment 07 (f3read after replug)

Spec: [amendment-07](../plans/20261019-1726-recovery-storage-skill/amendment-07-f3read-after-replug.md). Rules version `2026.10.20-6`.

### Fixed
- An f3read pass counts for PASS (flash capacity verify, SSD read verify) only with an `inventory --after-replug` observation between the last f3write ingest (else the verification gate confirm, else the window start) and the f3read ingest; otherwise `f3read-not-after-replug`. Real runs read the Windows host cache through WSL drvfs (158-276 MB/s against 17 MB/s from the card).
- f3write: a write error with less than one 1 MiB f3 block left is "volume became full" (`inconclusive`); F3 sizes parsed 1024-based with units.
- f3probe: the tab-indented `*Usable* size:` line is parsed.

### Added
- f3read `read_rate` (informational) in evidence and the report; real fixtures: card partition cached / after-replug reads, full-volume write at 4.00 KB, f3probe limbo.

## [0.6.0] - 2026-10-20 - Amendment 06 (F3 ingest from real outputs)

Spec: [amendment-06](../plans/20261019-1726-recovery-storage-skill/amendment-06-f3-ingest-real-outputs.md). Rules version `2026.10.20-5`.

### Fixed
- f3read result comes from its summary: f3read 8.0 exits 0 even with lost data, so a real counterfeit card was recorded `inconclusive`; now Data LOST > 0 is `fail` (corrupted / changed / overwritten bytes parsed), no summary is `inconclusive` whatever the exit code.
- f3write: a write error when the volume became full (WSL drvfs reports it as I/O error) is `inconclusive`, not `fail`.
- Evidence is re-parsed with the current parser from its stored blob wherever it is read (verdict, report, assess, re-ingest); stored parsed copies from older parsers no longer decide.

### Added
- Real F3 8.0 fixtures (`tests/fixtures/f3/`): stick pass, abort 134, volume-full write error, card with lost data, card removed mid-run.
- Playbook: f3probe from Windows through usbipd-win + WSL (kernel with usb-storage).

## [0.5.0] - 2026-10-20 - Amendment 05 (report fixes)

Spec: [amendment-05](../plans/20261019-1726-recovery-storage-skill/amendment-05-report-fixes.md). Rules version `2026.10.20-4`.

### Fixed
- `--redact` no longer masks report vocabulary after `serial:` ("serial: not reported" stayed "serial: **** reported").
- Session notes appear in report section 3 as `[ATTESTED]` items with who and timestamp, for every device of the session.
- After PASS / PASS_LIMITED, items of an assessment older than the verdict show `resolved by verdict <STATUS>` instead of their next tests; section 11 drops the stale next step. An `assess` after a verdict is a new assessment (the latest verdict is part of the inputs key).
- `assess`: a hypothesis backed only by `session.*` evidence drops to `low` once the source was written in this session.
- A verdict recorded while the latest observation has no medium or a weak match applies to the card in the reader: the report says so, and `device list` no longer shows it as the reader's status.
- Hypothesis evidence: identical path + value items are merged with a `count` (`(xN)` in text); one item per matching OS event repeated it before.

## [0.4.0] - 2026-10-19 - Amendments 03 and 04 (real-device run)

Specs: [amendment-03](../plans/20261019-1726-recovery-storage-skill/amendment-03-real-run-card-reader.md), [amendment-04](../plans/20261019-1726-recovery-storage-skill/amendment-04-verification-gate-window.md). Rules version `2026.10.19-3`.

### Fixed
- Card reader present with no medium (`no_media`), symptom `not-detected` and at least 2 distinct isolation steps now triages `HARDWARE_DIAGNOSIS_REQUIRED` (`T2a-not-detected-isolated`) instead of "insert or reseat the card"; the T5 no-media text lists the isolation steps not yet recorded (rules -2).
- PASS evidence window: a successful verification gate counts from its confirm, so f3read / h2testw evidence ingested inside it counts; before, the run-ingest-close flow could never reach PASS (`evidence-before-recovery`) (rules -3).

### Added
- `--tried reseat-media` and `--tried other-reader` (removable-media isolation).
- Playbooks: re-create a flash device's partition table (clear-disk, partition-write, format) when Windows builds no partition volume (MBR plus stale GPT header); F3 through WSL drvfs; reader drops off USB when a faulty card is inserted.

## [0.3.0] - 2026-10-19 - Amendment 02 (review round 2)

Spec: [amendment-02](../plans/20261019-1726-recovery-storage-skill/amendment-02-review-round-2.md). Commit f32e84f.

### Security
- Identity changes only by the operator: `gate close` never changes a fingerprint. A device not found exactly closes the gate with `identity_drift` and a `drift_reason` (`media-id-changed` or `device-changed`), and prints the `device link` command.
- `device link <observation> <device>` / `--new` (existing since phase 02) now requires the operator console. A link to a device with different hardware is refused (`hardware-mismatch`). A link clears drift on earlier closed gates.
- `--reason`, `--note`, `--file`, `--home` values containing unsafe shell characters are refused (`unsafe-characters`, exit 2) before anything is stored, because they are echoed into operator commands.
- Guard tokenizer rewritten: per-wrapper value-flag tables (sudo, env, xargs), assignment prefixes skipped, `command -v` never executes, heredoc bodies and multi-line quoted text ignored, `cp`/`tee`/`pv` judged by write target, `&>` and `>&` as redirects, device targets extended to `/dev/disk/by-*`, `/dev/mapper/*`, `/dev/md*`, `/dev/dm-*`, `/dev/loop*`.

### Fixed
- Last write tracked across sessions (`last_write_ts`, including confirmed-then-aborted write gates). A secured or waived data state older than the last write no longer counts (`data-not-secured`). Verdict window starts at the later of session start and last write.
- `secured --evidence` requires a closed, successful `image-ddrescue` gate in this session with evidence ingested after its confirmation (`image-gate-missing`).
- `collect` and gate snapshots attach smartctl results only when the answering identity matches (including the `-d sat` retry); otherwise `identity-conflict` and nothing stored.
- ATA self-test `lifetime_hours` 16-bit wrap handled when deciding the verdict window and ordering entries; the status nibble is read correctly.
- SSD, NVMe and external SSD read verify via f3read needs coverage at or above `verdict.CAPACITY_COVERAGE`.

## [0.2.0] - 2026-10-19 - Amendment 01 (operator console, full-coverage mapfiles)

Spec: [amendment-01](../plans/20261019-1726-recovery-storage-skill/amendment-01-operator-console-and-mapfile-coverage.md). Commit f32e84f.

### Security
- `gate confirm`, `session data-state` (`waived`, `secured --attested`, `not-needed`) and `ingest attested` require a human at an interactive console. `--phrase` removed. No console gives exit 3 `operator-console-required` with the command to run; a wrong answer gives `wrong-phrase` or `operator-declined`. Audit rows record `confirmed_by` / `who`; the report marks `[ATTESTED by operator]`.

### Fixed
- A ddrescue mapfile counts as a complete image only if it starts at 0, is contiguous, ends at the device byte count, has status `+` and no bad or untried bytes. Refusal reasons: `image-incomplete`, `image-not-contiguous`, `image-does-not-cover-device`. Applies to `secured` and to SSD/NVMe read verify.
- `parse_mapfile` now returns `start`, `end` and `contiguous`.

## [0.1.0] - 2026-10-19 - Initial skill

Commit d8990a5. Plan phases 01-08; frozen suite green on Python 3.12.

### Added
- CLI `scripts/rs.py` with `--json` and `--home`; a single guarded runner with an allowlist, timeout and recorded tool/version/argv/exit; sha256-frozen PowerShell scripts.
- SQLite store with evidence files hashed in the DB; sessions with data value and risk tolerance.
- Device identity (Windows and Linux parsers, smartctl normaliser, exact/probable/weak/ambiguous matching), `inventory`, `collect`, `ingest smartctl`.
- Health verdict, delta, risk-based triage, hypotheses, ddrescue and F3 parsers, `assess`, `ingest`.
- Gate state machine (open, confirm, close, abort), action catalog, R2 lock, data-rescue state, evidence-based `verdict` that refuses PASS without evidence.
- Report with `--check`, `device list/show`, `compare`.
- SKILL.md orchestrator, playbook references, `rs.py rules`.
- Cross-phase scenarios and install hardening.
- Skill-scoped PreToolUse guard hook denying matched destructive commands unless a gate is open; fails open with a visible warning if the script is missing.
