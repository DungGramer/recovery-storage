# Phase 05 - Report (§7) and fleet history (GĐ3)

## Context Links
- Spec §7 report contents, "verified / inferred / undetermined", §6 GĐ3 (multiple devices, history, comparison, grouping by symptom), §4 rule 10: [requirements.md](requirements.md)
- Delta validity rules: [researcher-05](research/researcher-05-health-rules.md) §6 (implemented in phase 03 `delta.py`)

## Overview
- Priority: P1. Status: Todo. Depends on 01-04.
- Commands: `report <session> [--device <id>] [--redact] [--out <path>] [--check]`, `device list [--group-by triage|category|status]`, `device show <id>`, `compare <snapA> <snapB> | --device <id>`.
- Read-only over the store; no new rules (reuses health, delta, triage, verdict).

## Key Insights
- Every statement in the report carries its epistemic tag and a reference: `[VERIFIED]` (tool output or parsed ingest, with tool/version/evidence id), `[ATTESTED]` (operator-attested evidence), `[INFERRED]` (rule-derived hypothesis, with rule id and confidence), `[UNDETERMINED]` (missing data, naming what is missing).
- Grouping is a deterministic key, not clustering: (latest triage class, primary hypothesis category, latest verdict).
- `history` and `groups` are not separate subsystems: `device show` and `device list --group-by` over existing rows cover GĐ3.

## Requirements
Report sections per device, in this order (spec §7): 1 Mục tiêu xử lý (goals, ceiling, preserve flag); 2 Thông tin nhận dạng (canonical identity + OS observations + class declared/detected); 3 Triệu chứng và bằng chứng (symptoms, isolation facts, snapshots, events); 4 Chẩn đoán và mức độ tin cậy (health verdict, triage class, constraints, hypotheses with alternative + next test); 5 Phương án đã thử (gates with kind, risk, outcome); 6 Công cụ, phiên bản, kết quả (tool_runs: tool, version, argv, exit, collection status; ingested files with sha256); 7 Thay đổi đã thực hiện (closed gates with writes_source, before/after snapshot ids, identity drift); 8 Kiểm định sau phục hồi (evidence used or missing per verdict matrix); 9 Trạng thái cuối cùng (latest verdict or `UNRESOLVED (no verdict recorded)`); 10 Hạn chế còn tồn tại; 11 Khuyến nghị sử dụng (PASS_LIMITED always adds "không dùng cho dữ liệu duy nhất hoặc quan trọng").
Headings in Vietnamese (user language), tags and identifiers in English.
`--redact`: serial -> `****` + last 4; eui64/wwn -> masked except last 4; home path -> `~`; usernames in paths removed.
`--check`: exit 0 when every section has content (a section may legitimately read "none" only for 5 and 7); else exit 3 listing empty sections.
`device list`: one line per device: id, model, bytes, class, latest triage, latest health, latest verdict, last seen. `--group-by` keys above; devices with no assessment grouped as `unassessed`.
`device show <id>`: chronological history across sessions: observations, snapshots, assessments, gates, data-state changes, verdicts.
`compare`: renders `delta.py` result; fields absent -> `n/a`; invalid pair -> header `INVALID COMPARISON: <reason>`, no per-field deltas shown, exit 0.

## Architecture
```
rslib/report.py   build_model(session, device) -> ReportModel (sections, tagged items) -> render_markdown(model, redact)
rslib/fleet.py    list/group/show/compare queries
```
Model first, render second: `--check` and tests inspect the model, rendering is a thin layer.

## Related Code Files
Create: `rslib/{report,fleet}.py`; tests `test_report_sections.py, test_report_redact.py, test_report_check.py, test_fleet.py, test_compare_cli.py`.
Modify: `rslib/cli.py`.

## Implementation Steps
1. ReportModel builder from store rows; tag assignment rules.
2. Markdown renderer + redaction.
3. `--check`.
4. fleet queries + compare rendering.

## Todo List
- [ ] report model + tags
- [ ] renderer + redact
- [ ] --check
- [ ] device list / show / group-by
- [ ] compare CLI

## Acceptance Criteria (observable)
- E1 Session with `scrutiny-usbjmicron-hdd-failing` collected, assessed, no gates, no verdict: report has all 11 headings in order; section 9 reads `UNRESOLVED (no verdict recorded)`; `--check` exits 3 listing section 9 (no verdict) and 8.
- E2 Each health/hypothesis line in section 4 has `[INFERRED]` + rule id + confidence; each SMART value in section 3 has `[VERIFIED]` + tool `smartctl 7.x` + evidence id; a field missing in the snapshot appears as `[UNDETERMINED] <field> not reported`.
- E3 Attested H2testw evidence appears with `[ATTESTED]` and its file sha256, never `[VERIFIED]`.
- E4 Closed format gate appears in sections 5 and 7 with outcome, and section 8 still lists the missing capacity verify (format success not counted).
- E5 PASS_LIMITED verdict -> section 11 contains the sentence forbidding use for unique/critical data; section 10 contains the `--limitation` text.
- E6 `--redact`: no full serial, eui64, wwn or home-directory username appears in output (test greps the rendered text for the unredacted values from the store).
- E7 `--out <path>` writes UTF-8 markdown; existing file is not overwritten without `--force` (exit 3).
- E8 `device list --group-by triage` with devices from fixtures {`scrutiny-usbjmicron-hdd-failing`, `scrutiny-ata-hdd-healthy`, `scrutiny-nvme-media-errors`, `missing-device`} -> groups SOFTWARE_RECOVERY_CANDIDATE, UNDETERMINED, `unassessed` as applicable; ordering stable (group key, then device id); same input -> byte-identical output.
- E9 `device show <id>` lists events chronologically across two sessions for the same device.
- E10 `compare` NVMe pair media_errors 0 -> 3: shows `+3`, power_on_hours `+10`; pair with hours going backwards -> `INVALID COMPARISON: power-on hours went backwards`; field missing on one side -> `n/a`.
- E11 `--json` for list/show/compare/report-model yields parseable JSON with the same data.

## Pros / cons vs alternative
Chosen: model-then-render markdown, tags per statement.
- Pros: completeness check and tests operate on structure, not text; one source for markdown and JSON.
- Cons: two layers instead of one.
Alternative: Jinja-like template string filled from queries.
- Pros: quick to read. Cons: stdlib has no templating beyond `string.Template`; completeness and tagging would be checked by text scraping. Rejected.

## Not Worth Doing If
- `device list --group-by category` is not worth building if no stored assessment yields a primary hypothesis category in the phase 07 scenarios; keep triage/status grouping only.

## Risk Assessment
- Reports leaking serials when shared -> `--redact` and SKILL.md instruction to redact before sharing outside the machine.
- Vietnamese headings vs English tags mixing -> fixed strings in one module, tested.

## Security Considerations
- Report never includes stdout of tools verbatim beyond the parsed fields; no user file names (none are collected).

## Next Steps
- Phase 06 documents the flow that ends in `report --check`.
