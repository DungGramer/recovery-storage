# Amendment 08 (2026-10-20): f3read run time from the log's mtime

Approved by the user on 2026-10-20 ("Làm nốt Amendment 07 Q2"). Spec for `test-designer` (tests first) and the
implementer. Closes amendment 07 Q2.

## Problem

Amendment 07 G1 orders events by ingest time and observation time. The CLI cannot see when f3read actually ran, so an
f3read log produced before the replug but ingested after it satisfies G1.

## H1. output_mtime

`ingest f3read` and `ingest f3write` record the source file's modification time as `output_mtime` (UTC, store
timestamp format `YYYY-MM-DDTHH:MM:SS.ffffffZ`). Decision: a sibling of `parsed`, not inside it: `parsed` is re-parsed
from the blob on every read (amendment 06 F5) and the blob does not carry the mtime. JSON: `evidence.output_mtime`;
store: key `output_mtime` in the evidence row's JSON document next to `parsed`. The mtime is set when the tool's
redirected output is closed, i.e. at the end of the run.

## H2. f3read moment

G1 uses the f3read moment = min(ingest ts, output_mtime) when output_mtime is present: the after-replug observation
must lie after the anchor and before that moment. A log whose output_mtime is before the replug is refused
`f3read-not-after-replug` even if ingested after the replug. An output_mtime later than the ingest ts (clock skew or a
touched file) is ignored and the ingest ts is used (min() gives the same result). The anchor is unchanged (amendment 07:
f3write ingest ts / gate confirm / window start).

## H3. Old rows

Rows ingested before this amendment (no output_mtime) keep the amendment 07 behaviour (ingest ts). The file is never
re-stat'ed after ingest.

## H4. Residual limitation (docs, not tested)

Copying a log without preserving mtime (plain `cp`) moves output_mtime to the copy time, which can only make the moment
later (min with the ingest ts); the playbook says to use `cp -p` or write the log directly to the path that is
ingested. A log edited or touched after the run is not detected.

## Frozen tests amended

`test_verdict.py` helper `ingest_f3` now ingests a temp copy of the fixture (bytes unchanged) whose mtime is the current
test-clock time, i.e. the log is written when it is ingested; before, the frozen fixture's checkout mtime (earlier
than the test's replug) made H2 refuse correctly. Purpose of every caller unchanged; the four PASS tests this fixes:
`test_D22_f3read_pass_covering_90pct_after_gate_pass`, `test_D22e_verdict_uses_the_current_parser_not_the_stored_parse`,
`test_D22c_f3read_ingested_inside_the_verification_gate_passes`,
`test_D22f_no_f3write_ingested_anchor_is_the_gate_confirm[replug-then-f3read-True]`. No other test or scenario ingests
f3read / f3write and then expects PASS (scenarios use attested H2testw; test_ingest_f3.py never calls `verdict set`).

## Open questions

- Q1. Whether f3write's output_mtime should replace its ingest ts as the G1 anchor (it is only recorded here).
