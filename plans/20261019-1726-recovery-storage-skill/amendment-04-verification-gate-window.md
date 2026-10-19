# Amendment 04 (2026-10-19): verification gates and the PASS evidence window

Requested by the orchestrating agent after a real-device run on 2026-10-19; approved by the user on
2026-10-19. Spec for `test-designer` (tests first) and the implementer. Changes the
frozen spec (amendment 02 B "Verdict window start"); tests and CONTRACT.md are amended by `test-designer`, code by the
implementer.

## Origin (real-device run 2026-10-19, USB stick D-564ce922bda3)

Gate `f3write-f3read` opened and confirmed -> f3write + f3read ran -> `rs.py ingest f3read` (pass, Data OK 8050743296
of 8054112256 bytes) -> `rs.py gate close <gate> --outcome success --evidence <id>`. Then `verdict set ... PASS` is
refused `evidence-before-recovery`: the close of that writes-source gate is the device's last write (amendment 02 B:
window start = max(session start, `last_write_ts`)) and the f3read evidence was ingested before the close. The
documented flow (run tool, ingest, close) can never reach PASS; evidence dedup by sha256 also prevents re-ingesting
after the close.

## B1. Verification kinds

- Verification kinds: `f3write-f3read`, `h2testw`, `f3probe`, `f3probe-destructive` (writes-source gates whose writes
  ARE the capacity test).
- PASS evidence window: a closed gate of a verification kind with outcome `success` contributes its `confirmed_ts` to
  the window start (not its close). Capacity evidence (f3read, f3probe, attested h2testw) ingested after that confirm
  counts toward PASS.

## B2. Other write kinds unchanged

`format`, `partition-write`, `clear-disk`, `fs-repair-on-source`, `badblocks-write`, `firmware-update`,
`mptool-reflash`: the close (or the abort after confirm) is the window start; evidence ingested before it ->
`evidence-before-recovery` (existing D22 / D22b tests unchanged).

## B3. No credit without success

A verification gate closed `failed` / `interrupted`, or aborted after confirm: its close / abort is the window start,
as today.

## B4. Data state unchanged

`secured` / `waived` count only when recorded after the last write; for a verification gate the last write is still
its close (the writes happened). Only the PASS evidence window changes.

## B5. Later writes still move the window

A later non-verification write (e.g. a format after the F3 gate) moves the window past the F3 evidence again ->
`evidence-before-recovery`.

## B6. Evidence before the confirm

Evidence ingested before the verification gate was confirmed (before open, or between open and confirm) does not
count.

## Open questions (not decided by this amendment; tests skipped or not asserted)

- Q1. Does B1 also move the observation window (>= 2 observations, one `--after-replug`) to the confirm? F3 guidance
  replugs between f3write and f3read, i.e. inside the gate. The tests replug after the close (passes either way).
- Q2. f3probe evidence is named a capacity kind here, but the phase-04 USB matrix lists only f3read (>= coverage) or
  attested H2testw as PASS items. This amendment changes the window, not the matrix; f3probe-good alone is not asserted
  as PASS.
- Q3. Two successive successful verification gates: the window start is the later confirm (max rule)? Not asserted.
- Q4. `badblocks-write` (hdd only) is not exercised by the stick tests; the B2 rule is asserted on the six other kinds.
- Q5. f3read evidence: no real f3read output with Data OK amounts is a fixture; the f3read form of B1 stays BLOCKED.
  The raw (redacted) f3read output of this real run would unblock it and the older D22 f3read skips.
