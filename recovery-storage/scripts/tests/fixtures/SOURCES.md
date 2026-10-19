# Fixture sources

All fixtures are real tool output. Identifiers (serial, WWN, EUI-64 extension, GUID/UUID, hostname) are
replaced by `tools/redact_fixtures.py` with deterministic same-length placeholders, consistent across files
(Windows `UniqueId eui.<hex>` still equals smartctl `nvme_namespaces[].eui64` oui+ext_id; NVMe OUI kept).
Raw originals are git-ignored under `plans/*/research/samples/`. Leak check: `python -I tools/redact_fixtures.py --check`.
A derived fixture (single field changed from a real file) must be named `*.derived.json` and listed below with the field and its original value.

## smartctl/ (smartctl `-j` JSON)

| File | Origin | smartctl | Content |
|---|---|---|---|
| `nvme-990pro-x.json` | this machine, `smartctl -j -x /dev/sda`, 2026-10-19 | 7.5 r5714 win | Samsung 990 PRO 1TB, healthy, exit 0 |
| `nvme-980pro-x.json` | this machine, `smartctl -j -x /dev/sdb`, 2026-10-19 | 7.5 | Samsung 980 PRO 2TB, healthy, exit 0 |
| `nvme-990pro-i-standby.json` | this machine, `smartctl -j -i -n standby /dev/sda` | 7.5 | identity only, exit 0 |
| `missing-device.json` | this machine, `smartctl -j -x /dev/sdz` | 7.5 | exit 1, "Unable to detect device type" |
| `scrutiny-ata-hdd-healthy.json` | AnalogJ/scrutiny `webapp/backend/pkg/models/testdata/smart-ata.json` | 7.0 | WDC WD140EDFZ HDD, healthy |
| `scrutiny-ata-ssd-healthy.json` | scrutiny `smart-ata-full.json` | 7.0 | Samsung 860 EVO, healthy |
| `scrutiny-ata-ssd-crc199.json` | scrutiny `smart-ata-failed-scrutiny.json` | 7.0 | Samsung 840, attr 199 raw 108 (link CRC) |
| `scrutiny-open-failed.json` | scrutiny `smart-fail.json` | 7.0 | exit 2, open failed, no device data |
| `scrutiny-usbjmicron-hdd-failing.json` | scrutiny `smart-fail2.json` | 7.1 | Hitachi HDD via usbjmicron, exit 216, passed false, attr 5=1975, 197=8 |
| `scrutiny-nvme-media-errors.json` | scrutiny `smart-nvme-failed.json` | 7.0 | Samsung 970 EVO, media_errors 7 |
| `scrutiny-sat-partial.json` | scrutiny `smart-sat.json` | 7.0 | sat, no model / smart_status / user_capacity |
| `scrutiny-scsi-no-smartctl-block.json` | scrutiny `smart-scsi.json` | n/a | SAS Seagate, no `smartctl` block |

Scrutiny: MIT license (`LICENSE-scrutiny`), commit `ac2056d6c3cef4a8dd6fe3e0b8c002d9595da75f`.

## windows/<capture>/ (this machine, Windows 11 26200, non-admin, 2026-10-19)

Captured by `tools/capture_fixtures.py <label>`: frozen scripts `rslib/ps/win-disks.ps1`, `win-pnp-chain.ps1`,
`win-events.ps1` (lookback 168 h, max 50, 300 chars) via `powershell.exe -NoProfile -NonInteractive -EncodedCommand`,
then `smartctl --scan-open -j` and `smartctl -j -x -n standby /dev/pdN` per disk, plus `-d sat` retry when no `smart_status`.
`*.meta.json` = exit code + stderr of that call.

| Capture | Devices | Notable facts |
|---|---|---|
| `baseline-nvme-only` | 2 NVMe (Disk 0 boot/system GPT, Disk 1 MBR) | no USB |
| `usb-stick` | + Disk 2 "General UDisk", USB `VID_ABCD&PID_1234`, 8054112256 B | smartctl exit 1 "Unknown USB bridge [0xabcd:0x1234]"; `-d sat` exit 2 "Open failed, Error=5" (non-admin); Get-Disk SerialNumber `"\t"`, Get-PhysicalDisk SerialNumber null; UniqueId = `USBSTOR\...:<HOSTNAME>`; MBR partition type 7 with no volume (filesystem not recognised) |
| `usb-sd` | + Disk 3 "Generic STORAGE DEVICE" (SD card in reader `VID_05E3&PID_0751`), 4026531840 B | FAT32 volume `E:`; SerialNumber `"["`; MBR Signature 0; smartctl same exit 1 / exit 2 pattern |
| `sd-reader-empty` | USB stick + the same SD reader with the card removed (live smoke 2026-10-19) | reader Disk 3: Size 0, OperationalStatus `No Media`, PartitionStyle RAW, IsOffline true -> observation `no_media` (triage must not call it a controller fault) |

## linux/wsl-ubuntu2204/ (this machine's WSL2 Ubuntu 22.04, util-linux 2.37.2, 2026-10-19)

| File | Command | Content |
|---|---|---|
| `lsblk-JOb.json` | `lsblk -J -O -b` | Hyper-V virtual disks (vendor `Msft    ` padded, model `Virtual Disk`, no `tran`, sizes as integers, `rm`/`ro` booleans) |
| `udevadm-sda.txt` | `udevadm info --query=property --name=/dev/sda` | properties of the first virtual disk |

## f3/ (real F3 8.0 output, this machine's WSL2 Ubuntu 22.04, volume mounted via drvfs, 2026-10-19 / 2026-10-20)

Verbatim stdout+stderr as the operator captured it (amendments 06, 07); no identifiers (checked with
`tools/redact_fixtures.py --check`). Sector = 512 B. The stick and f3write/f3read stick files are byte-identical to the
evidence ingested in the real run (sha256 equal to the store's evidence rows).

| File | Device | Exit code | Content |
|---|---|---|---|
| `f3read-stick-pass.txt` | USB stick D-564ce922bda3 (8054112256 B) | 0 | 8 files, Data OK 7.50 GB (15724108 sectors), Data LOST 0 |
| `f3read-stick-abort134.txt` | same stick, first f3read run | 134 | `Assertion 'size % SECTOR_SIZE == 0' failed` on the partial last file, no summary |
| `f3write-stick-volume-full.txt` | same stick | 0 | files 1-7 OK, `Write failure: Input/output error` on file 8 exactly when the volume became full (drvfs returns EIO instead of ENOSPC); final `Free space: 0.00 Byte` |
| `f3read-card-lost.txt` | 32 GB card D-2bc2a1f8a798 | 0 | Data OK 289.55 MB (592999 sectors), Data LOST 3.38 GB (7079816 sectors, all corrupted, 0 changed, 0 overwritten): f3read 8.0 exits 0 with data lost |
| `f3write-card-partition-full4k.txt` | same card, 294 MiB FAT32 partition (2026-10-20) | 0 | `Write failure: Input/output error` in file 1 when the volume became full (drvfs EIO); final `Free space: 4.00 KB` (less than one 1 MiB f3 block) |
| `f3read-card-partition-cached.txt` | same card partition, f3read right after f3write without a replug (2026-10-20) | 0 | Data OK 289.88 MB (593669 sectors), LOST 0; `Average reading speed: 158.61 MB/s` (Windows host cache through drvfs) |
| `f3read-card-partition-after-replug.txt` | same card partition after an operator replug (2026-10-20) | 0 | same sectors OK, LOST 0; `Average reading speed: 17.38 MB/s` (the card itself) |
| `f3probe-card-limbo.txt` | same card, `f3probe` on the raw device (2026-10-20) | 102 | `Bad news: ... counterfeit of type limbo`; `*Usable* size: 294.90 MB (603959 blocks)`, `Announced size: 30.16 GB (63246336 blocks)` |
| `f3write-card-removed.txt` | same card | 0 | files 1-3 OK, `Write failure` in file 4, `Can't create file /mnt/e/5.h2w` (operator removed the card mid-run); no final Free space line |

Derived:

| File | Base (real) | Field changed | Original value | New value |
|---|---|---|---|---|
| `f3write-stick-volume-full.free1mb.derived.txt` | f3/f3write-stick-volume-full.txt | final `Free space:` line | 0.00 Byte | 1.00 MB (amendment 06 F2: write failure with space left stays fail) |

## No real sample yet

ATA HDD behind a USB dock captured on Windows (HDD capture skipped 2026-10-19); elevated (admin) `-d sat` on USB;
native mmc SD (`/sys/block/mmcblk*`); Linux USB sysfs chain; f3read with non-zero Overwritten;
H2testw log;
ddrescue mapfile from a real run (research quotes the GNU manual example verbatim).

## Derived fixtures (added by test-designer, spec-first freeze 2026-10-19)

Built deterministically from the real files above (builder script kept out of the repo; every change is listed here).
A "logical field" that smartctl emits in two places (NVMe log value and its 7.5 global; POH in the NVMe log, ATA
attribute 9 and `power_on_time.hours`) is changed in all its places so no reader picks a stale copy.

| File | Base (real) | Field changed | Original value | New value |
|---|---|---|---|---|
| `nvme-990pro-x.cw1.derived.json` | smartctl/nvme-990pro-x.json | nvme_smart_health_information_log.critical_warning | 0 | 1 (C10) |
| `nvme-990pro-x.cw8.derived.json` | smartctl/nvme-990pro-x.json | nvme_smart_health_information_log.critical_warning | 0 | 8 (C10, C15) |
| `nvme-990pro-x.spare5.derived.json` | smartctl/nvme-990pro-x.json | available_spare (log) + spare_available.current_percent | 100 | 5 (C10) |
| `nvme-990pro-x.pu79.derived.json` | smartctl/nvme-990pro-x.json | percentage_used (log) + endurance_used.current_percent | 6 | 79 (C10) |
| `nvme-990pro-x.pu80.derived.json` | smartctl/nvme-990pro-x.json | percentage_used (log) + endurance_used.current_percent | 6 | 80 (C10) |
| `nvme-990pro-x.pu99.derived.json` | smartctl/nvme-990pro-x.json | percentage_used (log) + endurance_used.current_percent | 6 | 99 (C10) |
| `nvme-990pro-x.pu100.derived.json` | smartctl/nvme-990pro-x.json | percentage_used (log) + endurance_used.current_percent | 6 | 100 (C10) |
| `nvme-990pro-x.temp85.derived.json` | smartctl/nvme-990pro-x.json | temperature.current | 47 | 85 (= critical_limit_max, C13) |
| `nvme-990pro-x.media3-poh10.derived.json` | smartctl/nvme-990pro-x.json | media_errors (log); power_on_hours (log + power_on_time.hours) | 0; 5017 | 3; 5027 (plan phase-03 step 1 pair; C12, E10) |
| `nvme-990pro-x.poh-back.derived.json` | smartctl/nvme-990pro-x.json | power_on_hours (log + power_on_time.hours) | 5017 | 5007 (C12, E10) |
| `nvme-990pro-x.no-media-errors.derived.json` | smartctl/nvme-990pro-x.json | key nvme_smart_health_information_log.media_errors removed | 0 | absent (C12 n/a, E10) |
| `scrutiny-usbjmicron-hdd-failing.p197-12.derived.json` | smartctl/scrutiny-usbjmicron-hdd-failing.json | attr 197 raw (value+string); POH (attr 9 raw + power_on_time.hours) | 8; 65592 | 12; 65593 (plan C16c) |
| `scrutiny-usbjmicron-hdd-failing.r5up-p197down.derived.json` | smartctl/scrutiny-usbjmicron-hdd-failing.json | attr 5 raw; attr 197 raw; POH (attr 9 + power_on_time.hours) | 1975; 8; 65592 | 1976; 4; 65593 (C12 197 exempt) |
| `scrutiny-ata-ssd-healthy.satafirm.derived.json` | smartctl/scrutiny-ata-ssd-healthy.json | model_name | Samsung SSD 860 EVO 500GB | SATAFIRM S11 (C15; researcher-04 §4) |
| `scrutiny-ata-ssd-healthy.bytes0.derived.json` | smartctl/scrutiny-ata-ssd-healthy.json | user_capacity.bytes | 500107862016 | 0 (C15) |
| `scrutiny-ata-hdd-healthy.p197-1.derived.json` | smartctl/scrutiny-ata-hdd-healthy.json | attr 197 raw (value+string) | 0 | 1 (D23 counters-rising) |
| `scrutiny-ata-hdd-healthy.poh67236.derived.json` | smartctl/scrutiny-ata-hdd-healthy.json | POH (attr 9 raw value+string + power_on_time.hours) | 1730 | 67236 = 65536 + 1700: newest self-test raw 1708 is 65528 h old (amendment 02 E, D23b wrap through verdict set) |
| `scrutiny-ata-hdd-healthy.poh67244.derived.json` | smartctl/scrutiny-ata-hdd-healthy.json | POH (attr 9 raw value+string + power_on_time.hours) | 1730 | 67244 = 65536 + 1708: newest self-test raw 1708 is 0 h old (amendment 02 E counter-case) |
| `scrutiny-scsi-no-smartctl-block.no-serial.derived.json` | smartctl/scrutiny-scsi-no-smartctl-block.json | key serial_number removed | VE12VEKDB058NJLD0RYQ | absent (B22 ambiguous) |
| `smartctl-x-pd0.cw4.derived.json` | windows/baseline-nvme-only/smartctl-x-pd0.json | nvme_smart_health_information_log.critical_warning | 0 | 4 (D24) |
| `smartctl-x-pd0.eui-mismatch.derived.json` | windows/baseline-nvme-only/smartctl-x-pd0.json | nvme_namespaces[0].eui64.ext_id | 61296693158 | 61296693159 (B10 join_conflict) |
| `smartctl-x-pd1.serial-swap.derived.json` | windows/baseline-nvme-only/smartctl-x-pd1.json | serial_number | 4QPHHGYUSU50D9Z | 4QPHHGYUSU50D9Y (D13, D15, G4 swap) |
| `win-events.ntfs55.derived.json` | windows/baseline-nvme-only/win-events.json | events (array) | [] | one entry: time 2026-10-19T23:30:00Z, provider Ntfs, id 55, level 2, message = the verified text in requirements.md Facts verified; level 2 is an assumption (B21) |
| `win-disks.othersig.derived.json` | windows/usb-stick/win-disks.json | disks[Number=2].Signature | 1859593249 | 1859593250 (G3 look-alike stick) |
| `win-disks.twin.derived.json` | windows/usb-stick/win-disks.json | Disk 2 rows (disks, physical, wmi, partitions) duplicated as Disk 3 | no Disk 3 | identical copy numbered 3 (B16, D9) |
| `win-pnp-chain.twin.derived.json` | windows/usb-stick/win-pnp-chain.json | disks[Index=2] duplicated as Index 3 | no Index 3 | identical copy (B16, D9) |
| `win-disks.renumber3.derived.json` | windows/usb-stick/win-disks.json | stick disk number (disks.Number, physical.DeviceId, wmi.Index, partitions.DiskNumber) | 2 | 3 (D14 renumber) |
| `win-pnp-chain.renumber3.derived.json` | windows/usb-stick/win-pnp-chain.json | stick disks[].Index | 2 | 3 (D14) |
| `smartctl-x-pd3.from-pd2.derived.json` | windows/usb-stick/smartctl-x-pd2.json | smartctl.argv device + message path | /dev/pd2 | /dev/pd3 (twin / renumber answers) |
| `smartctl-x-sat-pd3.from-pd2.derived.json` | windows/usb-stick/smartctl-x-sat-pd2.json | smartctl.argv device + message path | /dev/pd2 | /dev/pd3 |
| `smartctl-x-sat-pd2.no-error.derived.json` | windows/usb-stick/smartctl-x-sat-pd2.json | smartctl.messages removed; smartctl.exit_status | Open failed Error=5 message; 2 | absent; 0 (B18 not_exposed) |
| `win-disks.sd-twin.derived.json` | windows/usb-sd/win-disks.json | Disk 3 rows duplicated as Disk 4 (volume copy DriveLetter null) | no Disk 4 | copy numbered 4 (D9b twin card) |
| `win-pnp-chain.sd-twin.derived.json` | windows/usb-sd/win-pnp-chain.json | disks[Index=3] duplicated as Index 4 | no Index 4 | identical copy (D9b) |
| `smartctl-x-pd4.from-pd3.derived.json` | windows/usb-sd/smartctl-x-pd3.json | smartctl.argv device + message path | /dev/pd3 | /dev/pd4 |
| `smartctl-x-sat-pd4.from-pd3.derived.json` | windows/usb-sd/smartctl-x-sat-pd3.json | smartctl.argv device + message path | /dev/pd3 | /dev/pd4 |
| `win-events.ntfs55x3.derived.json` | windows/usb-sd/win-events.json | events (array) | [] | three entries, times 2026-10-19T23:30:00Z / 23:31:00Z / 23:32:00Z, provider Ntfs, id 55, level 2, message = the verified text in requirements.md Facts verified with %1 = `E:` (the card's drive letter in usb-sd win-disks); level 2 is an assumption (amendment 05 R5: one hypothesis evidence item per distinct path/value, with a count) |
| `win-disks.media-online.derived.json` | windows/sd-reader-empty/win-disks.json | disks[Number=3].OperationalStatus | No Media | Online (amendment 03 C14c: same reader, latest observation `no_media` false; Size 0 and everything else verbatim) |
| `ddrescue-manual-1.30.finished.derived.map` | ingest/ddrescue-manual-1.30.map (researcher-04 §1) | status char of the status line and of every block line; positions and sizes verbatim | ? then + - / * ? | + everywhere (D4, D20, G9 complete image); multi-field, see test-designer open questions |
| `ddrescue-finished.980pro.derived.map` | ingest/ddrescue-manual-1.30.finished.derived.map (structure of the GNU manual 1.30 example, researcher-04 §1) | size of the last block line (pos 0x00120000); header comments, status line, first four blocks verbatim | 0x00048000 (floppy, image ends at 1474560) | 0x1D1C0FF6000 = 2000398934016 - 0x120000, image ends at the 980 PRO byte count 2000398934016 (amendment 01 B; D4, D5, D20, D20b, G9 nvme) |
| `ddrescue-finished.990pro.derived.map` | ingest/ddrescue-manual-1.30.finished.derived.map (structure of the GNU manual 1.30 example, researcher-04 §1) | size of the last block line (pos 0x00120000); everything else verbatim | 0x00048000 (floppy, image ends at 1474560) | 0xE8E0C96000 = 1000204886016 - 0x120000, image ends at the 990 PRO byte count 1000204886016 (amendment 01 B; D24, D24b) |
| `ddrescue-finished.hitachi500.derived.map` | ingest/ddrescue-manual-1.30.finished.derived.map (structure of the GNU manual 1.30 example, researcher-04 §1) | size of the last block line (pos 0x00120000); everything else verbatim | 0x00048000 (floppy, image ends at 1474560) | 0x7470AE6000 = 500107862016 - 0x120000, image ends at the Hitachi HDS721050DLE630 user_capacity.bytes 500107862016 of smartctl/scrutiny-usbjmicron-hdd-failing.json (amendment 01 B; G9 hdd) |

## ingest/ (text only from research quotes; no real ddrescue/F3 run exists)

| File | Source | Content |
|---|---|---|
| `ddrescue-manual-1.30.map` | researcher-04 §1 "Mapfile format (verbatim from manual, v1.30 example)", GNU ddrescue manual | verbatim block |
| `f3probe-good.verbatim.txt` | researcher-03 §1 (f3probe.c output lines) | the "Good news ... real thing" line; device name kept as the quoted placeholder X |
| `f3probe-damaged.verbatim.txt` | researcher-03 §1 (f3probe.c output lines) | the "Bad news ... is damaged" line |
| `f3probe-wraparound.verbatim.txt` | researcher-03 §1 (f3probe.c output lines) | the counterfeit line with type wraparound picked from the quoted alternation limbo/wraparound/chain |
| `f3write-no-space.verbatim.txt` | researcher-03 §1 (f3write.c) | No space! |

f3read output with numbers is NOT available (research quotes labels only): f3read cases that need values are
skipped as BLOCKED in the suite.

## Recording substitutions (RecordedRunner, tests/conftest.py)

- `smartctl -j -i -n standby /dev/pdN` (identity probe), `-j -x /dev/pdN` and `-j -i /dev/pdN` are answered with the
  `smartctl-x-pdN.json` capture of the same disk (`-x` output is a superset; identity keys identical).
- `-d sat` forms are answered with `smartctl-x-sat-pdN.json`. Exit codes come from `*.meta.json`.
- Tool-failure cells (G5, B20) use synthetic stdout (empty, or the bytes `{ not json`) and runner flags; they are
  failure injections, not device output.
- Amendment 02 D (test_collect_cli B17b, another disk answering at the path): `smartctl -j -x -n standby /dev/pd1` of
  `baseline-nvme-only` answered with the real `smartctl-x-pd0.json` (990 PRO) or the existing derived
  `smartctl-x-pd1.serial-swap.derived.json`; `smartctl -j -x -n standby -d sat /dev/pd2` of `usb-stick` answered with
  the real `usb-stick/smartctl-x-pd1.json` (980 PRO). Real files, wrong argv: no new fixture.

## In-test single-field mutations (not stored as files)

- test_enum_windows: Disk 1 BusType -> 17 / 7 / "USB"; win-events errors -> one entry (provider disk, error
  SYNTHETIC-ERROR-ID); Ntfs 55 event provider -> disk.
- test_enum_linux: lsblk size -> string; sda ptuuid and tran set.
- test_identity_match: pd0 eui64 ext_id +1; Disk 0 Size -512.
- test_smart_normalise: one extra top-level key added to nvme-990pro-x.
- test_delta: attr 5 raw 1975 -> 1974 (POH equal).
- test_wear: 840 attr 177 name -> Lifetime_Remaining%.
- test_ingest_mapfile: size token of line 10 (0x00000200) -> 0x200, 512, 010, 0o10, -0x200, -512, abc, 12z; status
  char of line 10 -> X; a trailing comment on line 9.
- test_hypotheses: PnP chain VID_ABCD&PID_1234 -> VID_05E3&PID_0751.
- test_verdict D23b (amendment 02 E): self-test tables built in the test from the numbers stated in the amendment
  (pass at 10000 with POH 70000; pass raw 4500 / fail raw 4564 with POH 70100; boundary 4464 / 4463; wrap order raw
  30 / 65530 with POH 65600) in the smartctl `ata_smart_self_test_log.standard.table` entry shape of
  `scrutiny-ata-hdd-healthy.json`; spec numbers, not device output. The real wrapped log is
  `scrutiny-usbjmicron-hdd-failing.json` (POH 65592, entries 42, 18, 4, 65530, ...), read unchanged.
- test_identity_drift / test_collect_cli B16b (amendment 02 A): no new data; the look-alike stick is the existing
  `win-disks.othersig.derived.json`.
- test_ingest_mapfile / test_datastate (amendment 01 B): the 980 PRO full-coverage map with its third block line
  (`0x00117200  0x00001000  +`) removed (gap -> not contiguous); the same map with the first block pos
  0x00000000 -> 0x00000200 and size 0x00117000 -> 0x00116E00 (contiguous, starts at 512, ends at the device byte count).
