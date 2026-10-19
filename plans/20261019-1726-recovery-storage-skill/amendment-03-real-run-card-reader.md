# Amendment 03 (2026-10-19): real run, card reader with no medium after isolation

Requested by the orchestrating agent after a real-device run on 2026-10-19; approved by the user on
2026-10-19. Spec for `test-designer` (tests first) and the implementer. Changes the
frozen spec; tests and CONTRACT.md are amended by `test-designer`, code by the implementer.

## Origin (real-device run 2026-10-19)

A microSD card in a USB card reader. Windows `Get-Disk` shows the reader "Generic STORAGE DEVICE", Size 0,
OperationalStatus `No Media` (observation fact `no_media` true; real capture `fixtures/windows/sd-reader-empty`).
The operator inserted the card, reseated it, tried another reader / adapter and another computer / phone: the card is
never detected. Session: goal `diagnosis-only`, `--device-type sd`, `--symptom not-detected`, `--tried other-host`.

Output before this amendment: `triage: UNDETERMINED (rule T5-undetermined)`, next test "the reader reports no media:
insert or reseat the card ...", which is wrong once those steps were done.

Causes:
1. Rule `T2a-not-detected-isolated` requires the device to be absent from the inventory. With a card reader the reader
   stays present; only the medium is missing.
2. The isolation facts (`--tried`) have no value for removable-media isolation (reseat, another reader).

## A1. Isolation values

- `--tried` (`session new`) adds two values: `reseat-media` (medium removed and reinserted, adapter lock switch
  checked) and `other-reader` (medium tried in another card reader or adapter).
- Existing values unchanged and keep their order; the new ones are appended:
  `other-port, other-cable, other-host, other-os, reseat-media, other-reader`.

## A2. Triage: reader present, no medium, isolated

When all of:
- the session symptoms include a DETECT symptom (`not-detected`),
- the latest observation of the device has `no_media` true (reader present),
- at least `triage.ISOLATION_MIN` (2) distinct isolation steps are recorded (any of the six values),

the class is `HARDWARE_DIAGNOSIS_REQUIRED`, rule id `T2a-not-detected-isolated`, branch `a`.
- Evidence includes `observation.no_media` = true, `session.symptoms` and `session.tried`.
- `next_test` names the medium (card), not the reader; says no software tool applies and the data needs a lab
  (monolithic card: lab read).
- Precedence: this case wins over the T5 `no_media` rule. `STOP_UNSAFE` (T1) still wins over it.

## A3. Unchanged boundaries

- `no_media` with `not-detected` but fewer than 2 distinct steps -> still `T5-undetermined`, next test insert / reseat.
- `no_media` without a detect symptom -> T5 as today.
- The absent-device T2a path is unchanged.

## A4. Missing steps listed

With fewer than 2 steps and `no_media`, the T5 `next_test` (or a hypothesis `next_test`) lists the missing isolation
steps, the new values included, so the operator knows what to record.

## Open questions (not decided by this amendment; tests skipped or not asserted)

- Q1. Is `disconnects-repeatedly` a DETECT symptom on the `no_media` path? A2 names only `not-detected`; the
  absent-device T2a accepts both.
- Q2. Do `reseat-media` / `other-reader` count as isolation steps on the absent-device T2a path (A3 says unchanged)?
  Its missing-steps list in `next_test` today names only the four old values.
- Q3. With `reseat-media` already recorded (one step), should the T5 `next_test` still say "insert or reseat"?
- Q4. Should `session set` accept `--tried`? Today only `session new` does (the reference says "session new or a new
  session").
- Q5. `next_test` wording by device type (monolithic card vs. full-size SD vs. USB stick) is not specified; the tests
  fix only `card`, `no software tool`, `lab`.
- Q6. `references/phase1-hardware-triage.md` lists four `--tried` values and says "a device still absent" makes it a
  hardware case; it needs the new values and the no-medium case (docs, not frozen).
