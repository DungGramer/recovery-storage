# SATA SSD and NVMe

smartctl 7.x is the collector on Windows and Linux (NVMe needs no admin on Windows, verified on this project's
machine). Signal meanings: [health-signals](health-signals.md); thresholds and the wear whitelist: `rs.py rules`.

Key points:
- NVMe critical warning bits, available spare against its threshold, media and data integrity errors, and
  percentage used are read directly from the health log; percentage used is not capped at the rated endurance.
- SATA SSD wear: the device statistics "Percentage Used Endurance Indicator" is preferred; attribute names are read
  as "% remaining" only when the smartctl name says remaining/left; other wear rows stay unknown.
- TBW is a datasheet value; host writes are computed (NVMe data units of 512000 bytes, SATA logical sectors written
  times sector size) and compared with the vendor TBW only if the operator supplies it.
- TRIM: data deleted on an SSD is generally not recoverable by software (vendor-lab position); recover from images
  or backups, not by scanning free space.
- A drive that reports a controller safe-mode identity (for example `SATAFIRM S11`, 0 or few MB) or an NVMe media
  read-only bit is a controller case: do not initialise, format or update firmware; see
  [controller-mptool](controller-mptool.md).

### Method: Read health and error logs
- Preconditions: device enumerated.
- Risk: R0 (gate kind: none)
- Tool: `rs.py collect <dev> --session <sid>` (smartctl -j -x), `rs.py assess <sid> <dev>`
- Expected result: health verdict with evidence; wear and host writes when exposed.
- Stop criteria: device drops off the bus during collection: record `disconnects-repeatedly`, do not loop.

### Method: Short self-test on an SSD or NVMe
- Preconditions: no data at risk or data secured; drive not in a read-only or safe mode.
- Risk: R1 (gate kind: smart-selftest-short)
- Tool: `smartctl -t short <confirmed path>` (NVMe device self-test via smartctl 7.x), then `rs.py collect`
- Expected result: test completes; health log unchanged.
- Stop criteria: critical warning appears, media errors grow, or the device resets.

### Method: Extended self-test on an SSD or NVMe
- Preconditions: as the short test; enough time.
- Risk: R1 (gate kind: smart-selftest-long)
- Tool: `smartctl -t long <confirmed path>`, then `rs.py collect`
- Expected result: completed; no new error log entries tied to media.
- Stop criteria: as the short test.

### Method: Full read verify after recovery
- Preconditions: post-recovery window (after the last R2 gate); destination with space for an image or a sink.
- Risk: R1 (gate kind: image-ddrescue)
- Tool: GNU ddrescue full pass with mapfile (see [imaging-ddrescue](imaging-ddrescue.md)), then
  `rs.py ingest ddrescue <sid> <dev> <mapfile>`
- Expected result: finished mapfile with no bad bytes; the SSD/NVMe PASS matrix uses it as the read verify.
- Stop criteria: read errors, resets, temperature at the device-reported limit.
