"""Phase 02 smartctl normaliser (B2-B6). Spec: phase-02 Key Insights, Requirements, B2-B6."""
import json

from conftest import eui64_of, fx_bytes, fx_json, sha256_hex, smart


def test_B2_nvme_990pro_identity():
    """B2. Mutation: eui64 built from ext_id in decimal, or bytes from nvme_total_capacity of another ns -> red."""
    rec = smart("smartctl/nvme-990pro-x.json")
    doc = fx_json("smartctl/nvme-990pro-x.json")
    idt = rec.identity
    assert idt["model"] == "Samsung SSD 990 PRO 1TB"
    assert idt["serial"] == doc["serial_number"]
    assert idt["firmware"] == "4B2QJXD7"
    assert idt["bytes"] == 1000204886016
    assert idt["protocol"] == "NVMe"
    assert idt["eui64"].lower() == "002538" + format(doc["nvme_namespaces"][0]["eui64"]["ext_id"], "010x")
    assert idt["eui64"].lower() == eui64_of(doc) == "0025380e45914fa6"


def test_B2_nvme_990pro_health_fields():
    """B2. Mutation: read temperature from a sensor array, or threshold from a wrong key -> red."""
    h = smart("smartctl/nvme-990pro-x.json").health_fields
    assert h["critical_warning"] == 0
    assert h["available_spare"] == 100
    assert h["available_spare_threshold"] == 10
    assert h["percentage_used"] == 6
    assert h["media_errors"] == 0
    assert h["power_on_hours"] == 5017
    assert h["temperature"] == 47
    assert h["temperature_warning"] == 82
    assert h["temperature_critical"] == 85
    assert h["overall_passed"] is True


def test_B3_sat_partial_absent_fields_stay_absent():
    """B3. Mutation: default missing model/bytes/status to ""/0/False -> red."""
    rec = smart("smartctl/scrutiny-sat-partial.json")
    assert rec.identity.get("model") is None
    assert rec.identity.get("bytes") is None
    assert rec.identity.get("serial") is None
    assert rec.health_fields.get("overall_passed") is None
    attrs = rec.health_fields["attributes"]
    doc = fx_json("smartctl/scrutiny-sat-partial.json")
    raw = {a["id"]: a["raw"]["value"] for a in doc["ata_smart_attributes"]["table"]}
    for aid in (5, 187, 188, 197, 198, 199):
        assert attrs[aid]["raw"] == raw[aid]
    assert rec.health_fields.get("temperature") == 29


def test_B4_scsi_without_smartctl_block_is_unknown_but_identity_parsed():
    """B4. Mutation: treat a missing `smartctl` block as ok (or as malformed and drop identity) -> red."""
    rec = smart("smartctl/scrutiny-scsi-no-smartctl-block.json")
    assert rec.collection_status == "unknown"
    assert rec.identity["model"] == "SEAGATE ST4000NM0043"
    assert rec.identity["bytes"] == 4000787030016


def test_B5_usbjmicron_bridge_type_and_external_hdd_class():
    """B5. Mutation: classify by rotation only (-> hdd) ignoring the bridge -> red."""
    rec = smart("smartctl/scrutiny-usbjmicron-hdd-failing.json")
    assert rec.identity["device_type"] == "usbjmicron"
    assert rec.identity["rotation_rate"] == 7200
    assert rec.detected_class == "external-hdd"


def test_B6_unknown_extra_keys_ignored():
    """B6 (in-test mutation: one extra top-level key). Mutation: strict schema rejecting new keys -> red."""
    from rslib.smart import normalise

    doc = fx_json("smartctl/nvme-990pro-x.json")
    doc["zz_future_smartctl_key"] = {"anything": [1, 2, 3]}
    rec = normalise(json.dumps(doc))
    base = smart("smartctl/nvme-990pro-x.json")
    assert rec.collection_status == "ok"
    assert rec.identity == base.identity
    assert rec.health_fields == base.health_fields


def test_B6_invalid_json_is_malformed_with_sha256():
    """B6. Mutation: raise on bad JSON, or skip the hash -> red."""
    from rslib.smart import normalise

    data = b"{ this is not json"
    rec = normalise(data)
    assert rec.collection_status == "malformed"
    assert rec.sha256 == sha256_hex(data)


def test_B6_json_without_format_version_is_malformed():
    """B6 'lacks json_format_version' (object with no smartctl document keys at all; see open question B4/B6)."""
    from rslib.smart import normalise

    data = b'{"foo": 1}'
    rec = normalise(data)
    assert rec.collection_status == "malformed"
    assert rec.sha256 == sha256_hex(data)


def test_B6_sha256_is_of_raw_bytes():
    """B6 'raw file still stored with sha256': sha256 of the exact input bytes. Mutation: hash re-serialised JSON -> red."""
    data = fx_bytes("smartctl/nvme-980pro-x.json")
    assert smart("smartctl/nvme-980pro-x.json").sha256 == sha256_hex(data)


def test_B6_cli_ingest_of_malformed_file_keeps_raw_hash(cli, tmp_path):
    """B6 at the CLI: malformed input still stored with sha256. Mutation: refuse to store malformed input -> red."""
    from conftest import new_session

    sid = new_session(cli)
    bad = tmp_path / "broken.json"
    bad.write_bytes(b"{ broken")
    res = cli("ingest", "smartctl", bad, "--session", sid)
    assert res.code in (0, 4), res
    assert res.data["snapshot"]["collection_status"] == "malformed"
    assert res.data["snapshot"]["sha256"] == sha256_hex(b"{ broken")
