# Phase 01 - Foundation: package, guarded runner, store, sessions, fixtures

## Context Links
- Spec §1.1 goals, §2 Phase 0 risk levels, §4 rule 10 (no sensitive data in logs), §5 storage: [requirements.md](requirements.md)
- smartctl read-only flags, exit bitmask: [researcher-01](research/researcher-01-smartctl-nvme-json.md) §2, §4
- Windows facts (PowerShell 5.1 UTF-16 redirect, Git Bash path rewrite): requirements.md "Facts verified"
- Fixtures (BUILT 2026-10-19 by main agent): `recovery-storage/scripts/tests/fixtures/SOURCES.md` (origins, commit ac2056d6 scrutiny MIT, redaction, "No real sample yet" list); dev tools `tools/capture_fixtures.py`, `tools/redact_fixtures.py`
- PowerShell scripts (BUILT): `recovery-storage/scripts/rslib/ps/{win-disks,win-pnp-chain,win-events}.ps1`

## Overview
- Priority: P0 (everything depends on it). Status: Todo (steps 1-2 Done by main agent 2026-10-19).
- Builds the skeleton every later phase plugs into: `rs.py` entry, `rslib` package, the ONLY process runner, SQLite store with evidence files, session model (goals, ceiling, preserve flag, data value, risk tolerance, symptoms), pytest wiring. Fixture corpus already exists.

## Key Insights
- Safety of the whole skill rests on one choke point: if only `runner.py` can spawn processes and it validates argv before spawn, "no code path runs a non-allow-listed command" becomes a checkable property (static scan + unit tests), not a promise.
- Allow-list, never deny-list (researcher-01 §4). PowerShell is allow-listed by frozen script content (sha256 of the shipped `.ps1` files), not by parsing script text; its parameters arrive only through validated env vars.
- subprocess with argv list avoids Git Bash `/dev/sda` rewriting and PowerShell UTF-16 redirection; decode stdout as UTF-8 (`errors="replace"`), PowerShell scripts set `[Console]::OutputEncoding` to UTF-8.
- Missing value is never 0: store layer keeps `null` + reason so later rules can say "unknown".

## Requirements
Functional
- Home: `--home` > env `RECOVERY_STORAGE_HOME` > `~/.recovery-storage`. Created on first use; on POSIX mode 0700.
- `session new|show|list|set|note`. Goals: the six spec goals, one or more. Ceiling `R0..R3`, default `R0`. `--preserve-data yes|no|unknown` (unknown behaves as yes). Goals `data-recovery` or `forensic-preservation` force preserve=yes. `--device-type` declared class, `--nominal` capacity, `--symptom` codes (fixed enum) + `--note` free text, `--os`/connection text.
- Phase-0 risk fields (spec "mức độ chấp nhận rủi ro và chi phí phục hồi", decision Q5): `--data-value irreplaceable|important|replaceable|unknown` (default unknown) and `--risk-tolerance low|medium|high` (default `medium`, see plan.md open question). Effective data value: `unknown` + preserve=yes -> `irreplaceable`; `unknown` + preserve=no -> `replaceable`. `session show` prints stored and effective value.
- Every session mutation is an appended audit event (who=operator|agent field, timestamp, old -> new); nothing is silently overwritten.
- Runner API: `run(tool_id, argv) -> RunResult{tool, tool_version, argv, exit_code, timed_out, tool_missing, duration_s, stdout, stderr}`; `CommandNotAllowed` raised before any spawn.
- Global CLI flags: `--json` (machine output), `--home`. Exit codes: 0 ok, 2 usage error, 3 refused (safety/evidence rule), 4 tool/environment failure, 5 needs human decision (ambiguous).
Non-functional
- Python >= 3.10 stdlib only at runtime (no 3.11+ APIs: `tomllib`, `datetime.UTC`, `StrEnum`, `ExceptionGroup`). pytest dev-only.
- No network access in any code path.

## Architecture
```
recovery-storage/scripts/rs.py            -> rslib.cli.main(sys.argv[1:])
rslib/cli.py       argparse tree; each subcommand = function(args, ctx) ; ctx = {store, runner, clock}
rslib/paths.py     home resolution, evidence dir layout
rslib/runner.py    SubprocessRunner (real) + RecordedRunner (tests, same validator); sole subprocess import
rslib/allowlist.py tool table: tool_id -> executable resolution, argv validator, default timeout, version probe
rslib/store.py     sqlite3, schema v1 (PRAGMA user_version), migrations list, atomic evidence writes
rslib/session.py   goal/ceiling/symptom enums, validation, audit events
```
Allow-list v1 (validators are exact, positional):
- `smartctl`: options subset of `-j -i -H -A -c -a -x`, `-l error|xerror|selftest|selective|directory|devstat|sataphy|scttemp`, `-n standby`, `-d auto|sat|sat,12|sat,16|nvme|sntjmicron|sntasmedia|sntrealtek|usbjmicron`, `--scan`, `--scan-open`, `-V`; exactly one device arg matching `/dev/(sd[a-z]{1,2}|pd\d{1,3}|nvme\d+(n\d+)?|mmcblk\d+)` except for scan/-V. Anything with `-t -s -S -o -C -X -g -T -r` or a `,x` suffix is rejected.
- `powershell`: `powershell.exe -NoProfile -NonInteractive -EncodedCommand <b64>` where b64 (UTF-16LE) decodes to the exact text of one of `rslib/ps/*.ps1` whose sha256 is in the frozen table in `allowlist.py` (ids `win-disks`, `win-pnp-chain`, `win-events`). Child env is built by the runner: for `win-events` only `RS_LOOKBACK_HOURS`, `RS_MAX_EVENTS`, `RS_MESSAGE_CHARS`, each a decimal integer within bounds (parameters in `allowlist.py`); anything else -> `CommandNotAllowed`.
- `lsblk -J -O -b [dev]`, `udevadm info --query=property --name=<dev>`, `blockdev --getro|--getsize64 <dev>`, `lsusb`, `journalctl -k -o json --since <iso> --no-pager`, `dmesg --time-format iso`.
- Executable resolution: `shutil.which`; override per tool via env `RS_<TOOL>` (absolute path, must exist).
Store schema v1 tables: `sessions, session_events, devices, observations, snapshots, assessments, evidence, gates, verdicts, tool_runs`. Phase 01 creates all tables (later phases fill them) so no migration is needed inside this plan; `tool_runs` stores every RunResult minus stdout (stdout goes to an evidence file, sha256 in row).

## Related Code Files
Create (all under `D:\Downloads\Documents\CODE\recovery-storage\`):
- `recovery-storage/scripts/rs.py`, `recovery-storage/scripts/rslib/{__init__,cli,paths,runner,allowlist,store,session}.py`
- `recovery-storage/scripts/tests/{conftest.py,test_runner.py,test_allowlist.py,test_store.py,test_session.py,test_no_subprocess_outside_runner.py}`
- `pytest.ini` (repo root: `testpaths = recovery-storage/scripts/tests`, `pythonpath = recovery-storage/scripts`)
Existing (do not recreate): `.gitignore` (samples ignored), `recovery-storage/scripts/tests/fixtures/**`, `recovery-storage/scripts/rslib/ps/*.ps1`, `tools/capture_fixtures.py`, `tools/redact_fixtures.py`.
Modify: `fixtures/SOURCES.md` only when later phases add derived fixtures.

## Implementation Steps
1. DONE (main agent): `.gitignore` ignores `plans/*/research/samples/`; `requirements.md` identifiers redacted in place.
2. DONE (main agent): redacted fixture corpus (smartctl, Windows captures, WSL lsblk/udevadm) + `SOURCES.md` + `LICENSE-scrutiny`.
3. `paths.py`, `store.py` (schema, user_version check, atomic write temp+rename, sha256).
4. `allowlist.py` (incl. sha256 table of `rslib/ps/*.ps1` and env bounds) + `runner.py` (timeout kill, tool_missing, version probe cached per process, RunResult persisted via store hook).
5. `session.py` + CLI `session *`.
6. Tests per acceptance criteria (frozen by test-designer before steps 3-5).

## Todo List
- [x] gitignore samples before first commit (main agent)
- [x] redacted fixture corpus + SOURCES.md + license (main agent)
- [ ] store schema v1 + evidence writer
- [ ] allow-list + runner (real + recorded)
- [ ] session commands + audit events
- [ ] static check: subprocess only in runner.py

## Acceptance Criteria (observable)
Home and store
- A1 `rs.py --home <tmp> session list` on empty dir: exit 0, creates `<tmp>/rs.sqlite` and `<tmp>/sessions/`, prints "no sessions".
- A2 With env `RECOVERY_STORAGE_HOME=<a>` and `--home <b>`: data lands in `<b>`. Env only: `<a>`. Neither: `~/.recovery-storage`.
- A3 Home path not writable: exit 4, message names the path; no traceback.
- A4 DB whose `user_version` is greater than the code's schema version: every command exits 4 with "database schema newer than this tool"; DB file unchanged (same sha256).
Sessions
- A5 `session new --goal data-recovery --goal diagnosis-only`: exit 0, prints new session id; `session show <id>` lists both goals, ceiling `R0`, preserve `yes`.
- A6 `--goal foo`: exit 2, message lists the six valid goals. `--ceiling R4`: exit 2.
- A7 `--goal data-recovery --preserve-data no`: preserve stored as `yes` and output states it was forced and why; audit event recorded.
- A8 `--nominal 64GB` stored as 64000000000 bytes; `1TB` -> 1000000000000; `500107862016` -> same; `64GiB` -> 68719476736; `abc` or `0` -> exit 2.
- A9 `--symptom mechanical-noise` accepted; `--symptom clicking-noise` (not in enum) -> exit 2 listing the enum. Enum (frozen): `mechanical-noise, burning-smell, physical-damage, liquid-damage, overheating, not-detected, disconnects-repeatedly, slow-io, read-only, wrong-capacity, raw-or-unreadable-fs, missing-partition, deleted-files, io-errors, encrypted-locked, not-spinning`. Isolation facts (frozen): `--tried other-port|other-cable|other-host|other-os` (repeatable), used by triage in phase 03.
- A9b `--data-value` / `--risk-tolerance` outside their enums -> exit 2. No flags -> stored `unknown` / `medium`. preserve=yes + data-value unknown -> `session show` prints effective `irreplaceable`; preserve=no + unknown -> effective `replaceable`. Changing either via `session set` writes an audit event.
- A10 `session set <id> --ceiling R2` then `session show`: ceiling R2 and an audit line `ceiling R0 -> R2` with timestamp. `session set` / `show` on unknown id: exit 2 "unknown session".
- A11 `--json` on any session command prints one JSON object parseable by `json.loads`; no other stdout text.
Runner and allow-list
- A12 Accepted argv (validator returns ok): `smartctl -j -x /dev/pd1`, `smartctl -j -i -n standby /dev/sda`, `smartctl --scan-open -j`, `smartctl -j -x -d sat /dev/sdb`, `smartctl -j -x /dev/nvme0n1`, `lsblk -J -O -b`.
- A13 Rejected before spawn (`CommandNotAllowed`, no process created, refusal recorded in `tool_runs` with exit_code null): `smartctl -t short /dev/sda`, `-s on`, `-o on`, `-S on`, `-C`, `-X`, `-d sat,x`, `-T permissive`, two device args, device `C:/Program Files/Git/dev/sda`, device `/dev/sda;rm`, tool id not in table, PowerShell whose decoded script differs by one byte from the shipped file (sha256 mismatch), `win-events` with `RS_LOOKBACK_HOURS=abc`, `=-1`, `=0`, above the upper bound, or an extra env var name.
- A13b A test asserts the sha256 table in `allowlist.py` equals the hashes of the files in `rslib/ps/` (editing a script without updating the table fails the suite).
- A14 Tool executable not found: RunResult `tool_missing=true`, exit_code null, no exception escapes `run()`.
- A15 Process exceeding timeout: killed, `timed_out=true`, exit_code null, duration >= timeout; a following call works.
- A16 Non-zero exit (e.g. smartctl 216): returned as data, not raised.
- A17 Every completed run writes stdout to an evidence file whose sha256 matches the `tool_runs` row; stderr stored truncated to a fixed parameter length.
- A18 Static check: in `rslib/`, `import subprocess`, `from subprocess`, `os.system`, `os.popen`, `os.exec*`, `os.spawn*`, `pty` appear only in `runner.py`. Test fails on any other hit.
- A19 `RecordedRunner` given an argv that has no recording raises (tests never silently pass on an unexpected command); it applies the same validator as the real runner.
Fixtures
- A20 `python -I tools/redact_fixtures.py --check` exits 0 (no identifier from the git-ignored originals appears under `recovery-storage/`); run before every commit that touches fixtures.
- A21 `SOURCES.md` names, for each fixture file: origin path or URL, commit, license, smartctl version, redaction, and for `*.derived.json` the single field changed and its original value.

## Pros / cons vs alternative
Chosen: argv allow-list validated inside one runner module + static scan.
- Pros: one choke point, testable without devices, impossible to reach a non-listed flag from CLI input; recorded runner reuses the same validator.
- Cons: every new read-only flag needs a code change; validators per tool must be maintained.
Alternative: run tools via shell strings with a deny-list of dangerous flags.
- Pros: flexible, less code. Cons: deny-lists miss new flags and quoting tricks; shell adds Git Bash path rewriting and encoding traps. Rejected.

## Not Worth Doing If
- Phase as a whole is always needed. Do not redo fixture capture/redaction: it is done and A20 is the check.

## Risk Assessment
- Real serials committed by accident -> samples git-ignored; A20 is a repeatable check.
- Timeout kill on Windows leaves grandchildren -> tools here spawn none (smartctl, powershell script without child processes); document the limit.
- SQLite locked by a second process -> use `timeout` on connect and short transactions; concurrent gate acquisition handled in phase 04 by constraint.

## Security Considerations
- Home dir holds serials: outside repo, 0700 on POSIX; Windows inherits user profile ACL.
- No user file contents are ever read or logged; stdout of R0 tools only.
- Env override `RS_<TOOL>` must be an absolute existing file; relative paths rejected (avoids CWD hijack).

## Next Steps
- Phase 02 parses the PowerShell outputs and uses `runner` + `store`. Phase 08 reads `gates` read-only from the guard hook: keep `gates.state` values exactly `pending|open|closed|aborted`.
