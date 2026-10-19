# Safety, risk levels and the gate protocol

## Risk levels (spec Phase 0)

| Level | Meaning | How it runs |
|---|---|---|
| R0 | read-only collection | `rs.py inventory`, `rs.py collect`, `rs.py assess`; no gate |
| R1 | non-destructive, changes device or OS state (self-test, offline, read stress of imaging) | gate, session ceiling at least R1 |
| R2 | writes the source: format, partition table, filesystem repair, capacity tests, firmware | gate, ceiling R2, data secured or waived, global lock |
| R3 | hardware level: open the device, board work, chip-off, NAND readers | gate kind `hardware-lab`, done by a lab |

Raise the ceiling only after the operator agrees: `rs.py session set <sid> --ceiling R1`. Never move to R2/R3 before
judging the effect on the session goal (data first).

## Gate protocol

1. `rs.py assess <sid> <dev>` in this session (a gate needs a current assessment).
2. `rs.py gate open <sid> <dev> <kind>` checks everything at once and lists every failing reason. On success it
   prints the confirmation block: model, full serial, bytes (GB and GiB), bus, VID:PID, the OS path valid now, kind,
   risk, stop criteria, triage constraints and the phrase.
3. Show the block to the operator. The phrase comes from the device (last 4 characters of a trusted serial, else the
   exact byte count), never "yes". The operator runs the confirm command in their own terminal (an interactive
   console is required; from an agent tool call it exits 3 `operator-console-required` and prints the command).
4. `rs.py gate confirm <gate>` asks for the phrase, then re-resolves the device immediately (a replug can renumber disks).
   If the device vanished or changed, the gate is aborted (`device-changed`): open a new one. On success it prints
   the only OS path to use. Run the action right away, on that path only.
5. `rs.py gate close <gate> --outcome success|failed|interrupted [--evidence <id>]` records the after-state. If the
   device at close is not the confirmed one, `identity_drift` is set and PASS is refused until resolved.
6. `rs.py gate abort <gate> --reason <text>` from pending or open; `rs.py gate list` shows holders. No automatic
   expiry: a stale gate is aborted by a human.

## Refusal reasons and what to do

| Reason | Meaning | Operator action |
|---|---|---|
| `unknown-action` | kind not in the catalog | pick a kind listed in the message |
| `no-assessment` | no assessment of this device in this session | run assess |
| `risk-above-ceiling` | kind risk above session ceiling | agree, then session set --ceiling |
| `stop-unsafe` | triage STOP_UNSAFE | only `hardware-lab` is allowed |
| `forensic-source-write` | goal forensic-preservation | never write the source; change goals only if the case changes |
| `data-not-secured` | data must be kept and is not secured | image first, then data-state secured, or waived with reason |
| `class-not-allowed` | kind not valid for the device class | choose the class-specific method |
| `missing-requirement` | `--dest-device`, `--controller-id` or `--tool-source` missing or unknown | provide it |
| `dest-is-source` | image destination is the source | pick another healthy device |
| `device-busy` / `global-lock-held` | another live gate on the device / any R2 gate anywhere | close or abort that gate |
| `device-not-found` / `identity-conflict` | not attached now, or a lookalike with another strong id | reconnect, re-run inventory |
| `ambiguous` (exit 5) | identity cannot be told apart | operator decides with device link |
| `boot-or-system-disk` | the OS runs from this disk | never act on it from the running OS; use a live system |

## Data state

`rs.py session data-state <sid> <dev> secured --evidence <ddrescue evidence id>` is accepted only for a finished
mapfile of this device with no bad, non-tried, non-trimmed or non-scraped bytes that covers the whole device (first
block at 0, contiguous, ends at the device byte count). Refusals: `image-incomplete`, `image-not-contiguous`,
`image-does-not-cover-device`. Other forms, typed by the operator at their own console: `secured --attested --reason
<what was copied and how it was checked>`, `waived --reason <text>`, `not-needed` (only when the session does not
preserve data). Data-first spans sessions: if any session that touched the device keeps its data, a write gate needs
secured or waived somewhere.

## After a gated write

Formatting or re-partitioning changes the MBR signature / GPT guid. `gate close` never changes a device identity:
it records identity drift with `drift_reason` `media-id-changed` (exactly one attached disk is the same hardware
with a new on-media id) or `device-changed`, and prints the operator command. The operator confirms in their own
terminal with `rs.py device link <observation> <device>`: it learns the new on-media id (device history) and clears
the drift of earlier gates on that device. Linking different hardware is refused (`hardware-mismatch`, use `--new`).

## Last write

The last write to a device is the close of a source-writing gate, or the abort of one that had been confirmed, in
any session. A secured / waived data state only counts if recorded after it, and the PASS evidence window starts at
it (or at the session start, whichever is later). Exception for the PASS window only: a successful verification
gate (`f3write-f3read`, `h2testw`, `f3probe`, `f3probe-destructive`) counts from its confirm, so capacity evidence
ingested inside it counts; a failed, interrupted or aborted one counts from its close. `secured --evidence` also needs a closed, successful
`image-ddrescue` gate on the device in the session, confirmed before the mapfile was ingested.

## Locks

R2 gates are serialised by one global lock per case store (a partial unique index in SQLite, so it holds across
processes and sessions). Each device has at most one live gate. R1 gates on other devices may run beside an R2 gate.

## OS-state methods

### Method: Take a disk offline in Windows before imaging or WSL attach
- Preconditions: device fingerprint confirmed; not the boot/system disk; data operations planned on that disk.
- Risk: R1 (gate kind: disk-offline)
- Tool: PowerShell `Set-Disk -Number <N> -IsOffline $true` with N from the confirmed path (Windows Storage module)
- Expected result: the disk disappears from Explorer; Get-Disk shows it Offline; no write to the media.
- Stop criteria: the disk number printed by gate confirm differs from what you are about to type; any prompt to
  initialise or format (cancel it).

### Method: Mark a disk read-only at OS level
- Preconditions: a forensic or data-first case without a hardware write blocker.
- Risk: R1 (gate kind: disk-readonly-attr)
- Tool: PowerShell `Set-Disk -Number <N> -IsReadOnly $true`; Linux `blockdev --setro` (kernel flag only)
- Expected result: OS refuses writes to the disk; re-check after replug because the attribute may not persist.
- Stop criteria: attribute does not stick after replug; for evidence of record prefer a hardware write blocker.

### Method: Disable automount for a suspect device
- Preconditions: the OS would mount or offer to format the device on connect.
- Risk: R1 (gate kind: automount-disable)
- Tool: Windows `mountvol /N` (restore with `mountvol /E`); Linux desktop: stop udisks automount for the session
- Expected result: no automatic mount or format prompt; enumeration still works.
- Stop criteria: Windows still offers to format (always cancel); restore automount at the end of the session.

### Method: General write to the source (format, partition table, clear)
- Preconditions: data secured or waived; goal allows writes; class and identity confirmed; reason recorded.
- Risk: R2 (gate kind: format)
- Tool: OS native (Format-Volume, mkfs.*, diskpart) on the confirmed path only
- Expected result: a usable filesystem; this proves nothing about health or capacity (verify afterwards).
- Stop criteria: any write error, disconnect or size different from the confirmation block.

### Method: Rewrite the partition table
- Preconditions: image taken; the intended layout written down; analysis done on the image first.
- Risk: R2 (gate kind: partition-write)
- Tool: TestDisk (Write only after review), sgdisk/parted, Windows Disk Management
- Expected result: partitions visible again; files readable read-only before any repair.
- Stop criteria: the tool proposes a geometry different from the image analysis; any I/O error.

### Method: Wipe the whole device
- Preconditions: operator confirmed twice that no data is needed; device-recovery goal.
- Risk: R2 (gate kind: clear-disk)
- Tool: PowerShell `Clear-Disk -RemoveData`, `diskpart clean`, `wipefs -a`
- Expected result: empty device ready for partitioning.
- Stop criteria: identity mismatch of any kind; irreversible, so never under time pressure.

### Method: Hand over to a data-recovery lab
- Preconditions: triage STOP_UNSAFE or HARDWARE_DIAGNOSIS_REQUIRED, or data value too high for further DIY risk.
- Risk: R3 (gate kind: hardware-lab)
- Tool: professional lab (cleanroom, PC-3000 class tools); not run by the operator
- Expected result: lab report and recovered data; record it with `rs.py ingest attested` and the verdict.
- Stop criteria: no further power-on by the operator once this gate is opened.
