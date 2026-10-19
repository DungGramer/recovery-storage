# Imaging with GNU ddrescue

Source: GNU ddrescue manual (gnu.org/software/ddrescue/manual). "Always use a mapfile unless you know you won't
need it." "Never try to rescue a r/w mounted partition." "Never try to repair a file system on a drive with I/O
errors; you will probably lose even more data."

- Destination: an image file on a different healthy drive (or another device), never the source.
- Two-pass pattern from the manual: pass 1 `ddrescue -f -n SRC DST mapfile` (skip scraping, get the easy areas),
  pass 2 `ddrescue -d -f -r3 SRC DST mapfile` (direct access, retries). Interrupt and resume with the same mapfile.
- Stop knobs in ddrescue: `-T` (time since last good read), `--min-read-rate`, `-X`, `-E`, `-e`. Heat, clicking and
  SMART growth are checked by you between passes: `rs.py collect` and `rs.py compare --device <dev>`.
- `-c` smaller cluster for slow drives; `-R` reverse when the start of the disk is bad.
- After each pass: `rs.py ingest ddrescue <sid> <dev> <mapfile>`. The parser reads the mapfile itself (hex, decimal or
  C++ octal numbers); rescued, bad and unfinished bytes are reported separately. A finished mapfile with nothing bad
  or unfinished lets you run `rs.py session data-state <sid> <dev> secured --evidence <id>`.
- Work on copies of the image afterwards (filesystem repair, PhotoRec, TestDisk).

Windows paths:
- WSL2: take the disk offline in Windows (gate kind `disk-offline`), then `wsl --mount \\.\PHYSICALDRIVE<N> --bare`
  (the flag exists on this project's machine) and run ddrescue inside WSL on the device that appears there; check
  model/serial inside WSL before reading. `<N>` is the disk number printed by gate confirm (`/dev/pd<N>`).
- USB passthrough with usbipd-win: a usbipd-attached mass-storage device showing up as a block device [UNVERIFIED]
  on the default WSL kernel; check `lsblk` and `dmesg` after attach.
- Linux live USB: the fallback when WSL shows I/O errors or the device does not appear.

### Method: Image a failing device with ddrescue
- Preconditions: triage SOFTWARE or CONTROLLER candidate (not STOP_UNSAFE); destination device known to the case
  store and healthy; destination free space at least the source size.
- Risk: R1 (gate kind: image-ddrescue)
- Tool: GNU ddrescue (Linux, WSL2, live USB); `rs.py gate open <sid> <dev> image-ddrescue --dest-device <dest>`
- Expected result: image plus mapfile; rescued share grows each pass; ingested mapfile evidence.
- Stop criteria: read rate collapsing, new clicking or beeping, temperature at the device limit, media counters
  rising between passes; then stop and reassess instead of adding retries.

### Method: Attach a whole disk to WSL2 without mounting
- Preconditions: Windows disk taken offline; WSL2 installed; admin shell available.
- Risk: R1 (gate kind: wsl-mount-bare)
- Tool: `wsl --mount \\.\PHYSICALDRIVE<N> --bare`, release with `wsl --unmount`
- Expected result: the disk appears as a block device inside WSL, readable by ddrescue.
- Stop criteria: any I/O error or the model/serial inside WSL does not match the confirmation block.
