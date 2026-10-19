# External drives and USB-SATA/NVMe bridges

- smartctl reaches the inner disk only through bridges it knows. Order to try: auto-detect, `-d sat`, then the NVMe
  bridge types `sntjmicron`, `sntasmedia`, `sntrealtek` (operator choice: `rs.py collect <dev> --session <sid> --dtype sat`).
  One smartctl call at a time per bridge; some bridges hang on passthrough, so every call has a timeout.
- Some bridges report a wrong SMART status byte; trust the attribute values and logs more than the one-line status.
- Link counters (interface CRC, command timeout) on a bridge point at the cable, port, power or the bridge itself,
  not the media.
- Without SMART through the bridge, an enclosure looks like a flash device (`usb-flash-or-card`). Declare the real
  type in the session (`--device-type hdd` or `ssd`): the class conflict then blocks a PASS until SMART is read
  (`classify-device-first`), so a HDD in an enclosure never passes on a flash-style capacity test alone.
- Bridge hardware encryption: some external drives (for example WD My Passport family) encrypt on the bridge board;
  a bare disk moved to another enclosure may show only ciphertext (WD KB 15150 via search snippet, vendor-lab
  positions). Keep such drives in their original enclosure, ask for the password first, image through the original
  bridge, never reset or change the password. The model-specific mechanism is unverified.
- A controller safe-mode identity behind a bridge (`SATAFIRM S11`) is reported by vendor labs as unreadable by OS
  tools: stop, no initialise/format, lab.

### Method: Collect SMART through a bridge with an explicit type
- Preconditions: auto-detect gave `unsupported_bridge` or no SMART; operator accepts trying a passthrough type.
- Risk: R0 (gate kind: none)
- Tool: `rs.py collect <dev> --session <sid> --dtype sat` (allowed types only: `sat`, `sat,12`, `sat,16`, `nvme`,
  `sntjmicron`, `sntasmedia`, `sntrealtek`, `usbjmicron`, `auto`)
- Expected result: SMART data of the inner disk, or a recorded reason why not.
- Stop criteria: the bridge hangs or the disk disconnects: do not retry other types in a loop; try another
  enclosure only when the drive has no bridge encryption.

### Method: Move the disk to a direct SATA/NVMe connection
- Preconditions: no bridge encryption (vendor documentation checked); enclosure suspected faulty.
- Risk: R0 (gate kind: none)
- Tool: desktop SATA port or a known-good enclosure; then `rs.py inventory --session <sid>` and `rs.py collect`
- Expected result: the inner disk enumerates with its own model/serial; SMART readable.
- Stop criteria: the drive is bridge-encrypted or the operator is unsure: keep the original enclosure.
