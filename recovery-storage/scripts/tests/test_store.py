"""Phase 01 - home resolution and store (A1-A4). Spec: phase-01 Requirements + Acceptance A1-A4."""
import hashlib
import sqlite3
import subprocess
import sys

import pytest

from conftest import BASELINE, SCRIPTS, make_runner


def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_A1_session_list_on_empty_home_creates_store_and_says_no_sessions(cli, home):
    """A1. Mutation: skip creating `<home>/sessions/` (or print nothing) -> red."""
    assert not home.exists()
    res = cli("session", "list", json_out=False)
    assert res.code == 0, res
    assert (home / "rs.sqlite").is_file()
    assert (home / "sessions").is_dir()
    assert "no sessions" in res.out.lower()


@pytest.mark.slow
def test_A1_rs_py_entry_point_runs_as_a_script(tmp_path):
    """A1 through the real entry `rs.py` (no device touched). Mutation: rs.py not calling cli.main -> red."""
    h = tmp_path / "h"
    p = subprocess.run([sys.executable, str(SCRIPTS / "rs.py"), "--home", str(h), "session", "list"],
                       capture_output=True, text=True, timeout=120)
    assert p.returncode == 0, p.stderr
    assert "no sessions" in p.stdout.lower()
    assert (h / "rs.sqlite").is_file()
    assert "Traceback" not in p.stderr


def test_A2_home_flag_beats_env(cli, tmp_path, monkeypatch):
    """A2. Mutation: env read before --home -> data lands in <a> -> red."""
    a, b = tmp_path / "a", tmp_path / "b"
    monkeypatch.setenv("RECOVERY_STORAGE_HOME", str(a))
    res = cli("session", "new", "--goal", "diagnosis-only", home=b)
    assert res.code == 0, res
    assert (b / "rs.sqlite").is_file()
    assert not (a / "rs.sqlite").exists()


def test_A2_env_used_when_no_flag(cli, tmp_path, monkeypatch):
    """A2. Mutation: ignore RECOVERY_STORAGE_HOME -> red."""
    a = tmp_path / "a"
    monkeypatch.setenv("RECOVERY_STORAGE_HOME", str(a))
    res = cli("session", "new", "--goal", "diagnosis-only", home=None)
    assert res.code == 0, res
    assert (a / "rs.sqlite").is_file()


def test_A2_default_home_is_dot_recovery_storage_in_user_home(cli, tmp_path, monkeypatch):
    """A2. Mutation: default to CWD or another dir name -> red."""
    user = tmp_path / "user"
    user.mkdir()
    monkeypatch.delenv("RECOVERY_STORAGE_HOME", raising=False)
    monkeypatch.setenv("HOME", str(user))
    monkeypatch.setenv("USERPROFILE", str(user))
    res = cli("session", "new", "--goal", "diagnosis-only", home=None)
    assert res.code == 0, res
    assert (user / ".recovery-storage" / "rs.sqlite").is_file()


def test_A3_unwritable_home_exits_4_and_names_path(cli, tmp_path):
    """A3: home below a regular file cannot be created. Mutation: let OSError escape (traceback) or exit 1 -> red."""
    blocker = tmp_path / "plainfile"
    blocker.write_text("x", encoding="utf-8")
    bad = blocker / "home"
    res = cli("session", "list", home=bad, json_out=False)
    assert res.code == 4, res
    assert str(bad) in res.text or bad.as_posix() in res.text


NEWER_SCHEMA_COMMANDS = [
    ("session", "list"),
    ("session", "new", "--goal", "diagnosis-only"),
    ("session", "show", "S-unknown"),
    ("inventory",),
    ("device", "list"),
    ("gate", "list"),
    ("verdict", "show", "S-unknown", "D-unknown"),
    ("assess", "S-unknown", "D-unknown"),
    ("report", "S-unknown"),
]


@pytest.mark.parametrize("args", NEWER_SCHEMA_COMMANDS, ids=lambda a: "-".join(a[:2]))
def test_A4_newer_schema_every_command_exit_4_db_unchanged(cli, home, args):
    """A4. Mutation: run migrations/writes before checking user_version -> sha256 changes or exit != 4 -> red."""
    from rslib.store import SCHEMA_VERSION

    assert cli("session", "list").code == 0
    db = home / "rs.sqlite"
    con = sqlite3.connect(db)
    con.execute(f"PRAGMA user_version = {int(SCHEMA_VERSION) + 1}")
    con.commit()
    con.close()
    before = _sha(db)
    res = cli(*args, runner=make_runner(BASELINE), json_out=False)
    assert res.code == 4, res
    assert "database schema newer than this tool" in res.text.lower()
    assert _sha(db) == before
