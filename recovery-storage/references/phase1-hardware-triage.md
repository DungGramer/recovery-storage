# Phase 1: hardware triage

Goal: find the cases where ordinary software attempts must stop. Triage classes come from `rs.py assess`
(rules in `rs.py rules`); this file explains what each permits and how to collect the isolation facts.

## Triage classes

| Class | Permits | Typical next step |
|---|---|---|
| `SOFTWARE_RECOVERY_CANDIDATE` | software diagnosis and recovery, under the listed constraints | image first when data matters |
| `CONTROLLER_RECOVERY_CANDIDATE` | controller/firmware investigation; read-only work | identify controller exactly, secure readable data |
| `HARDWARE_DIAGNOSIS_REQUIRED` | no further DIY passes | lab or hardware diagnosis |
| `STOP_UNSAFE` | only the `hardware-lab` gate | power down, escalate |
| `UNDETERMINED` | collect more evidence | the `next_test` of the assessment |

Constraints attached to triage (`image-before-any-write`, `no-fs-repair-on-source`, `minimise-power-on`,
`stop-if-read-rate-collapses`, `keep-original-enclosure`) are binding for every later gate.

A failing-but-readable disk without mechanical signs stays a software (imaging) candidate by default; it becomes
`HARDWARE_DIAGNOSIS_REQUIRED` when the data is irreplaceable and the operator's risk tolerance is low, or when media
counters rise between two snapshots of the same session. Mechanical noise or a disk that does not spin is
`STOP_UNSAFE`.

"Not visible in Explorer", "no partition" or "one tool does not see it" never prove a device is dead: they are
inputs to isolation, not verdicts.

## Symptom codes

Record operator observations with `rs.py session new ... --symptom <code>` (repeatable): `mechanical-noise`,
`not-spinning`, `burning-smell`, `physical-damage`, `liquid-damage`, `overheating`, `not-detected`,
`disconnects-repeatedly`, `slow-io`, `read-only`, `wrong-capacity`, `raw-or-unreadable-fs`, `missing-partition`,
`deleted-files`, `io-errors`, `encrypted-locked`.

## Isolation methods

Record each finished step with `--tried other-port|other-cable|other-host|other-os|reseat-media|other-reader`
(session new or a new session; the last two are for cards and removable media).
Two or more distinct recorded steps make "not detected" a hardware case when the device is still absent from the
latest inventory, or when a card reader is present but reports no medium (`no_media`: Size 0, "No Media") with
symptom `not-detected`. A card seen by no reader or host has a dead controller: no software tool applies, data only
through a lab.

### Method: Change port and cable
- Preconditions: device not detected, disconnecting, or CRC/link errors in SMART.
- Risk: R0 (gate kind: none)
- Tool: another USB port on the motherboard (not a hub), a known-good short cable, powered hub for 2.5" drives
- Expected result: stable enumeration in `rs.py inventory`; link counters stop growing between snapshots.
- Stop criteria: burning smell, heat, clicking: stop and record the symptom.

### Method: Check power and enclosure
- Preconditions: external HDD or bridge; spin-up sounds or repeated reconnects.
- Risk: R0 (gate kind: none)
- Tool: the original power adapter, a second enclosure only when the drive has no bridge encryption
- Expected result: the drive spins up once and stays enumerated.
- Stop criteria: bridge-encrypted drives stay in their original enclosure (see device-external-bridge).

### Method: Try another host or operating system
- Preconditions: port/cable tested; driver or automount behaviour suspected.
- Risk: R0 (gate kind: none)
- Tool: another computer; a Linux live USB (separates driver and automount effects from the device)
- Expected result: the device enumerates elsewhere (host problem) or nowhere (device problem).
- Stop criteria: changing OS is for isolating the environment; it does not repair hardware.

### Method: Read-only evidence pass
- Preconditions: device enumerated by the OS.
- Risk: R0 (gate kind: none)
- Tool: `rs.py inventory --session <sid>`, `rs.py collect <dev> --session <sid>`, `rs.py assess <sid> <dev>`
- Expected result: fingerprint, SMART (or a recorded reason why not), OS events, triage class and hypotheses.
- Stop criteria: the device disconnects or heats up during collection: stop and record `disconnects-repeatedly`.
