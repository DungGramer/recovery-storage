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

## Amendment 02 (2026-10-19): identity by operator, last write, image gate, snapshot identity, self-test wrap, SSD read verify, operator command text, guard tokenizer

Source: `plans/20261019-1726-recovery-storage-skill/amendment-02-review-round-2.md` (approved by the user after code
review round 2, findings N1-N16; reproductions in the reviewer's scratchpad `scen.py`, `scen2.py`, `selftest.py`,
`guard_corpus.py`). Where this section and anything above disagree, this section wins. Lines marked "test-designer
reading" fill gaps the amendment leaves open; they are open questions in the test-designer report and bind the frozen
tests until a further amendment.

### A. Identity changes only by the operator (N1, N4, N16)

- `gate close` never changes a device fingerprint (on-media ids included).
- "Found" at close = the re-resolution returns this device alone (exact, probable or a single weak match). Not found =
  not attached, `conflict`, `ambiguous`, or only its on-media id differs (test-designer reading of "exactly": a probable
  USB match by MBR signature and a single weak SD match stay "found", as the D9b / D9c / D15 counter-cases require).
- Not found -> the gate is still `closed` (exit 0), JSON `gate.identity_drift` = `true` (stays a JSON bool as in D15;
  the amendment's "= 1" is the stored value) and `gate.drift_reason`: `media-id-changed` when exactly one attached disk
  is the same hardware (model, bytes, USB ids, trusted serial / EUI / WWN) with another MBR signature / GPT guid, else
  `device-changed`. A clean close has `drift_reason` null or absent.
- The close output (JSON `message` / text) contains the operator command `device link <observation> <device>` for
  `media-id-changed`. Test-designer reading: the observation named is one the operator can link, and linking it with
  `YES` clears this gate's drift. For `device-changed` the printed observation is not asserted.
- `device link <observation> <device>` and `device link <observation> --new` ask the operator, exactly one `ask`:
  `Type YES to link observation <obs> (<model>, <bytes> bytes, <os_path>) to <device>: ` (for `--new` the target wording
  is free). No console -> exit 3 `operator-console-required`, message `python <abs>/rs.py device link <obs>
  <device|--new>` (amendment 01 A rules, optional global `--home` tolerated). Answer not exactly `YES` -> exit 3
  `operator-declined`. Refused or declined -> nothing linked, no device created, no id learned.
- Link to an existing device whose hardware matches: learns the observation's on-media ids (a later inventory of that
  disk resolves to the device) and clears `identity_drift` on every closed gate of that device whose close happened
  before the linked observation. Gates closed after that observation keep their drift.
- Link to a device with different hardware -> exit 3 `hardware-mismatch` (use `--new`); nothing changes.
- Ambiguous inventories (exit 5, B16) still need `device link`; tests answer `YES`; scenario `device link` steps carry
  `answers`.

### B. Last write (N2, N9)

- `last_write_ts(device)` = latest of `closed_ts` of a closed gate whose kind writes the source, and `closed_ts` of an
  aborted gate whose kind writes the source and that had been confirmed; across all sessions; None if none. Gates of
  kinds that do not write the source, and write gates aborted while still pending, are not writes.
- `secured` / `waived` count for a write gate only if recorded after `last_write_ts(device)`; a stale state ->
  `data-not-secured`. Recording the state again after the write makes it count.
- Verdict window start = max(session start, `last_write_ts(device)`); evidence before it -> `evidence-before-recovery`.

### C. Secured needs an image gate (N15)

- `session data-state <s> <d> secured --evidence E` also requires a gate of kind `image-ddrescue` on that device, state
  `closed`, outcome `success`, closed in this session, with E ingested after that gate was confirmed. Missing -> exit 3
  `image-gate-missing`, store unchanged. `secured --attested` and `waived` unchanged.
- Test-designer reading: a refused `secured --evidence` lists every failing check (`image-gate-missing` and the
  `mapfile_complete` reason), as `gate open` does (D8). Tests asserting one reason make every other check pass.
- Consequence (test-designer reading, open question): a boot/system disk (D3: no gate of any kind) and a device known
  only via ingest (not attached) can never be `secured --evidence`; the HDD scenario now ends `image-gate-missing`.
- conftest `secure()` = `image_gate()` (open, operator confirm with the opened gate's phrase, close success; dest =
  another attached device of the same capture) + ingest ddrescue + `secured --evidence`. Sessions using it allow R1.

### D. Snapshot identity (N7)

- `collect` attaches a smartctl result only when the answering identity matches the device (exact / probable / weak)
  or model and bytes are equal and no strong id (serial, EUI-64, WWN) differs; otherwise exit 3 `identity-conflict` and
  no snapshot is stored for the device (`device show` history gains no snapshot). The check also runs on the `-d sat`
  retry result. Test-designer reading: an answer with no identity at all (unknown bridge, open failed) is not a
  conflict and is stored as before (B17, B18 unchanged).
- Gate before/after snapshots apply the same rule (not asserted beyond D15 / D15b: other hardware at close is drift).

### E. Self-test hours wrap (N8)

```python
rslib.verdict.selftest_window(table: list[dict], latest_poh: int, since_hours: int) -> bool
    # table = smartctl `ata_smart_self_test_log.standard.table` entries
    #         ({"status": {"passed": bool, ...}, "lifetime_hours": int, 16-bit raw});
    # latest_poh = power-on hours of the snapshot;
    # entry inside the window when (latest_poh - h) % 65536 <= latest_poh - since_hours;
    # "after" = smaller distance (latest_poh - h) % 65536, never list position or raw hours;
    # True iff an inside entry with status.passed true has no inside entry with status.passed false after it.
```
Test-designer reading: the amendment fixes the formula, not a name; this pure entry point is the minimum the frozen
tests need. "No failed entry after it" is the phase-04 PASS matrix wording.

### F. SSD read verify (N13)

- ssd-sata / nvme / external-ssd: an f3read pass counts as read verify only with coverage >=
  `rslib.verdict.CAPACITY_COVERAGE` x device bytes; ddrescue needs the full-coverage mapfile (amendment 01 B); an
  attested pass still counts (plan Q3). The f3read cases stay BLOCKED (no sourced f3read output with Data OK numbers);
  only the parameter (0 < value <= 1) is tested.

### G. Operator command text (N5)

- `--reason`, `--note`, `--file`, `--home` values that would be echoed into a printed operator command must not contain
  `"` `$` backtick `;` `&` `|` `<` `>` or a newline: exit 2 `unsafe-characters` (in JSON `reasons` or in the text)
  before anything is stored, with or without an operator answer; no printed `rs.py` command line carries the value.
  Test-designer reading: the character rule is checked before the `--file` path is opened (on Windows `" | < >` and
  newline cannot be in an existing file name). Ordinary text (spaces, commas, dots, parentheses, Unicode) passes.
- `--home` is not tested (which commands echo it is open).

### H. Guard tokenizer (N3, N10, N11)

- `rslib.guard_patterns.find` and the hook: every Must BLOCK case matches (no open gate -> deny; one open gate ->
  allow, H10); no Must ALLOW case matches. PowerShell-tool cases: `$null = Clear-Disk ...`, `$r = Format-Volume ...`;
  all others Bash. Lists `test_guard_patterns.H5C_BLOCK_BASH`, `H5C_BLOCK_PS`, `H8B_ALLOW_BASH` are verbatim from the
  amendment; the heredoc and the multi-line `git commit -m` cases are one command string with embedded newlines.
- Rules: per-wrapper value-flag tables compared case-sensitively; `name =` / `$name =` assignment prefixes skipped;
  `command -v|-V` never executes; the whole text is tokenized (newlines separate commands outside quotes) and heredoc
  bodies are dropped; `cp` / `tee` / `pv` judged only by the write target; `&>` and `>&` are redirects; device targets
  include `/dev/disk/by-*`, `/dev/mapper/*`, `/dev/md*`, `/dev/dm-*`, `/dev/loop*`.

### Keys and reason codes added

| command | keys |
|---|---|
| `gate close` | `gate`: + `drift_reason` ("media-id-changed" / "device-changed" / null) |
| `device link` | unchanged keys (`observation_id`, `device_id`, `created`); asks the operator |

Reason codes: `media-id-changed`, `device-changed` (drift_reason values), `hardware-mismatch`, `image-gate-missing`,
`identity-conflict` (collect), `unsafe-characters`; amendment 01 `operator-console-required` / `operator-declined`
now also for `device link`.

## Amendment 03 (2026-10-19): card reader present, medium never detected after isolation

Source: `plans/20261019-1726-recovery-storage-skill/amendment-03-real-run-card-reader.md` (real-device run
2026-10-19: microSD in a USB reader, reader `No Media`, card never detected after reseat / other reader / other host).
Where this section and anything above disagree, this section wins. Lines marked "test-designer reading" fill gaps the
amendment leaves open; they are open questions in the test-designer report and bind the frozen tests until a further
amendment.

### A1. Isolation values

- `session new --tried` values, in this order (exit-2 text lists them in this order; A9 / sec. 2):
  `other-port`, `other-cable`, `other-host`, `other-os`, `reseat-media`, `other-reader`. Repeatable as before.
- Only `session new` accepts `--tried` (unchanged; amendment Q4).

### A2. Reader present, no medium, isolated -> T2a

- `inventory` observation key `no_media` (bool) is part of the contract (test-designer reading: the tests read it as a
  precondition; `true` for the real capture `windows/sd-reader-empty` Disk 3 = `/dev/pd3`, `false` for every other disk
  and for the derived `win-disks.media-online.derived.json`).
- `assess`: symptoms include `not-detected`, the device's LATEST observation has `no_media` true, and at least
  `triage.ISOLATION_MIN` (2) DISTINCT `--tried` values (any of the six) -> `triage.class` `HARDWARE_DIAGNOSIS_REQUIRED`,
  `rule_id` `T2a-not-detected-isolated`, `branch` `a`. Device type is not a condition (test-designer reading: A2 lists
  its conditions; `--device-type` is not among them).
- `triage.evidence` has items with `path` `observation.no_media` (`value` true), `session.symptoms` (value names
  `not-detected`) and `session.tried` (value names every recorded step; list or string).
- `triage.next_test` (case-insensitive) contains `card`, `no software tool` and `lab`, and does not contain
  `insert or reseat` (test-designer reading of "names the medium, says no software tool applies, data needs a lab";
  the T5 instruction is not repeated after the steps were recorded).
- Precedence: T1 (`T1-stop-unsafe`, `STOP_UNSAFE`) before this case; this case before the T5 `no_media` rule.

### A3. Unchanged

- `no_media` + `not-detected` + fewer than 2 distinct steps (none, one, or the same step twice) -> `T5-undetermined`,
  `next_test` contains `reseat` (case-insensitive).
- `no_media` + 2 steps + no detect symptom -> `T5-undetermined`, `next_test` contains `reseat`.
- An earlier `no_media` observation does not count when the latest observation of the device has `no_media` false ->
  not `HARDWARE_DIAGNOSIS_REQUIRED`, not `T2a-not-detected-isolated` (the class is otherwise not asserted).
- Absent-device T2a (C14) unchanged; `rule_id` `T2a-not-detected-isolated`.

### A4. Missing steps listed

- `no_media` + `not-detected` + fewer than 2 distinct steps -> `UNDETERMINED`, and the text of `triage.next_test` joined
  with every `hypotheses[].next_test` contains each of the six codes not recorded, verbatim (as C14 does for the absent
  path).

### Fixture added

- `windows/sd-reader-empty/win-disks.media-online.derived.json`: Disk 3 `OperationalStatus` `No Media` -> `Online`,
  everything else verbatim (fixtures/SOURCES.md), frozen. The real capture `windows/sd-reader-empty` (2026-10-19 live
  smoke) is used as-is; like every real capture it is governed by fixtures/SOURCES.md, not by the manifest.

## Amendment 04 (2026-10-19): verification gates and the PASS evidence window

Source: `plans/20261019-1726-recovery-storage-skill/amendment-04-verification-gate-window.md` (real-device run
2026-10-19: stick, gate `f3write-f3read`, f3read ingested before `gate close --outcome success` -> PASS refused
`evidence-before-recovery`). Where this section and anything above disagree, this section wins (it replaces the
amendment 02 B line "Verdict window start = max(session start, `last_write_ts(device)`)" for the PASS evidence window
only). Lines marked "test-designer reading" bind the frozen tests until a further amendment.

- Verification kinds: `f3write-f3read`, `h2testw`, `f3probe`, `f3probe-destructive`. All other writes-source kinds
  (`format`, `partition-write`, `fs-repair-on-source`, `clear-disk`, `badblocks-write`, `firmware-update`,
  `mptool-reflash`) are ordinary writes.
- PASS evidence window start (test-designer reading of B1-B6 as one formula) = max of: session start; `closed_ts` of
  every closed ordinary write gate; `closed_ts` of every write gate (either group) aborted after confirm; `closed_ts`
  of every verification gate closed `failed` / `interrupted`; `confirmed_ts` of every verification gate closed
  `success`. Across all sessions of the device, as `last_write_ts`. Capacity evidence ingested before it ->
  `evidence-before-recovery` (`verdict set ... PASS` exit 3).
- `last_write_ts(device)` (data state, amendment 02 B) is unchanged: a verification gate closed `success` still writes
  at its `closed_ts`; `secured` / `waived` recorded between its confirm and close are stale.
- Not changed: the observation window (>= 2 observations, one `--after-replug`; open question Q1), the PASS class
  matrix (f3probe is not added as a USB PASS item; Q2), evidence dedup by sha256.
- Tests (D22c, D4c) use attested H2testw as capacity evidence and `/dev/pd2` of `windows/usb-stick` with session
  `--goal device-recovery --preserve-data no --ceiling R2` (D4c: `--goal data-recovery --goal device-recovery
  --ceiling R2` + `waived`); `gate close` may carry `--evidence <id>` of evidence ingested inside the gate.

## Amendment 05 (2026-10-20): report fixes R1-R4

Source: `plans/20261019-1726-recovery-storage-skill/amendment-05-report-fixes.md` (approved by the user 2026-10-20,
"Sửa tiếp 4 lỗi báo cáo"; real reports of sessions S-81ff60a59449 and S-4fdc1ba07b90). Where this section and anything
above disagree, this section wins. Lines marked "test-designer reading" bind the frozen tests until a further
amendment.

### R1. Redaction (E6b)

- `--redact` masks identifier values only (serial, EUI-64, WWN, GUID values, host name, home path / user name); fixed
  report vocabulary is never masked. E6 (real serial masked, last 4 kept) unchanged.
- Test-designer reading: redaction preserves line structure (same number of markdown lines, same number of JSON items,
  observed on the real store). For a report of a device without identifier values (stick, empty reader: serial trust
  absent), every markdown line and every JSON item text that carries no path (`X:\`, `X:/`, `/home/`, `/Users/`,
  `/tmp/`), no `~` and no user name form is identical with and without `--redact`.

### R2. Session notes (E12)

- Every `session note` of the session appears in section 3 of every device of that session's report (test-designer
  reading: notes are session-level; `--device` reports include them), as an item with `tag` `[ATTESTED]` whose text
  contains the note text; the item (any key, or its text) carries the note's `who` and `ts` as `session show` returns
  them (ts shown at least to the second, `T` or space separator). Items in time order. The markdown line holding the
  note text contains `[ATTESTED`, the `who` value and the ts.
- Notes of other sessions never appear. `--redact` applies to note text like any other text (device serial and home
  path masked; ordinary words kept).

### R3. Resolved and stale hypotheses (E13, E13b)

- Effective verdict (`verdict show` of the session/device) PASS or PASS_LIMITED: for every assessment of that
  session/device made before the effective verdict's `ts`, no `next_test` string of it (triage or hypothesis) appears
  in the text of section 4 or 11 items; each of its hypothesis items in section 4 (the item whose text names the
  category) contains `resolved by verdict <STATUS>` (case-insensitive). The latest assessment made after the verdict is
  shown as today (no `resolved by verdict`, its `next_test` present). Other statuses: unchanged (open).
- `assess`: a hypothesis whose every evidence `path` starts with `session.` has `confidence` `low` when
  `last_write_ts(device)` (amendment 02 B) is later than this session's start; otherwise unchanged. The category is
  kept. Report section 4 shows the same confidence. Assessment JSON keeps every `next_test` non-empty (C18, G7).

### R4. Verdict on a card reader (E14, E8b)

- A verdict recorded while the device's latest observation has `no_media` true, or `match` `weak`, is scoped to the
  medium of that session: `verdict show` and the report of that session show it (section 9 item text contains
  `card in the reader` and `not the reader`, case-insensitive, besides the status); `device list` (`verdict` column)
  and `device list --group-by status` never show it as the device's status, in that session or later. Later sessions
  of the same device: `verdict show` effective null, section 9 `UNRESOLVED (no verdict recorded)` until a verdict of
  their own.
- A verdict recorded while the latest observation matches `exact` / `probable` with `no_media` false is the device's
  fleet status as today.
- Fixtures: `windows/sd-reader-empty` (real), `win-disks.media-online.derived.json` (amendment 03), `windows/usb-sd`
  inventoried twice (second observation `weak`).

### R5. Duplicate evidence items (C18b)

- Within one hypothesis, evidence items with the same `path` and the same `value` are one item. `assess --json`: that
  item keeps `path`, `value`, `strength` and gains `count` (int, the number of merged items) when more than one;
  absent or 1 otherwise (test-designer reading of "with a count"). Text forms (`assess` without `--json`, report JSON
  item text, report markdown) show it once as `<path>=<value> (x<count>)`; a single item has no `(x1)`.
- Fixture: `windows/usb-sd/win-events.ntfs55x3.derived.json` (3 x Ntfs 55 on volume `E:`, the card) with
  `windows/usb-sd` `/dev/pd3`: `partition-or-filesystem` evidence `observation.events.fs_corruption` = `Ntfs 55`,
  count 3.
