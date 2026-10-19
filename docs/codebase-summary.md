> Updated from commit: f32e84f3661ebe6fe8e1f291293603f6049caa1a

# Codebase Summary

Counts of files, lines or tests are deliberately absent; use `git ls-files` and `python -m pytest --collect-only -q -p no:cacheprovider` for them.

## Folder structure

```
.claude/                 frozen-tests.json (frozen suite manifest), memory/ (lessons), active-plan
docs/                    this documentation set
plans/<plan>/            requirements.md, plan.md, phase-*.md, amendment-*.md, research/
pytest.ini               testpaths, pythonpath, default marker filter
recovery-storage/        the skill (junctioned into ~/.claude/skills)
  SKILL.md               orchestrator instructions + PreToolUse hook frontmatter
  references/            playbooks per device class, tools, safety and gates, health signals
  scripts/
    rs.py                CLI entry
    guard_hook.py        PreToolUse hook entry
    install_junction.py  skill installer
    rslib/               library (below)
    rslib/ps/            frozen PowerShell scripts (win-disks, win-pnp-chain, win-events)
    tests/               frozen spec-first suite
tools/                   dev tools (capture_fixtures.py, redact_fixtures.py)
```

## Entry points

| File | Role |
|---|---|
| `recovery-storage/scripts/rs.py` | Puts `scripts/` on `sys.path`, calls `rslib.cli.main(sys.argv[1:])`, exits with its return code. Never passes an operator, so production always uses the console. |
| `recovery-storage/scripts/guard_hook.py` | Claude Code PreToolUse hook. Reads the hook JSON from stdin, matches destructive patterns, allows a matched command only while a gate is open in the case store (read-only SQLite). Exit 0 allow, 2 deny (or the code in `RS_GUARD_DENY_CODE`, mapped to 2 by the frontmatter wrapper), 1 non-blocking error. Spawns no process. |
| `recovery-storage/scripts/install_junction.py` | `python install_junction.py [--skills-dir DIR]`. Creates a junction (Windows) or symlink (elsewhere) `<skills-dir>/recovery-storage` -> the skill folder. Idempotent; an existing real folder or foreign link exits 3 untouched; a link failure exits 4. |

## Module map: `recovery-storage/scripts/rslib/`

| Module | Responsibility |
|---|---|
| `cli.py` | argparse command tree (`build_parser`), `main(argv, *, runner, clock, os_family, operator)`, handler dispatch table, `Ctx`, single-object `--json` output, exit-code mapping. |
| `errors.py` | `UsageError` (2), `Refused` (3), `EnvFailure` (4), `NeedsHuman` (5), all carrying machine `reasons`. |
| `paths.py` | Home resolution: `--home`, then `RECOVERY_STORAGE_HOME`, then `~/.recovery-storage`; sessions, runs and evidence directories. |
| `store.py` | SQLite store, `SCHEMA_VERSION`, schema check before use, tables (sessions, session_events, devices, observations, inventory_runs, snapshots, assessments, evidence, data_states, gates, verdicts, tool_runs), partial unique indexes for gate locks, helpers (`new_id`, `dumps`, `loads`, `record_run`). |
| `session.py` | Session fields (goals, ceiling, preserve-data, data value, risk tolerance, symptoms, tried), audit events, `session new/show/list/set/note`. |
| `allowlist.py` | `check(tool_id, args, env)`: the argv allow-list, `PS_SCRIPT_SHA256`, `PS_ENV_BOUNDS`, `CommandNotAllowed`. |
| `runner.py` | `SubprocessRunner` (the only module importing `subprocess`), `RecordedRunner` (tests), `RunResult`, timeouts, PATH lookup that ignores the CWD, `tool_runs` recording. |
| `enum_windows.py` | Parses `win-disks` and `win-pnp-chain` output into `OsDisk` records (bus, size from `Get-Disk.Size`, USB ids, boot/system flags). |
| `enum_linux.py` | Parses `lsblk -J -O -b`; reads USB and MMC facts from sysfs under a constrained root. |
| `smart.py` | `normalise` smartctl JSON into a record (collection status, identity, health fields, detected class), `exit_flags`, `classify_collection`. |
| `events.py` | Windows event JSON and dmesg parsing; only `Ntfs` 55 is tagged. |
| `identity.py` | Serial normalisation and trust, `Fingerprint`, `match` levels, `windows_join`. |
| `collect.py` | `inventory`, re-resolution of a device, `collect`, `ingest smartctl`, `device link`, snapshot-identity check, class aliases. |
| `health.py` | Health rules H1-H5 (failing, degraded, watch, healthy, unknown) over a snapshot; thresholds are module constants. |
| `delta.py` | Snapshot delta (counters, power-on hours); validity and rising media counters. |
| `wear.py` | Endurance and host-writes estimates from a whitelist of attributes and NVMe fields. |
| `triage.py` | Triage rules T1-T5, constraints and ranked hypotheses. |
| `assess.py` | `assess`: combines health, delta, triage, hypotheses; stores or returns an identical assessment per rules version. |
| `ingest.py` | Parsers for ddrescue mapfiles and F3 output (size-limited, line-oriented), `ingest ddrescue/f3probe/f3write/f3read/attested`. |
| `actions.py` | Frozen catalog of gate action kinds with risk, writes-source flag, allowed classes, required options, stop criteria. |
| `gate.py` | Gate state machine: open, confirm, close, abort, list; identity drift; locks. |
| `datastate.py` | Data state, `last_write_ts`, `mapfile_complete`, `session data-state`. |
| `verdict.py` | Evidence matrix for PASS, `verdict set/show`, self-test window logic. |
| `operator.py` | Operator console channel (`ConsoleOperator`, `ScriptedOperator`, `NoConsole`), echo-safety check for operator command text, operator command builder. |
| `report.py` | Per-device report with epistemic tags, `--check`, `--redact`, `--out`. |
| `fleet.py` | `device list` (grouping), `device show` (history), `compare`. |
| `rules_doc.py` | `rs.py rules`: renders rule tables, parameters and the wear whitelist from the same objects the code evaluates. |
| `guard_patterns.py` | Pure destructive-command matcher for the guard hook: tokenizer, wrapper tables, shell unwrapping, rule ids. |

Thresholds and rule parameters live in code only; read them with `python recovery-storage/scripts/rs.py rules`.

## Dev tools: `tools/`

- `capture_fixtures.py <label> [--out DIR]`: runs the frozen PowerShell scripts and read-only smartctl against the real machine and writes RAW output (real serials) to a git-ignored folder under the plan's `research/samples/`. Run with `python -I`.
- `redact_fixtures.py`: builds the committed fixture corpus from those raw files, replacing serials, WWNs, EUI-64 extensions, GUIDs and hostnames with deterministic same-shape placeholders. `--check` exits 1 if an original identifier is found under `recovery-storage/`. Run with `python -I`.

## Tests layout

All under `recovery-storage/scripts/tests/`; `pytest.ini` points `testpaths` there, adds `recovery-storage/scripts` to `pythonpath` and deselects the `live` marker by default.

- `CONTRACT.md`: the minimum signatures, output keys and exit codes the frozen tests rely on, plus sections for amendments 01 and 02. Part of the spec.
- `conftest.py`: shared helpers (CLI driver with a scripted operator, `RecordedRunner` answered from captures). No helper spawns smartctl or PowerShell.
- `test_*.py`: one file per module or behaviour group (store, runner, allow-list, enumeration, identity, health, triage, delta, ingest, gate, data state, verdict, report, fleet, guard hook and patterns, install, scenarios, skill docs, Python compatibility, no-subprocess-outside-runner, fixture sources, live smoke).
- `fixtures/`: real captures and single-field derivations. `SOURCES.md` lists the origin, tool version and content of every file and, for each `*.derived.*` file, the changed field and its original value. `windows/<capture>/` holds PowerShell and smartctl outputs from this machine; `smartctl/` holds this machine's NVMe output and Scrutiny (MIT, `LICENSE-scrutiny`) samples; `ingest/` holds ddrescue and F3 samples; `linux/` holds WSL output.
- `scenarios/<name>/`: cross-phase end-to-end cases (`script.json` drives the CLI, `expected.json` holds the outcome), run by `test_scenarios.py`.
- Frozen suite manifest: `.claude/frozen-tests.json` records the sha256 of each frozen file, the criterion-to-test map, criteria not fully automatable (`uncovered`) and the amendment history. See [code-standards.md](code-standards.md) for the amendment process.
- `live` marker: needs a real device, admin rights, another interpreter or a live Claude Code session; run with `-m live`. `slow` marks tests that spawn real non-device processes.
