# System Architecture

Sources: `plans/20261019-1726-recovery-storage-skill/requirements.md` (decisions, verified facts), `plan.md`, amendments 01 and 02, and the code under `recovery-storage/scripts/`.

## Purpose

`recovery-storage` is a Claude Code skill that orchestrates diagnosis and recovery of storage devices (USB, SD/microSD, HDD, SATA/NVMe SSD, external drives, USB-bridged and controller-based flash). It drives existing tools and collects, normalizes and stores their output. It never reimplements imaging, filesystem repair, SMART parsing or NAND decoding, and it never runs a risky action itself: it records, checks and asks a human (the gate).

## Approved stack

| Area | Choice |
|---|---|
| Language | Python >= 3.10, standard library only at runtime; no pip dependencies at runtime |
| Tests | pytest (dev only) |
| SMART / NVMe collector | smartctl 7.x with `-j`, the sole collector on Windows and Linux; nvme-cli is not used |
| Windows enumeration | `powershell.exe` 5.1 running the three frozen scripts in `rslib/ps/` (Storage cmdlets and CIM, JSON output) |
| Linux enumeration | `lsblk -J -O -b` plus sysfs file reads (USB chain, MMC). The CLI does not call `udevadm` or `lsusb`; the allow-list still admits fixed forms of both, unused by the commands |
| Linux event context | `journalctl -k` (fallback `dmesg`) |
| Case store | SQLite plus per-session JSON evidence under `~/.recovery-storage/`; override with `--home` or `RECOVERY_STORAGE_HOME` |

The store lives outside the repo because evidence contains device serials.

Skill layout: `recovery-storage/` holds `SKILL.md`, `references/`, `scripts/`. `~/.claude/skills/recovery-storage` is a junction (Windows) or symlink to that folder, created by `scripts/install_junction.py`.

## Components and data flow

```
 agent / operator
      |
      v
 rs.py -> rslib/cli.py  (argparse tree, --home, --json, --who; one reply per command)
      |
      |  every external process ------------------------------------------+
      v                                                                    |
 collect.py ---- runner.py (only module that imports subprocess) ----> allowlist.py (argv + frozen PS hashes)
   |  inventory / collect / ingest smartctl / device link                  |
   |                                                                       v
   |   enum_windows.py (win-disks, win-pnp-chain)            smartctl, powershell, lsblk, journalctl, dmesg ...
   |   enum_linux.py   (lsblk + sysfs)                       (all read-only; tool_runs row per call)
   |   smart.py (normalise smartctl JSON), events.py
   v
 identity.py: fingerprint -> match (exact / probable / weak / ambiguous / conflict / none)
   |   device ids bind to fingerprints, never to Disk Number or /dev path
   v
 store.py (SQLite rs.sqlite + sessions/<id>/evidence + runs/): observations, devices, snapshots
   |
   v
 assess.py: health.py (H1-H5) + delta.py + triage.py (T1-T5, constraints, hypotheses) + wear.py
   |   same inputs and rules version -> the stored assessment is returned unchanged
   v
 ingest.py: ddrescue mapfile, f3probe/f3write/f3read output, operator-attested results  --> evidence rows
   |
   v
 gate.py + actions.py: open -> (operator) confirm -> close | abort
   |   locks are partial unique indexes: one live R2 gate globally, one live gate per device
   v
 datastate.py: none / secured / waived / not-needed, last_write_ts(device)
   |
   v
 verdict.py: PASS / PASS_LIMITED / FAIL / REPAIR_REQUIRED / UNRESOLVED / RETIRED (matrix by device class)
   |
   v
 report.py: per-device report with epistemic tags, --check, --redact;  fleet.py: device list/show, compare
```

### Command flow of a session

1. `session new` records goals, risk ceiling (default R0), preserve-data, data value, risk tolerance, symptoms.
2. `inventory` runs enumeration through the runner and stores one observation per attached disk, each with a multi-attribute fingerprint and a match against known devices. An ambiguous result exits 5 and needs `device link` by the operator.
3. `collect` takes identity + SMART (smartctl, USB retry with `-d sat`) + OS events into a snapshot. A result is attached to a device only when the answering identity matches it; otherwise `identity-conflict`.
4. `assess` produces the health verdict, the triage class and constraints, and ranked hypotheses from stored evidence.
5. Risky actions go through the gate (below). `ingest` stores tool output the operator ran outside the process.
6. `session data-state` records whether the data is secured, waived or not needed.
7. `verdict set` refuses PASS unless the device class's evidence is present, then `report` renders the document. A verdict recorded while the reader showed no medium (or a weak match) is scoped to that session's card and never becomes the reader's fleet status (`fleet.medium_scoped`).

### Gate state machine

`pending -> open -> closed`, and `pending|open -> aborted`; nothing leaves `closed` or `aborted`. Every transition is a conditional UPDATE on the expected state.

- `gate open <session> <device> <kind>` evaluates every check and lists every failing reason at once: unknown action, no assessment, risk above session ceiling, STOP_UNSAFE triage, forensic goal on a source-writing action, data not secured, class not allowed, missing requirement (`--dest-device`, `--controller-id`, `--tool-source`), boot or system disk, ambiguous identity, global lock, device busy. It prints the confirmation block (model, serial, size, bus, VID:PID, OS path, stop criteria, phrase) and records the before-state snapshot.
- `gate confirm <gate>` asks the operator for the phrase (last 4 characters of a trusted serial, else the exact byte count), re-resolves the device immediately before the action and prints the only OS path to use. A device that changed since open aborts the gate.
- `gate close <gate> --outcome success|failed|interrupted` records the after-state. It never changes a fingerprint: if the device is not found exactly, the gate closes with `identity_drift` and a `drift_reason` (`media-id-changed` or `device-changed`), and the operator resolves it with `device link`.
- `gate abort` ends a live gate with a reason.

### Operator console channel

`rslib/operator.py` defines the channel for steps the agent must not be able to give itself: `gate confirm`, `session data-state` for `waived` / `secured --attested` / `not-needed`, `ingest attested`, and `device link`. `ConsoleOperator` requires a real console on stdin (`GetConsoleMode` on Windows, since `isatty()` is also true for NUL). Without one the command exits 3 with `operator-console-required` and prints the exact command line for the operator to run in their own terminal; nothing is stored. A wrong answer gives `wrong-phrase` (gate stays pending) or `operator-declined`. Audit rows store `confirmed_by` / `who` = `operator`; reports tag these items `[ATTESTED]`.

Known leak: a script that imports `rslib` and injects an operator, or a pseudo-terminal wrapper, defeats the console rule. It is the same leak class as script files for the guard hook.

### Data-first across sessions

- `last_write_ts(device)` is the latest close of a gate whose kind writes the source, or the abort of such a gate that had been confirmed, across all sessions.
- A write gate on a device whose data a session must preserve is refused (`data-not-secured`) unless a `secured` or `waived` state was recorded after `last_write_ts`. A stale state from before a format does not protect later data.
- `secured --evidence` needs a ddrescue mapfile for the device that covers the whole device (starts at 0, contiguous, ends at the device byte count, finished, nothing bad or unfinished), plus a closed, successful `image-ddrescue` gate in the same session confirmed before the mapfile was ingested.
- The verdict window starts at the later of session start and the last write, except that a successful verification gate (`f3write-f3read`, `h2testw`, `f3probe`, `f3probe-destructive`) counts from its confirm (amendment 04); data-state rules keep `last_write_ts` (the close).

### Verdict matrix

PASS is refused with every missing item named. Common requirements: no live gate, no unresolved identity drift, a replug observation and stable observations after the window start, a classified device. Per class:

| Class | Additional evidence after the window start |
|---|---|
| USB flash / SD | capacity verify: attested H2testw pass, or f3read pass covering at least `verdict.CAPACITY_COVERAGE` of device bytes |
| HDD, external HDD | post snapshot with healthy or watch verdict, valid non-rising media counters, a completed self-test inside the window (16-bit hour wrap handled) |
| SATA/NVMe SSD, external SSD | same health and counters, critical warning clear, read verify (complete ddrescue mapfile, f3read pass at coverage, or attested pass) |

`PASS_LIMITED` needs `--limitation` and at least one snapshot or evidence; other statuses need `--reason`. A successful format is never evidence.

### Guard hook path

`SKILL.md` frontmatter registers `scripts/guard_hook.py` as a PreToolUse hook for `Bash|PowerShell` when the skill is invoked.

1. The hook reads the tool call JSON from stdin and ignores other tools and non-matching commands without touching the store.
2. `rslib/guard_patterns.py` tokenizes the whole command text (quote aware, heredoc bodies dropped, wrappers and nested shells unwrapped, `-EncodedCommand` decoded) and matches destructive patterns.
3. A matched command passes only while some gate is `open` (and not older than `OPEN_GATE_MAX_HOURS`) in the case store, which the hook opens read-only. Any failure after a match denies.
4. Deny exits 2 (via the frontmatter wrapper) with the next steps on stderr; a missing hook script or an internal error before a decision exits 1 (non-blocking). Decisions are logged to `guard.log` in the home as rule id plus command sha256.

It is leaky by design: obfuscation, script files, GUI tools, unknown tools, any open gate unlocking every device, a different `--home`. The list is in `SKILL.md` ("Guard hook and its limits").

## External tools orchestrated

- smartmontools (smartctl): SMART and NVMe health, read-only collector.
- GNU ddrescue: imaging of failing media (run by the operator; the mapfile is ingested).
- TestDisk, PhotoRec: partition and file recovery (guided).
- F3 (f3probe, f3write, f3read): flash capacity verification (output ingested).
- H2testw: capacity verification, guided only, result attested by the operator.
- MPTool (controller-specific): guided only; the skill never fetches or runs firmware itself.

## Platform notes

Verified on Windows 11 with smartctl 7.5, non-admin.

- Addressing: `smartctl -j -i /dev/pdN` addresses `Get-Disk` Number N. `smartctl --scan-open -j` lists NVMe disks as `/dev/sdX` (type nvme) and works without admin.
- NVMe serial mismatch: Windows `Get-Disk`/`Get-PhysicalDisk` `SerialNumber` is the EUI-64 string, not the smartctl `serial_number`. Join on `Get-Disk.UniqueId` (`eui.` + 16 hex digits) against smartctl `nvme_namespaces[].eui64` (oui + ext_id), plus model and exact byte size.
- Size: use `Get-Disk.Size`, which equals smartctl `user_capacity.bytes`. Do not use `Win32_DiskDrive.Size` (geometry-truncated) or `Win32_DiskDrive.InterfaceType` (reports NVMe as `SCSI`).
- Admin-only: `Get-StorageReliabilityCounter` fails without admin, so it is not used.
- Without admin: the PnP parent chain via `Get-PnpDeviceProperty -KeyName DEVPKEY_Device_Parent` works.
- USB: `SerialNumber` is junk or null, the PnP instance id with `&` is Windows-generated, and `UniqueId` embeds the hostname, so USB devices often have no trusted serial (`serial_trust` absent). An SD card in a reader hides the card's own identity; the match level is `weak` and the gate rule applies.
- Event log: query by provider name, level and time window; only `Ntfs` event 55 carries a semantic tag.
- MSYS path conversion: Git Bash rewrites `/dev/sda` unless `MSYS_NO_PATHCONV=1`. Python `subprocess` with an argv list is unaffected.
- Output capture: PowerShell 5.1 `>` writes UTF-16LE; capture tool output through `subprocess`, not shell redirection.
- Missing device: smartctl exits with status 1 and "Unable to detect device type".
- Tool lookup: the runner resolves tools from absolute `PATH` entries only (never the CWD, `.exe` only on Windows); `RS_<TOOL>` (for example `RS_SMARTCTL`) overrides with an absolute file path.
