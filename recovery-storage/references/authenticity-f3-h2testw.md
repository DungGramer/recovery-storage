# Authenticity and capacity verification (F3, H2testw)

Sources: F3 README.rst, doc/usage.rst and source (github.com/AltraMayor/f3); heise H2testw page; GRC ValiDrive page.

- Only a write-then-read of the whole usable range proves capacity. A successful format writes metadata only and
  proves nothing; identity strings (model, VID/PID, CID) can be spoofed by modified firmware.
- Run these tests only after data is secured or not needed: they write the device.
- Three outcomes to keep apart: fake capacity (f3probe type limbo/wraparound/chain, f3read overwritten/lost),
  modified firmware or relabelled identity (identity mismatch while capacity passes), genuine but failing
  (f3probe damaged, read errors, read-only lock).

F3 facts (from source):
- f3probe: Linux only, root, whole unmounted device, USB-backed only (an internal SD reader is refused: use
  f3write/f3read). Exit codes: 0 good, 101 damaged, 102 limbo, 103 wraparound, 104 chain; anything else is a tool
  or usage error. Default mode saves and restores blocks, but a crash loses them; `--destructive` restores nothing.
- f3write writes `N.h2w` files into free space of a mounted filesystem (existing files untouched, volume filled);
  `No space!` means nothing was written. f3read summarises `Data OK`, `Data LOST`, `Corrupted`, `Slightly changed`,
  `Overwritten` and exits 1 on any bad sector. f3write/f3read also build on macOS and on Windows via Cygwin.
- f3fix rewrites the partition table to the usable size (cosmetic: the device stays fake); f3brew writes blocks.

Windows: H2testw 1.4 (GUI, no CLI) fills free space with files and reads them back; record the result with
`rs.py ingest attested <sid> <dev> --tool h2testw --result pass --file <screenshot-or-log>` (counts for PASS as
ATTESTED evidence). ValiDrive samples random locations only: a quick hint, not a full verify.

Ingest F3 output with its exit code: `rs.py ingest f3probe <sid> <dev> <out.txt> --exit-code <code>` (same for
f3write/f3read). The exit code is the primary signal; text that disagrees with it makes the record inconclusive.

### Method: Quick probe with f3probe (non-destructive mode)
- Preconditions: Linux host or live USB; device USB-backed and unmounted; data secured or not needed.
- Risk: R2 (gate kind: f3probe)
- Tool: `f3probe --time-ops <confirmed device>` (F3 extra tools, root)
- Expected result: exit 0 good, or 101-104 with a type; ingest the output.
- Stop criteria: write errors, disconnects, overheating; never rerun in a loop on a hang.

### Method: Destructive probe with f3probe
- Preconditions: operator confirmed that nothing on the device is needed.
- Risk: R2 (gate kind: f3probe-destructive)
- Tool: `f3probe --destructive --time-ops <confirmed device>`
- Expected result: as the quick probe, faster on fakes; contents are not restored.
- Stop criteria: as the quick probe.

### Method: Full verify with f3write and f3read
- Preconditions: freshly created filesystem covering the device; data secured or not needed; time for a full write
  and read.
- Risk: R2 (gate kind: f3write-f3read)
- Tool: `f3write <mountpoint>` then `f3read <mountpoint>` (Linux, macOS, Cygwin); ingest both outputs
- Expected result: f3read exit 0 with no lost, corrupted or overwritten data; delete the .h2w files afterwards.
- Stop criteria: write failure messages (often heat: slow down with `--max-write-rate`), disconnects.

### Method: Full verify with H2testw on Windows
- Preconditions: single partition formatted to full size; data secured or not needed.
- Risk: R2 (gate kind: h2testw)
- Tool: H2testw 1.4 (heise.de download), "all available space", write + verify
- Expected result: "Test finished without errors"; screenshot or log ingested as attested evidence.
- Stop criteria: write/verify errors, adapter or cable faults suspected (repeat on another port before concluding).
