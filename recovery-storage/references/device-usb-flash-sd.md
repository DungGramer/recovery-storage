# USB flash drives, SD and microSD cards

Facts from real captures on this project's machine (Windows 11, non-admin; fixtures/SOURCES.md):
- No SMART is normal. smartctl on a no-name stick: exit 1 "Unknown USB bridge"; the `-d sat` retry without admin:
  exit 2 "Open failed, Error=5" = `needs_elevation`. That is an environment fact, not a device fault: re-run
  `rs.py collect` from an elevated shell if SAT passthrough is worth trying. SMART absence on these sticks is
  otherwise unverified.
- Windows reports junk serials for such devices (a single character); identity then rests on model, exact bytes,
  VID/PID and the MBR signature / GPT guid. Re-partitioning changes that on-media id: after a gated format the
  close records identity drift (`media-id-changed`) and the operator confirms it is the same stick with
  `rs.py device link <observation> <device>` in their own terminal (learns the new id, clears the drift).
- An SD card in a USB reader shows the reader's VID/PID and often MBR signature 0: identity is weak. Gates still open
  when it is the only such card attached; the phrase is the exact byte count. Keep only one card in the reader.
- A data partition without a recognised filesystem (no volume, RAW) points to a partition/filesystem cause or to a
  controller returning garbage; image or inspect read-only first, verify capacity only after data is secured.
- VID `ABCD` / PID `1234` is commonly reported on no-name sticks [UNVERIFIED]: a weak authenticity hint, never a
  verdict and never a rule input.
- Write protection: physical LOCK switch on SD adapters, OS read-only attribute, controller end-of-life read-only
  mode (data still readable: image first) [UNVERIFIED], permanent write protect bit in the card's CSD register.
- Native SD readers on Linux expose the card CID (`/sys/block/mmcblk*/device/cid`); USB readers do not. CID fields
  are hints only (vendors can program them).

A full write/read verify (F3 or H2testw) is the only proof of real capacity; a successful format proves nothing.
See [authenticity-f3-h2testw](authenticity-f3-h2testw.md).

### Method: Identify a flash device read-only
- Preconditions: device attached.
- Risk: R0 (gate kind: none)
- Tool: `rs.py inventory --session <sid>`, `rs.py collect <dev> --session <sid>` (PowerShell frozen scripts, smartctl)
- Expected result: model, bytes, VID/PID, partition and filesystem facts, collection status recorded.
- Stop criteria: Windows asks to format the device: cancel, never accept.

### Method: Image a flash device before any test
- Preconditions: data must be kept; destination on another healthy drive.
- Risk: R1 (gate kind: image-ddrescue)
- Tool: GNU ddrescue with mapfile (see [imaging-ddrescue](imaging-ddrescue.md)); then `rs.py ingest ddrescue`
- Expected result: finished image; `rs.py session data-state <sid> <dev> secured --evidence <id>`.
- Stop criteria: the device turns read-only, disconnects repeatedly or gets hot.

### Method: Look up the controller for a dead or read-only stick
- Preconditions: identity readable; capacity 0 or absurd, or locked read-only.
- Risk: R0 (gate kind: none)
- Tool: ChipGenius / ChipEasy (Windows GUI, read-only) for controller and flash id; record results in a session note
- Expected result: controller vendor/model and flash id from two tools that agree.
- Stop criteria: tools disagree or the download source is unverifiable; see [controller-mptool](controller-mptool.md).
