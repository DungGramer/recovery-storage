"""SSD wear and host writes. Only names that state "remaining"/"left" are read as % remaining (smartmontools
drivedb names; researcher-05 §2); any other wear row is unknown. TBW is a vendor datasheet value, never read."""

# (attribute id, smartctl name) whose normalised VALUE is % life remaining
WEAR_WHITELIST = [
    (169, "Remaining_Lifetime_Perc"), (173, "Percent_Lifetime_Remain"), (202, "Percent_Lifetime_Remain"),
    (231, "Percent_Lifetime_Remain"), (231, "SSD_Life_Left"), (231, "Life_Remaining_Percent"),
    (233, "Remaining_Lifetime_Perc"), (177, "Lifetime_Remaining%"),
]
NVME_DATA_UNIT_BYTES = 512000  # NVMe Data Units = 1000 x 512 bytes (smartmontools nvmeprint.cpp host_writes)


def from_attribute(attr_id, name, value):
    if (attr_id, name) in WEAR_WHITELIST and isinstance(value, int):
        return value
    return None


def _devstat(rec, wanted):
    pages = ((rec.doc or {}).get("ata_device_statistics") or {}).get("pages") or []
    for pg in pages:
        for row in pg.get("table") or []:
            if row.get("name") == wanted and isinstance(row.get("value"), int):
                return row["value"]
    return None


def assess(rec):
    h = rec.health_fields or {}
    if isinstance(h.get("percentage_used"), int):
        return {"used_pct": h["percentage_used"], "remaining_pct": None, "source": "nvme", "confidence": "medium"}
    used = _devstat(rec, "Percentage Used Endurance Indicator")
    if used is not None:
        return {"used_pct": used, "remaining_pct": None, "source": "devstat", "confidence": "medium"}
    for aid, a in sorted((h.get("attributes") or {}).items()):
        rem = from_attribute(aid, a.get("name"), a.get("value"))
        if rem is not None:
            return {"used_pct": None, "remaining_pct": rem, "source": "attribute", "confidence": "low",
                    "attribute": aid}
    return {"used_pct": None, "remaining_pct": None, "source": None, "confidence": None}


def host_writes_bytes(rec):
    h = rec.health_fields or {}
    if isinstance(h.get("data_units_written"), int):
        return h["data_units_written"] * NVME_DATA_UNIT_BYTES
    sectors = _devstat(rec, "Logical Sectors Written")
    lbs = (rec.identity or {}).get("logical_block_size")
    if sectors is not None and isinstance(lbs, int):
        return sectors * lbs
    return None
