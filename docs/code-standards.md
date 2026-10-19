# Code Standards

## Language and dependencies

- Python >= 3.10, standard library only at runtime. No pip dependencies; `pytest` is for the test suite only.
- No network access in the library. Dev tools in `tools/` are run with `python -I`.

## Single subprocess choke point

- `rslib/runner.py` is the only module allowed to import `subprocess` (checked by `test_no_subprocess_outside_runner.py`). `guard_hook.py` spawns nothing; `install_junction.py` spawns nothing (junction via `_winapi`).
- Before spawning, the runner validates argv with `rslib/allowlist.py`. The allow-list is positive: every token must be recognised, anything else raises `CommandNotAllowed` and a refused `tool_runs` row is stored.
  - smartctl: fixed flags, one device matching `/dev/sdX`, `/dev/pdN`, `/dev/nvmeN[nM]` or `/dev/mmcblkN`, whitelisted `-l` logs and `-d` types.
  - powershell: only `-NoProfile -NonInteractive -EncodedCommand <base64 UTF-16LE>` of one of the frozen scripts in `rslib/ps/`, matched by sha256 (`PS_SCRIPT_SHA256`), with `RS_*` parameters validated against `PS_ENV_BOUNDS`. Editing a script requires updating the pinned hash.
  - lsblk, udevadm, blockdev, lsusb, journalctl, dmesg: exact fixed forms.
- Every call is recorded (tool, version, argv, exit code, duration, stderr truncated to `STDERR_MAX`, stdout in a content-addressed file with sha256).
- Tests replay recorded real outputs through `RecordedRunner`, which uses the same validator. Production code has no replay switch.

## Exit codes and errors

| Code | Meaning |
|---|---|
| 0 | ok |
| 2 | usage error |
| 3 | refused by a safety or evidence rule |
| 4 | tool or environment failure (including home not writable, schema newer than this tool) |
| 5 | needs a human decision (ambiguous identity) |

- No tracebacks to the user: handlers raise `UsageError`, `Refused`, `EnvFailure` or `NeedsHuman` from `rslib/errors.py` with machine `reasons`; `cli.main` maps them. Unexpected environment errors become exit 4.
- Missing data is never defaulted to 0 or false; it is reported as missing and leads to `unknown` or a refusal naming every missing item.

## JSON output contract

- Global flags go before the subcommand: `--home PATH`, `--json`, `--who agent|operator`.
- With `--json`, stdout is exactly one JSON object with `ok`, `exit_code`, `reasons` (machine codes), `message`, plus command-specific keys. Nothing else is printed to stdout.
- Reason codes are kebab-case and used verbatim by tests and SKILL.md (for example `data-not-secured`, `image-gate-missing`, `operator-console-required`). Command keys are in `recovery-storage/scripts/tests/CONTRACT.md`.
- Values echoed into a command the operator will paste (`--reason`, `--note`, `--file`, `--home`) must not contain `"`, `$`, backtick, `;`, `&`, `|`, `<`, `>` or a newline: exit 2 `unsafe-characters` before anything is stored.
- Timestamps come from the injected clock, ISO-8601 UTC.

## Rules as code

- Health, triage, verdict and wear rules are pure functions over normalised records, with rule ids and sources. Thresholds are module constants; documents point to `rs.py rules` instead of copying numbers.
- Untrusted input (tool output, mapfiles) is size-limited and parsed line by line; no `eval`.

## Fixtures

- Real tool output only, or a single-field derivation of a real file named `*.derived.*` and listed in `fixtures/SOURCES.md` with the changed field and original value.
- Identifiers (serial, WWN, EUI-64 extension, GUID, hostname) are redacted by `tools/redact_fixtures.py` with consistent same-shape placeholders so joins still hold. Raw captures are git-ignored. Check with `python -I tools/redact_fixtures.py --check`.
- `.gitattributes` marks the PowerShell scripts and fixtures `-text`: their sha256 is pinned, so git must not rewrite line endings.

## Frozen suite and amendment process

- The suite was written spec-first by `test-designer` and frozen; `.claude/frozen-tests.json` records sha256 per frozen file, the criteria-to-test map and the amendment history.
- Do not edit frozen tests to make code pass. A change to behaviour that the contract fixes is an amendment: write an `amendment-NN-*.md` under the plan, have `test-designer` update the tests and `CONTRACT.md` first, re-freeze (the manifest gains an `amendments` entry with files changed and criteria added), then change code.
- Review findings follow the same path: turn the reviewer's reproductions into spec tests before changing code, and re-review only the changed functions.
- A missing module makes a test fail, never skip.

## Windows traps

- PowerShell 5.1 `>` and `Out-File` write UTF-16LE; capture tool output through `subprocess`, never shell redirection.
- Git Bash rewrites `/dev/sda` to a Windows path unless `MSYS_NO_PATHCONV=1`; argv lists passed from Python are unaffected.
- `rslib/operator.py` shadows the stdlib `operator` module if `rslib/` itself is on `sys.path` (CWD without `-I`). Run Python with `-I` when the CWD is `rslib/`, and never put an entry script in `rslib/`. The name is fixed by amendment 01.
- `isatty()` is true for the NUL device on Windows; a real console is confirmed with `GetConsoleMode`.
- Text with backslashes (Python source, regexes) is written with file tools, never through a Bash heredoc.
- Python < 3.12 has no `os.path.isjunction`; `install_junction.py` falls back to the reparse-point attribute.

## Comment style

Caveman style: short, mechanism and pointer first, numbers and dates kept, no narrative. Replace a comment when the code changes; do not append.

## Documentation rules

Docs describe the current code only. No hand-written counts of tests, files or lines; no history inside docs (history goes to `project-changelog.md`). Every named file, command and reason code must exist.
