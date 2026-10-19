"""Phase 03 health verdict rules (C1-C11). Spec: phase-03 Requirements 'Health verdict' rules 1-5 + C1-C11.
Pure: rslib.health.verdict(rslib.smart.normalise(fixture), prev)."""
import pytest

from conftest import FIX, ev_paths, ev_text, smart


def V(rel, prev=None):
    from rslib.health import verdict

    return verdict(smart(rel), smart(prev) if prev else None)


def has(ev, path_prefix, value=None):
    for e in ev:
        if str(e.get("path", "")).startswith(path_prefix) and (value is None or e.get("value") == value):
            return True
    return False


def test_C1_usbjmicron_failing_high_with_evidence():
    """C1. Mutation: rule 1 checks only smart_status (misses attr 5 trip / 197 / self-test) -> red."""
    v = V("smartctl/scrutiny-usbjmicron-hdd-failing.json")
    assert (v.verdict, v.confidence) == ("failing", "high")
    assert has(v.evidence, "smart_status.passed", False)
    assert any(p.startswith("ata_smart_attributes[5]") for p in ev_paths(v.evidence))
    assert has(v.evidence, "ata_smart_attributes[197].raw", 8)
    assert "read failure" in ev_text(v.evidence).lower()
    assert any(e.get("strength") == "strong" for e in v.evidence)


def test_C2_nvme_media_errors_degraded_medium():
    """C2. Mutation: media_errors > 0 -> failing (too strong) or watch -> red; num_err_log weak."""
    v = V("smartctl/scrutiny-nvme-media-errors.json")
    assert (v.verdict, v.confidence) == ("degraded", "medium")
    assert has(v.evidence, "nvme_smart_health_information_log.media_errors", 7)
    weak = [e for e in v.evidence if str(e.get("path")).endswith("num_err_log_entries")]
    assert weak and weak[0]["value"] == 62 and weak[0]["strength"] == "weak"


def test_C3_crc199_is_watch_not_media_verdict():
    """C3. Mutation: 199 counted with 5/187/197/198 -> degraded -> red."""
    v = V("smartctl/scrutiny-ata-ssd-crc199.json")
    assert v.verdict == "watch"
    assert has(v.evidence, "ata_smart_attributes[199].raw", 108)


def test_C4_wd_hdd_clean_is_healthy_medium_never_high():
    """C4. Mutation: healthy with confidence high, or no next test -> red."""
    v = V("smartctl/scrutiny-ata-hdd-healthy.json")
    assert (v.verdict, v.confidence) == ("healthy", "medium")
    nt = (v.next_test or "").lower()
    assert "extended self-test" in nt and "surface read" in nt


def test_C5_860evo_healthy_medium():
    """C5 (wear part in test_wear). Mutation: 177 Wear_Leveling_Count treated as failing -> red."""
    v = V("smartctl/scrutiny-ata-ssd-healthy.json")
    assert (v.verdict, v.confidence) == ("healthy", "medium")


def test_C6_990pro_healthy_medium():
    """C6. Mutation: spare 100 vs threshold 10 compared the wrong way -> failing -> red."""
    v = V("smartctl/nvme-990pro-x.json")
    assert (v.verdict, v.confidence) == ("healthy", "medium")
    assert has(v.evidence, "nvme_smart_health_information_log.percentage_used", 6)
    assert has(v.evidence, "nvme_smart_health_information_log.available_spare", 100)
    assert v.next_test


def test_C7_sat_partial_unknown_lists_missing():
    """C7. Mutation: missing overall status defaulted to passed -> healthy -> red."""
    v = V("smartctl/scrutiny-sat-partial.json")
    assert v.verdict == "unknown"
    assert any("smart_status" in m for m in v.missing), v.missing
    assert any("user_capacity" in m for m in v.missing), v.missing
    assert any(p.startswith("ata_smart_attributes[5]") for p in ev_paths(v.evidence))
    assert any(p.startswith("ata_smart_attributes[197]") for p in ev_paths(v.evidence))


def test_C8_scsi_unknown_status_as_evidence_only():
    """C8. Mutation: apply ATA rules to SCSI -> healthy -> red."""
    v = V("smartctl/scrutiny-scsi-no-smartctl-block.json")
    assert v.verdict == "unknown"
    assert has(v.evidence, "smart_status.passed", True)


def test_C9_open_failed_unknown_needs_elevation():
    """C9. Mutation: open failure treated as device failure (failing) -> red."""
    v = V("smartctl/scrutiny-open-failed.json")
    assert v.verdict == "unknown"
    assert v.reason == "needs_elevation"
    assert "re-run collect from an elevated shell" in (v.next_test or "").lower()


def test_C9_missing_device_unknown_collection_failed():
    """C9. Mutation: reason left empty / next test generic -> red."""
    v = V("smartctl/missing-device.json")
    assert v.verdict == "unknown"
    assert v.reason == "collection_failed"
    nt = (v.next_test or "").lower()
    assert "connection" in nt or "device path" in nt


@pytest.mark.parametrize("rel,verdict", [
    ("smartctl/nvme-990pro-x.pu79.derived.json", "healthy"),
    ("smartctl/nvme-990pro-x.pu80.derived.json", "watch"),
    ("smartctl/nvme-990pro-x.pu99.derived.json", "watch"),
    ("smartctl/nvme-990pro-x.pu100.derived.json", "degraded"),
    ("smartctl/nvme-990pro-x.cw1.derived.json", "failing"),
    ("smartctl/nvme-990pro-x.cw8.derived.json", "failing"),
    ("smartctl/nvme-990pro-x.spare5.derived.json", "failing"),
])
def test_C10_derived_boundaries(rel, verdict):
    """C10. Mutations: watch threshold > instead of >= (80 -> healthy); degraded at > 100; bit 0/3 not read -> red."""
    assert V(rel).verdict == verdict


def test_rule3_temperature_at_op_limit_is_watch():
    """Rule 3 'temperature.current >= device-reported op_limit_max' (derived temp85, op_limit 82). Mutation: rule absent -> healthy -> red."""
    assert V("smartctl/nvme-990pro-x.temp85.derived.json").verdict == "watch"


def all_smart_rels():
    out = []
    for p in sorted((FIX / "smartctl").glob("*.json")):
        out.append(f"smartctl/{p.name}")
    for p in sorted((FIX / "windows").rglob("smartctl-x-*.json")):
        if not p.name.endswith(".meta.json"):
            out.append(p.relative_to(FIX).as_posix())
    return out


@pytest.mark.parametrize("rel", all_smart_rels())
def test_C11_no_healthy_high_on_any_fixture(rel):
    """C11 property. Mutation: lift the 'healthy' cap to high for NVMe -> red on 990/980 fixtures."""
    v = V(rel)
    assert not (v.verdict == "healthy" and v.confidence == "high")
    assert v.verdict in ("healthy", "watch", "degraded", "failing", "unknown")
    assert v.confidence in ("low", "medium", "high")


def test_health_rule_ids_come_from_rules_table():
    """F8 link: every verdict names a rule id that exists in rslib.health.RULES. Mutation: ad-hoc rule ids -> red."""
    from rslib.health import RULES

    ids = {r.id for r in RULES}
    for rel in all_smart_rels():
        assert V(rel).rule_id in ids, rel
