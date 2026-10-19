"""Phase 03 delta engine (C12). Spec: phase-03 Requirements 'Delta engine' + C12."""
import json

from conftest import fx_json, smart

BASE = "smartctl/nvme-990pro-x.json"


def D(a, b):
    from rslib.delta import delta

    return delta(a, b)


def test_C12_media_errors_rise_valid_plus_3():
    """C12. Mutation: delta = a - b (sign flipped) -> -3 -> red."""
    r = D(smart(BASE), smart("smartctl/nvme-990pro-x.media3-poh10.derived.json"))
    assert r.valid is True
    assert r.fields["media_errors"] == 3
    assert r.fields["power_on_hours"] == 10
    assert "media_errors" in r.rising


def test_C12_rising_counter_lifts_health_to_degraded():
    """C12 'health at least degraded with rising evidence'. Mutation: verdict ignores prev -> healthy -> red."""
    from rslib.health import verdict

    v = verdict(smart("smartctl/nvme-990pro-x.media3-poh10.derived.json"), smart(BASE))
    assert v.verdict in ("degraded", "failing")
    assert any(str(e.get("path", "")).startswith("delta.") and "media_errors" in str(e.get("path"))
               for e in v.evidence), v.evidence


def test_C12_power_on_hours_backwards_invalid():
    """C12. Mutation: no POH monotonic check -> valid -> red."""
    r = D(smart(BASE), smart("smartctl/nvme-990pro-x.poh-back.derived.json"))
    assert r.valid is False
    assert "power-on hours went backwards" in (r.reason or "")


def test_C12_invalid_pair_not_used_by_health():
    """C12 'no delta used'. Mutation: health consumes an invalid delta -> red."""
    from rslib.health import verdict

    v = verdict(smart("smartctl/nvme-990pro-x.poh-back.derived.json"), smart(BASE))
    assert not any(str(e.get("path", "")).startswith("delta.") for e in v.evidence)


def test_C12_different_identity_invalid():
    """C12 'Different serials -> invalid: identity differs'. Mutation: compare model only -> red."""
    r = D(smart(BASE), smart("smartctl/nvme-980pro-x.json"))
    assert r.valid is False
    assert "identity differs" in (r.reason or "")


def test_C12_197_falling_exempt_and_5_rising_counted():
    """C12 (derived r5up-p197down). Mutation: treat falling 197 as invalid, or count it as rising -> red."""
    r = D(smart("smartctl/scrutiny-usbjmicron-hdd-failing.json"),
          smart("smartctl/scrutiny-usbjmicron-hdd-failing.r5up-p197down.derived.json"))
    assert r.valid is True
    assert r.fields["attr_5"] == 1
    assert r.fields["attr_197"] == -4
    assert "attr_5" in r.rising and "attr_197" not in r.rising


def test_C12_other_counter_falling_invalid():
    """Requirements 'counters non-decreasing except 197' (in-test mutation: attr 5 raw 1975 -> 1974, POH equal).
    Mutation: exempt every counter -> valid -> red."""
    from rslib.smart import normalise

    doc = fx_json("smartctl/scrutiny-usbjmicron-hdd-failing.json")
    for a in doc["ata_smart_attributes"]["table"]:
        if a["id"] == 5:
            a["raw"]["value"], a["raw"]["string"] = 1974, "1974"
    r = D(smart("smartctl/scrutiny-usbjmicron-hdd-failing.json"), normalise(json.dumps(doc)))
    assert r.valid is False


def test_C12_field_absent_one_side_is_na_not_zero():
    """C12. Mutation: missing -> 0 -> red."""
    r = D(smart(BASE), smart("smartctl/nvme-990pro-x.no-media-errors.derived.json"))
    assert r.fields["media_errors"] == "n/a"
    assert r.fields["power_on_hours"] == 0
