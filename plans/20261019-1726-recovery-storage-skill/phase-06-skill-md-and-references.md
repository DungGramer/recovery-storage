# Phase 06 - SKILL.md (orchestrator) and references (playbooks)

## Context Links
- Spec whole document, esp. §1.3 tool priority, Phase 3 "điều kiện áp dụng, rủi ro, công cụ, kết quả kỳ vọng, tiêu chí dừng", §3 tool table, §4 rules, §5 orchestrator steps, §8 done criteria: [requirements.md](requirements.md)
- All five research reports (each playbook cites the report section it draws from)
- Skill authoring: `skill-creator` skill (description trigger evaluation)

## Overview
- Priority: P1. Status: Todo. Depends on 01-05 (command names final).
- Deliverables: `recovery-storage/SKILL.md`, `recovery-storage/references/*.md`, small `rs.py rules` command (prints the code's rule tables so docs never restate thresholds).

## Key Insights
- SKILL.md must stay lean: flow + hard rules + pointers. Detail lives in references read on demand; thresholds live in code and are shown by `rs.py rules` (single source).
- Every method in every playbook states five fields: preconditions, risk (R0-R3 + catalog kind), tool (with version/source), expected result, stop criteria. A lint test enforces the shape.
- Research items marked [M]/[K]/[UNVERIFIED] may appear only with the label `[UNVERIFIED]` and never as an instruction phrased as a rule.
- Report-template reference dropped: `rs.py report` is the template (over-engineering cut).

## Requirements
SKILL.md
- Frontmatter: `name: recovery-storage`; `description` covering EN + VI triggers: USB không nhận, thẻ nhớ lỗi / thẻ SD lỗi, cứu dữ liệu ổ cứng, khôi phục dữ liệu, kiểm tra USB fake dung lượng, USB giả dung lượng, SMART, sức khỏe ổ SSD, ổ NVMe, ổ cứng kêu lạch cạch, ổ cứng ngoài không nhận, recover data from failing drive, check SSD health, fake capacity USB, SD card not detected, ddrescue, TestDisk, PhotoRec, F3, H2testw. Non-triggers stated implicitly by scope (cloud storage, databases, git history).
- Frontmatter `hooks:` block is added in phase 08 (guard hook); this phase leaves only `name` and `description`.
- Body: how to run (`python <skill-dir>/scripts/rs.py ... --json`); Phase 0-5 mapped to commands (0 `session new`, asking the operator for goals, data value, risk tolerance, symptoms and isolation tests already tried; 1 `inventory`, `collect`, `assess` -> triage; 2 hypotheses + `ingest`; 3/4 `gate open/confirm/close` around external tools, re-`assess` after each attempt, no identical retry without new evidence; 5 `verdict`, `report --check`); hard rules (spec §4, condensed, plus: never type a device path yourself, use the one printed by `gate confirm`; never treat format success as evidence; stop and escalate on STOP_UNSAFE / HARDWARE_DIAGNOSIS_REQUIRED); the gate limit stated plainly (rs.py cannot block a direct tool call; do not make one); pointer table to references.
references/ (one purpose each)
- `safety-and-gates.md`: R0-R3, gate protocol step by step, refusal reasons and what the operator does for each, action catalog long form (kind -> stop criteria), data-state, locks.
- `phase1-hardware-triage.md`: isolation tests (port, cable, power, adapter/enclosure, other host, other OS), symptom codes, triage classes and what each permits, when to stop and go to a lab; "not detected in Explorer" is not proof of death.
- `device-hdd.md`, `device-ssd-nvme.md`, `device-usb-flash-sd.md`, `device-external-bridge.md` (USB bridge types for smartctl `-d`, bridge hardware encryption: keep original enclosure, vendor-source label; SATAFIRM S11 vendor-lab label). `device-usb-flash-sd.md` also records: no SMART is normal, `needs_elevation` means re-run elevated (not a fault), SD in a reader shows the reader's VID/PID (weak identity), and VID `ABCD` / PID `1234` is commonly reported on no-name sticks `[UNVERIFIED]` (weak authenticity hint, never a verdict).
- `imaging-ddrescue.md`: manual-sourced flags and two-pass pattern, mapfile, destination on a different healthy drive, Windows via `wsl --mount --bare` (verified to exist here) and live Linux; usbipd mass-storage `[UNVERIFIED]`; ingest the mapfile afterwards.
- `file-partition-recovery.md`: TestDisk/PhotoRec on the image only, `/cmd` syntax, `write` / `noconfirm,write` forbidden on source, `\\.\PhysicalDriveN` acceptance `[UNVERIFIED]`, encrypted volumes (BitLocker manage-bde, dislocker on a copy).
- `authenticity-f3-h2testw.md`: f3probe (Linux, USB-backed only, exit 0/101-104 vs other = tool error), f3write/f3read on any host, H2testw GUI on Windows, ValiDrive sampling caveat, how to ingest each, why format proves nothing.
- `controller-mptool.md`: identify (VID/PID, controller, flash ID) and guide only; never pick firmware by brand or capacity; provenance requirement; image first; human-only.
- `health-signals.md`: meaning of signals for reasoning (strong/medium/weak), pointer to `rs.py rules` for the exact thresholds, unverified items (HDD temperature bands, Seagate packed raws, event ids, generic serials) labelled.
- `tools-windows.md`, `tools-linux.md`: install (winget/scoop/apt), admin needs (verified: non-admin NVMe works; USB `-d sat` needs elevation (Error=5); ReliabilityCounter admin-only), event log query approach, Git Bash path trap, PowerShell 5.1 encoding trap.
`rs.py rules [--json]`: prints health rules, triage rules, parameters, wear whitelist, each with its source reference, generated from the same tables the code uses.

## Architecture
```
recovery-storage/
  SKILL.md                     flow + hard rules + pointers
  references/*.md              playbooks (method blocks with 5 fields)
  scripts/rslib/rules_doc.py   renders rule tables for `rs.py rules`
```
Method block shape (lint-enforced):
```
### Method: <name>
- Preconditions: ...
- Risk: R<n> (gate kind: <kind> | none)
- Tool: <tool, version/source>
- Expected result: ...
- Stop criteria: ...
```

## Related Code Files
Create: `recovery-storage/SKILL.md`, `recovery-storage/references/{safety-and-gates,phase1-hardware-triage,device-hdd,device-ssd-nvme,device-usb-flash-sd,device-external-bridge,imaging-ddrescue,file-partition-recovery,authenticity-f3-h2testw,controller-mptool,health-signals,tools-windows,tools-linux}.md`, `rslib/rules_doc.py`; tests `test_skill_docs.py` (lint), `test_rules_doc.py`.
Modify: `rslib/cli.py` (`rules`), rule modules only to expose tables (no behaviour change).

## Implementation Steps
1. `rs.py rules` from existing tables.
2. References, one per file, each method block citing its research section.
3. SKILL.md.
4. Lint test; description trigger evaluation with `skill-creator` (positive VI/EN prompts trigger, negative prompts do not).

## Todo List
- [ ] rules command
- [ ] reference files listed in Requirements
- [ ] SKILL.md
- [ ] docs lint test
- [ ] description trigger eval

## Acceptance Criteria (observable)
- F1 SKILL.md frontmatter parses (YAML subset: `name`, `description`), `name == recovery-storage`, description contains each trigger phrase listed in Requirements.
- F2 Every relative link in SKILL.md and references resolves to an existing file.
- F3 Every `rs.py <subcommand>` string in SKILL.md/references is a real subcommand (checked against the argparse tree); every subcommand in argparse is mentioned at least once in SKILL.md.
- F4 Every `### Method:` block has the five fields, non-empty; `Risk` names R0-R3 and either `none` or a catalog kind that exists in `actions.py`.
- F5 Every action kind in `actions.py` appears in at least one method block (no undocumented kind) and the R-level in the doc equals the catalog's.
- F6 No reference contains a numeric threshold that also exists in the rule tables (lint: numbers next to attribute ids 5/187/197/198/199 or `percentage_used` are flagged unless inside a quoted `rs.py rules` output block); thresholds are read via `rs.py rules`.
- F7 Lines carrying content from [M]/[K]/[UNVERIFIED] research items carry `[UNVERIFIED]` (reviewer check using the research reports; not automatable fully: listed in the phase review).
- F8 `rs.py rules --json` lists every health and triage rule with id, required fields, outcome, source reference; output equals what `health.py` / `triage.py` evaluate (test compares rule ids).
- F9 Trigger eval (skill-creator): Vietnamese and English positive prompts (e.g. "USB không nhận trên Windows", "kiểm tra thẻ nhớ có phải hàng fake dung lượng không", "check my NVMe health") select the skill; negative prompts ("khôi phục file đã xóa trên Google Drive", "recover a deleted git branch", "tối ưu database SQLite") do not. Result recorded with date and method in the phase review, not in the skill.
- F10 SKILL.md states: the gate limit, never type a device path, format success is not evidence, stop/escalate conditions, report redaction before sharing.

## Pros / cons vs alternative
Chosen: lean SKILL.md + per-topic references + generated rule tables.
- Pros: context loaded on demand; thresholds have one home (code); lint keeps docs and catalog in sync.
- Cons: more files; the agent must follow pointers.
Alternative: single large SKILL.md with everything.
- Pros: one read. Cons: loads all playbooks for every trigger, duplicates thresholds, drifts from code. Rejected.

## Not Worth Doing If
- A per-device-class reference is not worth a separate file if, after writing, it has no method block of its own (only pointers); merge it into its parent playbook instead.

## Risk Assessment
- Docs drift from code -> F3/F4/F5/F8 lints run in the suite.
- Description too broad (triggers on unrelated "storage" prompts) -> F9 negatives.
- Unverified lore turning into rules -> F7 review item + `[UNVERIFIED]` label convention.

## Security Considerations
- References never recommend downloading firmware or tools from unverified mirrors; ChipGenius-like tools listed with the "untrusted mirrors" caveat from research.

## Next Steps
- Phase 07 installs the skill and runs scenarios end to end.
