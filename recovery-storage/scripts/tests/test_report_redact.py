"""Phase 05 --redact (E6). Spec: phase-05 Requirements '--redact' + E6; spec §4 rule 10."""
import os
import pathlib
import re

import pytest

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


# ---------------- E6b (amendment 05 R1): redaction masks identifier values only, never fixed report words
_PATH = re.compile(r"[A-Za-z]:[\\/]|/home/|/Users/|/tmp/")


def _user_forms(home, tmp_path):
    forms = {os.environ.get("USERNAME"), os.environ.get("USER"), pathlib.Path.home().name}
    forms |= {p for p in pathlib.Path(tmp_path).parts if "~" in p}
    return {f.lower() for f in forms if f and len(f) >= 3}


def _personal(line, users):
    """A line carrying a path or a user name may legitimately change under --redact (home -> ~, user removed)."""
    low = line.lower()
    return bool(_PATH.search(line)) or "~" in line or any(u in low for u in users)


def _flow(cli, tmp_path, flow):
    from test_report_sections import reader_retired_flow, stick_pass_flow

    if flow == "stick-pass":
        sid, dev, _ = stick_pass_flow(cli, tmp_path)
    else:
        sid, dev = reader_retired_flow(cli)
    return sid, dev


@pytest.mark.parametrize("flow", ["stick-pass", "reader-retired"])
def test_E6b_redact_changes_only_identifier_values(cli, home, tmp_path, flow):
    """Amendment 05 R1. Both devices of the real runs have no serial (trust absent), so with --redact every line
    without a path / user name is byte-identical to the plain report (line structure preserved, test-designer reading
    of the observed renderer). Covers every fixed word these reports print (`not reported`, `none`, trust words,
    tags, gate / verdict / evidence wording), not only 'not'.
    Mutation: the serial pattern masks the word after 'serial:' ('serial: **** reported', real reports) -> red."""
    sid, dev = _flow(cli, tmp_path, flow)
    users = _user_forms(home, tmp_path)
    plain = cli("report", sid, "--device", dev, json_out=False)
    red = cli("report", sid, "--device", dev, "--redact", json_out=False)
    assert plain.code == 0 and red.code == 0, (plain, red)
    pl, rl = plain.out.splitlines(), red.out.splitlines()
    assert len(pl) == len(rl), (len(pl), len(rl))
    diff = [(p, r) for p, r in zip(pl, rl) if p != r and not _personal(p, users)]
    assert diff == []
    assert "not reported" in plain.out


@pytest.mark.parametrize("flow", ["stick-pass", "reader-retired"])
def test_E6b_redact_json_model_texts_unchanged_without_identifiers(cli, home, tmp_path, flow):
    """Amendment 05 R1 on the JSON model (E11 same data): item texts without a path / user name are equal with and
    without --redact. Mutation: JSON redaction keeps the word-eating pattern -> red."""
    sid, dev = _flow(cli, tmp_path, flow)
    users = _user_forms(home, tmp_path)

    def texts(*extra):
        res = cli("report", sid, "--device", dev, *extra)
        assert res.code == 0, res
        d = next(x for x in res.data["devices"] if x["device_id"] == dev)
        return [str(i.get("text")) for s in d["sections"] for i in s["items"]]

    a, b = texts(), texts("--redact")
    assert len(a) == len(b)
    assert [(x, y) for x, y in zip(a, b) if x != y and not _personal(x, users)] == []
