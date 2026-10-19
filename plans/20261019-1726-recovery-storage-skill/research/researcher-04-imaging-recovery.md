# Research Report: Imaging and recovery tooling for the `recovery-storage` skill
Date: 2026-10-19 (rev 2: gaps closed, unsourced claims dropped or moved to Unresolved)

## Summary
Image first with GNU ddrescue plus a mapfile; never run chkdsk, fsck, badblocks -w or any repair on the source. Windows 11: WSL2 `wsl --mount ... --bare` (verified locally by the coordinator), Linux live USB as fallback. TestDisk/PhotoRec run on the image copy; scripted `/cmd` syntax is now sourced. Encrypted media (BitLocker, bridge-encrypted USB drives) need the key or the original hardware; image the raw device and keep keys.

Rule in this report: a statement without a cited URL is marked [UNVERIFIED] and is not a basis for a hard skill rule.

## Method
Fetched: GNU ddrescue manual, cgsecurity wiki (Step By Step, Scripted run), Debian man pages (photorec, testdisk, dislocker), WD support KB (via search), Microsoft Learn manage-bde unlock (via search). Search budget exceeded at coordinator request.

## Findings

### 1. ddrescue ([manual](https://www.gnu.org/software/ddrescue/manual/ddrescue_manual.html))
- "Always use a mapfile unless you know you won't need it." Interrupt and resume with the same mapfile; saved periodically, `.bak` kept.
- "Never try to rescue a r/w mounted partition." "Never try to repair a file system on a drive with I/O errors; you will probably lose even more data."
- Manual pattern: pass 1 `ddrescue -f -n SRC DST mapfile`; pass 2 `ddrescue -d -f -r3 SRC DST mapfile`.
- Options (manual): `-n` skip scrape; `-d`/`--idirect` direct read; `-r N` retries (-1 infinite); `-R` reverse all passes; `-c` cluster size ("try smaller values for slow drives"); `-b` sector size; `-i`/`-s` domain start/size; `-a`/`--min-read-rate`; `-T`/`--timeout` max time since last good read; `-X` max read errors; `-E` max error rate; `-e` max bad areas; `--pause-on-error`; `--reset-slow`; `-A` re-mark non-trimmed/non-scraped as non-tried; `-M` retrim; `--odirect`; `-W` compare-before-write ("may reduce wear" on SSD).
- Stop criteria: ddrescue knobs are `-T`, `--min-read-rate`, `-X/-E/-e`. Heat, clicking, SMART growth are skill-level checks (section 5), not ddrescue features.
- Output image goes to a different healthy drive; never the source.

#### Mapfile format (verbatim from manual, v1.30 example)
```
# Mapfile. Created by GNU ddrescue version 1.30
# Command line: ddrescue -d -c18 /dev/fd0 fdimage mapfile
# Start time:   2015-07-21 09:37:44
# Current time: 2015-07-21 09:38:19
# Copying non-tried blocks... Pass 1 (forwards)
# current_pos  current_status  current_pass
0x00120000     ?               1
#      pos        size  status
0x00000000  0x00117000  +
0x00117000  0x00000200  -
0x00117200  0x00001000  /
0x00118200  0x00007E00  *
0x00120000  0x00048000  ?
```
- `#` at line start or after whitespace = comment. First non-comment line = status line (`current_pos current_status current_pass`). Then block lines: "2 non-negative integers and a status character" (pos, size in bytes).
- Status-line chars: `?` copying, `*` trimming, `%` sweeping, `/` scraping, `-` retrying, `F` filling, `G` generating approximate mapfile, `+` finished. Block chars: `?` non-tried, `*` non-trimmed, `/` non-scraped, `-` bad sector(s), `+` finished.
- Number format: written as `0x` hex in the 1.30 example. Manual: "If you edit the file, you may use decimal, hexadecimal, or octal values, using the same syntax as integer constants in C++, except for current_pass, which must be a decimal integer." Hence a robust parser must accept all three: a leading `0` without `x` means OCTAL (e.g. `010` = 8). Python `int(s, 0)` handles `0x`/`0o` but raises on `010`; write a custom parse. Which older versions wrote decimal is not sourced [UNVERIFIED]; the "logfile" name was used before "mapfile" [UNVERIFIED].
- Parser rule: skip comment lines; skip the first non-comment line (status); sum sizes per block char. rescued% = sum(`+`) / sum(all sizes); bad bytes = sum(`-`); unfinished = sum(`?*/`). Note: sizes of `*` and `/` are not yet proven bad, so report them separately.
- ddrescuelog: `-t` = "Print a summary of the contents of each mapfile to the standard output"; `-D` tests whether all blocks in the rescue domain are rescued; `-d` deletes the mapfile if the rescue is finished; `-l types` lists blocks; `-b` block size (default 512). The manual has no sample `-t` output, so the layout is UNSOURCED: the skill must parse the mapfile itself and use `-t` only for display. Example in manual: `ddrescuelog -l- -b4096 mapfile > badblocks1` then `e2fsck -v -f -L badblocks1 /dev/sdb1` (bad-block list for fsck of the COPY).

### 2. ddrescue on Windows 11
- WSL2 `wsl --mount \\.\PHYSICALDRIVEN --bare`: verified locally by coordinator (not re-checked). Disk must be Offline in Windows.
- usbipd-win: USB only; `usbipd list`, `bind`, `attach --wsl`; appears as `/dev/sdX`; Windows loses access while attached ([wiki](https://github.com/dorssel/usbipd-win/wiki/WSL-support), [Intel guide](https://docs.openedgeplatform.intel.com/2026.1/edge-ai-suites/ai-suite-federal-and-aerospace/edge-node-infrastructure-blueprint/how-to/set-up-windows-wsl.html)).
- Linux live USB: fallback when WSL shows I/O errors (judgement, not sourced).
- Native Windows tools (DMDE, OSFClone, HDDSuperClone, Roadkil, Cygwin): no source fetched; capabilities [UNVERIFIED], do not encode into rules.

### 3. TestDisk / PhotoRec ([Scripted run](https://www.cgsecurity.org/testdisk_doc/scripted_run.html), [man photorec](https://manpages.debian.org/testing/testdisk/photorec.8.en.html), [man testdisk](https://manpages.debian.org/testing/testdisk/testdisk.8.en.html), [Step By Step](https://www.cgsecurity.org/wiki/TestDisk_Step_By_Step))
- Man pages list only `/log` ("create a photorec.log / testdisk.log file") and `/debug` ("add debug information"); testdisk also `/dump`, `/list` ("display current partitions"). Synopsis: `photorec [/log] [/debug] [/d recup_dir] [device|image.dd|image.e01]`. `/cmd` is documented only on the wiki Scripted run page.
- PhotoRec scripted form: `photorec [/debug] [/log] [/logname file.log] [/d recup_dir] [/cmd <device> <command>]`. Commands comma-separated. Example for the skill: `photorec /log /d OUTDIR /cmd image.dd partition_none,fileopt,everything,enable,search`.
  - `/d`: output dir; "should be on a different device from the source"; if it exists PhotoRec appends `.1`, `.2`.
  - Commands: partition type (`partition_none`, `partition_i386`, `partition_gpt`, ..., `ask_type` from 6.9; autodetect if omitted); `fileopt` with `everything,enable|disable` (6.9+) or `<type>,enable|disable` (e.g. `jpg,enable`); `options` then `expert`, `keep_corrupted_file[_no]`, `paranoid[_no|_bf]`, `lowmem`, `mode_ext2`; `wholespace` or `freespace` (6.10+); `blocksize`; `search` starts recovery.
  - Order matters: a typical file-type-restricted run is `partition_none,fileopt,everything,disable,jpg,enable,search`.
- TestDisk scripted form: `testdisk [/debug] [/log] [/logname file.log] /cmd [file.dd|file.e01|device] cmd`. Menus: `analyze`, `list`, `advanced`, ...; commands `write` and `noconfirm,write` exist and WRITE the partition table, so an automated skill must never emit them against a source; use only on a copy of the image. `/list` is a read-only listing.
- Writes: TestDisk changes disk only after choosing "Write" and confirming (y/Enter) ([Step By Step](https://www.cgsecurity.org/wiki/TestDisk_Step_By_Step)).
- Image inputs: `.dd`, `.E01`, split `image.???` for both tools. Windows: run as Administrator; admin not needed for images; UAC prompt can be avoided with env `__COMPAT_LAYER=RunAsInvoker` before `photorec_win.exe` (Scripted run page).
- `\\.\PhysicalDriveN`: NOT documented on any fetched page (Linux `/dev/sdX` and DOS names only). Do not assert it works. Skill rule: on Windows pass an image file, or test the device arg in a spike.
- PhotoRec read-only on source: not stated on fetched pages; only the `/d` different-device guidance is sourced. [UNVERIFIED] as an absolute claim.

### 4. SSD / NVMe (vendor lab sources only; positions, not facts)
[Rossmann S11](https://rossmanngroup.com/services/ssd-data-recovery/controllers/phison-satafirm-s11), [PITS S11](https://www.pitsdatarecovery.com/blog/blog-ssd-satafirm-s11-recovery/), [Rossmann: software fails on SSD](https://rossmanngroup.com/problems/why-data-recovery-software-fails-ssd).
- SATAFIRM S11: drive appears as "SATAFIRM S11", capacity 0 B or 8 MB; labs say no OS tool or adapter can read it and flashing may overwrite the FTL. Skill action: detect, do not initialize or format, stop, advise lab.
- TRIM: labs say TRIM-erased data is generally not recoverable by software; timing is drive-dependent and unverified. "Minimise powered-on time" advice has no neutral source.
- ddrescue manual: for flash media, retrying until "the device controller succeeds and remaps the bad sectors internally" can help. No SSD-specific manual section.

### 5. HDD failure signs; why not repair
- Sourced: manual says dd-style sequential reads "may wear out the drive without rescuing anything"; never repair a filesystem on a drive with I/O errors.
- Skill stop triggers (clicking, beeping, spin-up failure, read rate collapse, SMART 5/197/198 rising) are practitioner judgement; no authoritative threshold source found [UNVERIFIED]. Make thresholds configurable.
- `badblocks -w` (destructive write test) and `chkdsk /r` / `fsck` on the source: reasoning follows from the manual quote above; no further source fetched.

### 6. Filesystem repair after imaging
- Sourced: ddrescuelog bad-block list feeds `e2fsck -L` on the copy (manual example).
- ntfsfix limits, exFAT/FAT32 repair tools: no source fetched [UNVERIFIED]. Policy: repair only a copy of the image; prefer read-only mount and file copy first.

### 7. Encryption
- BitLocker: [Microsoft Learn manage-bde unlock](https://learn.microsoft.com/en-us/windows-server/administration/windows-commands/manage-bde-unlock): unlocks "by using a recovery password or a recovery key" (`-RecoveryPassword`/`-rp`, `-RecoveryKey file.bek`; `-password` prompts). Without one of these the volume stays locked (inferred from the docs; no explicit "unrecoverable" sentence fetched).
- dislocker ([man](https://manpages.debian.org/testing/dislocker/dislocker.1.en.html), [README](https://github.com/Aorimn/dislocker)): works on an IMAGE of the encrypted partition: `dislocker -V encrypted.bitlocker -f key.BEK -- /mnt/ntfs` (man recommends a copy so the original is untouched). Methods: `-p` recovery password (prompts if omitted, keeps it off the command line), `-u` user password, `-f` bek file, `-k` FVEK file (66 bytes). Output `dislocker-file` is loop-mounted: `mount -o loop /mnt/ntfs/dislocker-file /mnt/clear`. Supports Vista to 10, AES-CBC/XTS 128/256, BitLocker To Go. Input is a partition image; for a whole-disk image the partition must be exposed first (inference, not sourced). Win 11 default is XTS; coverage of newer versions beyond the README is not sourced.
- Hardware encryption on USB bridges: [WD support KB 15150](https://support.wdc.com/knowledgebase/answer.aspx?ID=15150) (seen via search snippet only): hardware encryption is built in and cannot be changed; a drive removed from some enclosures may not be readable by other enclosures or computers; WD suggests a replacement enclosure of the same make and design. Labs ([Gillware](https://www.gillware.com/hard-drive-data-recovery/western-digital-data-recovery/wd-my-passport-data-recovery/), [Rossmann](https://rossmanngroup.com/services/wd-my-passport-recovery)) state the key lives on the bridge board and that a bare disk shows ciphertext; vendor positions. One SanDisk forum poster says newer Passports integrate the bridge on the drive, conflicting with the labs; treat the model-specific mechanism as unverified.
- "Got HW crypto?" (2015) paper: not found in search. The related [Meijer and van Gastel, IEEE S&P 2019](https://www.ieee-security.org/TC/SP2019/papers/310.pdf) concerns self-encrypting SSDs (Crucial, Samsung T3/T5), not WD bridges; secondary press says BitLocker defers to drive hardware encryption when advertised. I could not read the PDF text.
- Skill rule (supported): ask for keys/passwords first; image through the original enclosure/bridge; never move a bare disk, reset, or change the password; do not format/initialize.

## Recommendation
- Flow: read-only triage (`smartctl`) -> image decision -> ddrescue pass 1/2 with mapfile on separate drive -> own mapfile parser (accept hex/decimal/octal) -> work on copies only.
- Hard bans on the source: chkdsk, fsck, badblocks -w, formatting/initialising, TestDisk `write`/`noconfirm,write`, firmware flashing.
- Spike before coding: (a) does `photorec_win.exe /cmd \\.\PhysicalDrive1 ...` open a device; (b) `ddrescuelog -t` real output on a sample mapfile; (c) dislocker on a whole-disk image.

## Sources
GNU ddrescue manual; cgsecurity Scripted run, Step By Step; Debian man pages (photorec, testdisk, dislocker); dislocker README; Microsoft Learn manage-bde unlock; WD KB 15150; Gillware; Rossmann; PITS; usbipd-win wiki; Intel WSL guide; Meijer/van Gastel IEEE S&P 2019 (URLs inline above).

## Unresolved questions
1. `ddrescuelog -t` exact output; which ddrescue versions wrote decimal vs `0x` (only 1.30 example sourced).
2. `\\.\PhysicalDriveN` acceptance by TestDisk/PhotoRec on Windows; PhotoRec absolute read-only statement.
3. WD bridge-key mechanism per model; original "Got HW crypto?" paper not located.
4. BitLocker on whole-disk image with dislocker; explicit Microsoft statement on key-less unrecoverability.
5. LUKS header-loss claims (dropped, unsourced); ntfsfix/exFAT tools; SMART stop thresholds; neutral SSD/TRIM sources; native Windows imaging tools.
