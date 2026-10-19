"""Phase 03 wear + host writes (C3 wear, C5, C6). Spec: phase-03 Requirements 'SATA SSD wear', 'Host writes'."""
import json

import pytest

from conftest import fx_json, smart


def W(rel=None, rec=None):
    from rslib.wear import assess

    return assess(rec if rec is not None else smart(rel))


def test_C3_wear_leveling_count_not_whitelisted_is_unknown():
    """C3 'wear unknown (177 Wear_Leveling_Count not whitelisted)'. Mutation: treat 177 VALUE as remaining -> red."""
    w = W("smartctl/scrutiny-ata-ssd-crc199.json")
    assert w["used_pct"] is None and w["remaining_pct"] is None
    assert w["source"] is None


def test_C5_devstat_endurance_preferred():
    """C5 'wear from devstat endurance 19 (used), source devstat'. Mutation: use 177 (81) or remaining=19 -> red."""
    w = W("smartctl/scrutiny-ata-ssd-healthy.json")
    assert w["used_pct"] == 19
    assert w["source"] == "devstat"


def test_C6_nvme_percentage_used():
    """C6 'percentage_used 6'. Mutation: report 100-6 as used -> red."""
    w = W("smartctl/nvme-990pro-x.json")
    assert w["used_pct"] == 6 and w["source"] == "nvme"


def test_C6_nvme_host_writes_units_of_512000():
    """C6 'host writes = 74494327 x 512000 bytes'. Mutation: x 512 or x 1000 -> red."""
    from rslib.wear import host_writes_bytes

    assert host_writes_bytes(smart("smartctl/nvme-990pro-x.json")) == 74494327 * 512000


def test_sata_host_writes_from_devstat_logical_sectors():
    """Requirements 'SATA devstat Logical Sectors Written x logical block size' (860 EVO: 64777770148 x 512)."""
    from rslib.wear import host_writes_bytes

    assert host_writes_bytes(smart("smartctl/scrutiny-ata-ssd-healthy.json")) == 64777770148 * 512


def test_host_writes_absent_is_none():
    """'no TBW-remaining'; absent source -> None, not 0. Mutation: default 0 -> red."""
    from rslib.wear import host_writes_bytes

    assert host_writes_bytes(smart("smartctl/scrutiny-sat-partial.json")) is None


@pytest.mark.parametrize("aid,name", [
    (169, "Remaining_Lifetime_Perc"), (173, "Percent_Lifetime_Remain"), (202, "Percent_Lifetime_Remain"),
    (231, "Percent_Lifetime_Remain"), (231, "SSD_Life_Left"), (231, "Life_Remaining_Percent"),
    (233, "Remaining_Lifetime_Perc"), (177, "Lifetime_Remaining%"),
])
def test_wear_whitelist_rows_give_remaining_value(aid, name):
    """Requirements whitelist. Mutation: drop a row or return 100-VALUE -> red."""
    from rslib.wear import from_attribute

    assert from_attribute(aid, name, 87) == 87


@pytest.mark.parametrize("aid,name", [(177, "Wear_Leveling_Count"), (233, "Media_Wearout_Indicator"),
                                      (231, "Temperature_Celsius"), (169, "Unknown_Attribute")])
def test_wear_other_rows_unknown(aid, name):
    """Requirements 'Any other wear row -> wear unknown'. Mutation: whitelist by id only -> red."""
    from rslib.wear import from_attribute

    assert from_attribute(aid, name, 87) is None


def test_wear_attribute_source_confidence_low():
    """Requirements 'remaining = normalised VALUE, confidence low' (in-test rename of 840's 177 to a whitelisted name).
    Mutation: confidence medium for name-inferred wear -> red."""
    from rslib.smart import normalise

    doc = fx_json("smartctl/scrutiny-ata-ssd-crc199.json")
    for a in doc["ata_smart_attributes"]["table"]:
        if a["id"] == 177:
            a["name"] = "Lifetime_Remaining%"
    w = W(rec=normalise(json.dumps(doc)))
    assert w["remaining_pct"] == 98
    assert w["source"] == "attribute"
    assert w["confidence"] == "low"
