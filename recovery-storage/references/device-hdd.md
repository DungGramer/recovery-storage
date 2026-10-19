# HDD (internal SATA and the disk inside external enclosures)

Read SMART first (`rs.py collect`), assess, and image before anything that writes when data matters. Signal
meanings: [health-signals](health-signals.md). Exact thresholds: `rs.py rules`.

Key points:
- Rising reallocated / pending / offline-uncorrectable counters between two snapshots mean active degradation:
  image once, do not run repeated full reads or long tests first.
- Many failing drives show clean SMART; a healthy verdict is never stronger than medium confidence.
- A sleeping drive is not spun up by `collect` (`-n standby`); `--allow-spinup` is a deliberate choice.
- Clicking, beeping, repeated spin-up or a drive that does not spin: stop (spec rule 9). Do not stress test.
- Never run `chkdsk /r`, `fsck` repair or write-mode `badblocks` on a drive that holds needed data or shows I/O errors.

### Method: Short SMART self-test
- Preconditions: drive readable; no mechanical symptom; data either secured or the test accepted as low risk.
- Risk: R1 (gate kind: smart-selftest-short)
- Tool: `smartctl -t short <confirmed path>` (smartmontools 7.x), then `rs.py collect` to read the log
- Expected result: "Completed without error" in the self-test log; counters unchanged.
- Stop criteria: noise, heat, disconnect, or counters rising during the test (abort with `smartctl -X`).

### Method: Extended SMART self-test
- Preconditions: as short test; time available (hours on large disks); not before imaging a failing disk.
- Risk: R1 (gate kind: smart-selftest-long)
- Tool: `smartctl -t long <confirmed path>`, then `rs.py collect`; PASS for an HDD needs a completed test newer than the
  post-recovery window start
- Expected result: completed without error and no new failed entry; delta of media counters stays flat.
- Stop criteria: read failure in the log, rising counters, mechanical symptoms.

### Method: Read-only surface scan
- Preconditions: data secured or no data; drive stable; scan time accepted.
- Risk: R1 (gate kind: badblocks-readonly)
- Tool: `badblocks -sv <confirmed path>` (read-only mode, Linux) or a full ddrescue read to a sink
- Expected result: no bad blocks reported; re-collect shows no counter growth.
- Stop criteria: read rate collapsing, errors clustering, noise or heat.

### Method: Destructive write test (device reuse only)
- Preconditions: no data needed (data-state not-needed or waived); goal device-recovery; HDD only.
- Risk: R2 (gate kind: badblocks-write)
- Tool: `badblocks -wsv <confirmed path>`; never on SSD or flash (wear, no meaning for remapped NAND)
- Expected result: no errors; a later `rs.py collect` shows reallocations stable.
- Stop criteria: any error or growth in reallocated/pending counters: retire the drive instead of retrying.
