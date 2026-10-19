"""Snapshot delta. Valid only for the same identity with power-on hours and counters non-decreasing
(197 Current_Pending_Sector may fall: pending sectors get remapped or cleared). Absent on either side -> "n/a"."""
from dataclasses import dataclass, field

FIELDS = ["attr_5", "attr_187", "attr_197", "attr_198", "attr_199", "media_errors", "percentage_used",
          "num_err_log_entries", "power_on_hours"]
MEDIA_COUNTERS = ["attr_5", "attr_187", "attr_197", "attr_198", "media_errors"]  # growth = active degradation
MAY_FALL = {"attr_197"}


@dataclass
class DeltaResult:
    valid: bool
    reason: str = ""
    fields: dict = field(default_factory=dict)
    rising: list = field(default_factory=list)


def value(rec, name):
    h = rec.health_fields or {}
    if name.startswith("attr_"):
        a = (h.get("attributes") or {}).get(int(name[5:]))
        v = a.get("raw") if a else None
    else:
        v = h.get(name)
    return v if isinstance(v, int) and not isinstance(v, bool) else None


def _identity_differs(a, b):
    ia, ib = a.identity or {}, b.identity or {}
    for k in ("serial", "model", "bytes", "eui64", "wwn"):
        x, y = ia.get(k), ib.get(k)
        if x is not None and y is not None and str(x).strip().upper() != str(y).strip().upper():
            return True
    return False


def delta(a, b):
    """a = older snapshot, b = newer."""
    if _identity_differs(a, b):
        return DeltaResult(False, "identity differs")
    pa, pb = value(a, "power_on_hours"), value(b, "power_on_hours")
    if pa is not None and pb is not None and pb < pa:
        return DeltaResult(False, "power-on hours went backwards")
    fields = {}
    for f in FIELDS:
        x, y = value(a, f), value(b, f)
        fields[f] = "n/a" if x is None or y is None else y - x
    for f, d in fields.items():
        if d != "n/a" and d < 0 and f not in MAY_FALL:
            return DeltaResult(False, f"counter {f} went backwards")
    rising = [f for f in MEDIA_COUNTERS if fields[f] != "n/a" and fields[f] > 0]
    return DeltaResult(True, "valid", fields, rising)
