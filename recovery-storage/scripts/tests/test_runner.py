"""Phase 01 - runner (A13 spawn side, A14-A17, A19). Spec: phase-01 Requirements "Runner API" + A13-A19.

Real-process cases use a FAKE tool selected through the documented override env RS_SMARTCTL (absolute
existing path); no real smartctl/PowerShell is ever run.
"""
import os
import pathlib
import sqlite3
import subprocess
import sys

import pytest

from conftest import fx_bytes, recording, sha256_hex
from test_allowlist import FORBIDDEN_IDS, get_case


def _rows(home, where="1=1"):
    con = sqlite3.connect(pathlib.Path(home) / "rs.sqlite")
    con.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in con.execute(f"SELECT * FROM tool_runs WHERE {where}")]
    finally:
        con.close()


def _store(tmp_path):
    from rslib.store import open_store

    return open_store(tmp_path / "home"), tmp_path / "home"


def _no_spawn(monkeypatch):
    import rslib.runner as rr

    spawned = []

    def boom(*a, **k):
        spawned.append(a)
        raise AssertionError("process spawned for a forbidden command")

    monkeypatch.setattr(subprocess, "Popen", boom)
    for name in ("Popen", "run", "call", "check_output"):
        if hasattr(rr, name) and callable(getattr(rr, name)) and getattr(rr, name).__module__ == "subprocess":
            monkeypatch.setattr(rr, name, boom)
    return spawned


@pytest.mark.parametrize("case_id", FORBIDDEN_IDS)
def test_A13_subprocess_runner_refuses_before_spawn_and_records(case_id, tmp_path, monkeypatch):
    """A13. Mutation: validate after Popen, or skip the refusal row -> red."""
    from rslib.runner import CommandNotAllowed, SubprocessRunner

    spawned = _no_spawn(monkeypatch)
    store, home = _store(tmp_path)
    _, tool, args, env = get_case(case_id)
    with pytest.raises(CommandNotAllowed):
        SubprocessRunner(store=store).run(tool, args, env=env)
    assert spawned == []
    store.close()
    rows = _rows(home)
    assert len(rows) == 1, rows
    assert rows[0]["refused"] in (1, True)
    assert rows[0]["exit_code"] is None


def test_A14_tool_missing_is_data_not_exception(tmp_path, monkeypatch):
    """A14. Mutation: let FileNotFoundError escape, or report exit_code 127 -> red."""
    from rslib.runner import SubprocessRunner

    empty = tmp_path / "emptybin"
    empty.mkdir()
    monkeypatch.setenv("PATH", str(empty))
    monkeypatch.delenv("RS_SMARTCTL", raising=False)
    store, home = _store(tmp_path)
    res = SubprocessRunner(store=store).run("smartctl", ["-j", "-x", "/dev/pd99"])
    assert res.tool_missing is True
    assert res.exit_code is None
    assert res.timed_out is False
    store.close()
    rows = _rows(home)
    assert rows and rows[-1]["tool_missing"] in (1, True) and rows[-1]["exit_code"] is None


def test_runner_env_override_must_be_absolute(tmp_path, monkeypatch):
    """Security: RS_<TOOL> relative path rejected (no CWD hijack). Mutation: honour relative path -> red."""
    from rslib.runner import SubprocessRunner

    spawned = _no_spawn(monkeypatch)
    empty = tmp_path / "emptybin"
    empty.mkdir()
    monkeypatch.setenv("PATH", str(empty))
    monkeypatch.setenv("RS_SMARTCTL", "smartctl.exe" if os.name == "nt" else "smartctl")
    store, _ = _store(tmp_path)
    from rslib.runner import CommandNotAllowed

    try:
        res = SubprocessRunner(store=store).run("smartctl", ["-j", "-x", "/dev/pd99"])
    except CommandNotAllowed:
        res = None
    assert spawned == []
    assert res is None or res.tool_missing is True


def _fake_tool(tmp_path):
    """Fake smartctl: /dev/pd7 sleeps 4 s, /dev/pd6 exits 216, otherwise prints JSON + one stderr line."""
    py = sys.executable
    if os.name == "nt":
        p = tmp_path / "fake-smartctl.bat"
        p.write_text("\r\n".join([
            "@echo off",
            'if "%~1"=="-V" (echo smartctl 7.5 fake& exit /b 0)',
            f'if "%~3"=="/dev/pd7" ("{py}" -c "import time; time.sleep(4)" & exit /b 0)',
            'if "%~3"=="/dev/pd6" (echo {"fake": 216}& exit /b 216)',
            'echo {"fake": 0}',
            "echo fake-stderr-line 1>&2",
            "exit /b 0",
        ]) + "\r\n", encoding="ascii")
    else:
        p = tmp_path / "fake-smartctl"
        p.write_text("\n".join([
            "#!/bin/sh",
            'if [ "$1" = "-V" ]; then echo "smartctl 7.5 fake"; exit 0; fi',
            f'if [ "$3" = "/dev/pd7" ]; then exec "{py}" -c "import time; time.sleep(4)"; fi',
            'if [ "$3" = "/dev/pd6" ]; then echo \'{"fake": 216}\'; exit 216; fi',
            'echo \'{"fake": 0}\'',
            "echo fake-stderr-line 1>&2",
            "exit 0",
        ]) + "\n", encoding="ascii")
        p.chmod(0o755)
    return p


@pytest.mark.slow
def test_A15_timeout_kills_and_next_call_works(tmp_path, monkeypatch):
    """A15. Mutation: no timeout (blocks 4 s, timed_out False) or exit_code set after kill -> red."""
    from rslib.runner import SubprocessRunner

    monkeypatch.setenv("RS_SMARTCTL", str(_fake_tool(tmp_path)))
    store, _ = _store(tmp_path)
    r = SubprocessRunner(store=store, timeouts={"smartctl": 1.0})
    res = r.run("smartctl", ["-j", "-x", "/dev/pd7"])
    assert res.timed_out is True
    assert res.exit_code is None
    assert res.duration_s >= 1.0
    nxt = r.run("smartctl", ["-j", "-x", "/dev/pd1"])
    assert nxt.timed_out is False and nxt.exit_code == 0


@pytest.mark.slow
def test_A16_nonzero_exit_returned_as_data(tmp_path, monkeypatch):
    """A16. Mutation: raise CalledProcessError on non-zero exit -> red."""
    from rslib.runner import SubprocessRunner

    monkeypatch.setenv("RS_SMARTCTL", str(_fake_tool(tmp_path)))
    store, _ = _store(tmp_path)
    res = SubprocessRunner(store=store).run("smartctl", ["-j", "-x", "/dev/pd6"])
    assert res.exit_code == 216
    assert res.timed_out is False and res.tool_missing is False


@pytest.mark.slow
def test_A17_real_run_stdout_evidence_sha_matches_row(tmp_path, monkeypatch):
    """A17 (real runner). Mutation: hash stderr, or store stdout in the row only -> red."""
    from rslib.runner import SubprocessRunner

    monkeypatch.setenv("RS_SMARTCTL", str(_fake_tool(tmp_path)))
    store, home = _store(tmp_path)
    res = SubprocessRunner(store=store).run("smartctl", ["-j", "-x", "/dev/pd1"])
    assert res.exit_code == 0
    store.close()
    row = [r for r in _rows(home) if r["exit_code"] == 0][-1]
    p = pathlib.Path(row["stdout_path"])
    p = p if p.is_absolute() else home / p
    data = p.read_bytes()
    assert sha256_hex(data) == row["stdout_sha256"]
    assert b'"fake": 0' in data
    assert "fake-stderr-line" in (row["stderr"] or "")


def test_A17_recorded_run_evidence_and_stderr_truncation(tmp_path):
    """A17 (recorded runner persists the same way). Mutation: store full stderr, or wrong sha -> red."""
    from rslib.runner import STDERR_MAX, RecordedRunner

    store, home = _store(tmp_path)
    long_err = "E" * (int(STDERR_MAX) + 500)
    rr = RecordedRunner([recording("smartctl", ["-j", "-x", "-n", "standby", "/dev/pd1"],
                                   "windows/baseline-nvme-only/smartctl-x-pd1.json", stderr=long_err)], store=store)
    res = rr.run("smartctl", ["-j", "-x", "-n", "standby", "/dev/pd1"])
    assert res.exit_code == 0
    assert res.tool_version == "7.5"
    store.close()
    row = _rows(home)[-1]
    p = pathlib.Path(row["stdout_path"])
    p = p if p.is_absolute() else home / p
    assert sha256_hex(p.read_bytes()) == row["stdout_sha256"] == sha256_hex(
        fx_bytes("windows/baseline-nvme-only/smartctl-x-pd1.json"))
    stored = row["stderr"] or ""
    assert 0 < len(stored) <= int(STDERR_MAX)
    assert long_err.startswith(stored)


def test_A19_recorded_runner_raises_on_unrecorded_argv():
    """A19. Mutation: return an empty RunResult for unknown argv -> red."""
    from rslib.runner import RecordedRunner, UnrecordedCommand

    rr = RecordedRunner([recording("smartctl", ["-j", "-x", "/dev/pd1"], "smartctl/nvme-980pro-x.json")])
    with pytest.raises(UnrecordedCommand):
        rr.run("smartctl", ["-j", "-x", "/dev/pd2"])
    assert rr.unrecorded == [("smartctl", ("-j", "-x", "/dev/pd2"))]
    rr.unrecorded.clear()  # handled here; autouse guard checks the rest


def test_A19_recorded_runner_uses_same_validator():
    """A19. Mutation: RecordedRunner answers a recorded forbidden argv -> red."""
    from rslib.runner import CommandNotAllowed, RecordedRunner

    rr = RecordedRunner([recording("smartctl", ["-t", "short", "/dev/sda"], "smartctl/nvme-990pro-x.json")])
    with pytest.raises(CommandNotAllowed):
        rr.run("smartctl", ["-t", "short", "/dev/sda"])
    assert rr.calls == []


def test_A19_recorded_runner_answers_recording():
    """A19 positive: exact argv -> recorded stdout and exit. Mutation: ignore recorded exit code -> red."""
    from rslib.runner import RecordedRunner

    rec = recording("smartctl", ["-j", "-x", "-n", "standby", "/dev/pd2"], "windows/usb-stick/smartctl-x-pd2.json")
    rr = RecordedRunner([rec])
    res = rr.run("smartctl", ["-j", "-x", "-n", "standby", "/dev/pd2"])
    assert res.exit_code == 1
    assert res.stdout in (fx_bytes("windows/usb-stick/smartctl-x-pd2.json"),
                          fx_bytes("windows/usb-stick/smartctl-x-pd2.json").decode("utf-8"))
    assert rr.calls == [("smartctl", ("-j", "-x", "-n", "standby", "/dev/pd2"))]


def test_A14_A15_recorded_missing_and_timeout_flags():
    """Recorded failure modes (used by B20/G5) surface as RunResult flags. Mutation: drop the flags -> red."""
    from rslib.runner import RecordedRunner, Recording

    rr = RecordedRunner([Recording("smartctl", ["-j", "-x", "/dev/pd1"], tool_missing=True, exit_code=None),
                         Recording("smartctl", ["-j", "-x", "/dev/pd0"], timed_out=True, exit_code=None)])
    a = rr.run("smartctl", ["-j", "-x", "/dev/pd1"])
    b = rr.run("smartctl", ["-j", "-x", "/dev/pd0"])
    assert a.tool_missing is True and a.exit_code is None
    assert b.timed_out is True and b.exit_code is None
