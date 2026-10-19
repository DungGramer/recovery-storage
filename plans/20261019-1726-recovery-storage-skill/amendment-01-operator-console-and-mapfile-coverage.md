# Amendment 01 (2026-10-19): operator console confirmation, full-coverage mapfiles

Approved by the user after code review finding C1 / H7. Changes the frozen spec; tests and CONTRACT.md are
amended by `test-designer`, code by the implementer.

## A. Operator console (finding C1)

Problem: the agent reads the phrase from `gate open` output and could run `gate confirm`, `data-state waived`,
`data-state secured --attested`, `ingest attested` itself. Decision: these require a human at an interactive
console; the agent cannot provide one.

Contract:
- `rslib.cli.main(argv, *, runner=None, clock=None, os_family=None, operator=None)`.
- `operator`: object with `ask(prompt: str) -> str` (one line typed by the human). Default:
  `rslib.operator.ConsoleOperator()`, which requires `sys.stdin.isatty()`; otherwise it raises
  `rslib.operator.NoConsole`. Tests inject `rslib.operator.ScriptedOperator(answers: list[str])` (answers consumed in
  order; running out raises `NoConsole`). `rs.py` never passes an operator (production always uses the console).
- Commands that need the operator (each records `who = operator` in its audit row):
  1. `gate confirm <gate>`: no `--phrase` argument any more. The CLI prints the confirmation summary and asks
     `Type the confirmation phrase: `; the answer is compared with the gate phrase.
  2. `session data-state <s> <d> waived --reason T`, `secured --attested --reason T`, `not-needed`: asks
     `Type YES to record data state <state> for <device> (<model>, <bytes> bytes): `; anything but `YES` -> exit 3
     `operator-declined`.
  3. `ingest attested ...`: asks `Type YES to attest <tool> <result> for <device>: `; same rule.
- No console (`NoConsole`) -> exit 3, reason `operator-console-required`, message contains the exact command line for
  the operator to run in their own terminal: `python <abs path>/rs.py gate confirm <gate>` (resp. data-state / ingest).
  Nothing is changed in the store.
- Wrong phrase -> exit 3 `wrong-phrase`, gate stays pending (as D12). Unchanged elsewhere: `gate open` still shows the
  phrase in its confirmation block (the operator reads it there).
- Audit: `gates` rows store `confirmed_by` (`operator`); `data_states` and `evidence` rows store `who`; the report
  shows `[ATTESTED by operator]` for attested items.
- Known leak (SKILL.md): a script that imports rslib and injects an operator, or a pseudo-terminal wrapper, defeats
  this; it is the same leak class as script files.

Test amendments: every `gate confirm ... --phrase P` becomes `gate confirm G` with a ScriptedOperator answering P
(conftest `confirm()` helper and the Cli driver take `operator=`/`answers=`); every waived / attested / secured
--attested / not-needed call gets a `YES` answer; new cases: no operator (default console, stdin not a TTY) -> exit 3
`operator-console-required` with the command line; operator answers `no` -> exit 3 `operator-declined`, store
unchanged; `--phrase` given -> argparse exit 2.

## B. Full-coverage mapfiles (finding H7)

Decision: a ddrescue mapfile counts as a complete image (data-state secured, SSD/NVMe read verify) only if it covers
the whole device: first block starts at 0, blocks are contiguous (each pos == previous pos + size), the last block
ends exactly at the device byte count, the status line is `+`, and there are no bad / non-tried / non-trimmed /
non-scraped bytes.

Contract:
- `parse_mapfile(text)` result adds `start` (pos of first block), `end` (pos + size of last block), `contiguous` (bool).
  Existing fields unchanged (C20/C21 stay valid).
- `rslib.datastate.mapfile_complete(parsed, device_bytes) -> (bool, reason)`; reasons: `image-incomplete` (unfinished
  or bad), `image-not-contiguous`, `image-does-not-cover-device` (start != 0 or end != device bytes, or device bytes
  unknown).
- `session data-state ... secured --evidence E` refusal reasons: one of the three above (exit 3); the message still
  suggests `waived --reason`.
- Verdict SSD/NVMe read verify: a ddrescue record counts only when `mapfile_complete` is true for the device.

Fixture amendment: derived mapfiles with the verbatim 1.30 structure but sizes scaled so they end exactly at the
device byte count, e.g. `ingest/ddrescue-finished.980pro.derived.map` (2000398934016 bytes) and
`ingest/ddrescue-finished.990pro.derived.map` (1000204886016 bytes), listed in SOURCES.md as derived (structure from
the GNU manual example, sizes computed). The verbatim 1.30 floppy mapfile on an NVMe device -> refused
`image-does-not-cover-device` (new case). A mapfile with a gap -> `image-not-contiguous` (new case).
