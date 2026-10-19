# Partition and file recovery (TestDisk, PhotoRec) on an image

Sources: cgsecurity.org TestDisk Step By Step and Scripted run pages; Debian man pages for photorec/testdisk.

- Run both tools on the image (`.dd`, `.E01`), not on the source. TestDisk changes a disk only after "Write" plus
  confirmation; its scripted commands `write` and `noconfirm,write` write the partition table and are forbidden on
  the source (the guard hook blocks a `/cmd` list containing write).
- PhotoRec scripted form: `photorec /log /d OUTDIR /cmd image.dd partition_none,fileopt,everything,enable,search`.
  The output directory must be on a different device from the source. File type restriction:
  `partition_none,fileopt,everything,disable,jpg,enable,search` (order matters).
- TestDisk scripted form: `testdisk /log /cmd image.dd analyze,quicksearch` for read-only analysis; `/list` lists
  partitions read-only.
- Windows: `photorec_win.exe` / `testdisk_win.exe`; images need no admin. Passing a raw device such as
  `\\.\PhysicalDrive1` is not documented on the fetched pages [UNVERIFIED]: prefer an image file.
- Filesystem repair: only on a copy of the image. ddrescue can export a bad-block list for `e2fsck -L` on the copy
  (manual example `ddrescuelog -l- -b4096 mapfile > badblocks1`). ntfsfix/exFAT repair limits are unverified.
- Encrypted volumes: BitLocker unlocks with the recovery password or key (`manage-bde -unlock -rp ...`, Microsoft
  Learn); dislocker works on an image of the encrypted partition (`dislocker -V image -p -- /mnt/x`, then loop-mount
  `dislocker-file`). Ask for keys before anything else; never format or re-initialise.

### Method: Carve files from an image with PhotoRec
- Preconditions: image taken (finished or best-effort mapfile); output directory on another device.
- Risk: R0 (gate kind: none)
- Tool: PhotoRec 7.x (`photorec /log /d OUTDIR /cmd image.dd partition_none,fileopt,everything,enable,search`)
- Expected result: recovered files by type in OUTDIR; names and folders are not restored.
- Stop criteria: output disk filling up; running against the source device instead of the image.

### Method: Analyse partitions on an image with TestDisk
- Preconditions: image taken; missing partition or RAW filesystem symptom.
- Risk: R0 (gate kind: none)
- Tool: TestDisk 7.x on the image (`/log`, `analyze`, `quicksearch`, `list` for files)
- Expected result: candidate partition layout and a file listing, written down before any write.
- Stop criteria: never choose Write while pointed at the source device.

### Method: Repair a filesystem on the source
- Preconditions: data secured or waived; image analysis shows the repair is needed; goal device-recovery.
- Risk: R2 (gate kind: fs-repair-on-source)
- Tool: OS native repair (`chkdsk /f`, `fsck`, `ntfsfix`) on the confirmed path
- Expected result: filesystem mounts; files readable; re-collect shows no new errors.
- Stop criteria: any I/O error during repair (stop: repairs on failing media lose more data).
