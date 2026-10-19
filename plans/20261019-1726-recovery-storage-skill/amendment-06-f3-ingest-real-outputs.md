# Amendment 06 (2026-10-20): F3 ingest from real F3 8.0 outputs

Approved by the user on 2026-10-20 ("Làm và commit"). Spec for `test-designer` (tests first) and the implementer.
Changes the frozen spec (phase 03 C23 f3read / f3write parsing; phase 04 D22 f3read form); tests and CONTRACT.md are
amended by `test-designer`, code by the implementer.

## Origin (real runs 2026-10-19, WSL2 Ubuntu 22.04, F3 8.0, volume mounted via drvfs)

Five real outputs, now verbatim fixtures under `recovery-storage/scripts/tests/fixtures/f3/` (fixtures/SOURCES.md):
- `f3read-stick-pass.txt`: stick D-564ce922bda3, exit 0, Data OK 15724108 sectors, Data LOST 0 (pass).
- `f3read-stick-abort134.txt`: same stick, exit 134, assertion `size % SECTOR_SIZE == 0` on a partial last file, no
  summary.
- `f3write-stick-volume-full.txt`: same stick, exit 0, `Write failure: Input/output error` on the last file exactly when
  the volume became full (drvfs returns EIO instead of ENOSPC), final `Free space: 0.00 Byte`.
- `f3read-card-lost.txt`: 32 GB card D-2bc2a1f8a798, exit 0, Data OK 592999 sectors, Data LOST 7079816 sectors (all
  corrupted, 0 overwritten). Before this amendment `rs.py ingest f3read ... --exit-code 0` recorded `inconclusive (exit
  code 0 / summary not parsed)`: wrong.
- `f3write-card-removed.txt`: same card, files 1-3 OK, `Write failure` in file 4, `Can't create file 5.h2w` (the
  operator removed the card mid-run), exit 0.

Fact: f3read 8.0 exits 0 even when data is lost. The claim "f3read exits 1 on any bad sector" (phase-03 Requirements
"exit code (0 pass, 1 bad)", references/authenticity-f3-h2testw.md) is wrong for 8.0.

## F1. f3read result from the parsed summary

- Data LOST > 0 -> `fail`; the reason names the lost bytes and the corrupted / changed / overwritten split.
- Data LOST == 0 and Data OK > 0 -> `pass`.
- No parsable summary -> `inconclusive`, whatever the exit code (exit 134 case, and exit 0 without a summary).
- A non-zero exit code with a summary is recorded (`exit_code`) but does not flip the summary result (reading fixed
  here: the summary is printed only after every file was validated, so it is the measurement).
- Parsed bytes: `data_ok_bytes`, `data_lost_bytes`, `corrupted_bytes`, `changed_bytes`, `overwritten_bytes` (sectors x
  512).

## F2. f3write failure when the volume became full

- `Write failure` or `Can't create file` with the final `Free space: 0.00 Byte` (the volume became full): `inconclusive`,
  reason "write error when the volume became full (a filesystem-full error reported as I/O error, e.g. WSL drvfs);
  verify with f3read".
- `Write failure` with free space left > 0: `fail` as today. Reading fixed here: no final `Free space` line (the card
  was removed mid-run) is not the volume-full case -> `fail`.

## F3. Verdict

- The card's fail record never satisfies capacity verify (PASS refused `capacity-verify-missing`).
- The stick's pass record still does (Data OK 8050743296 of 8054112256 B >= `verdict.CAPACITY_COVERAGE` x bytes).

## F4. Unblocked tests

- `test_C23_f3read_exit0_data_lost_zero_pass`, `test_D22_f3read_pass_covering_90pct_after_gate_pass`,
  `test_D22_f3read_before_gate_evidence_before_recovery`, `test_D22c_f3read_ingested_inside_the_verification_gate_passes`
  (amendment 04 Q5) now run on the real pass fixture.
- New: the nvme below-coverage case of amendment 02 F (8 GB verified on a 1 TB NVMe is not a read verify).
- Still BLOCKED: f3read with non-zero Overwritten (C23 fake-capacity hypothesis); the ssd-sata / external-ssd and
  at/above-coverage halves of amendment 02 F.

## F5. Evidence parsed by an older parser (added 2026-10-20, same approval)

The real card f3read evidence (E-0fa5fe3226ed in the live store) was ingested under the old parser and stores parsed
result `inconclusive`; `rs.py ingest f3read` on the same file returns the existing row (sha256 dedup) with the old
result.
- Decision: re-parse on read. Wherever evidence is read (verdict, report, assess, and the row returned by a dedup
  re-ingest of the same bytes), the parse comes from the current parser applied to the stored blob and its stored exit
  code; a stored parsed copy is a cache, never trusted. The stored blob, `sha256` and evidence id never change; a
  re-ingest of the same bytes does not create a row.
- Context only (no contract change): on the card, data beyond about 295 MiB is unstable (zeros on small raw reads,
  pseudo-random on large reads); belongs in the session notes.

## Open questions (not decided; not asserted)

- Q1. Which hypothesis a corrupted-only f3read fail (card) raises (nand-degradation vs fake-capacity) is not specified.
- Q2. Data LOST == 0 and Data OK == 0 (empty volume) -> not pass; inconclusive or fail is not asserted.
- Q3. Whether an f3write `inconclusive` (volume full) or `fail` record should block PASS when an f3read pass exists is
  not changed (today: the f3read pass decides; asserted only for the inconclusive case of the real run).
- Q4. Docs: references/authenticity-f3-h2testw.md exit-code text (coordinator follow-up).
