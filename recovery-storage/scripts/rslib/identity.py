"""Multi-attribute device identity (spec §4 rule 1): never key on Disk Number, drive letter or /dev/sdX.

Canonical identity comes from smartctl when it answers (model, serial, bytes, eui64, wwn); OS fields are
secondary. Windows reports an NVMe SerialNumber as the EUI-64 (`XXXX_XXXX_XXXX_XXXX.`): that is an eui64,
never a serial. Match levels: exact > probable > weak; conflict / ambiguous / none (phase 02 Architecture).
"""
import re
from dataclasses import asdict, dataclass, field

EUI_FORM = re.compile(r"^[0-9A-Fa-f]{4}(_[0-9A-Fa-f]{4}){3}$")
EUI_UNIQUE_ID = re.compile(r"^eui\.([0-9A-Fa-f]{16})$")

LEVEL_ORDER = ["exact", "probable", "weak"]


def normalise_serial(raw):
    out = {"raw": raw, "serial_norm": None, "eui64": None}
    if not isinstance(raw, str):
        return out
    s = raw.strip().rstrip(".").strip()
    if EUI_FORM.match(s):
        out["eui64"] = s.replace("_", "").lower()
        return out
    if s and len(s) > 1 and any(c.isalnum() for c in s):
        out["serial_norm"] = s.upper()
    return out


def serial_trust(serial_raw, other_attached=()):
    norm = normalise_serial(serial_raw)["serial_norm"]
    if not norm:
        return "absent"
    if len(set(norm)) == 1:
        return "low"
    others = {normalise_serial(o)["serial_norm"] for o in other_attached}
    if norm in others:
        return "low"
    return "high"


@dataclass
class Fingerprint:
    model: object = None
    serial_norm: object = None
    serial_trust: object = "absent"
    bytes: object = None
    bus: object = None
    vid: object = None
    pid: object = None
    eui64: object = None
    wwn: object = None
    ptuuid: object = None
    mbr_signature: object = None
    os_ids: dict = field(default_factory=dict)

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, d):
        d = dict(d or {})
        known = {k: d.get(k) for k in cls.__dataclass_fields__ if k in d}
        if known.get("os_ids") is None:
            known["os_ids"] = {}
        return cls(**known)


@dataclass
class MatchResult:
    level: str
    device_ids: list = field(default_factory=list)


def _low(v):
    return v.strip().lower() if isinstance(v, str) and v.strip() else None


def _model(v):
    return " ".join(v.split()).casefold() if isinstance(v, str) and v.strip() else None


def fingerprint(os_disk=None, smart=None, attached=()):
    """Combine OS observation and smartctl identity. `attached`: serial strings of OTHER attached devices."""
    sid = (smart.identity if smart is not None else {}) or {}
    fp = Fingerprint()
    other_serials = [a.serial_norm if isinstance(a, Fingerprint) else a for a in attached]
    if sid.get("serial"):
        n = normalise_serial(sid["serial"])
        fp.serial_norm = n["serial_norm"]
        fp.serial_trust = serial_trust(sid["serial"], [s for s in other_serials if s])
    fp.model = sid.get("model")
    fp.bytes = sid.get("bytes")
    fp.eui64 = _low(sid.get("eui64"))
    fp.wwn = _low(sid.get("wwn"))
    if os_disk is not None:
        n = normalise_serial(os_disk.serial_raw)
        if fp.serial_norm is None and n["serial_norm"]:
            fp.serial_norm = n["serial_norm"]
            fp.serial_trust = serial_trust(os_disk.serial_raw, [s for s in other_serials if s])
        if fp.eui64 is None:
            m = EUI_UNIQUE_ID.match(os_disk.unique_id or "")
            fp.eui64 = (m.group(1).lower() if m else None) or n["eui64"]
        fp.model = fp.model or (os_disk.model.strip() if isinstance(os_disk.model, str) else None)
        fp.bytes = fp.bytes if fp.bytes is not None else os_disk.bytes
        fp.bus = os_disk.bus
        if os_disk.usb:
            fp.vid, fp.pid = _low(os_disk.usb.get("vid")), _low(os_disk.usb.get("pid"))
        fp.ptuuid = _low(os_disk.ptuuid)
        fp.mbr_signature = os_disk.mbr_signature or None
        fp.os_ids = {k: v for k, v in (("disk_number", os_disk.number), ("dev_path", os_disk.os_path),
                                       ("unique_id", os_disk.unique_id)) if v is not None}
    elif sid.get("protocol"):
        fp.bus = sid["protocol"].lower()
    if fp.serial_norm is None:
        fp.serial_trust = "absent"
    return fp


def _strong_conflict(a, b):
    if a.serial_trust == "high" and b.serial_trust == "high" and a.serial_norm and b.serial_norm \
            and a.serial_norm != b.serial_norm:
        return True
    for k in ("eui64", "wwn"):
        x, y = _low(getattr(a, k)), _low(getattr(b, k))
        if x and y and x != y:
            return True
    return False


def _strong_equal(a, b):
    for k in ("eui64", "wwn"):
        x, y = _low(getattr(a, k)), _low(getattr(b, k))
        if x and y and x != y:
            return False
    return True


def _same_model_bytes(a, b):
    return _model(a.model) is not None and _model(a.model) == _model(b.model) \
        and a.bytes is not None and a.bytes == b.bytes


def _same_usb(a, b):
    return bool(a.vid and a.pid) and _low(a.vid) == _low(b.vid) and _low(a.pid) == _low(b.pid)


def _media_id(fp):
    return [x for x in (_low(fp.ptuuid), fp.mbr_signature or None) if x]


def _level(fp, cand):
    if not _same_model_bytes(fp, cand):
        return None  # a different disk altogether, never a "conflict"
    if _strong_conflict(fp, cand):
        return "conflict"
    if fp.serial_trust == "high" and cand.serial_trust == "high" and fp.serial_norm == cand.serial_norm \
            and _strong_equal(fp, cand):
        return "exact"
    if fp.serial_trust != "high" or cand.serial_trust != "high":
        x, y = _low(fp.eui64) or _low(fp.wwn), _low(cand.eui64) or _low(cand.wwn)
        if x and y and x == y:
            return "exact" if fp.serial_trust == "high" or cand.serial_trust == "high" else "probable"
        if _same_usb(fp, cand):
            a_ids, b_ids = _media_id(fp), _media_id(cand)
            if a_ids and b_ids:
                if (_low(fp.ptuuid) and _low(fp.ptuuid) == _low(cand.ptuuid)) or \
                        (fp.mbr_signature and fp.mbr_signature == cand.mbr_signature):
                    return "probable"
                # ids differ: another stick, or the same one re-partitioned (MBR signature / GPT guid change on
                # every repartition) -> a human decides
                return "model_bytes"
            return "weak"
    return "model_bytes"


def match(fp, candidates, attached=()):
    levels = {}
    for dev_id, cand in candidates.items():
        lv = _level(fp, cand)
        if lv:
            levels[dev_id] = lv
    for lv in LEVEL_ORDER:
        ids = [d for d, x in levels.items() if x == lv]
        if len(ids) > 1:
            return MatchResult("ambiguous", sorted(ids))
        if len(ids) == 1:
            if lv == "weak" and any(_same_model_bytes(fp, o) and _same_usb(fp, o) for o in attached):
                return MatchResult("ambiguous", ids)
            if lv == "probable" and any(_level(o, candidates[ids[0]]) == "probable" for o in attached):
                # two attached lookalikes carrying the same on-media id (e.g. the same ISO written to both)
                return MatchResult("ambiguous", ids)
            return MatchResult(lv, ids)
    mb = [d for d, x in levels.items() if x == "model_bytes"]
    if mb:
        return MatchResult("ambiguous", sorted(mb))
    if any(x == "conflict" for x in levels.values()):
        return MatchResult("conflict", sorted(d for d, x in levels.items() if x == "conflict"))
    return MatchResult("none", [])


def windows_join(os_disk, smart):
    """Is this smartctl record the disk Get-Disk reported? NVMe: UniqueId eui.<hex> == smartctl eui64 + bytes."""
    m = EUI_UNIQUE_ID.match((os_disk.unique_id or "") if os_disk is not None else "")
    if not m or smart is None or not (smart.identity or {}).get("eui64"):
        return "not_applicable"
    same_eui = m.group(1).lower() == smart.identity["eui64"].lower()
    same_bytes = smart.identity.get("bytes") is not None and smart.identity.get("bytes") == os_disk.bytes
    return "joined" if same_eui and same_bytes else "join_conflict"
