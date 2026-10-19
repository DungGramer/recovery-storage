---
name: recovery-storage
description: "Diagnose and recover storage devices (USB flash, SD/microSD, HDD, SATA/NVMe SSD, external drives, USB bridges) with existing tools: read-only evidence (smartctl, OS inventory), Phase-1 triage, gated risky actions, evidence-based verdicts and per-device reports. Use for 'USB không nhận', 'thẻ nhớ lỗi', 'thẻ SD lỗi', 'cứu dữ liệu ổ cứng', 'khôi phục dữ liệu', 'kiểm tra USB fake dung lượng', 'USB giả dung lượng', 'SMART', 'sức khỏe ổ SSD', 'ổ NVMe', 'ổ cứng kêu lạch cạch', 'ổ cứng ngoài không nhận', 'recover data from failing drive', 'check SSD health', 'fake capacity USB', 'SD card not detected', ddrescue, TestDisk, PhotoRec, F3, H2testw. Not for cloud storage, databases or git history."
hooks:
  PreToolUse:
    - matcher: "Bash|PowerShell"
      hooks:
        - type: command
          command: 'f="${CLAUDE_SKILL_DIR:-$HOME/.claude/skills/recovery-storage}/scripts/guard_hook.py"; if [ ! -f "$f" ]; then echo "recovery-storage guard: hook script not found at $f; guard inactive" >&2; exit 1; fi; w="$f"; if command -v cygpath >/dev/null 2>&1; then w="$(cygpath -w "$f")"; fi; if [ "$OS" = "Windows_NT" ]; then p=python; else p=python3; fi; RS_GUARD_DENY_CODE=3 "$p" "$w"; rc=$?; if [ "$rc" -eq 3 ]; then exit 2; elif [ "$rc" -ne 0 ]; then echo "recovery-storage guard: hook error (exit $rc); not blocking" >&2; exit 1; fi; exit 0'
---

# recovery-storage

Orchestrates diagnosis and recovery of storage devices. The skill never images, repairs, flashes or tests
capacity itself: it drives read-only tools, records evidence per device, gates every risky action behind an
identity re-check and a human confirmation, and refuses a PASS without the evidence the device class needs.
Priority order (spec): no irreversible data loss > no further damage > evidence before diagnosis > right tool >
independent verification > keep a device only with proof it works.

Below, `rs.py` means `python "${CLAUDE_SKILL_DIR}/scripts/rs.py" --json` (Python 3.10+, stdlib only). Every command
prints one JSON object with `ok`, `exit_code`, `reasons`, `message`. Exit codes: 0 ok, 2 usage, 3 refused by a
safety/evidence rule (read `reasons`), 4 tool or environment failure, 5 a human must decide (ambiguous identity).
Case data lives in `~/.recovery-storage` (or `--home`, env `RECOVERY_STORAGE_HOME`); it holds serials, so it stays
outside any repo. Requires smartmontools 7.x: see [tools-windows](references/tools-windows.md) /
[tools-linux](references/tools-linux.md).

## Hard rules

1. Identify devices by fingerprint (model, serial, bytes, EUI-64/WWN, VID/PID, on-media id), never by Disk number,
   drive letter or `/dev/sdX`. An `ambiguous` result (exit 5) and any identity drift go to the operator, who runs
   `rs.py device link <observation> <device>` or `rs.py device link <observation> --new` in their own terminal.
2. Never type a device path yourself. Use only the path printed by `rs.py gate confirm` for the action, and run the
   action right after confirm.
3. Every action above R0 goes through a gate: `rs.py gate open` -> show the confirmation block -> the operator runs
   `rs.py gate confirm <gate>` in their own terminal and types the phrase there -> run the external tool ->
   `rs.py gate close`. Confirm, waivers and attestations need an interactive console: from your tool calls they exit 3
   `operator-console-required` and print the exact command for the operator. Never try to work around that.
4. Data first: with data to preserve, no write to the source until `rs.py session data-state <sid> <dev> secured`
   holds (a ddrescue mapfile covering the whole device, or the operator's attestation with reason) or the operator
   waives it. Data-first spans sessions: a session that keeps the device's data protects it everywhere.
5. A successful format is never evidence of recovery or of real capacity. Only the verdict matrix decides PASS.
6. On `STOP_UNSAFE` stop all software actions and escalate to a lab; on `HARDWARE_DIAGNOSIS_REQUIRED` escalate to
   hardware diagnosis. Mechanical noise, burning smell, not spinning: stop before any further power-on.
7. No firmware or MPTool from an unverified source, and never chosen by brand or capacity
   ([controller-mptool](references/controller-mptool.md)).
8. Do not repeat an identical attempt without new evidence: after each attempt re-run `rs.py assess` and state what
   changed. Do not loop writes on a device that hangs, overheats or disconnects.
9. Do not mount or repair a filesystem on the source when evidence must be preserved; work on an image.
10. Reports carry serials: share only `rs.py report <sid> --redact` output outside the operator's machine.

The gate is a record-and-check step: the CLI (`rs.py`) cannot block a direct tool call that skips it. Do not make one.

## Flow (spec Phase 0-5)

**Phase 0 - goal and risk.** Ask the operator: goals (data-recovery, device-recovery, diagnosis-only,
authenticity-check, health-assessment, forensic-preservation), whether data must be kept, data value
(irreplaceable/important/replaceable), risk tolerance (low/medium/high), nominal capacity, device type, symptoms and
isolation steps already tried. Then:
`rs.py session new --goal data-recovery --data-value irreplaceable --risk-tolerance low --symptom io-errors --tried other-port`
(ceiling starts at R0; `rs.py session set <sid> --ceiling R1` only when an R1 step is agreed; `rs.py session show <sid>`,
`rs.py session list`, `rs.py session note <sid> <text>`).

**Phase 1 - hardware triage.** `rs.py inventory --session <sid>`, then `rs.py collect <dev> --session <sid>`, then
`rs.py assess <sid> <dev>`. The triage class tells whether software work may continue and under which constraints
([phase1-hardware-triage](references/phase1-hardware-triage.md)). "Not visible in Explorer" proves nothing.

**Phase 2 - evidence and cause.** Read `hypotheses` (category, confidence, evidence, alternative, next test). Captures
made elsewhere (WSL, live Linux, another host): `rs.py ingest smartctl <file> --session <sid>`. History and deltas:
`rs.py compare <snapA> <snapB>`, `rs.py compare --device <dev>`, `rs.py device show <dev>`. Signal meanings:
[health-signals](references/health-signals.md); thresholds: `rs.py rules`.

**Phase 3/4 - recovery and alternatives.** Choose the method by cause, from the playbook for the device class
([device-hdd](references/device-hdd.md), [device-ssd-nvme](references/device-ssd-nvme.md),
[device-usb-flash-sd](references/device-usb-flash-sd.md), [device-external-bridge](references/device-external-bridge.md),
[imaging-ddrescue](references/imaging-ddrescue.md), [file-partition-recovery](references/file-partition-recovery.md),
[authenticity-f3-h2testw](references/authenticity-f3-h2testw.md)). Each method states preconditions, risk, tool,
expected result and stop criteria. Gate commands: `rs.py gate open <sid> <dev> <kind>`,
`rs.py gate confirm <gate>` (operator, own terminal), `rs.py gate close <gate> --outcome success|failed|interrupted`,
`rs.py gate abort <gate> --reason <text>`, `rs.py gate list` ([safety-and-gates](references/safety-and-gates.md)).
Attach results: `rs.py ingest ddrescue <sid> <dev> <mapfile>`, `rs.py ingest f3probe <sid> <dev> <out.txt> --exit-code <n>`,
`rs.py ingest f3write <sid> <dev> <out.txt> --exit-code <n>`, `rs.py ingest f3read <sid> <dev> <out.txt> --exit-code <n>`,
`rs.py ingest attested <sid> <dev> --tool h2testw --result pass --file <log-or-screenshot>`. Data state:
`rs.py session data-state <sid> <dev> secured --evidence <id>` (or `waived --reason`, `not-needed`).

**Phase 5 - verification and verdict.** Ask the operator to unplug and replug, then
`rs.py inventory --session <sid> --after-replug` and `rs.py collect <dev> --session <sid>`. Then
`rs.py verdict set <sid> <dev> PASS` (refusal lists every missing item), or PASS_LIMITED with `--limitation`,
or FAIL / REPAIR_REQUIRED / UNRESOLVED / RETIRED with `--reason`; `rs.py verdict show <sid> <dev>`. Finish with
`rs.py report <sid> --check` and `rs.py report <sid> --out <file.md>`. A PASS_LIMITED device is never used for unique
or critical data.

**Many devices (batch).** `rs.py device list --group-by triage|category|status` and `rs.py device show <dev>`.
Destructive (R2) gates are serialised by a global lock across sessions; one live gate per device.

## Device classes and where to read

| Situation | Read |
|---|---|
| R0-R3, gate protocol, refusal reasons, data state, locks | [safety-and-gates](references/safety-and-gates.md) |
| Not detected, isolation tests, when to go to a lab | [phase1-hardware-triage](references/phase1-hardware-triage.md) |
| HDD, self-tests, surface read | [device-hdd](references/device-hdd.md) |
| SATA SSD / NVMe health, wear, read-only firmware | [device-ssd-nvme](references/device-ssd-nvme.md) |
| USB stick, SD/microSD, card readers | [device-usb-flash-sd](references/device-usb-flash-sd.md) |
| External enclosures, USB bridges, bridge encryption | [device-external-bridge](references/device-external-bridge.md) |
| Imaging a failing device | [imaging-ddrescue](references/imaging-ddrescue.md) |
| Partition / file recovery on an image | [file-partition-recovery](references/file-partition-recovery.md) |
| Fake capacity, write/read verify | [authenticity-f3-h2testw](references/authenticity-f3-h2testw.md) |
| Controller / firmware / MPTool | [controller-mptool](references/controller-mptool.md) |
| Signal meaning, confidence | [health-signals](references/health-signals.md) |
| Windows / Linux tool setup and traps | [tools-windows](references/tools-windows.md), [tools-linux](references/tools-linux.md) |

## Report

`rs.py report <sid>` renders the spec §7 sections per device in Vietnamese headings; every statement is tagged
`[VERIFIED]` (tool output we hold: tool, version, evidence id, sha256), `[ATTESTED]` (operator statement or
attachment), `[INFERRED]` (rule id + confidence) or `[UNDETERMINED]`. `--check` exits 3 while a section lacks content
(sections 8 and 9 stay empty until a verdict exists). Use `--redact` before sharing.

## Guard hook and its limits

Invoking this skill registers a PreToolUse hook (frontmatter) for Bash and PowerShell; verified 2026-10-19 on
Windows 11 + Git Bash in bypass-permissions mode (a matched `f3probe --destructive` was denied, `smartctl -j` passed).
It reads the case store from `RECOVERY_STORAGE_HOME` or `~/.recovery-storage` only: a session using another `--home`
is invisible to it. It blocks commands that write
to a device or change its state (disk/partition/format cmdlets, diskpart, mkfs, wipefs, partitioners, dd to a device,
ddrescue, f3probe/f3write/f3fix/f3brew, write-mode badblocks, TestDisk write, hdparm security/write, nvme
format/sanitize, smartctl state changes, blkdiscard, fsck/chkdsk repair) unless a gate is `open`. Rule ids live in
`scripts/rslib/guard_patterns.py`. A deny explains the next commands. It is leaky by construction:

- obfuscation: variables, aliases, `eval`, string building; an undecodable `-EncodedCommand` is treated as destructive;
- script files: `python x.py`, `./x.sh`, `x.ps1`, batch files;
- GUI tools (H2testw, MPTool, Disk Management, vendor utilities) and tools not in the list;
- MCP and other non-Bash tools; anything the user runs outside Claude;
- any open gate unlocks every matched command on every device (the hook cannot map a command to a device);
- it stays active for the rest of the session once the skill is invoked; sessions where the skill was never invoked
  have no hook;
- the pattern list is not exhaustive: unknown tools and new syntax pass; an open gate older than 12 h no longer
  unlocks;
- the operator console check (gate confirm, waivers, attestations) is defeated by a script that imports the library
  with an injected operator or by a pseudo-terminal wrapper.

A missing hook script prints "guard inactive"; any other hook error is reported and does not block (only a matched
destructive command without an open gate, or an unreadable gate store at that moment, is denied).
