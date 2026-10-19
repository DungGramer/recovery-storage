"""Phase 04 locks (D17-D19). Spec: phase-04 Requirements 'device-busy', 'global-lock-held', Architecture
(partial unique indexes gates_global on lock_slot / gates_device on device_id WHERE state IN pending, open) + D17-D19."""
import sqlite3

import pytest

from conftest import USB_STICK, close, confirm, gate_ok, open_gate, prepared

DEVREC = ("--goal", "device-recovery", "--preserve-data", "no", "--ceiling", "R2")


def two_devices(cli):
    """Device A = USB stick (session 1), device B = 980 PRO NVMe (session 2), same home, same capture."""
    s1, a, _ = prepared(cli, USB_STICK, "/dev/pd2", *DEVREC)
    s2, b, _ = prepared(cli, USB_STICK, "/dev/pd1", *DEVREC)
    return s1, a, s2, b


def test_D17_global_r2_lock_names_holder(cli):
    """D17. Mutation: lock per session instead of per home -> second R2 opens -> red."""
    s1, a, s2, b = two_devices(cli)
    g_a, _ = gate_ok(cli, USB_STICK, s1, a, "format")
    res = open_gate(cli, USB_STICK, s2, b, "format")
    assert res.code == 3, res
    assert "global-lock-held" in res.reasons
    assert g_a in res.text


def test_D17_r1_elsewhere_allowed_while_r2_held(cli):
    """D17. Mutation: global lock covers R1 too -> red."""
    s1, a, s2, b = two_devices(cli)
    gate_ok(cli, USB_STICK, s1, a, "format")
    gate_ok(cli, USB_STICK, s2, b, "smart-selftest-short")


@pytest.mark.parametrize("kind", ["disk-offline", "format"])
def test_D17_second_gate_same_device_busy(cli, kind):
    """D17. Mutation: no per-device lock -> two gates on one device -> red."""
    s1, a, _, _ = two_devices(cli)
    gate_ok(cli, USB_STICK, s1, a, "format")
    res = open_gate(cli, USB_STICK, s1, a, kind)
    assert res.code == 3, res
    assert "device-busy" in res.reasons


def _db(home):
    con = sqlite3.connect(home / "rs.sqlite", timeout=5)
    con.row_factory = sqlite3.Row
    return con


def test_D18_db_constraint_enforces_single_r2_holder(cli, home):
    """D18: the DB (not only Python code) refuses a second pending/open R2 row. A second connection inserts a
    copy of the holder with another id and device. Mutation: lock checked in Python only (no partial unique index) -> red."""
    s1, a, s2, b = two_devices(cli)
    g_a, _ = gate_ok(cli, USB_STICK, s1, a, "format")
    con = _db(home)
    try:
        cols = [r["name"] for r in con.execute("PRAGMA table_info(gates)")]
        row = dict(con.execute("SELECT * FROM gates WHERE id = ?", (g_a,)).fetchone())
        assert row["lock_slot"] == "R2" and row["state"] == "pending"
        idtype = [r["type"] for r in con.execute("PRAGMA table_info(gates)") if r["name"] == "id"][0]
        row["id"] = None if "INT" in idtype.upper() else f"{g_a}-race"
        row["device_id"] = b
        with pytest.raises(sqlite3.IntegrityError) as ei:
            con.execute(f"INSERT INTO gates ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                        [row[c] for c in cols])
        assert "unique" in str(ei.value).lower()
        assert "lock_slot" in str(ei.value) or "gates_global" in str(ei.value)
    finally:
        con.rollback()
        con.close()


def test_D18_db_constraint_enforces_single_live_gate_per_device(cli, home):
    """D18 companion (gates_device index). Mutation: device-busy checked in Python only -> red."""
    s1, a, _, _ = two_devices(cli)
    g, _ = gate_ok(cli, USB_STICK, s1, a, "disk-offline")
    con = _db(home)
    try:
        cols = [r["name"] for r in con.execute("PRAGMA table_info(gates)")]
        row = dict(con.execute("SELECT * FROM gates WHERE id = ?", (g,)).fetchone())
        idtype = [r["type"] for r in con.execute("PRAGMA table_info(gates)") if r["name"] == "id"][0]
        row["id"] = None if "INT" in idtype.upper() else f"{g}-race"
        with pytest.raises(sqlite3.IntegrityError) as ei:
            con.execute(f"INSERT INTO gates ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                        [row[c] for c in cols])
        assert "unique" in str(ei.value).lower()
    finally:
        con.rollback()
        con.close()


@pytest.mark.parametrize("finish", ["close", "abort"])
def test_D19_next_r2_after_close_or_abort(cli, finish):
    """D19. Mutation: lock row not released on close/abort -> red."""
    s1, a, s2, b = two_devices(cli)
    g_a, _ = gate_ok(cli, USB_STICK, s1, a, "format")
    if finish == "close":
        assert confirm(cli, USB_STICK, g_a, "8054112256").code == 0
        assert close(cli, USB_STICK, g_a, "success").code == 0
    else:
        assert cli("gate", "abort", g_a, "--reason", "done").code == 0
    gate_ok(cli, USB_STICK, s2, b, "format")
