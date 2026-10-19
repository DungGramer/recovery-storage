"""Phase 05 fleet (E8, E9, E11). Spec: phase-05 Key Insights 'Grouping is a deterministic key', Requirements
'device list', 'device show' + E8/E9/E11; spec §6 GĐ3."""
import json

from conftest import assess, ingest_smart, new_session, ok

E8_ASSESSED = ["smartctl/scrutiny-usbjmicron-hdd-failing.json", "smartctl/scrutiny-ata-hdd-healthy.json",
               "smartctl/scrutiny-nvme-media-errors.json", "smartctl/missing-device.json"]
UNASSESSED = "smartctl/nvme-990pro-x.json"


def fleet(cli):
    sid = new_session(cli, "--goal", "diagnosis-only")
    devs = {}
    for rel in E8_ASSESSED:
        d = ingest_smart(cli, sid, rel).data["device_id"]
        assess(cli, sid, d)
        devs[rel] = d
    devs[UNASSESSED] = ingest_smart(cli, sid, UNASSESSED).data["device_id"]
    return sid, devs


def test_E8_group_by_triage(cli):
    """E8. Mutation: unassessed devices dropped instead of grouped `unassessed` -> red."""
    _, devs = fleet(cli)
    d = ok(cli("device", "list", "--group-by", "triage"))
    groups = {g["key"]: sorted(g["device_ids"]) for g in d["groups"]}
    assert groups == {
        "SOFTWARE_RECOVERY_CANDIDATE": sorted(devs[r] for r in E8_ASSESSED[:3]),
        "UNDETERMINED": [devs["smartctl/missing-device.json"]],
        "unassessed": [devs[UNASSESSED]],
    }


def test_E8_ordering_stable_and_byte_identical(cli):
    """E8 'ordering stable (group key, then device id); same input -> byte-identical output'. Mutation: dict/set order -> red."""
    fleet(cli)
    a = cli("device", "list", "--group-by", "triage", json_out=False)
    b = cli("device", "list", "--group-by", "triage", json_out=False)
    assert a.code == b.code == 0
    assert a.out == b.out
    d = ok(cli("device", "list", "--group-by", "triage"))
    keys = [g["key"] for g in d["groups"]]
    assert keys == sorted(keys)
    for g in d["groups"]:
        assert g["device_ids"] == sorted(g["device_ids"])


def test_device_list_columns(cli):
    """Requirements 'device list: id, model, bytes, class, latest triage, latest health, latest verdict, last seen'."""
    _, devs = fleet(cli)
    rows = {r["device_id"]: r for r in ok(cli("device", "list"))["devices"]}
    r = rows[devs["smartctl/scrutiny-usbjmicron-hdd-failing.json"]]
    assert r["model"] == "Hitachi HDS721050DLE630" and r["bytes"] == 500107862016
    assert r["class"] == "external-hdd"
    assert r["triage"] == "SOFTWARE_RECOVERY_CANDIDATE" and r["health"] == "failing"
    assert r["last_seen"]
    assert rows[devs[UNASSESSED]]["triage"] in (None, "", "unassessed")


def test_E9_device_show_chronological_across_sessions(cli):
    """E9. Mutation: history limited to one session, or unsorted -> red."""
    s1 = new_session(cli)
    dev = ingest_smart(cli, s1, "smartctl/scrutiny-usbjmicron-hdd-failing.json").data["device_id"]
    assess(cli, s1, dev)
    s2 = new_session(cli)
    assert ingest_smart(cli, s2, "smartctl/scrutiny-usbjmicron-hdd-failing.p197-12.derived.json").data["device_id"] == dev
    assess(cli, s2, dev)
    ok(cli("verdict", "set", s2, dev, "FAIL", "--reason", "pending sectors growing"))
    h = ok(cli("device", "show", dev))["history"]
    ts = [x["ts"] for x in h]
    assert ts == sorted(ts)
    assert {x["session_id"] for x in h} >= {s1, s2}
    types = [x["type"] for x in h]
    for t in ("snapshot", "assessment", "verdict"):
        assert t in types
    first_s2 = next(i for i, x in enumerate(h) if x["session_id"] == s2)
    assert all(x["session_id"] != s1 for x in h[first_s2:] if x["type"] == "snapshot")


def test_E11_list_and_show_json_parseable(cli):
    """E11. Mutation: text mixed into --json output -> red."""
    _, devs = fleet(cli)
    for args in (("device", "list"), ("device", "list", "--group-by", "status"), ("device", "show", devs[UNASSESSED])):
        r = cli(*args)
        assert r.code == 0, r
        assert isinstance(json.loads(r.out), dict)
