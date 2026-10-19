# Phase 04 - Gate (risky-action control) and verdict (evidence-gated final status)

## Context Links
- Spec §1.1 goals, §2 Phase 0 R0-R3, Phase 3/4 rules, Phase 5 post-recovery tests + final statuses, §4 safety rules 1-9, GĐ3 "no concurrent destructive actions": [requirements.md](requirements.md)
- Imaging and bans on source (ddrescue, TestDisk write, chkdsk/fsck): [researcher-04](research/researcher-04-imaging-recovery.md) §1, §3, §5
- F3 / H2testw / MPTool risk: [researcher-03](research/researcher-03-flash-counterfeit-controller.md) §1, §2, §4, §6
- Self-test is R1 (state change): [researcher-01](research/researcher-01-smartctl-nvme-json.md) §4

## Overview
- Priority: P0. Status: Todo. Depends on 01-03.
- Commands: `gate open|confirm|close|abort|list`, `session data-state`, `verdict set|show`, `inventory --after-replug` flag.
- The skill never executes R1+ actions itself. The gate is the record + check + human confirmation step around an action the operator or agent runs with the external tool.

## Key Insights
- Wrong-device is the costliest failure. Checks at `open` are not enough: confirmation can take minutes and a replug renumbers disks. `confirm` re-resolves immediately before the action and prints the only OS path to use.
- "Data first" must be a state with evidence, not a flag the agent can flip: `secured` needs an ingested complete image or an explicit operator attestation with reason.
- Format success is never evidence: no gate outcome is an evidence type for `verdict`.
- Limit (state plainly in SKILL.md): rs.py cannot stop a direct tool call that skips the gate; phase 08 adds a PreToolUse guard hook as a second, leaky barrier that only checks "some gate is `open`". Gate `state` values are a contract with that hook.

## Requirements
Action catalog (frozen data; unknown kind refused). Fields: kind, risk, writes_source, allowed_classes, requires[], stop_criteria (short text; long form in references).
| kind | risk | writes source | classes | requires |
|---|---|---|---|---|
| smart-selftest-short, smart-selftest-long | R1 | no (device state) | hdd, ssd-sata, nvme, external-* | - |
| disk-offline, disk-readonly-attr, automount-disable | R1 | no (OS state) | all | - |
| wsl-mount-bare | R1 | no | all | - |
| image-ddrescue | R1 | no (read stress) | all | `--dest-device` (inventory device != source) |
| badblocks-readonly | R1 | no | hdd, external-hdd | - |
| f3probe, f3probe-destructive, f3write-f3read, h2testw | R2 | yes | usb-flash-or-card, sd | - |
| format, partition-write, fs-repair-on-source, clear-disk, badblocks-write | R2 | yes | all (badblocks-write: hdd only) | - |
| firmware-update, mptool-reflash | R2 | yes | all | `--controller-id`, `--tool-source` (provenance text) |
| hardware-lab (open device, board repair, chip-off) | R3 | n/a | all | - |
Gate open checks (all evaluated; every failing reason reported; exit 3, or 5 when the only reason is ambiguity):
`unknown-action`, `no-assessment` (none for this device in session), `device-not-found`, `ambiguous`, `identity-conflict`, `boot-or-system-disk` (Windows IsBoot/IsSystem; Linux any child mounted at `/`, `/boot`, `/boot/efi` or active swap), `risk-above-ceiling`, `stop-unsafe` (triage STOP_UNSAFE refuses R1/R2; R3 allowed), `forensic-source-write` (goal forensic-preservation and writes_source -> always refused until goals change), `data-not-secured` (preserve=yes and writes_source and data-state not in {secured, waived}), `class-not-allowed`, `missing-requirement`, `dest-is-source`, `device-busy` (another pending/open gate on this device), `global-lock-held` (another pending/open R2 gate anywhere in this home).
Gate open success: state `pending`; prints confirmation block: model, serial (full), bytes + GB/GiB, bus, vid/pid, current OS path(s), kind, risk, writes_source, stop criteria, triage constraints, and the expected phrase (last 4 chars of normalised serial when trust high; else the exact byte count). Records before-state (fresh inventory observation + R0 smartctl snapshot; collection failure recorded, not blocking).
Gate confirm `--phrase`: wrong phrase -> exit 3, stays pending. Re-resolve: not found / conflict / ambiguous -> state `aborted(device-changed)`, lock released, exit 3. Success -> state `open`, prints the OS path valid now and the instruction to run the action immediately.
Gate close `--outcome success|failed|interrupted [--note] [--evidence <id>...]`: only from `open`; records after-state (inventory + R0 snapshot); identity at close differs from open -> `identity_drift=true` and output warns; releases locks.
Gate abort `--reason`: from pending/open; releases locks. No automatic expiry.
Data state `session data-state <session> <device> secured --evidence <ddrescue-id>`: accepted only if the mapfile is finished with bad == 0 and non_tried + non_trimmed + non_scraped == 0 and belongs to this device; `secured --attested --reason <text>` (e.g. files copied and verified by operator); `waived --reason <text>`; `not-needed` only when preserve=no.
Verdict `verdict set <session> <device> <STATUS>`; statuses PASS, PASS_LIMITED, FAIL, REPAIR_REQUIRED, UNRESOLVED, RETIRED. History kept, latest wins.
PASS requires all common items + class items; refusal lists every missing item by name (exit 3):
- Common: no pending/open gate on device; no unresolved `identity_drift`; post-recovery window = after the last closed R2 gate on device (or session start if none); in that window >= 2 observations matching exact/probable with equal bytes, at least one taken with `inventory --after-replug`.
- hdd, external-hdd: post snapshot health in {healthy, watch}; self-test entry "Completed without error" whose lifetime hours >= power_on_hours of the window-start snapshot and no failed entry after it; valid delta pre -> post with no rise in 5/187/197/198.
- ssd-sata, nvme, external-ssd: post snapshot health in {healthy, watch}; NVMe critical_warning 0; valid delta with no rise in 5/187/197/198/media_errors; one read verify (ddrescue finished with bad 0, or f3read pass, or attested pass).
- usb-flash-or-card, sd: f3read pass covering >= 0.9 x device bytes (parameter; coverage unknown -> missing item) or attested H2testw pass (counts for PASS, labelled ATTESTED: decision Q3 2026-10-19).
- class unknown or conflicting with declared: refused `classify-device-first`.
PASS_LIMITED: requires `--limitation <text>` and at least one post-window snapshot or ingested evidence; refused if latest health failing. FAIL / REPAIR_REQUIRED / UNRESOLVED / RETIRED: require `--reason <text>`.

## Architecture
```
rslib/actions.py   frozen catalog (dataclass rows)
rslib/gate.py      open/confirm/close/abort; uses identity.match, collect (R0), store
rslib/datastate.py data-state transitions + evidence checks
rslib/verdict.py   evidence matrix per class -> Ok | Refused(missing[])
store: gates(id, session, device, kind, risk, state, lock_slot, phrase_hash, before_obs, before_snap, after_obs, after_snap, identity_drift, outcome, ts...)
       UNIQUE INDEX gates_global ON gates(lock_slot) WHERE state IN ('pending','open')   -- lock_slot = 'R2' for R2 kinds, NULL otherwise
       UNIQUE INDEX gates_device ON gates(device_id) WHERE state IN ('pending','open')
```
State machine: `pending -> open -> closed`; `pending|open -> aborted`; nothing leaves `closed`/`aborted`.

## Related Code Files
Create: `rslib/{actions,gate,datastate,verdict}.py`; tests `test_actions_catalog.py, test_gate_open.py, test_gate_confirm_close.py, test_gate_lock.py, test_datastate.py, test_verdict.py`.
Modify: `rslib/cli.py`, `rslib/collect.py` (`--after-replug`), `rslib/store.py` (indexes, if not created in phase 01).

## Implementation Steps
1. Catalog + state machine (pure) with tests.
2. Open checks (each reason a pure predicate over session/device/assessment/observations).
3. Confirm/close/abort with re-resolution via RecordedRunner scenarios (device present, absent, swapped).
4. Lock indexes; concurrency test with two connections.
5. Data state; verdict matrix; CLI.

## Todo List
- [ ] catalog + state machine
- [ ] open checks (all reasons)
- [ ] confirm / close / abort with re-resolution
- [ ] DB-enforced locks
- [ ] data-state transitions
- [ ] verdict evidence matrix + CLI

## Acceptance Criteria (observable)
Gate open
- D1 `gate open <s> <d> rm-rf` -> exit 3 `unknown-action`, lists valid kinds.
- D2 Session ceiling R0, kind `smart-selftest-short` (R1) -> `risk-above-ceiling`. Ceiling R1 -> opens (pending), phrase shown.
- D3 Device flagged IsBoot or IsSystem (Windows capture) -> `boot-or-system-disk` for any kind, any ceiling.
- D4 Goal data-recovery, data-state none, kind `format` (ceiling R2) -> `data-not-secured`. After `data-state secured --evidence <complete mapfile>` -> opens.
- D5 Goal forensic-preservation, kind `format`, data-state secured -> still `forensic-source-write`. Kind `image-ddrescue` -> allowed (R1, no source write) if other checks pass.
- D6 Triage STOP_UNSAFE: kind `image-ddrescue` -> `stop-unsafe`; kind `hardware-lab` with ceiling R3 -> opens.
- D7 No assessment for device in this session -> `no-assessment`.
- D8 Several failing checks at once (e.g. ceiling + data-not-secured) -> all reasons listed, exit 3.
- D9 Device absent from current inventory -> `device-not-found`; two candidates probable -> exit 5 `ambiguous` with candidate list.
- D9b `usb-sd` Disk 3 (weak match: reader VID/PID, Signature 0, no serial) as the only such device attached -> gate opens; confirmation block contains the line "identity weak: same-size media in this reader cannot be told apart"; phrase = exact byte count 4026531840. A second attached device with same model + bytes + vid/pid -> exit 5 `ambiguous`.
- D9c Before/after-state collection returning `needs_elevation` (USB on non-admin Windows) is recorded and does not block open/confirm/close.
- D10 `image-ddrescue` without `--dest-device` -> `missing-requirement`; `--dest-device` equal to the source device -> `dest-is-source`. `mptool-reflash` without `--controller-id` or `--tool-source` -> `missing-requirement`. `f3probe` on class hdd -> `class-not-allowed`.
- D11 Confirmation block contains model, full serial, bytes, current OS path, kind, risk, stop criteria and the expected phrase; serial trust high -> phrase = last 4 chars of serial; trust low/absent (incl. the verified USB junk serials) -> phrase = exact byte count.
Confirm / close / abort
- D12 Wrong phrase -> exit 3, gate still `pending`. Right phrase, device unchanged -> `open`, prints OS path.
- D13 Device disappears between open and confirm (RecordedRunner returns inventory without it) -> state `aborted(device-changed)`, locks released, exit 3. Device replaced by another with same model and size but different serial -> `aborted(device-changed)`.
- D14 Device renumbered (Disk 2 -> Disk 3, same fingerprint) between open and confirm -> confirm succeeds and prints the NEW path `/dev/pd3`.
- D15 Device swapped between confirm and close -> close succeeds, `identity_drift=true`, output warns; a later `verdict set PASS` is refused with `unresolved-identity-drift`.
- D16 `gate close` on a pending or closed gate -> exit 3. `gate abort` on closed -> exit 3.
Locks
- D17 R2 gate pending on device A; open R2 on device B (other session, same home) -> `global-lock-held` naming the holding gate. R1 on device B -> allowed. Second gate of any risk on device A -> `device-busy`.
- D18 Two processes/connections racing to open R2 gates: exactly one succeeds (DB constraint), the other gets `global-lock-held`.
- D19 After close or abort, the next R2 open succeeds.
Data state
- D20 `secured --evidence` with verbatim 1.30 mapfile (bad 512, unfinished) -> exit 3 `image-incomplete`, suggests `waived --reason`. With a mapfile all `+` -> secured. `waived` without `--reason` -> exit 2. `not-needed` when preserve=yes -> exit 3.
Verdict
- D21 USB stick: format gate closed with outcome success and no f3 evidence -> `verdict set PASS` exit 3 listing `capacity-verify-missing`, `replug-observation-missing`.
- D22 USB stick with f3read pass covering >= 0.9 x bytes after the last R2 gate + after-replug observation -> PASS accepted. Same f3read evidence dated before the last R2 gate -> refused `evidence-before-recovery`.
- D23 HDD (`scrutiny-ata-hdd-healthy` as post snapshot) without self-test newer than window start -> refused `selftest-missing`; with derived post snapshot showing 197 rising -> refused `counters-rising`.
- D24 NVMe sda post snapshot + ddrescue full-read evidence (finished, bad 0) + after-replug observation -> PASS accepted. Derived critical_warning 4 post snapshot -> refused.
- D25 Class unknown -> refused `classify-device-first`.
- D26 PASS_LIMITED without `--limitation` -> exit 2; with it and latest health failing -> exit 3. FAIL/RETIRED without `--reason` -> exit 2.
- D27 `verdict show` lists history newest first; the latest is the effective status.

## Pros / cons vs alternative
Chosen: record-and-confirm gate (open -> confirm -> operator/agent runs tool -> close), catalog-driven, DB-enforced locks.
- Pros: works for every tool incl. GUI, WSL and live Linux; checks are pure and testable; confirm re-resolution closes the renumbering window; locks survive crashes and parallel sessions.
- Cons: the action itself runs outside rs.py, so a careless direct call is not blocked (mitigated by SKILL.md, permission prompts, phase 08 guard hook); stale locks need a human `abort`.
Alternative: `gate run -- <tool> {dev}` exec wrapper that substitutes the resolved path and runs the tool.
- Pros: path never typed by the agent; strongest wrong-device protection for CLI tools. Cons: only covers non-interactive tools running on the same host (not H2testw, MPTool, diskpart, WSL ddrescue from Windows); needs a second allow-list of destructive argv; long-running processes inside rs.py. Rejected for v1; revisit if native-Linux use dominates.

## Not Worth Doing If
- The `wsl-mount-bare` and `disk-readonly-attr` kinds are not worth keeping if the phase 02 spike shows WSL cannot be used for imaging on this machine; then remove them from the catalog rather than ship unusable kinds.

## Risk Assessment
- Operator types the phrase without reading -> phrase derived from the device, not a generic "yes"; block lists serial and size first.
- Stale lock after crash -> `gate list` shows holder; `gate abort --reason` by operator; no auto-expiry by design.
- Attested evidence abused -> report labels it ATTESTED and shows the attached file sha256 (Q3: counts for PASS).

## Security Considerations
- Phrase stored as hash, full serial shown only in the terminal block (report redaction in phase 05).
- `--tool-source` provenance is free text recorded verbatim; spec rule 6 (no unverified firmware) stays a human responsibility stated in references.

## Next Steps
- Phase 08 guard hook reads `gates` (state `open`) read-only; no schema change needed.
- Phase 05 renders gates, data-state, verdicts into the report.
