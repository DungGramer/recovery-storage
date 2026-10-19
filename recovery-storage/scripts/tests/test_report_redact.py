"""Phase 05 --redact (E6). Spec: phase-05 Requirements '--redact' + E6; spec §4 rule 10."""
import os
import pathlib

from conftest import assess, eui64_of, fx_json, ingest_smart, new_session


def _wwn_forms(doc):
    w = doc["wwn"]
    full = f"{w['naa']:x}{w['oui']:06x}{w['id']:09x}"
    return {full, f"{w['id']:x}", str(w["id"]), f"{w['naa']:x} {w['oui']:06x} {w['id']:09x}"}


def test_E6_redact_removes_serial_eui_wwn_and_username(cli, home):
    """E6. Mutation: redact serial only (eui/wwn/home path leak) -> red."""
    sid = new_session(cli, "--goal", "diagnosis-only")
    secrets = set()
    for rel in ("smartctl/nvme-990pro-x.json", "smartctl/scrutiny-ata-hdd-healthy.json"):
        dev = ingest_smart(cli, sid, rel).data["device_id"]
        assess(cli, sid, dev)
        doc = fx_json(rel)
        secrets.add(doc["serial_number"])
        if "nvme_namespaces" in doc:
            secrets.add(eui64_of(doc))
        if "wwn" in doc:
            secrets |= _wwn_forms(doc)
    plain = cli("report", sid, json_out=False)
    assert plain.code == 0, plain
    assert fx_json("smartctl/nvme-990pro-x.json")["serial_number"] in plain.out  # unredacted report does show it
    red = cli("report", sid, "--redact", json_out=False)
    assert red.code == 0, red
    low = red.out.lower()
    leaked = [s for s in secrets if s.lower() in low]
    assert leaked == []
    assert "****" in red.out
    serial = fx_json("smartctl/nvme-990pro-x.json")["serial_number"]
    assert serial[-4:] in red.out  # last 4 kept
    assert str(home) not in red.out and pathlib.Path(home).as_posix() not in red.out
    user = os.environ.get("USERNAME") or os.environ.get("USER") or pathlib.Path.home().name
    if user and len(user) >= 4:
        assert user.lower() not in low


def test_E6_redact_applies_to_json_model(cli):
    """E6 + E11 (same data in JSON). Mutation: redact markdown only -> red."""
    sid = new_session(cli, "--goal", "diagnosis-only")
    dev = ingest_smart(cli, sid, "smartctl/nvme-990pro-x.json").data["device_id"]
    assess(cli, sid, dev)
    res = cli("report", sid, "--redact")
    assert res.code == 0, res
    doc = fx_json("smartctl/nvme-990pro-x.json")
    assert doc["serial_number"] not in res.out
    assert eui64_of(doc) not in res.out.lower()
