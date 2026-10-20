# Amendment 09 (2026-10-20): OS events go to the nearest holder of the drive letter

Approved by the user on 2026-10-20 ("Làm, commit + push"). Spec for `test-designer` (tests first) and the implementer.

## Problem

Real run 2026-10-20: a 4 GB microSD (FAT32, `E:`) in a USB reader was assessed `partition-or-filesystem` (medium) with
evidence `observation.events.fs_corruption=Ntfs 55 (x25)`. The 25 System events "A corruption was discovered in the file
system structure on volume E:." were logged 2026-10-19T17:19Z-17:31Z, while a different card (32 GB NTFS, device
D-2bc2a1f8a798, first observed 2026-10-19T17:32:37Z holding `E:`) was in the reader; the 4 GB card was first observed
many hours later. Events are matched to a device by drive letter only, and drive letters are reused across media.

## E1. Nearest holder

An OS event that names a volume by drive letter L at time t is attributed to device D only if, among all observations
(any device, any session) whose partitions show drive letter L, the one nearest in time to t (before or after) belongs
to D. If that nearest observation belongs to another device, the event is not evidence for D. Equal distance to
observations of different devices: not attributed (conservative).

## E2. No holder

If no observation anywhere shows letter L, behaviour is unchanged (attributed as today).

## E3. Other naming

Events that name the device by other means (if any exist in the current matcher, e.g. disk number / PDO / harddisk
number) keep today's behaviour; state what you find from the CONTRACT and black-box probes.

## E4. Output

Assess output and report reflect it: the misattributed events disappear from D's hypotheses and evidence; the other
device's assessment can still use them.

## Test-designer findings (black-box probes on the code of 2026-10-20, commit 746fc2c)

- The matcher reads the drive letter from the observation's partitions (a partition `DriveLetter` with no volume row is
  enough) and compares case-insensitively (`e:` matches `E:`).
- E3 is empty today: Ntfs 55 naming `\Device\HarddiskVolume3`, a volume GUID or no letter, and untagged `disk` events
  naming `\Device\Harddisk3\DR3`, `Disk 3 (PDO name ...)` or `PhysicalDrive3` never reach a device's health, triage or
  hypotheses. Only Ntfs 55 (`fs_corruption`) with a drive letter does.
- E2 therefore reads (test-designer reading): an event naming a letter that no observation shows is evidence for no
  device, as today. No probe found a case where today's code attributes such an event, so "attributed as today" has
  no observable instance (open question Q1).
- `collect` records an observation (re-resolution) at collect time; it counts as an observation of E1 like any other.
- Report section 3 ("Triệu chứng và bằng chứng") lists every event of the snapshot's host-wide capture
  (`[VERIFIED] OS event ...`), including events on a letter no device holds. Test-designer reading of E4 "disappear
  from D's ... evidence": section 3 of D's report no longer lists an event attributed to another device; that
  device's section 3 still lists it. Events on a letter no observation shows: not asserted (E2).

## Frozen tests added

`test_hypotheses.py` C17d; fixture `windows/usb-stick/win-disks.stick-e.derived.json` (Disk 2 partition `DriveLetter`
null -> `E`, the stand-in for another medium holding `E:`). No frozen test amended.

## Open questions

- Q1. E2 "attributed as today": confirm the reading "an event on a letter no observation shows is evidence for no
  device" (the only behaviour observed today).
- Q2. An observation with no device (`device_id` null: ambiguous, unlinked) nearest to the event: is the event then
  attributed to nobody, or is that observation skipped? Not tested.
- Q3. Gate before/after observations: counted as observations (reading of "all observations"); not tested separately.
- Q4. Report section 3 reading above (drop for D, keep for the nearest holder) binds the frozen test until overturned.
