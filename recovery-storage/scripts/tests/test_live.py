"""Criteria that need a real device, admin rights, another interpreter or a live Claude Code session.
All `live` (deselected by default; run with `python -m pytest -m live`). Manual checks FAIL until their result is
recorded in the phase review; they never pass silently."""
import json
import shutil
import subprocess
import sys

import pytest

from conftest import REPO, SCRIPTS

pytestmark = pytest.mark.live


def rs(home, *args, timeout=600):
    p = subprocess.run([sys.executable, str(SCRIPTS / "rs.py"), "--home", str(home), "--json", *args],
                       capture_output=True, text=True, timeout=timeout)
    assert "Traceback" not in p.stderr, p.stderr
    return p.returncode, (json.loads(p.stdout) if p.stdout.strip() else None), p


@pytest.mark.slow
def test_G11_live_r0_smoke_on_this_machine(tmp_path):
    """G11 (needs this machine: 2 NVMe + USB stick + SD reader plugged in, non-admin, smartctl 7.5).
    Expected: NVMe joined exactly, health healthy/medium, boot/system flagged; USB/SD serial absent, needs_elevation,
    SOFTWARE_RECOVERY_CANDIDATE; report --redact --check exit 3 naming section 9 (8 allowed, see E1). Record date, interpreter,
    smartctl version in the phase-07 review."""
    h = tmp_path / "home"
    code, d, _ = rs(h, "session", "new", "--goal", "health-assessment")
    assert code == 0
    sid = d["session"]["id"]
    code, inv, p = rs(h, "inventory", "--session", sid)
    assert code == 0, p.stderr
    obs = {o["os_path"]: o for o in inv["observations"]}
    nvme = [o for o in obs.values() if o["fingerprint"]["bus"] == "nvme"]
    usb = [o for o in obs.values() if o["fingerprint"]["bus"] == "usb"]
    assert len(nvme) == 2 and len(usb) == 2
    assert all(o["join"] == "joined" for o in nvme)
    assert any(o["is_boot"] and o["is_system"] for o in nvme)
    assert all(o["fingerprint"]["serial_trust"] == "absent" for o in usb)
    for o in nvme + usb:
        code, c, p = rs(h, "collect", o["device_id"], "--session", sid)
        assert code == 0, p.stderr
        code, a, p = rs(h, "assess", sid, o["device_id"])
        assert code == 0, p.stderr
        if o in nvme:
            assert (a["assessment"]["health"]["verdict"], a["assessment"]["health"]["confidence"]) == ("healthy", "medium")
        else:
            assert c["snapshot"]["collection_status"] == "needs_elevation"
            assert a["assessment"]["triage"]["class"] == "SOFTWARE_RECOVERY_CANDIDATE"
    code, r, p = rs(h, "report", sid, "--redact", "--check")
    # G11 says "except section 9"; E1 says a no-verdict report also lacks section 8 (open question E1/G11).
    assert code == 3 and 9 in r["check"]["missing_sections"], p.stdout
    assert set(r["check"]["missing_sections"]) <= {8, 9}, p.stdout


@pytest.mark.slow
@pytest.mark.parametrize("version", ["3.10", "3.12"])
def test_G10_suite_green_on_python(version):
    """G10: full (non-live) suite exit 0 on the uv-managed interpreter. Record interpreter path + version in the review."""
    uv = shutil.which("uv")
    assert uv, "uv not on PATH (decision Q6: `uv python install 3.10`)"
    p = subprocess.run([uv, "run", "--python", version, "--with", "pytest>=8,<9", "python", "-m", "pytest", "-q",
                        "-m", "not live"], cwd=REPO, capture_output=True, text=True, timeout=3600)
    assert p.returncode == 0, p.stdout[-4000:] + p.stderr[-2000:]


def test_phase02_step6_wsl_bare_mount_identity_spike():
    """Phase 02 step 6 (admin + disk offline, R1, operator-run): after `wsl --mount <disk> --bare`, does WSL lsblk
    show the real model/serial? Result goes to SOURCES.md, not code."""
    pytest.fail("MANUAL: run the WSL bare-mount spike, record the result (model/serial real or virtual) in "
                "fixtures/SOURCES.md and the phase-02 review.")


def test_phase08_step1_spike_hook_enforced_in_bypass_permissions():
    """Phase 08 step 1: is ${CLAUDE_SKILL_DIR} substituted in hook commands, and does exit 2 deny Bash and PowerShell
    calls in bypassPermissions? Gates the whole phase ('Not Worth Doing If')."""
    pytest.fail("MANUAL: run the phase-08 spike in a live Claude Code session; record (a) substitution, (b) deny "
                "enforced for Bash and PowerShell, Claude Code version, permission mode, date.")


def test_H17_live_guard_hook_behaviour():
    """H17: after invoking the skill: Bash `blkdiscard /dev/rs-guard-sentinel` and PowerShell
    `Clear-Disk -Number 9999 -WhatIf` denied with the guard message; `smartctl -j -i /dev/sdz` runs; after gate open +
    confirm of an R1 kind on the USB stick the Bash sentinel is allowed; after gate abort denied again."""
    pytest.fail("MANUAL: run H17 in a live session; record date, Claude Code version, permission mode, each outcome.")
