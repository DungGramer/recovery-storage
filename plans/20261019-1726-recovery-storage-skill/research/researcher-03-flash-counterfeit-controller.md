# Research Report: Flash counterfeit detection, controller recovery, SD/USB health
Date: 2026-10-19 (rev 2: F3 source, H2testw, WSL gaps closed)

Legend: [V] verified from a primary source read this session (cited); [M] model memory, NOT verified.

## Summary
Recommendation: the skill should IDENTIFY and GUIDE, never flash. Use F3 as the authority on capacity fraud: f3probe for a fast verdict (Linux, USB only), f3write/f3read for a full verify (any host with a mounted filesystem). Identity data (VID/PID, iSerial, controller name, SD CID) is supporting evidence only. Classify from evidence, never from brand/capacity: (a) fake capacity (f3probe type limbo/wraparound/chain, or f3read Overwritten/Lost), (b) modified firmware/relabelled identity (identity mismatch but capacity passes), (c) genuine-but-failing (f3probe "damaged", read errors, read-only lock).
Controller reflashing (MPTool) is vendor-specific, data-destroying, brick-prone: skill prints identification and pointers, requires explicit confirmation, and does not automate it.
Skill can parse f3probe via exit code AND text (exit codes now verified from source, see below).

## Method
Read primary sources: GitHub AltraMayor/f3 (API: default branch `master`; README.rst, doc/usage.rst, src/f3probe.c, f3read.c, f3write.c, f3brew.c, libutils.h/.c, libdevs.c), readthedocs usage, heise H2testw page, Microsoft Learn "Connect USB devices", GRC ValiDrive. Searches: iFlash/ChipGenius, SD CID/CSD, WSL usbipd mass storage. Note: repo has README.rst (not .md; earlier 404).

## Findings

### 1. F3 suite
- Platforms [V: README.rst "Compile stable software on ..."]: f3write/f3read build on Linux, FreeBSD, macOS (Homebrew `brew install f3`, MacPorts), Windows via Cygwin (needs gcc-core, make, libargp-devel, special build flags). f3probe, f3fix, f3brew are "extra applications": Linux only (libudev v1, libparted v0), built with `make extra`; README says they require Linux and on Mac/Windows to use the Docker image (`docker run --rm --device /dev/sdX peron/f3 f3probe ...`); README warns device passthrough is "tricky" on Mac/Windows. Pre-built Windows native f3probe: not offered.
- f3probe [V: usage docs + f3probe.c]:
  - Root; target is the whole unmounted block device (`/dev/sdX`), not a partition. Source rejects devices not backed by USB: "is not backed by a USB device" (libdevs.c). So built-in/PCIe SD readers cannot be probed; use f3write/f3read.
  - Default (conservative) mode saves blocks, probes, restores ("recovering blocks... Done"); a crash means no restore and some fakes cannot be restored exactly. Out-of-memory message in source: "try f3probe --destructive ... Please back your data up". `--destructive` ignores contents, nothing restored; README example: `f3probe --destructive --time-ops /dev/sdX` with warning "This will destroy any previously stored data". `--min-memory` reduces RAM. `--time-ops` adds "Operation: total time / blocks = avg time" lines for Read/Write (I/O speeds only reported with --destructive per source comment) and Reset. Marked experimental in docs.
  - Output lines (f3probe.c): `Good news: The device `X' is the real thing`; `Bad news: The device `X' is damaged`; `Bad news: The device `X' is a counterfeit of type limbo|wraparound|chain`, followed by hint commands `f3brew --fix-cmd --end-at=<last_good_block> X` and `f3fix --last-sec=<last_good_sector> X`; geometry lines `*Usable* size:`, `Announced size:`, `Module:` (power of 2, wrap parameter), `Approximate cache size:`, `Physical block size:`, then `Probe time:`.
  - Exit codes [V: f3probe.c line 561 `return fake_type == FKTY_GOOD ? 0 : 100 + fake_type;` and enum in libutils.h]: 0 good; 101 damaged (BAD); 102 limbo; 103 wraparound; 104 chain. Arg/setup failures exit 1 or errno-like non-zero (not 10x). So `$? == 0` is a pass; 10x are verdicts, not tool errors. Also treat any other non-zero as "inconclusive".
  - Types semantics [V: libutils.h comments]: limbo = discards data after a limit; wraparound = overwrites data after a limit; chain = sequence of wraparound and limbo regions; damaged = at least partially damaged.
  - Runtime [V: docs]: 16 GB fake about 1m13s; genuine 3.77 GB about 10m in conservative mode.
- f3write/f3read [V: f3write.c, f3read.c, libutils.c]: f3write ("fill a drive out with .h2w files") prints `Free space: X unit`, `Creating file N.h2w ... OK!`, then free space and `Average writing speed`; if no space prints `No space!` and returns 1; write errors print `Write failure: <errno text>` (EIO hint: overheating, use --max-write-rate). Writes into free space of a mounted FS as N.h2w files (1 GB each); existing files are not modified, but the volume is filled; remove .h2w afterwards. f3read summary (libutils.c): `Data OK:`, `Data LOST:`, then indented `Corrupted:`, `Slightly changed:`, `Overwritten:`, then `Average reading speed:`. Exit codes: f3read returns 1 if any bad/changed/overwritten sectors (or not all read), else 0; f3write returns 0 normally, 1 on "No space!". Parse the text lines for numbers; use exit code of f3read as pass/fail.
- f3fix [V: usage docs, README]: partition covering usable size from `--last-sec=N` of f3probe; rewrites partition table; then mkfs and re-test. Linux only. Cosmetic, device stays fake.
- f3brew [V: f3brew.c doc string + f3probe hint]: "F3 Block REad and Write -- assess the media of a block device writing blocks, resetting the drive, and reading the blocks back". Block-device test over a block range (`--start-at`, `--end-at`, `--reset-type`, `--max-read-rate`), `--fix-cmd` shows the f3fix command. Linux only, writes to the device (treat as destructive); f3probe's hint says to use it to check all blocks in the usable area. Skill: do not run without confirmation.

### 2. Windows tools
| Tool | Reads | Writes? | CLI | Notes |
|---|---|---|---|---|
| H2testw 1.4 (2008) [V: heise.de/download/product/h2testw-50539] | none | yes: random data in files up to 1 GB each until the medium is full, then reads back and compares | none; page describes run EXE and choose drive (GUI), and points to F3 for command-line on other OSes | Portable, Windows-only, works on Win 10/11 per page. Format first with single partition, move data off; it also overwrites deleted data. False positives from adapters, cables, RAM. Writes files in free space, not raw device. |
| ValiDrive (GRC) [V: grc.com/validrive.htm] | random spot-check across declared capacity, access times, drive map | yes (random test data, read back) | none documented | Sampling not full; page text ambiguous on coverage. |
| FakeFlashTest [M] | sector-level test | yes | GUI | Unverified. |
| ChipGenius [V partial] | VID/PID, controller vendor/model, flash ID | no | GUI | Many untrusted mirrors. |
| ChipEasy [V: pendriveapps.com] | controller brand/model, VID/PID, firmware (Phison, Alcor, Chipsbank) | no | GUI portable | |
| Flash Drive Information Extractor [M] | VID/PID, controller, chip info | no | GUI | Unverified. |
Scripting [M]: Windows native read-only identity via `Get-CimInstance Win32_DiskDrive` (PNPDeviceID has VID/PID, serial), `Get-PnpDevice`; Linux `lsusb -v`, `udevadm info`, `smartctl -d sat` (often unsupported on USB sticks).

### 2b. WSL2 + usbipd-win for f3probe
- Microsoft Learn (updated 2026-06) [V]: usbipd-win 5.0+, Win 11 22000+ (Win 10 via Store WSL), WSL kernel >= 5.10.60.1; flow `usbipd list`, `usbipd bind --busid X` (admin), `usbipd attach --wsl --busid X`, then `lsusb` in WSL. While attached, Windows cannot use the device. The doc never mentions block devices or mass storage.
- GitHub microsoft/WSL#11335 [V via search snippet]: "CONFIG_USB_STORAGE not enabled in default kernel" on WSL 2.1.5.0 (kernel 5.15.146.1-2) with a UAS device; no resolution seen. Hence attach may succeed (`lsusb` shows it) while no `/dev/sdX` appears; a custom kernel with USB mass storage + UAS may be required. An Intel guide claims the drive appears as `/dev/sdb` (lsblk) but that is vendor documentation for a specific setup.
- Verdict: NOT guaranteed. Skill should check `lsblk`/`dmesg`/`lsmod` (usb-storage, uas) after attach and fall back to f3write/f3read on Windows or a Linux live USB. Even if /dev/sdX appears, f3probe also checks udev for a USB backing device (libdevs.c), which usbipd-attached devices normally satisfy [M, untested]. Practical test on the target machine is required.

### 3. Signs of fake capacity / modified firmware
- Wraparound/limbo: f3probe type; f3read `Overwritten` (wrap) or large `Data LOST` (limbo).
- Reported size vs NAND capacity: controller tools show Flash ID decoding to smaller size than OS reports [M].
- VID/PID mismatch: a "SanDisk" labelled drive with Alcor/Chipsbank VID/PID or generic strings; legit SanDisk normally VID 0781 [M]. Suggestive, not proof (OEM rebrands). Generic/duplicated serial, blank iSerial: weak signals. Modified firmware can spoof strings, so identity is never decisive [M].
- "Format succeeded" proves nothing: formatting writes only filesystem metadata; a fake declares a large size and discards/aliases writes beyond real NAND; only write-then-read of the whole range exposes it (F3 intro: "fills the device with pseudorandom data and then checks if it returns the same" [V: README.rst]).
- Genuine-but-failing: f3probe `damaged` (exit 101), I/O errors in dmesg/Event Log, speed collapse, with Usable == Announced.

### 4. Controller recovery (MPTool)
- Concept [M]: vendor MP tools (Phison, SMI, Alcor, Chipsbank, Innostor) rewrite firmware, bad-block map, capacity, VID/PID; tool version must match controller revision and NAND flash ID; mismatch gives wrong capacity or brick; all data erased.
- flashboot.ru iFlash [V secondhand]: VID/PID + flash ID database mapping to controller and MP tools; Russian; same VID/PID spans several models so VID/PID is insufficient. Workflow: ChipGenius/ChipEasy then iFlash then vendor tool (low-quality secondary sources; flashboot.ru itself not fetched).
- Realistic for skill: collect read-only identifiers, report mismatch evidence, give lookup pointer, refuse to automate flashing; require image/backup first and typed confirmation. Never choose firmware by brand/capacity.

### 5. Health and registers
- USB sticks: generally no SMART. Industrial vendor tools (SanDisk Industrial, Swissbit, Kingston, ATP, Apacer) exist [M], names/commands unverified.
- SD CID [V: sming/RIOT docs]: MID 8b, OID 16b, PNM 40b, PRV 8b, PSN 32b, MDT 12b, CRC7; MID/OID assigned by SD Association; contents programmable by vendor tools, counterfeits may copy them: hint not proof. Linux native mmc: `/sys/block/mmcblk0/device/{cid,csd,manfid,oemid,name,date,serial}`; USB card readers usually hide CID/CSD [M].
- CSD [V partial]: PERM_WRITE_PROTECT and TMP_WRITE_PROTECT bits (SD Physical Layer v5.00 section 5.3.2); programmable by CMD27; permanent bit not clearable [M]; TMP semantics not confirmed.
- Write protect [M]: LOCK switch on SD/microSD adapter (host-read; a broken switch yields read-only); OS read-only attribute; controller-enforced read-only at NAND end-of-life (data readable: image first, do not format); permanent CSD bit. No primary source found for the end-of-life behaviour.

### 6. Safe authenticity procedure
1. Identify with read-only commands; user confirms target (model, size, serial).
2. Image/copy data first (ddrescue). F3 conservative mode is not a backup.
3. Quick: `f3probe --time-ops /dev/sdX` (root, whole disk, USB only); `--destructive` only after explicit confirmation that data is gone. Interpret exit code 0/101-104.
4. Full: mount, `f3write <mnt>` then `f3read <mnt>`; pass = f3read exit 0 and Data LOST 0. Write cost = free space once (one program/erase cycle over the volume) plus a full read; hours on large cards.
5. After verdict: delete .h2w files; for fakes optional f3fix (confirm) or replace. Never reformat/reflash a genuine-failing device before imaging.
6. Windows: H2testw (GUI, free-space files) or F3 via Cygwin build/WSL; ValiDrive for a fast sample (writes; may miss partial fakes).

## Sources
- F3 repo (default branch master): https://github.com/AltraMayor/f3 ; README https://raw.githubusercontent.com/AltraMayor/f3/master/README.rst ; source https://github.com/AltraMayor/f3/tree/master/src (f3probe.c, f3read.c, f3write.c, f3brew.c, libutils.h, libdevs.c)
- F3 docs: https://fight-flash-fraud.readthedocs.io/en/stable/usage.html
- Heise H2testw: https://www.heise.de/download/product/h2testw-50539
- GRC ValiDrive: https://www.grc.com/validrive.htm
- Microsoft Learn: https://learn.microsoft.com/en-us/windows/wsl/connect-usb ; issue https://github.com/microsoft/WSL/issues/11335 (snippet only)
- usbipd-win: https://github.com/dorssel/usbipd-win
- ChipEasy: https://pendriveapps.com/chipeasy-usb-flash-drive-information-tool ; iFlash: http://flashboot.ru/iflash/ (secondhand)
- CID: https://sming.readthedocs.io/en/latest/api/structStorage_1_1SD_1_1CID.html ; https://riot-os.readthedocs.io/generated/file/sdcard__spi_8h.html

## Unresolved questions
1. Does a usbipd-attached stick appear as /dev/sdX on current default WSL kernel (issue #11335 outcome)? Needs a test on the target machine.
2. FakeFlashTest and Flash Drive Information Extractor behaviour and CLI (primary sources not read); ChipGenius trusted download source.
3. Vendor health tools (SanDisk Industrial, Swissbit, Kingston, ATP): names, commands, platforms.
4. Primary evidence for controller-enforced read-only at end of life; TMP_WRITE_PROTECT semantics (SD Physical Layer spec).
5. flashboot.ru iFlash query format and terms; MP tool download provenance.
6. f3probe exit code for argument/device errors beyond exit(1): not fully enumerated.
