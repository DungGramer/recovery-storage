# Test contract (frozen with the spec-first suite, 2026-10-19)

The plan (`plans/20261019-1726-recovery-storage-skill/`) names modules and behaviours; where it leaves a
signature, output key or exit code open, this file fixes the MINIMUM the frozen tests rely on. It is part
of the spec. Anything not stated here is the implementer's choice. Changing anything here = amendment
(report it, do not edit the frozen tests).

Conventions: "dict" = JSON-like mapping with exactly the named keys present (extra keys allowed).
"str enum" values are lowercase-kebab unless quoted otherwise. All timestamps are ISO-8601 UTC strings
produced from the injected clock.

## 1. Entry point and context

```python
rslib.cli.main(argv: list[str], *, runner=None, clock=None, os_family=None, operator=None) -> int   # operator: Amendment 01
rslib.cli.build_parser() -> argparse.ArgumentParser          # used by F3 (subcommand tree)
```
- Returns the exit code; prints to `sys.stdout` / `sys.stderr`. Never raises for user, tool or store
  errors (no traceback on stderr). argparse usage errors may surface as `SystemExit(2)`; tests accept that.
- `runner`: object with `run(tool_id, args, env=None) -> RunResult` and a writable attribute `store`
  (None until bound). When `main` receives a runner whose `store` is None it assigns the opened store
  before dispatch, so every run is persisted (A17, G5). Default: `SubprocessRunner()`.
- `clock`: zero-arg callable returning a timezone-aware UTC `datetime`. Every stored timestamp
  (sessions, events, observations, snapshots, evidence, gates, verdicts, tool_runs) comes from it.
- `os_family`: `"windows"` or `"linux"`; selects enumeration (PowerShell scripts vs lsblk). Default from
  `sys.platform`.
- Global flags go BEFORE the subcommand: `--home PATH`, `--json`.
- `rs.py` = `sys.exit(rslib.cli.main(sys.argv[1:]))`.
- (Amendment 01) `operator`: object with `ask(prompt) -> str`; default `rslib.operator.ConsoleOperator()`. See the
  "Amendment 01" section at the end.

Exit codes (phase 01): 0 ok, 2 usage error, 3 refused (safety/evidence rule), 4 tool/environment
failure (incl. home not writable, schema newer, purpose of the command failed), 5 needs human
decision (ambiguous identity).

## 2. `--json` output

With `--json` stdout is exactly ONE JSON object (A11) and nothing else. Every object has:
- `ok`: bool, `exit_code`: int
- `reasons`: list of machine codes (empty when ok). Refusal / failure / ambiguity codes named in the
  plan are used verbatim (`unknown-action`, `risk-above-ceiling`, `data-not-secured`, `ambiguous`,
  `device-not-found`, `device-changed`, `global-lock-held`, `device-busy`, `image-incomplete`,
  `capacity-verify-missing`, `replug-observation-missing`, `evidence-before-recovery`,
  `selftest-missing`, `counters-rising`, `classify-device-first`, `unresolved-identity-drift`, ...).
- `message`: human text (may be empty).
Exit-2 usage errors may skip JSON; their text (stdout or stderr) must list the valid values (A6, A9).

Command-specific keys (only those tests read):

| command | keys |
|---|---|
| `session new/show/set` | `session`: {`id`, `goals`[list], `ceiling`, `preserve_data` ("yes"/"no"/"unknown"), `preserve_forced` bool, `data_value`, `effective_data_value`, `risk_tolerance`, `nominal_bytes` int/null, `symptoms`[list], `tried`[list], `device_type` str/null}; `show` also `events`: [{`ts`, `who` ("operator"/"agent"), `field`, `old`, `new`}] |
| `session list` | `sessions`: [session...] |
| `session data-state` | `data_state`: "none"/"secured"/"waived"/"not-needed" |
| `inventory` | `observations`: [{`observation_id`, `device_id` (null when ambiguous/unlinked), `match` ("exact"/"probable"/"weak"/"ambiguous"/"conflict"/"none"), `created` bool, `os_path` ("/dev/pdN" or lsblk path), `join` ("joined"/"join_conflict"/"not_applicable"), `model`, `bytes`, `is_boot`, `is_system`, `fs_unrecognised`, `detected_class`, `usb` ({`vid`,`pid`,`usb_serial`} or null), `fingerprint`: {`model`,`serial_norm`,`serial_trust`,`bytes`,`bus`,`vid`,`pid`,`eui64`,`wwn`,`ptuuid`,`mbr_signature`,`os_ids`}, `candidates`: [{`device_id`,`model`,`bytes`}]}] |
| `device link` | `observation_id`, `device_id`, `created` |
| `collect` | `device_id`, `snapshot`: {`id`, `collection_status`, `source` ("collected"), `tool_version`, `spinup` bool, `sha256`}, `events`: {`status`, `items`: [{`provider`,`id`,`level`,`time`,`message`,`tag`}]}, `detected_class`, `declared_class`, `class_conflict` bool |
| `ingest smartctl` | `device_id`, `created` bool, `match`, `snapshot`: {`id`, `collection_status`, `source` ("ingested"), `sha256`, `tool_version`} |
| `ingest ddrescue/f3probe/f3write/f3read/attested` | `evidence`: {`id`, `kind`, `sha256`, `level` ("parsed"/"attested"), `parsed`: parser output (sec. 6)} |
| `assess` | `assessment`: {`id`, `rules_version`, `inputs`: {`snapshot_ids`, `evidence_ids`}, `health`: HealthVerdict dict, `triage`: {`class`, `rule_id`, `branch` ("a"/"b"/"c" for HARDWARE_DIAGNOSIS_REQUIRED else null), `constraints`[list], `evidence`[list], `next_test`}, `hypotheses`: [{`category`, `confidence`, `evidence`[list], `alternative`, `next_test`}]} |
| `gate open` | `gate`: {`id`, `state`, `kind`, `risk`, `writes_source`}, `confirmation`: {`model`, `serial`, `bytes`, `bus`, `vid`, `pid`, `os_paths`[list], `kind`, `risk`, `writes_source`, `stop_criteria`, `constraints`, `phrase`, `identity_level`}, `before`: {`observation_id`, `snapshot_id`, `collection_status`}, `candidates` (exit 5): [{`os_path`, `model`, `bytes`}] |
| `gate confirm` | `gate`: {`id`, `state`, `abort_reason`}, `os_path` |
| `gate close` | `gate`: {`id`, `state`, `outcome`, `identity_drift`}, `after`: {`observation_id`, `snapshot_id`, `collection_status`} |
| `gate abort` / `gate list` | `gate` / `gates`: [{`id`, `state`, `kind`, `risk`, `device_id`, `session_id`}] |
| `verdict set` | `verdict`: {`status`, `ts`}; refusal: `reasons` = every missing item |
| `verdict show` | `verdicts`: [{`status`, `ts`, `reason`, `limitation`}] newest first, `effective`: status |
| `device list` | `devices`: [{`device_id`, `model`, `bytes`, `class`, `triage`, `health`, `verdict`, `last_seen`}], `groups`: [{`key`, `device_ids`}] (with `--group-by`) |
| `device show` | `device`: {...}, `history`: [{`ts`, `session_id`, `type`, `id`}] chronological |
| `compare` | `valid` bool, `reason`, `fields`: {name: int delta or "n/a"} |
| `report` | `devices`: [{`device_id`, `sections`: [{`number`, `heading`, `items`: [{`tag`, `text`, `rule_id`, `confidence`, `tool`, `evidence_id`, `sha256`}]}]}], `check`: {`ok`, `missing_sections`[ints]} |
| `rules` | `health_rules`, `triage_rules`: [{`id`, `required_fields`, `outcome`, `source`}], `parameters`: [{`name`, `value`, `source`}], `wear_whitelist`: [{`id`, `name`}] |

Evidence item (health, triage, hypothesis): dict {`path`, `value`, `strength` ("strong"/"medium"/"weak")}.
`path` is the dotted smartctl JSON path (`smart_status.passed`,
`nvme_smart_health_information_log.media_errors`, `ata_smart_self_test_log.standard.table[2].status.string`);
ATA attributes use `ata_smart_attributes[<id>].<value|worst|thresh|raw|when_failed>`; delta items use
`delta.<field>`; OS facts use `observation.<field>`; ingested records use `evidence.<kind>.<field>`.

## 3. Commands and arguments

```
session new --goal G [--goal G...] [--ceiling R0..R3] [--preserve-data yes|no|unknown]
            [--device-type T] [--nominal SIZE] [--symptom S...] [--tried T...] [--note TEXT] [--os TEXT]
            [--data-value irreplaceable|important|replaceable|unknown] [--risk-tolerance low|medium|high]
session show|list|note <id> <text>|set <id> [--ceiling] [--data-value] [--risk-tolerance] [--goal...]
session data-state <session> <device> secured|waived|not-needed [--evidence ID] [--attested] [--reason T]
            (Amendment 01: waived / secured --attested / not-needed ask the operator for `YES`)
inventory [--session SID] [--after-replug]
collect <device> --session SID [--dtype T] [--allow-spinup]
device link <observation> (<device> | --new) ; device list [--group-by triage|category|status] ; device show <id>
ingest smartctl <file> --session SID
ingest ddrescue|f3probe|f3write|f3read <session> <device> <file> [--exit-code N]   (f3*: --exit-code required)
ingest attested <session> <device> --tool h2testw|other --result pass|fail --file F [--note T]
            (Amendment 01: asks the operator for `YES`)
assess <session> <device>
gate open <session> <device> <kind> [--dest-device D] [--controller-id X] [--tool-source T]
gate confirm <gate>   (Amendment 01: no --phrase; phrase typed at the operator prompt)
gate close <gate> --outcome success|failed|interrupted [--note T] [--evidence ID...]
gate abort <gate> --reason T ; gate list
verdict set <session> <device> <STATUS> [--limitation T] [--reason T] ; verdict show <session> <device>
report <session> [--device ID] [--redact] [--out PATH] [--force] [--check]
compare <snapA> <snapB> | compare --device <id>      (device form: two most recent snapshots, older -> newer)
rules
```
- `assess` evaluates the device's latest snapshot in that session; `prev` = the most recent earlier
  snapshot of the same device from ANY session (health delta), while triage branch (c) only uses pairs
  from the same session.
- `ingest smartctl` of a document with no identity at all creates a new device (B22 "no match -> new
  device created"); that device has no readable identity (C17).
- Text (non-JSON) output must contain the literal strings quoted in the plan: `no sessions` (A1),
  `database schema newer than this tool` (A4), `forced` (A7), `ceiling R0 -> R2` (A10),
  `re-run elevated to try SAT passthrough; this is not a device fault` (B18), `winget install
  smartmontools.smartmontools` and `scoop install smartmontools` (B20), `identity weak: same-size media
  in this reader cannot be told apart` (D9b), `waived --reason` (D20), `INVALID COMPARISON: <reason>` (E10),
  `UNRESOLVED (no verdict recorded)` (E1). Matching is case-insensitive.

## 4. Runner and allow-list

```python
rslib.runner.RunResult            # attrs: tool, tool_version, argv, exit_code, timed_out, tool_missing, duration_s, stdout, stderr
rslib.runner.CommandNotAllowed    # Exception; also importable from rslib.allowlist (same class)
rslib.runner.UnrecordedCommand    # Exception raised by RecordedRunner for an allowed argv with no recording
rslib.runner.STDERR_MAX: int      # stored stderr truncation length
rslib.runner.SubprocessRunner(store=None, timeouts: dict[str, float] | None = None)
rslib.runner.Recording(tool_id, args, stdout=b"", exit_code=0, stderr="", tool_version=None,
                       tool_missing=False, timed_out=False)   # attrs tool_id, args (same names)
rslib.runner.RecordedRunner(recordings: list[Recording], store=None)
    .run(tool_id, args, env=None) -> RunResult
    .calls       list[tuple[str, tuple[str, ...]]]  answered calls, in order
    .unrecorded  list[tuple[str, tuple[str, ...]]]  allowed calls with no recording (also raised)
rslib.allowlist.check(tool_id, args, env=None) -> None   # raises CommandNotAllowed
rslib.allowlist.PS_SCRIPT_SHA256: dict[str, str]          # {"win-disks"|"win-pnp-chain"|"win-events": sha256 hex of file bytes}
rslib.allowlist.PS_ENV_BOUNDS: dict[str, tuple[int, int]] # inclusive bounds for RS_LOOKBACK_HOURS, RS_MAX_EVENTS, RS_MESSAGE_CHARS
```
- `args` excludes the executable. Tool ids: `smartctl`, `powershell`, `lsblk`, `udevadm`, `blockdev`,
  `lsusb`, `journalctl`, `dmesg`. PowerShell args are exactly
  `["-NoProfile", "-NonInteractive", "-EncodedCommand", b64]`, b64 = base64(UTF-16LE(file text read as UTF-8)).
- `env` = only the `RS_*` parameters of the call; the runner builds the child environment.
- Recording key = (tool_id, tuple(args)); env is validated, not part of the key. The validator runs
  BEFORE the lookup (a recorded but forbidden argv still raises `CommandNotAllowed`).
- Version probing (e.g. `smartctl -V`) is internal to `SubprocessRunner`, never issued via `run()`;
  `RecordedRunner` reports `Recording.tool_version`.
- Windows identity probe issued by `inventory`/re-resolution: `smartctl -j -i -n standby /dev/pd<N>`;
  `collect`: `smartctl -j -x -n standby <path>`, USB retry `smartctl -j -x -n standby -d sat <path>`,
  `--allow-spinup` drops `-n standby`; `--dtype T` inserts `-d T` before the device path.

## 5. Store

```python
rslib.store.SCHEMA_VERSION: int
rslib.store.open_store(home) -> Store      # creates <home>/rs.sqlite and <home>/sessions/; Store.close()
```
Tables read directly by tests (column names fixed):
- `tool_runs(tool, tool_version, argv, exit_code, timed_out, tool_missing, refused, duration_s, stderr,
  stdout_sha256, stdout_path)`; `stdout_path` relative to home (or absolute under home); refused rows
  have `refused = 1` and `exit_code` NULL.
- `gates(id, state, lock_slot, device_id, ...)`; `state` in `pending|open|closed|aborted` (phase 08 contract);
  partial unique indexes as in phase 04. (Amendment 01) column `confirmed_by`.
- (Amendment 01) `data_states(..., who)` and `evidence(id, ..., who)`; see the "Amendment 01" section.

## 6. Pure modules

```python
rslib.smart.normalise(data: bytes | str, *, exit_code: int | None = None) -> SmartRecord
    # attrs: collection_status, flags (frozenset[str]), message (str|None), identity (dict: model, serial,
    #        firmware, bytes, protocol, device_type, eui64, wwn, rotation_rate), health_fields (dict),
    #        detected_class (str|None), sha256, raw (bytes)
    # health_fields keys (value None when the source lacks it, never 0/False by default):
    #   all: overall_passed, power_on_hours, temperature
    #   NVMe: critical_warning, available_spare, available_spare_threshold, percentage_used, media_errors,
    #         num_err_log_entries, data_units_written, temperature_warning, temperature_critical
    #   ATA: attributes = {id(int): {"name", "value", "worst", "thresh", "raw", "when_failed"}}
rslib.smart.exit_flags(code: int) -> frozenset[str]       # bits 3-7 only:
    # 8 smart_failing, 16 prefail_threshold_now, 32 attribute_failed_in_past, 64 error_log_has_records, 128 selftest_log_has_errors
rslib.smart.classify_collection(exit_code: int | None, messages: list[str]) -> str   # collection status enum
rslib.enum_windows.parse(win_disks_text: str, pnp_chain_text: str | None = None) -> list[OsDisk]
rslib.enum_linux.parse_lsblk(text: str) -> list[OsDisk]
rslib.enum_linux.sysfs_usb(dev_name: str, sys_root=pathlib.Path("/sys")) -> dict | None
rslib.enum_linux.sysfs_mmc(dev_name: str, sys_root=pathlib.Path("/sys")) -> dict | None
    # OsDisk attrs: number (int|None), os_path, model, bytes, bus, serial_raw, unique_id, mbr_signature,
    #   ptuuid, is_boot, is_system, health_status, partition_style, fs_unrecognised, usb (dict|None),
    #   tran, removable, read_only, hotplug
rslib.events.parse_windows(text: str) -> EventsResult   # attrs: status, items (list[dict] as in collect JSON)
rslib.identity.normalise_serial(raw) -> dict {"raw", "serial_norm", "eui64"}
rslib.identity.serial_trust(serial_raw, other_attached=()) -> "high"|"low"|"absent"
rslib.identity.Fingerprint(**fields)        # keyword-only, every field optional (None / {} default)
rslib.identity.fingerprint(os_disk=None, smart=None, attached=()) -> Fingerprint
rslib.identity.match(fp, candidates: dict[str, Fingerprint], attached=()) -> MatchResult(level, device_ids)
    # attached = fingerprints of the OTHER currently attached devices; level adds "conflict"
rslib.identity.windows_join(os_disk, smart) -> "joined"|"join_conflict"|"not_applicable"
rslib.health.verdict(rec: SmartRecord, prev: SmartRecord | None = None) -> HealthVerdict
    # attrs: verdict, confidence, evidence (list), missing (list[str] of JSON paths), reason, next_test, rule_id
rslib.health.RULES / rslib.triage.RULES    # sequences of objects with id, outcome, required_fields, source; triage rules also branch
rslib.delta.delta(a: SmartRecord, b: SmartRecord) -> DeltaResult(valid, reason, fields, rising)
    # fields keys: attr_5, attr_187, attr_197, attr_198, attr_199, media_errors, percentage_used,
    #              num_err_log_entries, power_on_hours; value = int (b - a) or "n/a"; rising = list of keys
rslib.wear.assess(rec) -> dict {"used_pct", "remaining_pct", "source" ("devstat"|"attribute"|"nvme"|None), "confidence"}
rslib.wear.from_attribute(attr_id: int, name: str, value: int) -> int | None   # remaining % for whitelisted rows
rslib.wear.host_writes_bytes(rec) -> int | None
rslib.ingest.MalformedInput(Exception)  # attr .line (1-based) or None for whole-file problems
rslib.ingest.parse_mapfile(text) -> obj attrs total, rescued, bad, non_tried, non_trimmed, non_scraped, rescued_pct, finished
    # (Amendment 01) + start, end, contiguous
rslib.datastate.mapfile_complete(parsed, device_bytes) -> (bool, reason)   # Amendment 01
rslib.operator.ConsoleOperator / ScriptedOperator(answers) / NoConsole    # Amendment 01
rslib.ingest.parse_f3probe(text, exit_code) -> dict {"result": "good"|"damaged"|"fake"|"inconclusive", "fake_type", "reason"}
rslib.ingest.parse_f3write(text, exit_code) -> dict {"result", "reason"}
rslib.ingest.parse_f3read(text, exit_code) -> dict {"result": "pass"|"fail"|"inconclusive", "reason", "data_ok_bytes", "data_lost_bytes", "overwritten_bytes"}
rslib.actions.CATALOG: dict[str, Action]   # Action attrs: kind, risk ("R1".."R3"), writes_source (bool|None for n/a),
                                           # requires (tuple of flag names, e.g. ("--dest-device",)), stop_criteria (str),
                                           # allows(cls: str) -> bool  ("external-*" covers every external-<inner> class)
rslib.guard_patterns.find(command: str) -> Match | None      # Match attrs: rule_id, segment
rslib.guard_patterns.RULES                                     # objects with attr id
```
Reasons/strings fixed for tests: delta invalid reasons contain `power-on hours went backwards` /
`identity differs`; f3probe disagreement reason contains `disagree`; f3write `No space!` reason contains
`nothing written`; health `reason` for collection problems = the collection status value
(`needs_elevation`, `collection_failed`, ...).

## 7. Guard hook and installer

```python
guard_hook.main() -> int     # recovery-storage/scripts/guard_hook.py; reads sys.stdin, env RECOVERY_STORAGE_HOME
install_junction.main(argv: list[str] | None = None) -> int   # flag --skills-dir DIR (default ~/.claude/skills)
```
`guard.log` line: one line per matched decision containing the rule id, the decision word (`deny`/`allow`),
the gate id or `-`, and the sha256 hex of the command.

## Amendment 01 (2026-10-19): operator console, full-coverage mapfiles

Source: `plans/20261019-1726-recovery-storage-skill/amendment-01-operator-console-and-mapfile-coverage.md`
(approved by the user after code review findings C1 / H7). Where this section and sections 1-7 disagree, this
section wins. Lines marked "test-designer reading" fill gaps the amendment leaves open; they are listed as open
questions in the test-designer report and bind the frozen tests until a further amendment.

### A. Operator console

```python
rslib.cli.main(argv, *, runner=None, clock=None, os_family=None, operator=None) -> int
rslib.operator.NoConsole                      # Exception subclass
rslib.operator.ConsoleOperator()              # .ask(prompt) -> str; raises NoConsole unless sys.stdin.isatty()
rslib.operator.ScriptedOperator(answers: list[str])   # .ask returns answers in order; exhausted -> NoConsole
```
- `operator=None` -> `ConsoleOperator()`. `rs.py` never passes an operator. Tests pass a ScriptedOperator (the
  conftest `Cli` driver passes an EMPTY one unless `answers=` / `operator=` is given).
- Commands that ask; exactly ONE `ask` call per invocation (test-designer reading; D12d, D20e, C24d and the
  scenario runner count prompts):
  1. `gate confirm <gate>`: no `--phrase` argument (argparse exit 2 if given). Prints the confirmation summary,
     asks `Type the confirmation phrase: `; the answer is compared with the gate phrase. Wrong -> exit 3
     `wrong-phrase`, gate stays `pending`, `confirmed_by` stays empty/NULL. Right -> as before (re-resolution,
     `os_path`, D12-D14).
  2. `session data-state <s> <d> waived --reason T`, `secured --attested --reason T`, `not-needed`: asks
     `Type YES to record data state <state> for <device> (<model>, <bytes> bytes): `. Any answer other than the
     exact string `YES` (lowercase `yes`, empty, `Y`, `no`) -> exit 3 `operator-declined`, store unchanged.
     `secured --evidence E` does NOT ask (tool evidence).
  3. `ingest attested ...`: asks `Type YES to attest <tool> <result> for <device>: `; same `YES` rule. Other
     `ingest` kinds do NOT ask.
- Usage errors (missing `--reason`, missing `--file`) stay exit 2 whether or not an answer is available. Other
  refusals (e.g. `not-needed` with preserve=yes) keep their own reason, never an operator reason, when the
  operator answered `YES`.
- `NoConsole` -> exit 3, reason `operator-console-required`; `message` contains the command line for the human:
  `python <abs path>/rs.py gate confirm <gate>` (resp. `python <abs path>/rs.py session data-state <s> <d> <state> ...`,
  `python <abs path>/rs.py ingest attested <s> <d> ...`). `<abs path>` = absolute directory of `rs.py`; either path
  separator accepted, compared case-insensitively. Test-designer reading: an optional global `--home <path>` between
  `rs.py` and the subcommand is allowed (the human must reach the same store). Nothing in `gates`, `data_states`,
  `evidence` changes (tool_runs / observations written by re-resolution before the ask are allowed).
- Audit: `gates.confirmed_by` = `operator` after a confirm; `data_states.who` = `operator` for the asked states;
  `evidence.who` = `operator` for attested evidence. Table names `data_states` and `evidence` are fixed;
  `evidence.id` equals the JSON `evidence.id`; a `data_states` row holds the session id in one of its columns.
- Report: the JSON item `tag` of attested evidence stays `[ATTESTED]` (four-tag rule, E3,
  `test_report_tags_only_the_four`); the rendered markdown shows `[ATTESTED by operator]` (test-designer reading of
  "the report shows").
- Known leak (documented in SKILL.md, not tested): a script importing rslib and injecting an operator, or a
  pseudo-terminal wrapper, defeats this.

### B. Full-coverage mapfiles

- `parse_mapfile(text)` adds `start` (pos of first block), `end` (pos + size of last block), `contiguous` (bool:
  every pos == previous pos + size). Existing fields unchanged. Positions/sizes wider than 32 bits parse
  (`0x1D1C0FF6000`).
- `rslib.datastate.mapfile_complete(parsed, device_bytes) -> (ok: bool, reason: str | None)`; `parsed` = the
  object returned by `rslib.ingest.parse_mapfile` (attribute access; test-designer reading, D20b unit cases).
  Complete only if
  `start == 0`, contiguous, `end == device_bytes`, finished (status line `+`), and bad == non_tried == non_trimmed ==
  non_scraped == 0. Reasons: `image-incomplete` (unfinished, or bad / non-tried / non-trimmed / non-scraped bytes),
  `image-not-contiguous`, `image-does-not-cover-device` (start != 0, end != device bytes, or device bytes
  unknown/None).
- Precedence when several fail (test-designer reading; the kept D20 and G9 cases use the verbatim floppy partial
  map, which is both incomplete and too small for a real disk): `image-incomplete`, then `image-not-contiguous`,
  then `image-does-not-cover-device`.
- Device byte count = the device's identity bytes (inventory observation `bytes` / snapshot `user_capacity.bytes`,
  equal on every fixture used). Test-designer reading: every test that needs it has a snapshot of the device
  (collect or ingest smartctl) and, for captures, an inventory observation.
- `session data-state <s> <d> secured --evidence E` refuses with the `mapfile_complete` reason (exit 3); the
  message still suggests `waived --reason`. Evidence of another device stays refused (exit 3).
- Verdict, SSD/NVMe "one read verify": a ddrescue record counts only when `mapfile_complete` is true for that
  device (other read-verify forms unchanged).
- Fixtures: `ingest/ddrescue-finished.980pro.derived.map` (2000398934016 B),
  `ingest/ddrescue-finished.990pro.derived.map` (1000204886016 B), `ingest/ddrescue-finished.hitachi500.derived.map`
  (500107862016 B): verbatim 1.30 structure, last block size computed (fixtures/SOURCES.md).
