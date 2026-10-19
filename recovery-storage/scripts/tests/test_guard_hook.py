"""Phase 08 guard hook (H1-H3, H7, H10-H14, H16 + one real-process run). Spec: phase-08 Requirements 'Hook command',
'guard_hook.py behaviour' 1-9 + H1-H16. Gate states are built with phase 04 commands in a temp home."""
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

from conftest import BASELINE, SCRIPTS, Cli, gate_ok, gate_open_state, nvme1, phrase_980
from test_guard_patterns import ALLOW, AM02_ALLOW, AM02_BLOCK, BLOCK, H4, H8

SENTINEL_BASH = ("Bash", H4[0])
SENTINEL_PS = ("PowerShell", "Clear-Disk -Number 2 -RemoveData")


def payload(tool, cmd):
    return json.dumps({"tool_name": tool, "tool_input": {"command": cmd}})


def hook(stdin_text, home, monkeypatch, capsys):
    import guard_hook

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
