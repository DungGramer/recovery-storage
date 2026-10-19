# Amendment 07 (2026-10-20): f3read counts only after a replug; full volume below one f3 block

Approved by the user on 2026-10-20 ("Làm và commit"). Spec for `test-designer` (tests first) and the implementer.
Changes the frozen spec (amendment 06 F2; phase 04 PASS matrix f3read item; amendment 04 window); tests and CONTRACT.md
are amended by `test-designer`, code by the implementer.

## Origin (real runs)

- An f3read run right after f3write without unplugging reads from the Windows host cache through WSL drvfs: stick
  2026-10-19 f3read 275.95 MB/s (a PASS was recorded on it); card 2026-10-20 f3read 158.61 MB/s on a 294 MiB
  partition; after an operator replug the same card read at 17.38 MB/s. F3 docs advise unplugging between f3write and
  f3read.
- On the card's FAT32 partition f3write hit the drvfs full-volume EIO with final `Free space: 4.00 KB` (less than one
  1 MiB f3 block), so amendment 06 F2 (exactly `0.00 Byte`) recorded `fail`.
- Real f3probe on the card: exit 102, counterfeit of type limbo, usable 294.90 MB of announced 30.16 GB.

New real fixtures (verbatim, fixtures/SOURCES.md `f3/`): `f3write-card-partition-full4k.txt`,
`f3read-card-partition-cached.txt`, `f3read-card-partition-after-replug.txt`, `f3probe-card-limbo.txt`.

## G1. f3read after a replug

An f3read pass counts as capacity verify (flash PASS), SSD read verify, and inside the amendment 04 window, only if the
device has an after-replug observation (`inventory --after-replug`, match exact / probable / linked, same bytes)
whose ts lies after the anchor and before the f3read ingest. Anchor (decided): the last f3write ingest of that device
in the session before the f3read ingest; else the confirm of the verification gate the f3read was ingested in; else
the PASS evidence window start (amendment 04). Otherwise PASS is refused with the new reason
`f3read-not-after-replug`, named in the refusal. Attested H2testw is unchanged (no replug-order rule: H2testw runs on
the Windows host and the operator attests the result).

Consequence (amendment 04 Q1 resolved): observations taken inside a verification gate (after its confirm) count for
the PASS observation window; the documented flow is confirm -> f3write -> ingest f3write -> replug (`inventory
--after-replug`, `inventory`) -> f3read -> ingest f3read -> close.

Frozen tests amended for the G1 order (replug before the f3read ingest, purpose unchanged):
`test_D22_f3read_pass_covering_90pct_after_gate_pass`, `test_D22c_f3read_ingested_inside_the_verification_gate_passes`,
`test_D22e_verdict_uses_the_current_parser_not_the_stored_parse` (amendment 06 F5). Every other test that ingests an
f3read either expects a refusal (`test_D22_f3read_before_gate_evidence_before_recovery`, `test_D22d_*`, `test_D24c_nvme_*`,
the G1 refusal cases) or never calls `verdict set`; no scenario ingests an f3read.

## G2. Read rate

The f3read parse records `read_rate`, the text after `Average reading speed:` (e.g. `17.38 MB/s`), None without the
line. Informational, no rule; the report shows it.

## G3. f3write full volume

Write failure (`Write failure` / `Can't create file`) with a final free space below 1 MiB (one f3 block) ->
`inconclusive` (volume became full); >= 1 MiB -> `fail`. Units Byte / KB / MB / GB are binary (F3 prints 1024-based
sizes: 15724108 sectors = 7.50 GB). Boundary decided: `1.00 MB` = 1 MiB = not below -> `fail` (the amendment 06 derived
fixture `f3write-stick-volume-full.free1mb.derived.txt` stays `fail`). No final free-space line stays `fail`
(amendment 06 reading).

## G4. Existing verdicts

PASS verdicts recorded before this rule are not rewritten (no migration; `verdict show` keeps them). `verdict set PASS`
again is refused when the evidence fails G1.

## f3probe real sample

The real limbo output fills the f3probe real-sample gap. Phase-03 "Parse `*Usable* size:` / `Announced size:` when
present": the real lines are tab-indented and must be parsed (`usable_size`, `announced_size` text).

## Open questions (not decided; not asserted)

- Q1. G4 cannot be exercised without a store written by the old code; check by hand on a copy of the live store
  (session S-81ff60a59449 keeps PASS in `verdict show`; `verdict set PASS` again refused `f3read-not-after-replug`).
- Q2. The order is judged by ingest and observation times; the tool cannot see when f3read actually ran. An operator
  who ingests late can still satisfy G1 without a real replug.
- Q3. Whether the after-replug observation must also fall inside the PASS window when the anchor is a confirm earlier
  than a later write (a later write already moves the window, amendment 04 B5): not asserted separately.
- Q4. SSD read verify by f3read with G1: no attached SSD fixture reaches the coverage, so only the flash path is
  asserted.
