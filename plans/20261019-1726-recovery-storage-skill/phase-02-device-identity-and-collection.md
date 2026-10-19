# Phase 02 - Device identity and R0 collection

## Context Links
- Spec §2.1 identity, §4 rule 1 (multi-attribute identity): [requirements.md](requirements.md)
- Verified Windows facts (pdN == Disk Number, NVMe SerialNumber is EUI-64, UniqueId == eui64, Get-Disk.Size exact, Win32_DiskDrive.Size truncated, ReliabilityCounter admin-only, PnP parent works non-admin, Ntfs 55): requirements.md "Facts verified"
- smartctl JSON keys, scan, USB `-d` types, standby: [researcher-01](research/researcher-01-smartctl-nvme-json.md) §1, §3, §7
- Enumeration, fingerprint, match levels: [researcher-02](research/researcher-02-os-enumeration.md) §1, §4, §6 (most items [K]: verify on capture)
- Fixtures (BUILT): `fixtures/smartctl/*`, Windows captures `fixtures/windows/{baseline-nvme-only,usb-stick,usb-sd}/` (win-disks, win-pnp-chain, win-events, smartctl scan + per-disk `-x -n standby` + `-d sat` retry, each with `.meta.json` exit/stderr), WSL `fixtures/linux/wsl-ubuntu2204/{lsblk-JOb.json,udevadm-sda.txt}`; see `fixtures/SOURCES.md`
- PowerShell scripts (BUILT): `rslib/ps/*.ps1`; output envelopes `schema: win-disks/1` (`disks, physical, wmi, partitions, volumes`), `win-pnp-chain/1` (`disks[].Chain[]`), `win-events/1` (`events, errors`)

## Overview
- Priority: P0. Status: Todo. Depends on phase 01.
- Commands: `inventory`, `collect <device-id>`, `ingest smartctl <file>`, `device link`. All R0.
- Produces normalised identity + health records consumed by phase 03 rules and phase 04 gate re-resolution.

## Key Insights
- Never key on Disk Number, PhysicalDriveN, drive letter or `/dev/sdX`: they change on re-enumeration. They are recorded per observation only.
- Canonical identity comes from smartctl when it answers (model, serial_number, user_capacity.bytes, wwn, nvme eui64); OS fields are secondary. On Windows NVMe the OS serial is the EUI-64 and must not be compared with smartctl serial; the join is `Get-Disk.UniqueId` == `eui.` + eui64 hex.
- eui64 hex from smartctl = OUI as 6 hex digits + ext_id as 10 hex digits (oui 9528 -> `002538`; verified on this machine).
- smartctl exit status is a bitmask: bits 0-2 collection failure (data absent/incomplete, never "healthy"), 3-4 failing, 5-7 history.
- USB sticks usually have no SMART: absence is a fact to record, not a failure of the device. Verified on this machine: no-name stick -> smartctl exit 1 "Unknown USB bridge [0xabcd:0x1234]"; `-d sat` non-admin -> exit 2 "Open failed, Error=5" = needs elevation, not a device fault. NVMe needs no admin.
- Verified USB identity facts: Get-Disk SerialNumber is 1-char junk (`"\t"`, `"["`) while Get-PhysicalDisk SerialNumber is null -> no usable serial; the PnP USB node instance id (`USB\VID_ABCD&PID_1234\5&...&8`) is Windows-generated (contains `&`), so no USB serial either; Get-Disk UniqueId for USB is `USBSTOR\...:<HOSTNAME>` (host-specific: an OS id, never a cross-host identity). MBR Signature 0 (SD card) carries no identity. PS 5.1 `Select-Object` emits enums as strings (`"USB"`, `"NVMe"`, `"Healthy"`): parsers accept string and numeric forms.
- SD card behind a USB reader exposes the reader's VID/PID (`05E3:0751`), not the card's CID: two same-size cards in that reader are indistinguishable unless the media carries a partition-table id.
- A sleeping HDD must not be spun up silently: first call uses `-n standby`; spin-up is an explicit flag.

## Requirements
Functional
- Windows enumeration: the shipped scripts `rslib/ps/{win-disks,win-pnp-chain,win-events}.ps1` (already written; this phase writes the Python parsers and runner wiring only). Fields: Get-Disk (Number, FriendlyName, SerialNumber, UniqueId, Guid, Signature, BusType, Size, PartitionStyle, IsOffline, IsReadOnly, IsBoot, IsSystem, HealthStatus, OperationalStatus, Location, Path), Get-PhysicalDisk (FriendlyName, SerialNumber, UniqueId, MediaType, BusType, FirmwareVersion, Size), Win32_DiskDrive (Index, PNPDeviceID, Model), PnP parent chain to first `USB\VID_xxxx&PID_xxxx\...` node.
- Linux enumeration: `lsblk -J -O -b`, `udevadm info --query=property --name=<dev>`, `blockdev --getro`, sysfs file reads (`/sys/block/<dev>/device` upward to `idVendor`/`idProduct`/`serial`; `/sys/block/mmcblk*/device/{cid,manfid,oemid,name,serial}` when native mmc). File reads are not processes; done in `enum_linux.py` with paths constrained to `/sys/`.
- smartctl identity probe per OS disk: Windows `/dev/pd<Number>`, Linux the lsblk path; `-j -i -n standby`.
- Collection status (frozen enum): `ok, standby, not_exposed, unsupported_bridge, needs_elevation, collection_failed, malformed, unknown, tool_missing, timeout`. `needs_elevation` = message contains `Open failed, Error=5` (Windows access denied); `unsupported_bridge` = message `Unknown USB bridge` / `Unsupported USB bridge` / `type is ambiguous`. Both are environment facts, never device-failure evidence.
- Filesystem facts from `partitions`/`volumes` (Windows) and lsblk `fstype` (Linux): a partition with no volume object or empty FileSystem -> observation fact `fs_unrecognised` (input to phase 03 hypothesis `partition-or-filesystem`); volume labels and mount paths are not collected.
- `collect`: re-resolve device (exact/probable/weak-single, else exit 5 or 3), then `-j -x -n standby`; if bus is USB and no SMART data, exactly one retry with `-d sat`; `--dtype <type>` from the allow-list for NVMe bridges chosen by operator; `--allow-spinup` drops `-n standby` and records that a deliberate spin-up happened. Also OS events in window [session start - lookback parameter, now].
- Events: Windows System log by provider list (parameter) + level Error/Warning + window + MaxEvents; Linux `journalctl -k -o json --since`, fallback `dmesg`; permission failure recorded as `events: unavailable(<reason>)`. Store provider, id, level, time, message truncated to a parameter length. Only Ntfs 55 gets a semantic tag (`fs_corruption`); no other id table in code.
- `ingest smartctl <file>`: same normaliser for JSON captured elsewhere (WSL, live Linux, another host); resolves device by smartctl identity.
- `device link <observation-id> <device-id>|--new`: operator resolves an ambiguous observation.
- Device class detection: protocol NVMe -> `nvme`; ATA rotation_rate > 0 -> `hdd`, == 0 -> `ssd-sata`; USB bus with SMART via bridge type (`sat`, `usbjmicron`, `snt*`) -> `external-<inner>`; USB without SMART -> `usb-flash-or-card`; Windows BusType SD/MMC or Linux mmcblk -> `sd`. Declared class (session) vs detected: conflict recorded as evidence, declared never overwritten.
Non-functional
- Each subprocess call has its own timeout; one smartctl call at a time per device (no concurrency on a bridge).

## Architecture
```
rslib/enum_windows.py  PS scripts (frozen strings) -> parse -> [OsDisk]
rslib/enum_linux.py    lsblk/udevadm/sysfs -> [OsDisk]
rslib/smart.py         smartctl JSON -> SmartRecord{collection_status, exit_bits, identity, health_fields, raw_ref}
rslib/identity.py      normalise serial, serial_trust, fingerprint(OsDisk, SmartRecord), match(fp, candidates) -> MatchResult
rslib/events.py        OS events -> [Event]
rslib/collect.py       orchestration for inventory / collect / ingest smartctl
```
Fingerprint fields: `model, serial_norm, serial_trust(high|low|absent), bytes, bus, vid, pid, eui64|wwn, ptuuid|mbr_signature, os_ids{disk_number|dev_path, unique_id}`.
Serial normalisation: keep raw; normalised = trim, uppercase, drop trailing `.`; Windows NVMe EUI form (`XXXX_XXXX_..._XXXX.`) is classified as eui64, not serial.
serial_trust absent: empty after trim, or length 1, or no alphanumeric character (covers the verified `"\t"` / `"["` junk). serial_trust low: single repeated character, or identical serial on two currently attached devices. USB node instance-id segment containing `&` -> `usb_serial` absent (Windows-generated, verified on both captures). `mbr_signature` 0 -> absent. Windows USB `UniqueId` stored in `os_ids` only.
Match (candidate = stored device fingerprint):
- conflict: any strong id (serial with trust high, eui64, wwn) present on both and different -> not a match, even if model/size equal.
- exact: high-trust serial equal + model equal + bytes equal (+ eui64/wwn equal when both present).
- probable: serial low/absent; model + bytes + vid/pid equal AND an on-media id (ptuuid / GPT disk guid / non-zero mbr_signature) present on both and equal.
- weak: serial low/absent; model + bytes + vid/pid equal, no on-media id on at least one side (blank media, SD in a reader with Signature 0). Usable by `collect` and `gate` only when it is the single attached device with that model + bytes + vid/pid; otherwise ambiguous.
- ambiguous: more than one candidate reaches the best level, or only model + bytes match.
- none: no candidate.

## Related Code Files
Create: `recovery-storage/scripts/rslib/{enum_windows,enum_linux,smart,identity,events,collect}.py`; tests `test_smart_normalise.py, test_exit_bits.py, test_identity_match.py, test_enum_windows.py, test_enum_linux.py, test_collect_cli.py`; fixtures `fixtures/windows/*.json`, `fixtures/linux/*.json` (captured, redacted).
Existing (read, do not recreate): `rslib/ps/*.ps1`, `fixtures/windows/**`, `fixtures/linux/**`.
Modify: `rslib/cli.py` (new subcommands), `fixtures/SOURCES.md` (WSL spike note only).

## Implementation Steps
1. `smart.py` normaliser + exit-bit decoder against existing fixtures (no new capture needed).
2. `identity.py` (normalise, trust, fingerprint, match).
3. DONE (main agent): PowerShell scripts written; captures `baseline-nvme-only`, `usb-stick`, `usb-sd` redacted. This phase: parsers for those envelopes.
4. Linux parsers against the WSL capture (DONE capture: virtual disks, vendor `Msft    ` padded, no `tran`); USB sysfs chain and native mmc have no real sample: tested only for "missing chain -> usb null" / "no mmc dir -> sd_native false".
5. `events.py`, `collect.py`, CLI wiring.
6. Spike (record result in SOURCES.md, not code): after `wsl --mount <disk> --bare` (needs admin + disk offline, R1, operator-run), does WSL lsblk show the real model/serial or a virtual one? Determines whether ptuuid is the only cross-env identity there.

## Todo List
- [ ] smartctl normaliser + exit bits
- [ ] identity normalise/trust/fingerprint/match
- [x] Windows scripts + real capture + redaction (main agent)
- [ ] Windows parsers (win-disks / win-pnp-chain / win-events envelopes)
- [ ] Linux parsers (WSL capture)
- [ ] events
- [ ] inventory / collect / ingest smartctl / device link CLI
- [ ] WSL bare-mount identity spike noted

## Acceptance Criteria (observable)
smartctl normalisation (fixtures by name)
- B1 Exit bits: 0 -> `collection ok`, no flags. 216 (`scrutiny-usbjmicron-hdd-failing`) -> collection ok + flags {smart_failing(8), prefail_threshold_now(16), error_log_has_records(64), selftest_log_has_errors(128)}. 2 (`scrutiny-open-failed`) -> `needs_elevation` with message text "Open failed, Error=5" preserved. 1 (`missing-device`) -> `collection_failed`, message "Unable to detect device type". `windows/usb-stick/smartctl-x-pd2.json` (exit 1, "Unknown USB bridge [0xabcd:0x1234]") -> `unsupported_bridge`; `windows/usb-stick/smartctl-x-sat-pd2.json` (exit 2, Error=5) -> `needs_elevation`. 4 -> `collection_failed` (command failed). 32 -> flag `attribute_failed_in_past`.
- B2 `nvme-990pro-x` -> identity {model "Samsung SSD 990 PRO 1TB", serial = redacted value, firmware "4B2QJXD7", bytes 1000204886016, protocol NVMe, eui64 = `002538` + 10-hex of ext_id}; health fields include critical_warning 0, available_spare 100, threshold 10, percentage_used 6, media_errors 0, power_on_hours 5017, temperature 47, temp warning 82 / critical 85.
- B3 `scrutiny-sat-partial` (no model, no smart_status, no user_capacity) -> model `null`(absent), bytes `null`(absent), overall_status `null`(absent); attributes 5/187/188/197/198/199 present with raw values; no field defaulted to 0 or false.
- B4 `scrutiny-scsi-no-smartctl-block` (no `smartctl` block) -> collection_status `unknown` (not ok), identity still parsed (model "SEAGATE ST4000NM0043", bytes 4000787030016).
- B5 `scrutiny-usbjmicron-hdd-failing` -> device.type `usbjmicron`, detected class `external-hdd` (rotation 7200, bridge type).
- B6 Unknown extra keys in input are ignored; JSON that is not valid JSON or lacks `json_format_version` -> collection_status `malformed`, raw file still stored with sha256.
Identity
- B7 Serial `"  ABC123XYZ.  "` -> normalised `ABC123XYZ`; `1111_2222_3333_4444.` -> classified eui64 `1111222233334444` (separators and trailing dot dropped), serial absent.
- B8 Trust: `""`, `"\t"`, `"["` -> absent; `"0000000000"` -> low (repeated char); two attached devices both `"ABC123"` -> both low; `"WDXYZ12345"` alone -> high.
- B9 Match table (each a test): same serial(high)+model+bytes -> exact; same + different eui64 -> conflict; serial absent, model+bytes+vid/pid+ptuuid equal -> probable; serial absent, model+bytes+vid/pid equal and MBR signature 1859593249 equal -> probable; same but signature 0 on both -> weak (signature 0 never counts); weak with a second attached device of same model+bytes+vid/pid -> ambiguous; serial absent, two stored candidates both probable -> ambiguous (exit 5 at CLI, no auto-link); only model+bytes equal -> ambiguous; nothing -> none.
- B10 Windows join: Get-Disk UniqueId `eui.<16 hex>` (redacted fixture value) + Size 1000204886016 joins the smartctl record whose eui64 equals those 16 hex digits + bytes (case-insensitive). Same size but different eui -> not joined; observation records `join_conflict`.
- B11 Size source: Windows bytes taken from Get-Disk.Size; Win32_DiskDrive.Size never used for identity (fixture where they differ proves it).
Windows/Linux enumeration (captured fixtures)
- B12 `windows/baseline-nvme-only/win-disks.json`: two disks, Disk 0 (990 PRO, GPT) flagged is_boot and is_system, Disk 1 (980 PRO, MBR) not; bus `NVMe` string -> `nvme`; a unit case with numeric BusType 17 -> `nvme` and 7 -> `usb`; HealthStatus string kept as text.
- B12b `windows/usb-stick/win-disks.json` Disk 2: model "General UDisk", bus usb, bytes 8054112256, serial_trust absent (Get-Disk `"\t"`, PhysicalDisk null), unique_id kept in os_ids only, mbr_signature 1859593249, partition MbrType 7 with no volume -> `fs_unrecognised=true`.
- B12c `windows/usb-sd/win-disks.json` Disk 3: model "Generic STORAGE DEVICE", bytes 4026531840, serial `"["` -> absent, mbr_signature 0 -> absent, volume FAT32 present -> `fs_unrecognised=false`.
- B13 PnP chain: `usb-stick` Disk 2 -> vid `ABCD`, pid `1234`, usb_serial absent (instance segment contains `&`); `usb-sd` Disk 3 -> vid `05E3`, pid `0751`, usb_serial absent; NVMe disks (chain PCI -> ACPI, no `USB\` node) -> `usb = null` (not guessed).
- B14 Linux lsblk capture: sizes parsed as integers even if given as strings; `tran`, `rm`, `ro`, `hotplug`, `ptuuid` mapped; missing sysfs USB chain -> `usb = null`.
Commands (RecordedRunner)
- B15 `inventory` on this machine's capture: lists each disk with fingerprint, match level vs stored devices, OS path; first run creates devices; second run with same capture reuses the same device ids (no duplicates).
- B16 `inventory` where a stored device now matches ambiguously: exit 5, prints candidates with model/size/os path; no observation linked. `device link <obs> <dev>` then links it; `device link <obs> --new` creates a device.
- B17 `collect <dev>`: runs exactly `smartctl -j -x -n standby <path>` (assert recorded argv), stores snapshot + raw evidence + tool version "7.5"; device not present at collect time -> exit 3 `device-not-found`, nothing stored except the refusal.
- B18 `collect` on the `usb-stick` Disk 2 (RecordedRunner with its captures): first call `smartctl -j -x -n standby /dev/pd2` -> `unsupported_bridge`; exactly one retry `smartctl -j -x -n standby -d sat /dev/pd2` -> final snapshot status `needs_elevation`, exit 0, output says "re-run elevated to try SAT passthrough; this is not a device fault". Retry answering with no SMART and no error -> `not_exposed`, exit 0.
- B18b Detected class for `usb-stick` and `usb-sd` devices: `usb-flash-or-card` (bus usb, no SMART); session-declared `sd` vs detected `usb-flash-or-card` is NOT a conflict (reader hides card type); declared `hdd` vs detected `usb-flash-or-card` is recorded as conflict.
- B19 smartctl in standby (bit 1 + power_mode standby) -> snapshot `standby, not spun up`, exit 0; `collect --allow-spinup` repeats without `-n` and records `spinup=true`.
- B20 smartctl missing -> snapshot collection_status `tool_missing`, exit 4, message includes install options `winget install smartmontools.smartmontools` / `scoop install smartmontools`. Timeout -> `timeout`, exit 4.
- B21 Events: Ntfs id 55 in window -> tagged `fs_corruption`; other provider events kept untagged; `win-events.json` captures parse (envelope `events`, `errors`); providers not registered on the host (USBSTOR, sdbus, fastfat) are absent from `errors` and cause no warning; a non-empty `errors` entry -> `events partial (<provider>: <error id>)`; access denied -> `events unavailable` with reason; collect still exit 0 in all three.
- B22 `ingest smartctl <file>`: file with identity matching a stored device -> snapshot attached with `source=ingested`, sha256 recorded; no match -> new device created and reported as such; ambiguous -> exit 5.

## Pros / cons vs alternative
Chosen: smartctl-first canonical identity, OS ids as observations.
- Pros: same identity on Windows, WSL and live Linux; avoids the Windows NVMe serial trap; matches what the gate must re-check.
- Cons: devices with no smartctl answer (most USB sticks, SD readers) fall back to probable/weak matching (verified: no usable serial on either captured USB device).
Alternative: OS-native identity (Get-Disk / lsblk serial) as the key.
- Pros: always available, no smartctl dependency for inventory. Cons: differs per OS for the same disk (EUI-64 vs serial), breaks cross-environment history. Rejected as primary; kept as secondary fields.

## Not Worth Doing If
- Linux USB sysfs-chain parsing beyond "null when absent" is not worth building until a real Linux capture of a USB device exists (check `fixtures/linux/` first). Windows USB parsing is in scope: captures exist.

## Risk Assessment
- PowerShell field shapes differ on UAS / USB-SATA docks (unseen; USB stick and SD reader are captured) -> parsers tolerate missing/extra properties and both string/numeric enums.
- `-x` slow or hanging on weak bridges -> per-call timeout, one retry type only, `--dtype` operator choice.
- Re-enumeration between Get-Disk and smartctl call -> join check (B10) catches mismatched pairing.
- WSL bare mount may hide model/serial -> spike step 6; ptuuid fallback.

## Security Considerations
- Raw outputs contain serials: stored only under home; reports redact on request (phase 05).
- Event messages truncated; no file paths from user volumes are queried.
- sysfs reads constrained to `/sys/` prefix (no path traversal from device names).

## Next Steps
- Phase 03 consumes SmartRecord + events + session symptoms.
