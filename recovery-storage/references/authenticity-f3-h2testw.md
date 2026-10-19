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
  `Overwritten`. Unplug and replug the device (or at least remount) between f3write and f3read: on Windows / WSL
  drvfs the host cache serves a read right after the write (real runs 2026-10-19/20: 158-276 MB/s cached vs 17 MB/s
  from the card); an f3read rate far above the device's uncached rate is not a verify. f3read 8.0 exits 0 even when
  data is lost (real card 2026-10-20: Data LOST 3.38 GB, exit 0): the
  summary decides. f3write/f3read also build on macOS and on Windows via Cygwin.
- f3fix rewrites the partition table to the usable size (cosmetic: the device stays fake); f3brew writes blocks.
- Windows host (verified 2026-10-20): f3probe runs in WSL once the USB reader is attached with usbipd-win
  (`usbipd bind --busid <id>` elevated, `usbipd attach --wsl --busid <id>`); the WSL kernel needs usb-storage
  (absent in 5.15.167, present as a module in 6.18 after `wsl --update`; `modprobe usb-storage`). Confirm the gate
  while Windows still sees the device, verify the Linux node by exact bytes, `TRAN usb` and model (WSL's own disks
  are "Msft Virtual Disk"), `usbipd detach` before `gate close`. A real limbo card: f3probe usable size matched the
  raw-read boundary of the f3read loss exactly.

Windows: H2testw 1.4 (GUI, no CLI) fills free space with files and reads them back; record the result with
`rs.py ingest attested <sid> <dev> --tool h2testw --result pass --file <screenshot-or-log>` (counts for PASS as
ATTESTED evidence). ValiDrive samples random locations only: a quick hint, not a full verify.

Ingest F3 output with its exit code: `rs.py ingest f3probe <sid> <dev> <out.txt> --exit-code <code>` (same for
f3write/f3read). f3probe: the exit code is the primary signal; text that disagrees with it makes the record
inconclusive. f3read: the summary decides (Data LOST > 0 fail, 0 with Data OK pass, no summary inconclusive), the exit
code is only recorded. f3write: a write error when the volume became full (final free space 0) is inconclusive.
Stored F3 evidence is re-parsed with the current parser whenever it is read.

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
- Tool: `f3write <mountpoint>`, `rs.py ingest f3write`, operator unplugs and replugs, `rs.py inventory --session
  <sid> --after-replug`, then `f3read <mountpoint>` and `rs.py ingest f3read` (Linux, macOS, Cygwin, WSL drvfs).
  PASS refuses an f3read without that replug in between (`f3read-not-after-replug`). If the last file is partial and
  f3read aborts (exit 134), truncate it to a multiple of 512 and rerun.
- Expected result: f3read summary with Data LOST 0 at the device's real read rate; delete the .h2w files afterwards.
- Stop criteria: write failure messages (often heat: slow down with `--max-write-rate`), disconnects.

### Method: Full verify with H2testw on Windows
- Preconditions: single partition formatted to full size; data secured or not needed.
- Risk: R2 (gate kind: h2testw)
- Tool: H2testw 1.4 (heise.de download), "all available space", write + verify
- Expected result: "Test finished without errors"; screenshot or log ingested as attested evidence.
- Stop criteria: write/verify errors, adapter or cable faults suspected (repeat on another port before concluding).
