# System Architecture

Source: `plans/20261019-1726-recovery-storage-skill/requirements.md` (sections "Decisions settled with the user" and "Facts verified on this machine").

## Purpose

`recovery-storage` is a Claude Code skill that orchestrates diagnosis and recovery of storage devices (USB, SD/microSD, HDD, SATA/NVMe SSD, external drives, USB-bridged and controller-based flash). It drives existing tools and collects, normalizes and stores their output. It never reimplements imaging, filesystem repair, SMART parsing or NAND decoding.

## Approved stack

| Area | Choice |
|---|---|
| Language | Python >= 3.10, standard library only at runtime (`subprocess`, `json`, `sqlite3`, `argparse`, `hashlib`); no pip dependencies at runtime |
| Tests | pytest |
| SMART / NVMe collector | smartctl 7.x with `-j`, the sole collector on Windows and Linux; nvme-cli is optional, Linux only |
| Windows enumeration | `powershell.exe` 5.1, Storage cmdlets and CIM, output as JSON |
| Linux enumeration | `lsblk -J -O -b`, `udevadm`, `lsusb`, sysfs |
| Case store | SQLite plus per-session JSON evidence under `~/.recovery-storage/`; override with `--home` or `RECOVERY_STORAGE_HOME` |

The store lives outside the repo because evidence contains device serials.

Skill layout: `recovery-storage/` holds `SKILL.md`, `references/`, `scripts/`; `~/.claude/skills/recovery-storage` is a junction to that folder.

## External tools orchestrated

- smartmontools (smartctl): SMART and NVMe health.
- GNU ddrescue: imaging of failing media.
- TestDisk: partition recovery.
- PhotoRec: file recovery.
- F3: flash capacity verification.
- H2testw: flash capacity verification, guided only.
- MPTool (controller-specific): guided only; the skill never fetches or runs firmware itself.

## Platform notes

Verified on Windows 11 with smartctl 7.5, non-admin.

- Addressing: `smartctl -j -i /dev/pdN` addresses `Get-Disk` Number N. `smartctl --scan-open -j` lists NVMe disks as `/dev/sdX` (type nvme) and works without admin.
- NVMe serial mismatch: Windows `Get-Disk`/`Get-PhysicalDisk` `SerialNumber` is the EUI-64 string, not the smartctl `serial_number`. Join on `Get-Disk.UniqueId` (`eui.` + 16 hex digits) against smartctl `nvme_namespaces[].eui64` (oui + ext_id), plus model and exact byte size.
- Size: use `Get-Disk.Size`, which equals smartctl `user_capacity.bytes`. Do not use `Win32_DiskDrive.Size` (geometry-truncated) or `Win32_DiskDrive.InterfaceType` (reports NVMe as `SCSI`).
- Admin-only: `Get-StorageReliabilityCounter` fails without admin, so it is optional.
- Without admin: the PnP parent chain via `Get-PnpDeviceProperty -KeyName DEVPKEY_Device_Parent` works.
- Event log: query by provider name, level and time window; do not rely on a hard-coded event ID list as the only filter.
- MSYS path conversion: Git Bash rewrites `/dev/sda` unless `MSYS_NO_PATHCONV=1`. Python `subprocess` with an argv list is unaffected.
- Output capture: PowerShell 5.1 `>` writes UTF-16LE; capture tool output through `subprocess`, not shell redirection.
- Missing device: smartctl exits with status 1 and an error message "Unable to detect device type".

## Components and data flow

To be filled from the implementation plan once it lands.
