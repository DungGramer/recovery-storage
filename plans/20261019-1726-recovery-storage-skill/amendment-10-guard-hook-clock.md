# Amendment 10 (2026-10-21): guard hook clock is injectable; the 12 h open-gate limit is specified

Approved by the user on 2026-10-21 ("có cả 2", answering "sửa lỗi hẹn giờ qua amendment 10"). Spec for
`test-designer` (tests first) and the implementer.

## Problem

Since 2026-10-20 12:00Z six frozen tests fail on an unchanged tree (checked 2026-10-21 on 706a5db and 225eff7):
`test_guard_hook.py` H10, H10b, H13 (x2), H14 (x2). Each builds an `open` gate through the CLI, whose `FakeClock`
(`tests/conftest.py`) starts at 2026-10-20T00:00:00Z. `guard_hook._gates` compares the gate time with the wall clock
(`dt.datetime.now`) and treats a gate open for more than `OPEN_GATE_MAX_HOURS` = 12 as stale, so 12 h after that
fixed date every test-built open gate stops unlocking. The suite went red by date alone.

The 12 h limit itself exists only in code and SKILL.md ("an open gate older than 12 h no longer unlocks"); no spec
or test covers it.

## G1. One clock

`guard_hook.py` reads the current UTC time only through a module-level function `_now()` returning an aware UTC
`datetime`. The stale check and the `guard.log` timestamp both use it. Default: the wall clock. Tests replace it
(monkeypatch `guard_hook._now`); no frozen test outcome may depend on the wall clock.

## G2. Stale open gate (specifies current behaviour)

The gate time is `confirmed_ts`, or `ts` when `confirmed_ts` is null. An `open` gate whose gate time is more than
12 h before `_now()` does not unlock a matched command. Exactly 12 h still unlocks (strictly greater is stale). The
deny message names that gate and says it has been open for more than 12 h, and still prints the next-step hint. A
stale gate does not stop another, non-stale open gate from unlocking. An unparseable or timezone-less gate time is
not stale (today's behaviour).

## G3. Existing tests

H10, H10b, H13, H14 keep their assertions; only the time they run at is pinned inside the 12 h window of the
`FakeClock` era. `FakeClock` is not changed.

## G4. Sweep

Check the rest of the frozen suite for any other outcome that compares `FakeClock` data with the wall clock (the
production code reads the wall clock in `guard_hook.py`, `rslib/store.py:_utcnow` and `rslib/cli.py`); report what
you find.
