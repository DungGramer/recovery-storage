# Linux tools (native, WSL2, live USB)

- Install: `sudo apt install smartmontools gddrescue testdisk f3` (Debian/Ubuntu package names; F3 extra tools
  f3probe/f3fix/f3brew may need a source build with `make extra`).
- Enumeration used by the CLI: `lsblk -J -O -b` (sizes in bytes, transport, removable, read-only, partition table id)
  and sysfs reads under `/sys` for USB VID/PID and native SD CID. Disks smartctl may not probe (zram, virtio, nbd)
  are listed without SMART. `udevadm info --query=property` is useful by hand for vendor/serial details. Run
  inventory with the Linux host's Python: `rs.py inventory --session <sid>`.
- Kernel messages: `journalctl -k` (fallback `dmesg`) for I/O errors, USB resets, UAS errors; the CLI records them as
  context only.
- `blockdev --setro <dev>` sets a kernel read-only flag; a filesystem already mounted read-write may still write until
  remounted.
- Disable desktop automount (udisks) during a session; never mount a source read-write.
- WSL2: virtual disks appear as `Msft Virtual Disk`; a physical disk appears only after `wsl --mount ... --bare` from
  Windows. Check its model/serial inside WSL against the confirmation block before reading.
- Ingest captures made here into a Windows case store: `rs.py ingest smartctl <file> --session <sid>`.

### Method: Collect from a live Linux system
- Preconditions: booted live USB or Linux host; device attached; case store path chosen (`--home` on a USB stick
  that is not the source).
- Risk: R0 (gate kind: none)
- Tool: `rs.py inventory --session <sid>`, `rs.py collect <dev> --session <sid>` (or `smartctl -j -x` saved to a file
  and ingested later)
- Expected result: identity and SMART captured outside the original OS; driver effects separated from device faults.
- Stop criteria: kernel log shows repeated resets or I/O errors: stop, record, reassess before imaging.
