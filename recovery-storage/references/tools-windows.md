# Windows tools and traps

Verified on Windows 11 (build 26200) with smartmontools 7.5, non-admin, 2026-10-19 (fixtures/SOURCES.md):
- Install smartmontools: `winget install smartmontools.smartmontools` (admin) or `scoop install smartmontools`
  (no admin). Override the binary with env `RS_SMARTCTL=<absolute path>`.
- smartctl `/dev/pdN` is Disk Number N of `Get-Disk`. NVMe health is readable without admin. USB SAT passthrough
  (`-d sat`) needs an elevated shell (`Open failed, Error=5` otherwise).
- Windows reports an NVMe "SerialNumber" as the EUI-64 (`XXXX_XXXX_XXXX_XXXX.`); the real serial comes from
  smartctl. The join between both is `Get-Disk UniqueId` (`eui.<hex>`) plus exact bytes; the CLI does this join itself.
- `Get-Disk.Size` is exact; `Win32_DiskDrive.Size` is geometry-truncated and its InterfaceType calls NVMe "SCSI".
- `Get-StorageReliabilityCounter` needs admin ("Access to a CIM resource was not available").
- USB `UniqueId` contains the host name; USB serials are often a single junk character.
- PowerShell 5.1 `>` writes UTF-16LE; the CLI captures output through its runner instead.
- Git Bash rewrites `/dev/sda` into a Windows path unless `MSYS_NO_PATHCONV=1`; call tools through the CLI or with
  that variable set.
- Event log: the CLI queries the System log per provider (disk, Ntfs, volmgr, partmgr, storahci, stornvme, UASPStor,
  Kernel-PnP and others) for errors and warnings in a window; providers missing on a host are normal.
- Disk Management / diskpart / Format-Volume write the disk: only inside an open gate, on the confirmed number.
- When Windows offers to format a newly attached device, always cancel.

### Method: Read-only inventory on Windows
- Preconditions: none (non-admin works; elevated adds USB SAT passthrough).
- Risk: R0 (gate kind: none)
- Tool: `rs.py inventory --session <sid>` (frozen PowerShell scripts `win-disks`, `win-pnp-chain`; smartctl -i)
- Expected result: each disk with fingerprint, match level, OS path, boot/system flags and USB VID/PID.
- Stop criteria: exit 4 (PowerShell or smartctl missing / failing): fix the environment, do not guess identities.

### Method: Elevated re-collect for USB SAT passthrough
- Preconditions: `needs_elevation` recorded for a USB device; operator agrees to an Administrator shell.
- Risk: R0 (gate kind: none)
- Tool: elevated terminal, then `rs.py collect <dev> --session <sid>`
- Expected result: SMART of a disk behind a SAT bridge, or `not_exposed` for a plain stick.
- Stop criteria: still no SMART: accept that the device does not expose it; move to capacity/read verification.
