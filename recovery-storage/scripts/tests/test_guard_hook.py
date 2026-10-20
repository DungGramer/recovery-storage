"""Phase 08 guard hook (H1-H3, H7, H10-H14, H16 + one real-process run). Spec: phase-08 Requirements 'Hook command',
'guard_hook.py behaviour' 1-9 + H1-H16. Gate states are built with phase 04 commands in a temp home.
Amendment 10: hook clock = `guard_hook._now()`; `hook()` pins it inside the FakeClock era (G3); H19 one clock (G1),
H20 stale open gate after 12 h (G2)."""
import datetime as dt
import hashlib
import io
import json
import os
import pathlib
import re
import shutil
import sqlite3
import subprocess
import sys

import pytest

from conftest import BASELINE, SCRIPTS, UTC, Cli, FakeClock, gate_ok, gate_open_state, nvme1, phrase_980
from test_guard_patterns import ALLOW, AM02_ALLOW, AM02_BLOCK, BLOCK, H4, H8

SENTINEL_BASH = ("Bash", H4[0])
SENTINEL_PS = ("PowerShell", "Clear-Disk -Number 2 -RemoveData")

# Amendment 10 G3: FakeClock start + 1 h; CLI-built gates sit minutes after the start -> inside the 12 h window.
ERA = FakeClock().now + dt.timedelta(hours=1)
_ERA = object()


def payload(tool, cmd):
    return json.dumps({"tool_name": tool, "tool_input": {"command": cmd}})


def hook(stdin_text, home, monkeypatch, capsys, now=_ERA):
    """now: default -> pin `guard_hook._now` to ERA (raising=False: tests without a gate still run before `_now`
    exists; H19 requires it); datetime -> pin to it (attribute must exist); None -> leave the clock alone."""
    import guard_hook

    if now is _ERA:
        monkeypatch.setattr(guard_hook, "_now", lambda: ERA, raising=False)
    elif now is not None:
        monkeypatch.setattr(guard_hook, "_now", lambda: now)
    if home is None:
        monkeypatch.delenv("RECOVERY_STORAGE_HOME", raising=False)
    else:
        monkeypatch.setenv("RECOVERY_STORAGE_HOME", str(home))
    monkeypatch.setattr(sys, "stdin", io.StringIO(stdin_text))
    capsys.readouterr()
    try:
        code = guard_hook.main()
    except SystemExit as e:
        code = e.code if isinstance(e.code, int) else 1
    cap = capsys.readouterr()
    return code, cap.out, cap.err


def store_with(tmp_path, final_state):
    """Home with one gate in `final_state` (pending|open|closed|aborted), built through the CLI."""
    home = tmp_path / f"home-{final_state}"
    cli = Cli(home)
    sid, dev = nvme1(cli, "--goal", "diagnosis-only", "--ceiling", "R1")
    if final_state == "pending":
        g, _ = gate_ok(cli, BASELINE, sid, dev, "smart-selftest-short")
    else:
        g = gate_open_state(cli, BASELINE, sid, dev, "smart-selftest-short", phrase_980())
        if final_state == "closed":
            assert cli("gate", "close", g, "--outcome", "success", runner=cli.runner(BASELINE)).code == 0
        elif final_state == "aborted":
            assert cli("gate", "abort", g, "--reason", "test").code == 0
    con = sqlite3.connect(home / "rs.sqlite")
    try:
        states = [r[0] for r in con.execute("SELECT state FROM gates")]
    finally:
        con.close()
    assert states == [final_state]
    return home, g


# ---------------- H1-H3
def test_H1_unparseable_input_exit_1(tmp_path, monkeypatch, capsys):
    """H1. Mutation: exit 2 on bad input (blocks every call) -> red."""
    code, _, err = hook("not json", tmp_path, monkeypatch, capsys)
    assert code == 1
    assert "unreadable hook input" in err


def test_H2_other_tools_pass_silently(tmp_path, monkeypatch, capsys):
    """H2. Mutation: inspect Read tool input -> red."""
    code, out, _ = hook('{"tool_name":"Read","tool_input":{"file_path":"x"}}', tmp_path, monkeypatch, capsys)
    assert code == 0 and out == ""


def test_H3_non_matching_command_never_opens_store(tmp_path, monkeypatch, capsys):
    """H3. Mutation: open the DB before matching (corrupt DB -> error) -> red."""
    home = tmp_path / "corrupt"
    home.mkdir()
    (home / "rs.sqlite").write_bytes(b"this is not a sqlite database at all" * 10)
    code, out, _ = hook(payload("Bash", "ls -la"), home, monkeypatch, capsys)
    assert code == 0 and out == ""
    assert not (home / "guard.log").exists()


# ---------------- H7 / H12 fresh home
@pytest.mark.parametrize("tool,cmd", BLOCK, ids=[c for _, c in BLOCK])
def test_H7_blocked_without_gate_message(tool, cmd, tmp_path, monkeypatch, capsys):
    """H7 (+ H12 fresh home). Mutation: deny without rule id / next-step hint, or exit 1 -> red."""
    from rslib.guard_patterns import find

    rule = find(cmd).rule_id
    code, out, err = hook(payload(tool, cmd), tmp_path / "fresh", monkeypatch, capsys)
    assert code == 2
    assert rule in err
    assert "no gate is open" in err
    assert "rs.py gate open" in err


@pytest.mark.parametrize("tool,cmd", ALLOW, ids=[c for _, c in ALLOW])
def test_H8_H9_allowed_without_gate(tool, cmd, tmp_path, monkeypatch, capsys):
    """H8/H9 through the hook. Mutation: hook blocks a read-only command -> red."""
    code, out, _ = hook(payload(tool, cmd), tmp_path / "fresh", monkeypatch, capsys)
    assert code == 0 and out == ""


@pytest.mark.parametrize("tool,cmd", AM02_BLOCK, ids=[c for _, c in AM02_BLOCK])
def test_H7b_amendment02_blocked_through_hook(tool, cmd, tmp_path, monkeypatch, capsys):
    """Amendment 02 H Must BLOCK, end to end through guard_hook.main (no gate): exit 2 with rule id and next step.
    Mutation: the hook tokenizes differently from guard_patterns (e.g. strips `$x =` only in find()) -> red."""
    code, out, err = hook(payload(tool, cmd), tmp_path / "fresh", monkeypatch, capsys)
    assert code == 2, (cmd, err)
    assert "no gate is open" in err
    assert "rs.py gate open" in err


@pytest.mark.parametrize("tool,cmd", AM02_ALLOW, ids=[c for _, c in AM02_ALLOW])
def test_H8c_amendment02_allowed_through_hook(tool, cmd, tmp_path, monkeypatch, capsys):
    """Amendment 02 H Must ALLOW through the hook (multi-line command text arrives as one tool_input.command).
    Mutation: the hook splits the payload on newlines before tokenizing (heredoc body becomes a command) -> red."""
    code, out, _ = hook(payload(tool, cmd), tmp_path / "fresh", monkeypatch, capsys)
    assert (code, out) == (0, ""), cmd


def test_H10b_amendment02_open_gate_unlocks_new_block_list(tmp_path, monkeypatch, capsys):
    """H10 for the amendment 02 corpus: with one open gate every newly matched command passes. Mutation: the new
    matches bypass the gate lookup (always deny) -> red."""
    home, _ = store_with(tmp_path, "open")
    for tool, cmd in AM02_BLOCK:
        code, out, _ = hook(payload(tool, cmd), home, monkeypatch, capsys)
        assert (code, out) == (0, ""), cmd


# ---------------- H10 / H11
def test_H10_one_open_gate_unlocks_matched_commands(tmp_path, monkeypatch, capsys):
    """H10. Mutation: require the gate's device to match the command path -> red (documented leak, by design)."""
    home, _ = store_with(tmp_path, "open")
    for tool, cmd in BLOCK:
        code, out, _ = hook(payload(tool, cmd), home, monkeypatch, capsys)
        assert (code, out) == (0, ""), cmd


def test_H11_pending_gate_still_blocks_and_names_it(tmp_path, monkeypatch, capsys):
    """H11. Mutation: count pending as open -> red."""
    home, g = store_with(tmp_path, "pending")
    code, _, err = hook(payload(*SENTINEL_BASH), home, monkeypatch, capsys)
    assert code == 2
    assert str(g) in err and "gate confirm" in err


@pytest.mark.parametrize("state", ["closed", "aborted"])
def test_H11_closed_or_aborted_gates_block(state, tmp_path, monkeypatch, capsys):
    """H11. Mutation: any gate row unlocks -> red."""
    home, _ = store_with(tmp_path, state)
    for tool, cmd in (SENTINEL_BASH, SENTINEL_PS):
        code, _, err = hook(payload(tool, cmd), home, monkeypatch, capsys)
        assert code == 2 and "no gate is open" in err


# ---------------- H12 store states
def _corrupt(home):
    home.mkdir(parents=True)
    (home / "rs.sqlite").write_bytes(b"garbage" * 100)


def _newer(home):
    from rslib.store import SCHEMA_VERSION

    assert Cli(home)("session", "list").code == 0
    con = sqlite3.connect(home / "rs.sqlite")
    con.execute(f"PRAGMA user_version = {int(SCHEMA_VERSION) + 1}")
    con.commit()
    con.close()


@pytest.mark.parametrize("make", [_corrupt, _newer], ids=["corrupt", "newer-schema"])
def test_H12_unreadable_store_fails_closed_for_matched(make, tmp_path, monkeypatch, capsys):
    """H12. Mutation: unreadable store treated as 'no gate' message or as allow -> red."""
    home = tmp_path / "h"
    make(home)
    code, _, err = hook(payload(*SENTINEL_BASH), home, monkeypatch, capsys)
    assert code == 2 and "cannot read gate store" in err
    code, out, _ = hook(payload("Bash", H8[0]), home, monkeypatch, capsys)
    assert (code, out) == (0, "")


@pytest.mark.slow
def test_H12_locked_store_fails_closed_for_matched(tmp_path, monkeypatch, capsys):
    """H12 'DB locked past the timeout'. Mutation: wait forever or allow on lock -> red."""
    home, _ = store_with(tmp_path, "open")
    con = sqlite3.connect(home / "rs.sqlite", isolation_level=None)
    con.execute("PRAGMA locking_mode=EXCLUSIVE")
    con.execute("BEGIN EXCLUSIVE")
    con.execute("UPDATE gates SET state = state")
    try:
        code, _, err = hook(payload(*SENTINEL_BASH), home, monkeypatch, capsys)
        assert code == 2 and "cannot read gate store" in err
        code, out, _ = hook(payload("Bash", H8[0]), home, monkeypatch, capsys)
        assert (code, out) == (0, "")
    finally:
        con.execute("ROLLBACK")
        con.close()


# ---------------- H13
def test_H13_env_home_is_read(tmp_path, monkeypatch, capsys):
    """H13. Mutation: hook always reads ~/.recovery-storage -> red."""
    home, _ = store_with(tmp_path, "open")
    user = tmp_path / "user"
    user.mkdir()
    monkeypatch.setenv("HOME", str(user))
    monkeypatch.setenv("USERPROFILE", str(user))
    code, _, _ = hook(payload(*SENTINEL_BASH), home, monkeypatch, capsys)
    assert code == 0


def test_H13_default_home_when_env_unset(tmp_path, monkeypatch, capsys):
    """H13. Mutation: unset env -> CWD or no store -> red."""
    user = tmp_path / "user"
    user.mkdir()
    home, _ = store_with(tmp_path, "open")
    shutil.move(str(home), str(user / ".recovery-storage"))
    monkeypatch.setenv("HOME", str(user))
    monkeypatch.setenv("USERPROFILE", str(user))
    code, _, _ = hook(payload(*SENTINEL_BASH), None, monkeypatch, capsys)
    assert code == 0


# ---------------- H14
def test_H14_audit_line_has_rule_decision_gate_hash_not_text(tmp_path, monkeypatch, capsys):
    """H14. Mutation: log the command text (leaks paths) or skip the hash -> red."""
    from rslib.guard_patterns import find

    home, g = store_with(tmp_path, "open")
    cmd = SENTINEL_BASH[1]
    assert hook(payload(*SENTINEL_BASH), home, monkeypatch, capsys)[0] == 0
    fresh = tmp_path / "fresh-log"
    fresh.mkdir()
    assert hook(payload(*SENTINEL_BASH), fresh, monkeypatch, capsys)[0] == 2
    hook(payload("Bash", H8[0]), home, monkeypatch, capsys)  # non-matching: no line
    for h, gate in ((home, str(g)), (fresh, None)):
        lines = (h / "guard.log").read_text(encoding="utf-8").splitlines()
        assert len(lines) == 1, lines
        ln = lines[0]
        assert find(cmd).rule_id in ln
        assert re.search(r"\b(deny|allow)\b", ln)
        assert hashlib.sha256(cmd.encode("utf-8")).hexdigest() in ln
        assert cmd not in ln and "/dev/sdb1" not in ln
        if gate:
            assert gate in ln


def test_H14_logging_failure_keeps_decision(tmp_path, monkeypatch, capsys):
    """H14 'read-only home still yields the correct exit code' (guard.log made unwritable as a directory).
    Mutation: log error turns into exit 1 / allow -> red."""
    home = tmp_path / "ro"
    (home / "guard.log").mkdir(parents=True)
    code, _, err = hook(payload(*SENTINEL_BASH), home, monkeypatch, capsys)
    assert code == 2 and "no gate is open" in err
    home2, _ = store_with(tmp_path, "open")
    (home2 / "guard.log").mkdir()
    assert hook(payload(*SENTINEL_BASH), home2, monkeypatch, capsys)[0] == 0


# ---------------- amendment 10: H19 one clock (G1), H20 stale open gate (G2)
H = dt.timedelta(hours=1)
S = dt.timedelta(seconds=1)
FAR = dt.datetime(2036, 1, 1, tzinfo=UTC)


def store_ts(text):
    """Store timestamp `YYYY-MM-DDTHH:MM:SS.ffffffZ` (amendment 08 H1) -> aware UTC. strptime: 3.10 has no 'Z' isoformat."""
    return dt.datetime.strptime(text, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=UTC)


def ts_text(when):
    return when.strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def gate_row(home, g):
    con = sqlite3.connect(home / "rs.sqlite")
    con.row_factory = sqlite3.Row
    try:
        return dict(con.execute("SELECT * FROM gates WHERE id = ?", (g,)).fetchone())
    finally:
        con.close()


def set_gate(home, g, **cols):
    """Edit a CLI-built gate row (commit + close before the hook opens the store read-only)."""
    con = sqlite3.connect(home / "rs.sqlite")
    try:
        for col, val in cols.items():
            con.execute(f"UPDATE gates SET {col} = ? WHERE id = ?", (val, g))
        con.commit()
    finally:
        con.close()


def assert_stale_deny(res, g):
    """G2 deny: names the gate, 'more than 12 h', next-step hint (phase 08 item 6: rule id + `rs.py gate open`)."""
    from rslib.guard_patterns import find

    code, out, err = res
    assert code == 2, err
    assert str(g) in err, err
    assert "more than 12 h" in err, err
    assert "rs.py gate open" in err, err
    assert find(SENTINEL_BASH[1]).rule_id in err, err


def test_H19_now_default_is_the_aware_utc_wall_clock():
    """G1 'module-level function `_now()` returning an aware UTC datetime. Default: the wall clock.'
    Mutation: no `_now` (today) -> red; naive or local-time default -> red; a fixed default time -> red."""
    import guard_hook

    got = guard_hook._now()
    assert isinstance(got, dt.datetime) and got.tzinfo is not None, got
    assert got.utcoffset() == dt.timedelta(0), got
    assert abs(got - dt.datetime.now(UTC)) < dt.timedelta(minutes=5), got


def test_H19_stale_check_reads_now(tmp_path, monkeypatch, capsys):
    """G1 'the stale check uses `_now()`'. Fresh CLI-built open gate: `_now` far in the future -> stale (deny); `_now`
    one hour after the gate time -> unlocks. Mutation: stale check reads `dt.datetime.now` -> the near half red (the
    far half is green on today's code by accident: the wall clock is past the FakeClock era)."""
    home, g = store_with(tmp_path, "open")
    assert_stale_deny(hook(payload(*SENTINEL_BASH), home, monkeypatch, capsys, now=FAR), g)
    near = store_ts(gate_row(home, g)["confirmed_ts"]) + H
    assert hook(payload(*SENTINEL_BASH), home, monkeypatch, capsys, now=near)[:2] == (0, "")


def test_H19_guard_log_time_is_now(tmp_path, monkeypatch, capsys):
    """G1 'the guard.log timestamp uses `_now()`'; phase 08 item 9 'UTC time'. Allow (open gate) and deny (fresh home)
    lines carry the pinned time, `YYYY-MM-DDTHH:MM:SS` (suffix `Z` / `+00:00` not decided). Mutation: log line stamped
    with `dt.datetime.now` -> red; local time -> red."""
    home, g = store_with(tmp_path, "open")
    t_allow = (store_ts(gate_row(home, g)["confirmed_ts"]) + H).replace(microsecond=0)
    assert hook(payload(*SENTINEL_BASH), home, monkeypatch, capsys, now=t_allow)[0] == 0
    fresh = tmp_path / "fresh-log"
    fresh.mkdir()
    t_deny = dt.datetime(2026, 10, 20, 5, 6, 7, tzinfo=UTC)
    assert hook(payload(*SENTINEL_BASH), fresh, monkeypatch, capsys, now=t_deny)[0] == 2
    for h, t in ((home, t_allow), (fresh, t_deny)):
        lines = (h / "guard.log").read_text(encoding="utf-8").splitlines()
        assert len(lines) == 1, lines
        assert t.strftime("%Y-%m-%dT%H:%M:%S") in lines[0], (t, lines[0])


def test_H20_exactly_12h_unlocks_one_second_more_is_stale(tmp_path, monkeypatch, capsys):
    """G2 'more than 12 h before `_now()` does not unlock ... Exactly 12 h still unlocks (strictly greater is stale)';
    gate time = confirmed_ts (here 11 s after ts). Deny message: gate id, 'more than 12 h', next-step hint.
    Mutation: `>=` -> first half red; gate time = ts -> first half red (ts is 12 h 11 s old); limit 13 h / no limit ->
    second half red; deny without gate id / hint -> red."""
    home, g = store_with(tmp_path, "open")
    row = gate_row(home, g)
    t = store_ts(row["confirmed_ts"])
    assert store_ts(row["ts"]) < t, row
    assert hook(payload(*SENTINEL_BASH), home, monkeypatch, capsys, now=t + 12 * H)[:2] == (0, "")
    assert_stale_deny(hook(payload(*SENTINEL_BASH), home, monkeypatch, capsys, now=t + 12 * H + S), g)


def test_H20_gate_time_is_the_confirm_time_not_the_open_time(tmp_path, monkeypatch, capsys):
    """G2 'gate time is `confirmed_ts`'. Gate opened, confirmed 13 h later (phase 04: no automatic expiry); `_now` =
    confirm + 1 h -> unlocks; confirm + 12 h + 1 s -> stale. Mutation: gate time = ts (open time) or min(ts,
    confirmed_ts) -> first half red."""
    home = tmp_path / "home-late-confirm"
    cli = Cli(home)
    sid, dev = nvme1(cli, "--goal", "diagnosis-only", "--ceiling", "R1")
    g, _ = gate_ok(cli, BASELINE, sid, dev, "smart-selftest-short")
    cli.clock.advance(hours=13)
    from conftest import confirm

    res = confirm(cli, BASELINE, g, phrase_980())
    assert res.code == 0 and res.data["gate"]["state"] == "open", res
    row = gate_row(home, g)
    t = store_ts(row["confirmed_ts"])
    assert t - store_ts(row["ts"]) > 13 * H, row
    assert hook(payload(*SENTINEL_BASH), home, monkeypatch, capsys, now=t + H)[:2] == (0, "")
    assert_stale_deny(hook(payload(*SENTINEL_BASH), home, monkeypatch, capsys, now=t + 12 * H + S), g)


def test_H20_null_confirmed_ts_uses_ts(tmp_path, monkeypatch, capsys):
    """G2 'or `ts` when `confirmed_ts` is null' (row edited via sqlite: the CLI never leaves an open gate unconfirmed).
    ts + 12 h -> unlocks; ts + 12 h + 1 s -> stale. Mutation: null confirmed_ts treated as not stale -> second half
    red; as stale / skipped -> first half red."""
    home, g = store_with(tmp_path, "open")
    set_gate(home, g, confirmed_ts=None)
    t = store_ts(gate_row(home, g)["ts"])
    assert hook(payload(*SENTINEL_BASH), home, monkeypatch, capsys, now=t + 12 * H)[:2] == (0, "")
    assert_stale_deny(hook(payload(*SENTINEL_BASH), home, monkeypatch, capsys, now=t + 12 * H + S), g)


@pytest.mark.parametrize("stale_row,fresh_ts_first", [("cli", False), ("copy", False), ("cli", True), ("copy", True)],
                         ids=["stale-cli-row", "stale-copy-row", "stale-cli-row-fresh-ts-older",
                              "stale-copy-row-fresh-ts-older"])
def test_H20_stale_gate_does_not_stop_a_fresh_open_gate(stale_row, fresh_ts_first, tmp_path, monkeypatch, capsys):
    """G2 'A stale gate does not stop another, non-stale open gate from unlocking'. Second open gate = sqlite copy of
    the CLI-built row on the BASELINE 990 PRO (/dev/pd0: `gate open` refuses it, boot-or-system-disk). Stale gate time
    14 h old, fresh 1 h; row order varied by rowid (which row is stale) and by ts (fresh gate opened before the stale
    one, confirmed later). Mutation: any stale open gate denies -> red; only the first / last row (rowid or ts order)
    decides -> one id red."""
    home = tmp_path / "home-two"
    cli = Cli(home)
    sid, dev = nvme1(cli, "--goal", "diagnosis-only", "--ceiling", "R1")
    g = gate_open_state(cli, BASELINE, sid, dev, "smart-selftest-short", phrase_980())
    from conftest import device_at

    dev0 = device_at(cli, BASELINE, sid, "/dev/pd0")
    assert dev0 != dev
    base = store_ts(gate_row(home, g)["confirmed_ts"])
    con = sqlite3.connect(home / "rs.sqlite")
    try:
        cols = [r[1] for r in con.execute("PRAGMA table_info(gates)")]
        row = dict(zip(cols, con.execute("SELECT * FROM gates WHERE id = ?", (g,)).fetchone()))
        row.update(id="G-amendment10b", device_id=dev0)
        con.execute(f"INSERT INTO gates ({', '.join(row)}) VALUES ({', '.join('?' * len(row))})", list(row.values()))
        con.commit()
        states = [r[0] for r in con.execute("SELECT state FROM gates ORDER BY rowid")]
    finally:
        con.close()
    assert states == ["open", "open"]
    old, new = (g, "G-amendment10b") if stale_row == "cli" else ("G-amendment10b", g)
    set_gate(home, old, ts=ts_text(base), confirmed_ts=ts_text(base))
    set_gate(home, new, ts=ts_text(base - H if fresh_ts_first else base + 13 * H), confirmed_ts=ts_text(base + 13 * H))
    assert hook(payload(*SENTINEL_BASH), home, monkeypatch, capsys, now=base + 14 * H)[:2] == (0, "")


@pytest.mark.parametrize("col,kind", [("confirmed_ts", "garbage"), ("confirmed_ts", "naive"),
                                      ("ts", "garbage"), ("ts", "naive")])
def test_H20_unparseable_or_naive_gate_time_is_not_stale(col, kind, tmp_path, monkeypatch, capsys):
    """G2 'An unparseable or timezone-less gate time is not stale'. The gate-time column (confirmed_ts; ts with
    confirmed_ts null) gets text that is not a time, or the store format without `Z`; `_now` far in the future ->
    unlocks. Test-designer reading: a non-null unparseable confirmed_ts is the gate time (no fall back to the old ts).
    Mutation: unparseable -> stale -> red; naive read as UTC -> red; parse error -> exit 1 / deny -> red."""
    home, g = store_with(tmp_path, "open")
    row = gate_row(home, g)
    bad = "not-a-time" if kind == "garbage" else row[col][:-1]
    if col == "ts":
        set_gate(home, g, confirmed_ts=None, ts=bad)
    else:
        set_gate(home, g, confirmed_ts=bad)
    assert hook(payload(*SENTINEL_BASH), home, monkeypatch, capsys, now=FAR)[:2] == (0, "")


# ---------------- real process + H16
@pytest.mark.slow
def test_hook_real_process_run(tmp_path):
    """Phase 08 Related Code Files 'one real-process run of the script'. Mutation: import-time failure -> red."""
    env = dict(os.environ, RECOVERY_STORAGE_HOME=str(tmp_path / "fresh"))
    run = lambda tool, cmd: subprocess.run([sys.executable, str(SCRIPTS / "guard_hook.py")], input=payload(tool, cmd),
                                           capture_output=True, text=True, env=env, timeout=60)
    p = run(*SENTINEL_BASH)
    assert p.returncode == 2 and "no gate is open" in p.stderr
    p2 = run("Bash", H8[0])
    assert p2.returncode == 0 and p2.stdout == ""


def git_bash():
    if os.name != "nt":
        return shutil.which("bash")
    git = shutil.which("git")
    if git:
        for cand in (pathlib.Path(git).parents[1] / "bin" / "bash.exe", pathlib.Path(git).parents[1] / "usr" / "bin" / "bash.exe"):
            if cand.is_file():
                return str(cand)
    return None


@pytest.mark.slow
def test_H16_frontmatter_command_with_missing_script_exit_1(tmp_path):
    """H16. Mutation: bare `python <path>` (python exits 2 = deny everything when the file is missing) -> red."""
    from test_skill_docs import frontmatter

    fm, _ = frontmatter()
    cmd = fm["hooks"]["PreToolUse"][0]["hooks"][0]["command"]
    bash = git_bash()
    assert bash, "Git Bash (or POSIX bash) required for H16"
    fake = tmp_path / "home"
    fake.mkdir()
    env = dict(os.environ, HOME=str(fake), USERPROFILE=str(fake), CLAUDE_SKILL_DIR=str(fake / "no-skill"))
    p = subprocess.run([bash, "-c", cmd], input=payload(*SENTINEL_BASH), capture_output=True, text=True, env=env,
                       timeout=60)
    assert p.returncode == 1, (p.returncode, p.stderr)
    assert "guard inactive" in p.stderr
