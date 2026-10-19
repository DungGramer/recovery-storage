# Amendment 05 (2026-10-20): report fixes (redaction, notes, stale hypotheses, verdict on a card reader)

Approved by the user on 2026-10-20 ("Sửa tiếp 4 lỗi báo cáo"). Spec for `test-designer` (tests first) and the
implementer. Changes the frozen spec (phase 05 report, fleet views; phase 03 hypothesis confidence); tests and
CONTRACT.md are amended by `test-designer`, code by the implementer.

## Origin (real reports, 2026-10-19)

`rs.py report <sid> --device <dev> [--redact]` on the real store, sessions S-81ff60a59449 (USB stick, PASS) and
S-4fdc1ba07b90 (microSD in a USB reader, RETIRED). Four defects:

## R1. Redaction corrupts report text

`--redact` turns "serial: not reported (trust absent)" into "serial: **** reported (trust absent)": the serial
pattern hits the word "not".
- Redaction masks only real identifier values (serials, EUI-64 / WWN, GUIDs, host names, home path / user name) as
  today. Fixed report vocabulary ("not reported", "none", trust words, tags, gate / verdict / evidence wording) is
  never masked. A device with a real serial still gets it masked (E6 unchanged).
- Every redaction pattern is checked against all fixed report words, not only "not".

## R2. Session notes missing from the report

`rs.py session note <sid> <text>` never appears in the report.
- Notes recorded in the session appear in section 3 "Triệu chứng và bằng chứng", tagged `[ATTESTED]`, with who and
  timestamp, in time order.
- With `--redact` they pass through the same redaction. Notes from other sessions do not appear.

## R3. Stale hypotheses after recovery

After PASS the report still lists the pre-recovery hypothesis `partition-or-filesystem` (evidence now only
`session.symptoms`) and its next test "image or read-only inspect, then capacity verify after data is secured" as
current; section 11 repeats the pre-verdict next step.
- Decision (a): when the effective verdict of the session/device is PASS or PASS_LIMITED, items of an assessment made
  before that verdict are kept in section 4 for history but marked `resolved by verdict <STATUS>`, and none of that
  assessment's next tests (triage and hypotheses) is shown in section 4 or 11. An assessment made after the verdict is
  current and shown as today. FAIL / REPAIR_REQUIRED / UNRESOLVED / RETIRED leave the items open.
- Decision (b): a hypothesis whose every evidence item is an operator statement (`session.*`), in an assessment of a
  device written in this session (`last_write_ts(device)` later than the session start), has confidence `low` (the
  category is kept, not dropped). Before the write, and for symptoms recorded in a session that starts after the
  write, confidence is as today.

## R4. Verdict on a medium without its own identity is attached to the reader

microSD in a USB reader: the device record is the reader ("Generic STORAGE DEVICE", 0 bytes, `no_media`, match weak);
RETIRED recorded on it would become the reader's effective status in later sessions and fleet views.
- (a) A verdict recorded while the device's latest observation is `no_media` or has match `weak` (card reader) is
  scoped to the medium of that session: shown in that session's report and `verdict show`, not the reader's status in
  later sessions or fleet views (`device list` verdict column, `--group-by status`).
- (b) The report wording for such a verdict says it applies to the card in the reader, not the reader.
- A verdict on a device with its own identity (exact / probable match, medium present) is unchanged.

## R5. Duplicate hypothesis evidence items (added 2026-10-20, same approval)

Real `rs.py assess` on a RAW NTFS card printed `observation.events.fs_corruption=Ntfs 55` 17 times in one hypothesis
(one per matching System event).
- Identical evidence items (same path and value) appear once per hypothesis, with a count when more than one (e.g.
  `observation.events.fs_corruption=Ntfs 55 (x17)`), in `assess` text, `assess --json` and the report.
- A single item carries no count marker.

## Open questions (not decided; not asserted)

- Q1. R4 scope decided when the verdict is recorded, or recomputed from the latest observation at display time? The
  fixtures cannot tell them apart.
- Q2. R3 (b) "only remaining evidence": read here as "symptom-only after a write in this session"; the alternative
  reading "an earlier assessment had non-session evidence that is gone" is not asserted.
- Q3. R3 (a) when the PASS is later superseded by a non-PASS verdict, or PASS in another session: per session/device
  effective verdict only (as `verdict show`).
- Q4. R4 for a scoped verdict: does `device show` history still list it (as history)? Not asserted (history is not a
  status).
- Q5. Fixed vocabulary is checked on two real-run report shapes (stick PASS, empty reader RETIRED); words that only
  other flows print are covered by the rule, not by a test.
- Q6. R5 strength of the merged item when the duplicates differ in strength (they do not in any fixture), and items
  with the same path but different values (must stay separate; no fixture yields one) are not asserted.
