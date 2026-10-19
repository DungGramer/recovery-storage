# Health signals: what they mean (exact thresholds: `rs.py rules`)

This file explains signals for reasoning. The numbers the rules use live only in code and are printed by:

```
rs.py rules
```

Strength of evidence:
- Strong: overall SMART status FAILED; a pre-fail attribute at or past its threshold; growth of reallocated,
  reported-uncorrectable, pending or offline-uncorrectable counters between two valid snapshots; NVMe critical
  warning (spare, media read-only, reliability, persistent memory); spare below its threshold; growing NVMe media
  errors; a self-test read failure.
- Medium: non-zero media counters that are stable; endurance consumed or nearly consumed.
- Weak / context: temperature; interface CRC and command timeout counters (cable, port, power, bridge); NVMe error
  log entry count (often benign); historical bits in the smartctl exit status.

Reading rules of thumb:
- A clean report is not proof of health: Backblaze found a large share of failed drives without any of the five key
  counters raised. Healthy is never stated with high confidence; it always carries a next test.
- Growth outranks absolute values: compare snapshots (`rs.py compare --device <dev>`). A comparison is invalid when
  the identity differs or power-on hours go backwards; then no delta is used.
- Missing data stays unknown: USB sticks, SD cards and many bridges expose no SMART; `needs_elevation` and
  `unsupported_bridge` are environment facts, never device faults.
- Interface CRC errors point at the link, never at the media.
- Wear on SATA SSDs: vendor attributes disagree; only names that say remaining/left are read (whitelist in
  `rs.py rules`), device statistics are preferred.
- TBW is a datasheet number; host writes are computed from the device counters.

Unverified items (not used by any rule):
- HDD temperature bands from forums or vendor marketing [UNVERIFIED]; the rules only use limits the device itself
  reports.
- Seagate packed raw encodings for some attributes [UNVERIFIED]; raw values are compared only as deltas of the same
  drive.
- Windows storage event ids other than Ntfs 55 [UNVERIFIED]; events are context, only Ntfs 55 gets a tag.
- Generic/duplicated serial lists for counterfeit sticks [UNVERIFIED]; serial trust is structural only.

### Method: Track a device over time
- Preconditions: two or more snapshots of the same device (any sessions).
- Risk: R0 (gate kind: none)
- Tool: `rs.py compare <snapA> <snapB>`, `rs.py compare --device <dev>`, `rs.py device show <dev>`
- Expected result: per-field deltas, or "INVALID COMPARISON" with the reason.
- Stop criteria: counters rising within one session: stop repeated reads, reassess (triage may become hardware).
