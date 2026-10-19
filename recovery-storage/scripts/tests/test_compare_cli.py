"""Phase 05 compare (E10, E11). Spec: phase-05 Requirements 'compare' + E10."""
import json

from conftest import ingest_smart, new_session, ok

BASE = "smartctl/nvme-990pro-x.json"


def snaps(cli, a_rel, b_rel):
    sid = new_session(cli)
    a = ingest_smart(cli, sid, a_rel).data
    b = ingest_smart(cli, sid, b_rel).data
    return a["snapshot"]["id"], b["snapshot"]["id"], a["device_id"]


def test_E10_media_errors_plus3_poh_plus10(cli):
    """E10. Mutation: print absolute values instead of deltas -> red."""
    a, b, dev = snaps(cli, BASE, "smartctl/nvme-990pro-x.media3-poh10.derived.json")
    d = ok(cli("compare", a, b))
    assert d["valid"] is True
    assert d["fields"]["media_errors"] == 3 and d["fields"]["power_on_hours"] == 10
    t = cli("compare", a, b, json_out=False)
    assert t.code == 0 and "+3" in t.out and "+10" in t.out
    dd = ok(cli("compare", "--device", dev))
    assert dd["fields"]["media_errors"] == 3


def test_E10_backwards_hours_invalid_header_no_fields(cli):
    """E10. Mutation: still print per-field deltas for an invalid pair -> red."""
    a, b, _ = snaps(cli, BASE, "smartctl/nvme-990pro-x.poh-back.derived.json")
    t = cli("compare", a, b, json_out=False)
    assert t.code == 0, t
    assert "INVALID COMPARISON: power-on hours went backwards" in t.out
    assert "-10" not in t.out
    d = ok(cli("compare", a, b))
    assert d["valid"] is False and not d["fields"]


def test_E10_missing_field_na(cli):
    """E10. Mutation: missing -> 0 -> red."""
    a, b, _ = snaps(cli, BASE, "smartctl/nvme-990pro-x.no-media-errors.derived.json")
    d = ok(cli("compare", a, b))
    assert d["fields"]["media_errors"] == "n/a"
    t = cli("compare", a, b, json_out=False)
    assert "n/a" in t.out


def test_E11_compare_json_parseable(cli):
    """E11. Mutation: extra text in --json -> red."""
    a, b, _ = snaps(cli, BASE, "smartctl/nvme-990pro-x.media3-poh10.derived.json")
    assert isinstance(json.loads(cli("compare", a, b).out), dict)
