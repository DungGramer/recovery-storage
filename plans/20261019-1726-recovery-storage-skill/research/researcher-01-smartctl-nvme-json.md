# Research Report: smartctl / nvme-cli JSON for recovery-storage skill
Date: 2026-10-19

## Summary
Use `smartctl` (smartmontools 7.5, 2025-04-30) as the single collector on Windows and Linux: it covers ATA, SCSI/USB-SAT and NVMe (native and via USB bridges) and emits one JSON schema. nvme-cli is optional, Linux-only in practice. Always parse `smartctl.exit_status` as a bitmask, never as pass/fail. Bits 0,1,2 mean "collection failed"; bits 3,4 mean "drive failing"; bits 5,6,7 are historical warnings.
Read-only whitelist: `--scan-open`, `-i -H -A -c -l error -l selftest -l xerror -x -a -j`, `-n standby`. Everything with `-s`, `-S`, `-o`, `-t`, `-C`, `-X`, `-g`-with-value, `-d ...,x` unsafe overrides is a state change (R1 or higher).
The smartmontools.org wiki is behind Anubis bot protection (HTTP "Access Denied") and could not be read. Claims below come from the man page source and C++ source on GitHub (authoritative, master = 7.5 line). USB/SAT wiki lore is marked unverified.

## Method
Fetched raw man page `smartctl.8.in`, `NEWS`, `smartctl.cpp`, `ataprint.cpp`, `nvmeprint.cpp`, `scsiata.cpp` from github.com/smartmontools/smartmontools; nvme-cli `src/nvme-print-json.c`, releases; Scoop/winget manifests; 1 web search. Dates 2025-2026.

## 1. JSON keys (smartctl -j -x)
Flags `--json=c` compact, `g` gron-style, `o` embeds plaintext in `smartctl.output[]`, `s` sorted, `v` verbose unsafe ints (`KEY_s` string companions for >53-bit) [man: smartctl.8.in L327-370].
Globals: `json_format_version` = `[1, 0]` (hardcoded) [smartctl.cpp L80-81]; `smartctl.exit_status` [smartctl.cpp L1706]; `smartctl.messages[]` with `string` and `severity` (only non-empty; e.g. open failures) [L1362-1364]; `smartctl.output[]` only with `o`.
Device identity (ataprint.cpp / nvmeprint.cpp key lists): `device` (`name`, `info_name`, `type`, `protocol`), `model_name`, `model_family`, `serial_number`, `firmware_version`, `wwn`, `user_capacity` (`blocks`, `bytes`), `logical_block_size`, `physical_block_size`, `rotation_rate` (0 = SSD), `form_factor`, `interface_speed`, `in_smartctl_database`, `smart_support` (`available`, `enabled`), `power_mode` (with `-n`).
Health: `smart_status.passed` (bool). NVMe adds `smart_status.nvme.value` plus bit booleans (see 5) [nvmeprint.cpp L448-480].
ATA attrs: `ata_smart_attributes.table[]` each with `id`, `name`, `value`, `worst`, `thresh`, `when_failed` (`"now"`, `"past"`, or `""`), `flags{value,string,prefailure,updated_online,performance,error_rate,event_count,auto_keep}`, `raw{value,string}` [ataprint.cpp L1334-1353]. Also `ata_smart_data`, `ata_smart_error_log` (`summary.count`, `summary.logged_count`, `extended`), `ata_smart_self_test_log` (`standard.table[]`, `standard.count`), `ata_smart_selective_self_test_log`, `ata_sct_status`, `ata_sct_temperature_history`, `ata_sct_erc`, `ata_device_statistics`, `ata_pending_defects_log`, `sata_phy_event_counters`, `seagate_farm_log` (7.5).
Convenience globals (ATA, SCSI, NVMe): `power_on_time.hours`, `power_cycle_count`, `temperature.current` (Celsius) [ataprint/nvmeprint]. 7.5 adds `endurance_used`, `spare_available` globals and `power_mode.*` [NEWS 7.5, L13-18].
NVMe: `nvme_smart_health_information_log` (`critical_warning`, `temperature`, `available_spare`, `available_spare_threshold`, `percentage_used`, `data_units_read`, `data_units_written`, `host_reads`, `host_writes`, `controller_busy_time`, `power_cycles`, `power_on_hours`, `unsafe_shutdowns`, `media_errors`, `num_err_log_entries`, `warning_temp_time`, `critical_comp_time`, `temperature_sensors[]`) [nvmeprint.cpp L489-]; also `nvme_error_information_log`, `nvme_self_test_log`, `nvme_total_capacity`, `nvme_namespaces`, `nvme_version`.
Note: key sets are inferred from source string literals; absent keys must be tolerated (`.get`), since devices omit logs.

## 2. Exit status bitmask [man smartctl.8.in L2494-2522]
- Bit 0 (1): command line did not parse.
- Bit 1 (2): device open failed, no IDENTIFY DEVICE, or device in low-power mode (`-n`).
- Bit 2 (4): a SMART/ATA command failed, or checksum error in SMART structure.
- Bit 3 (8): SMART status "DISK FAILING". (NVMe: critical_warning != 0 sets the same FAILSTATUS [nvmeprint.cpp L839-843]).
- Bit 4 (16): prefail Attributes <= threshold now.
- Bit 5 (32): OK but some attribute was <= threshold in the past.
- Bit 6 (64): error log contains records. Bit 7 (128): self-test log contains errors.
Classification: `status & 0b111` = collection problem (data incomplete or absent, do not call the disk healthy). `status & 0b11000` = failing. `status & 0b11100000` = advisory history. Bit 6/7 are common on old but working drives. Exit 0 with `smart_status` missing means no health verdict.
`-n standby,STATUS` returns a custom status when asleep (man L905-936); pick a value outside 0-255 conflicts, e.g. 3 collides with bits 0,1, so use 0 and check `power_mode`.

## 3. Device naming, scan, USB
Windows names [man L115-182]: `/dev/sd[a-z]` = `\\.\PhysicalDrive0..25` (a=0); `/dev/pd[0-255]` = PhysicalDriveN; drive letters `X:` work for basic disks; `/dev/csmi[0-9],N` Intel RST / AMD RAID ports; `/dev/nvme[0-9]` or `/dev/nvme[0-9]n[1-9]`, `/dev/nvmes[0-9]` (behind `\\.\ScsiN:`) need NVME_PASS_THROUGH_IOCTL; NVMe on stornvme.sys can use `/dev/sd*`/`/dev/pd*` and does NOT need admin for `-x` info, admin only when state changes (`-t`). The `/dev/` prefix is optional.
`--scan` lists name, type, protocol; `--scan-open` also opens each device and may change the type via autodetection; `-d TYPE` can be repeated to combine scans [man L298-318]. Per source, JSON scan emits `devices[]` with `name`, `info_name`, `type`, `protocol`, and `open_error` when open fails [smartctl.cpp L1519-1561]. `-d test` prints guessed then final type and exits [man L395-410].
USB bridge types [man L440-520]: `sat[,auto][,12|16]` (default 16-byte; `sat,auto` uses SAT only if INQUIRY vendor "ATA     "), `usbjmicron[,p][,x][,PORT]`, `usbcypress`, `usbasm1352r,PORT` (7.4+), and NVMe bridges `sntasmedia[/sat]`, `sntjmicron[,NSID][/sat]`, `sntrealtek[/sat]` (the `/sat` fallback suffix is marked "NEW EXPERIMENTAL 7.5"). `-d auto` guesses from OS info or a matching USB ID in the drive database (`drivedb.h`).
No-SMART USB sticks / SD readers: source shows error strings "Unknown USB bridge %s", "Unsupported USB bridge %s", "USB bridge %s type is ambiguous" [scsiata.cpp L1525-1539] and "Please specify device type with the -d option." [smartctl.cpp L1631]; open failure prints "Smartctl open device: %s failed: %s" [L1661]. Expect a non-zero exit with bit 1 (open/IDENTIFY failed) and/or bit 2, plus entries in `smartctl.messages`. Exact exit value for a plain flash stick not verified on hardware.
Recommended probe order for a USB disk: autodetect; if no health data, try `-d sat`; for NVMe enclosures `-d sntjmicron`, `sntasmedia`, `sntrealtek`; stop after first working type.

## 4. Read-only vs state-changing
Read-only (report only): `-i`, `-H`, `-A`, `-c`, `-a`, `-x`, `-l error|xerror|selftest|selective|directory|devstat|sataphy|scttemp...`, `-g` (get only), `--scan[-open]`, `-n`, `-q`, `-j`, `-V`, `-d test`. Caveat: `-x` can touch many logs and slow weak bridges; this is still reads. CSMI on AMD RAID is read-only by default (writes need registry CSMI=Full) [man L157-168].
State-changing: `-s on|off` (enable/disable SMART; also `-s aam/apm/wcache/lookahead/standby,now/security-freeze`, `-s` set mode) [man L1096-1135], `-S on|off` (attribute autosave), `-o on|off` (automatic offline test), `-t short|long|conveyance|offline|select,...|vendor,N` (starts a self-test), `-C` (captive; "may busy out the drive", unmounted only), `-X` (abort), `-b`/`-f` are only error-handling modifiers, `-r ataioctl` debug, `-d ...,x` / `usbcypress,0xN` overrides ("risk of damage") [man L460-480]. Man says `-t` needs admin on Windows NVMe [man L181-183].
Self-test classification: `-t short|long` is non-destructive to data but changes device state (writes self-test log, load, may keep drive busy), so R1, never captive (`-C`) in this skill. Recommend whitelisting by argv allowlist, not by denylist.
Also note: an unsupported `-x` call on a disabled-SMART drive does not enable it (needs `-s on`), so report "SMART disabled" and stop.

## 5. nvme-cli JSON
`nvme smart-log /dev/nvme0 -o json` keys [nvme-cli src/nvme-print-json.c L814-846]: `critical_warning` (int, or object in some modes with `value`, `available_spare`, `temp_threshold`, `reliability_degraded`, `ro`, `vmbu_failed`, `pmr_ro`), `temperature` (Kelvin in raw JSON, verify), `avail_spare`, `spare_thresh`, `percent_used`, `data_units_read`, `data_units_written`, `host_read_commands`, `host_write_commands`, `controller_busy_time`, `power_cycles`, `power_on_hours`, `unsafe_shutdowns`, `media_errors`, `num_err_log_entries`.
Critical warning bits: 0x01 spare below threshold, 0x02 temperature, 0x04 reliability degraded, 0x08 read-only media, 0x10 volatile backup failed, 0x20 PMR read-only/unreliable (confirmed in smartctl source for same bits [nvmeprint.cpp L457-478]). Smartctl names: `available_spare`, `available_spare_threshold`, `percentage_used` (differ from nvme-cli's `avail_spare`, `spare_thresh`, `percent_used`).
Other commands: `nvme id-ctrl -o json`, `nvme error-log -o json` exist (standard nvme-cli commands); JSON key names for these not extracted here.
Windows: nvme-cli v3.1 (latest release) has a "Fix the Windows build" change and `meson.build` has `host_system == 'windows'` branches, but README lists only Linux distros/FreeBSD and I found no official Windows binary. Decision: use smartctl for NVMe on Windows; nvme-cli optional on Linux, with smartctl JSON as primary.

## 6. Windows install
- winget: `winget install smartmontools.smartmontools` (id confirmed in winget-pkgs manifest, v7.5, nullsoft installer, `Scope: machine` so admin/UAC to install) [github.com/microsoft/winget-pkgs manifests/s/smartmontools].
- Scoop: `scoop install smartmontools` (Main bucket, v7.5, extracts with 7z, shims `smartctl.exe`, `smartctl-nc.exe`, `smartd.exe`, no admin) [github.com/ScoopInstaller/Main bucket/smartmontools.json].
- Chocolatey: package `smartmontools` v7.5.0 exists (nupkg HTTP 200). Needs admin.
- Default install path (installer): `C:\Program Files\smartmontools\bin\smartctl.exe` (unverified in this run; search could not confirm; use `where.exe smartctl` plus that fallback).
- Admin: raw disk access (`\\.\PhysicalDriveN`) normally needs elevation; man says NVMe on stornvme.sys can read info without admin. Plan on "run elevated" and report a clean error otherwise.
- Drive DB: `update-smart-drivedb.ps1` writes into the install dir; skip (network and file write).

## 7. Gotchas
- Standby: `-n standby` skips spinning up a sleeping HDD; exits with bit 1 if asleep, JSON gets `power_mode`. If the user wants data, a second run without `-n` is a deliberate spin-up (state change for HDD, flag it).
- `-T permissive` ignores failures of mandatory SMART commands, "may be given more than once"; can print misleading "Feature X not supported" then "enable failed" [man L800-830]. Use only as a retry on bridges, and mark the result lower-confidence.
- SAT passthrough hangs on some bridges (cheap USB enclosures stall on ATA PASS-THROUGH, or 48-bit commands as noted for JMicron in man L470-475): wrap each smartctl call in a Python subprocess timeout (e.g. kill after a configurable limit) and never run several concurrently on one bridge. Wiki confirmation unverified (wiki blocked).
- Prolific/JM20336 bridges return bogus status bytes [scsiata.cpp L1033-1046]: `smart_status.passed` from such bridges is unreliable, cross-check with attributes.
- Schema: `json_format_version` is `[1,0]` in master; NEWS shows additive changes between 7.x releases (new keys, `model_name` re-added for SCSI, `scsi_temperature` renamed back) [NEWS L12-18,108-120], so key-presence checks are mandatory and save `smartctl_version` from output.
- The 53-bit integer rule: large `raw.value`/`data_units` may exceed JSON safe ints; Python handles it, JS needs `v` option.
- `--json` ignores plaintext, so capture stderr and `messages` too.

## Sources
- https://raw.githubusercontent.com/smartmontools/smartmontools/master/smartmontools/smartctl.8.in
- https://raw.githubusercontent.com/smartmontools/smartmontools/master/smartmontools/smartctl.cpp
- https://raw.githubusercontent.com/smartmontools/smartmontools/master/smartmontools/ataprint.cpp
- https://raw.githubusercontent.com/smartmontools/smartmontools/master/smartmontools/nvmeprint.cpp
- https://raw.githubusercontent.com/smartmontools/smartmontools/master/smartmontools/scsiata.cpp
- https://raw.githubusercontent.com/smartmontools/smartmontools/master/smartmontools/NEWS
- https://raw.githubusercontent.com/linux-nvme/nvme-cli/master/src/nvme-print-json.c
- https://github.com/linux-nvme/nvme-cli (README, releases/latest v3.1, meson.build)
- https://raw.githubusercontent.com/ScoopInstaller/Main/master/bucket/smartmontools.json
- https://github.com/microsoft/winget-pkgs/tree/master/manifests/s/smartmontools/smartmontools/7.5
- https://community.chocolatey.org/packages/smartmontools
- https://www.smartmontools.org/wiki/Download (listed by search; page itself not read)

## Unresolved questions
1. smartmontools.org wiki (USB, FAQ, TocDoc) unreadable behind Anubis; USB hang lore and exact flash-stick output/exit status need a real device test or a browser fetch.
2. Exact key layout of nvme-cli `id-ctrl` / `error-log` JSON and whether `critical_warning` is int or object in `-o json` normal mode (source shows both branches).
3. Whether nvme-cli temperature in JSON is Kelvin (source shows `temperature` int; unchecked conversion).
4. Default winget install dir (`C:\Program Files\smartmontools`) not confirmed; installer is x86 (win32) only in the manifest, also runs on x64.
5. Whether `-n standby` on Windows behind USB bridges reliably reports power mode.
6. Self-test on removable/USB bridges: R1 classification agreed, but caller must decide if `-t short` is ever allowed in the default flow.
