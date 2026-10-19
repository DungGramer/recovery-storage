"""Phase 07 tool-failure matrix (G5). Spec: phase-07 Requirements 'Tool failure matrix for smartctl, PowerShell, lsblk:
missing, timeout, non-zero exit, malformed JSON, empty stdout -> collection status recorded, no traceback, exit 4 where
the command's purpose failed, assessment unknown/UNDETERMINED' + G5. Failure stdout is synthetic (not device output)."""
import sqlite3

import pytest

from conftest import BASELINE, assess, device_at, make_runner, new_session, recording

MODES = {
    "missing": dict(tool_missing=True, exit_code=None, stdout=b""),
    "timeout": dict(timed_out=True, exit_code=None, stdout=b""),
    "malformed": dict(exit_code=0, stdout=b"{ not json"),
    "empty": dict(exit_code=0, stdout=b""),
}
SMART_STATUS = {"missing": "tool_missing", "timeout": "timeout", "nonzero": "collection_failed",
                "malformed": "malformed", "empty": "malformed"}


def rows(home, tool):
    con = sqlite3.connect(home / "rs.sqlite")
    con.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in con.execute("SELECT * FROM tool_runs WHERE tool = ?", (tool,))]
    finally:
        con.close()


@pytest.mark.parametrize("mode", ["missing", "timeout", "nonzero", "malformed", "empty"])
def test_G5_smartctl_collect_failure_cells(cli, home, mode):
    """G5 smartctl row. Mutation: malformed JSON raises / stored as ok / exit 0 -> red."""
    sid = new_session(cli)
    dev = device_at(cli, BASELINE, sid, "/dev/pd1")
    key = ("smartctl", ("-j", "-x", "-n", "standby", "/dev/pd1"))
    src = "smartctl/missing-device.json" if mode == "nonzero" else dict(MODES[mode])
    before = len(rows(home, "smartctl"))
    res = cli("collect", dev, "--session", sid, runner=make_runner(BASELINE, replace={key: src}))
    assert res.code == 4, res
    assert res.data["snapshot"]["collection_status"] == SMART_STATUS[mode]
    assert len(rows(home, "smartctl")) > before
    a = assess(cli, sid, dev)
    assert a["health"]["verdict"] == "unknown"
    assert a["triage"]["class"] == "UNDETERMINED"


@pytest.mark.parametrize("mode", ["missing", "timeout", "nonzero", "malformed", "empty"])
def test_G5_powershell_inventory_failure_cells(cli, home, mode):
    """G5 PowerShell row (win-disks). Mutation: empty disk list reported as success -> red."""
    kw = dict(MODES[mode]) if mode != "nonzero" else dict(exit_code=1, stdout=b"")
    r = make_runner(BASELINE, {"win-disks": kw})
    sid = new_session(cli)
    res = cli("inventory", "--session", sid, runner=r)
    assert res.code == 4, res
    assert res.reasons
    got = rows(home, "powershell")
    assert got
    if mode == "missing":
        assert any(x["tool_missing"] for x in got)
    if mode == "timeout":
        assert any(x["timed_out"] for x in got)


@pytest.mark.parametrize("mode", ["missing", "timeout", "nonzero", "malformed", "empty"])
def test_G5_lsblk_inventory_failure_cells(cli, home, mode):
    """G5 lsblk row (Linux enumeration). Mutation: lsblk failure falls through to an empty inventory, exit 0 -> red."""
    kw = dict(MODES[mode]) if mode != "nonzero" else dict(exit_code=1, stdout=b"")
    r = make_runner(extra=[recording("lsblk", ["-J", "-O", "-b"], **kw)])
    sid = new_session(cli)
    res = cli("inventory", "--session", sid, runner=r, os_family="linux")
    assert res.code == 4, res
    assert res.reasons
    assert rows(home, "lsblk")
