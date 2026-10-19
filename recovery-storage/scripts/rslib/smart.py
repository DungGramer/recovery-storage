"""smartctl -j JSON -> SmartRecord. Reads smartctl's own JSON; no SMART decoding of our own.

Absent stays None (never 0/False). Exit status bitmask (smartctl man page, researcher-01 §2):
bits 0-2 = collection problems (data absent/incomplete, never "healthy"), 3-4 failing, 5-7 history.
"""
import hashlib
import json
import re
from dataclasses import dataclass, field

FLAG_BITS = {8: "smart_failing", 16: "prefail_threshold_now", 32: "attribute_failed_in_past",
             64: "error_log_has_records", 128: "selftest_log_has_errors"}

COLLECTION_STATUSES = ("ok", "standby", "not_exposed", "unsupported_bridge", "needs_elevation", "collection_failed",
                       "malformed", "unknown", "tool_missing", "timeout")

# environment facts, not device evidence (phase 02 Requirements)
ELEVATION_PATTERNS = ("Open failed, Error=5",)
BRIDGE_PATTERNS = ("Unknown USB bridge", "Unsupported USB bridge", "type is ambiguous")
STANDBY_PATTERNS = ("STANDBY", "SLEEP mode")

USB_BRIDGE_TYPES = re.compile(r"^(usb\w*|snt\w*)")
NVME_BRIDGE_TYPES = re.compile(r"^snt\w*")


def exit_flags(code):
    if not isinstance(code, int):
        return frozenset()
    return frozenset(name for bit, name in FLAG_BITS.items() if code & bit)


def classify_collection(exit_code, messages):
    text = " | ".join(messages or [])
    if any(p in text for p in ELEVATION_PATTERNS):
        return "needs_elevation"
    if any(p in text for p in BRIDGE_PATTERNS):
        return "unsupported_bridge"
    if exit_code is None:
        return "unknown"
    if exit_code & 0b111:
        if exit_code & 0b010 and any(p in text for p in STANDBY_PATTERNS):
            return "standby"
        return "collection_failed"
    return "ok"


@dataclass
class SmartRecord:
    collection_status: str
    flags: frozenset = frozenset()
    message: object = None
    identity: dict = field(default_factory=dict)
    health_fields: dict = field(default_factory=dict)
    detected_class: object = None
    sha256: str = ""
    raw: bytes = b""
    doc: object = None
    exit_code: object = None
    tool_version: object = None


def _get(d, *path):
    for p in path:
        if isinstance(d, dict) and p in d:
            d = d[p]
        elif isinstance(d, list) and isinstance(p, int) and -len(d) <= p < len(d):
            d = d[p]
        else:
            return None
    return d


def _eui64(doc):
    for ns in doc.get("nvme_namespaces") or []:
        e = ns.get("eui64") if isinstance(ns, dict) else None
        if isinstance(e, dict) and isinstance(e.get("oui"), int) and isinstance(e.get("ext_id"), int):
            return f"{e['oui']:06x}{e['ext_id']:010x}"
    return None


def _wwn(doc):
    w = doc.get("wwn")
    if isinstance(w, dict) and all(isinstance(w.get(k), int) for k in ("naa", "oui", "id")):
        return f"{w['naa']:x}{w['oui']:06x}{w['id']:09x}"
    return None


def _identity(doc):
    dev = doc.get("device") if isinstance(doc.get("device"), dict) else {}
    model = doc.get("model_name") or (" ".join(x for x in (doc.get("scsi_vendor"), doc.get("scsi_product")) if x)
                                      or None)
    return {
        "model": model.strip() if isinstance(model, str) and model.strip() else None,
        "serial": doc.get("serial_number"),
        "firmware": doc.get("firmware_version") or doc.get("scsi_revision"),
        "bytes": _get(doc, "user_capacity", "bytes"),
        "protocol": dev.get("protocol"),
        "device_type": dev.get("type"),
        "eui64": _eui64(doc),
        "wwn": _wwn(doc),
        "rotation_rate": doc.get("rotation_rate"),
        "logical_block_size": doc.get("logical_block_size"),
    }


def _attributes(doc):
    table = _get(doc, "ata_smart_attributes", "table")
    if not isinstance(table, list):
        return None
    out = {}
    for a in table:
        if isinstance(a, dict) and isinstance(a.get("id"), int):
            out[a["id"]] = {"name": a.get("name"), "value": a.get("value"), "worst": a.get("worst"),
                            "thresh": a.get("thresh"), "raw": _get(a, "raw", "value"),
                            "when_failed": a.get("when_failed"),
                            "prefailure": _get(a, "flags", "prefailure")}
    return out


def _health(doc):
    nv = doc.get("nvme_smart_health_information_log")
    nv = nv if isinstance(nv, dict) else {}
    passed = _get(doc, "smart_status", "passed")
    h = {
        "overall_passed": passed if isinstance(passed, bool) else None,
        "power_on_hours": _get(doc, "power_on_time", "hours"),
        "power_cycle_count": doc.get("power_cycle_count"),
        "temperature": _get(doc, "temperature", "current"),
        "temperature_op_limit_max": _get(doc, "temperature", "op_limit_max"),
        "temperature_critical_limit_max": _get(doc, "temperature", "critical_limit_max"),
    }
    if nv or doc.get("nvme_composite_temperature_threshold") is not None:
        h.update({
            "critical_warning": nv.get("critical_warning"),
            "available_spare": nv.get("available_spare"),
            "available_spare_threshold": nv.get("available_spare_threshold"),
            "percentage_used": nv.get("percentage_used"),
            "media_errors": nv.get("media_errors"),
            "num_err_log_entries": nv.get("num_err_log_entries"),
            "data_units_written": nv.get("data_units_written"),
            "temperature_warning": _get(doc, "nvme_composite_temperature_threshold", "warning"),
            "temperature_critical": _get(doc, "nvme_composite_temperature_threshold", "critical"),
        })
        if h["power_on_hours"] is None:
            h["power_on_hours"] = nv.get("power_on_hours")
        if h["temperature"] is None:
            h["temperature"] = nv.get("temperature")
    attrs = _attributes(doc)
    if attrs is not None:
        h["attributes"] = attrs
    return h


def detect_class(identity, bus=None):
    """Device class from smartctl identity, refined by the OS bus when known."""
    dtype = (identity.get("device_type") or "").lower()
    proto = (identity.get("protocol") or "").upper()
    rot = identity.get("rotation_rate")
    usb_bridge = bool(USB_BRIDGE_TYPES.match(dtype)) or (bus == "usb")
    if proto == "NVME" or NVME_BRIDGE_TYPES.match(dtype):
        return "external-ssd" if usb_bridge else "nvme"
    if proto == "ATA" or dtype.startswith("sat") or USB_BRIDGE_TYPES.match(dtype):
        if isinstance(rot, int) and not isinstance(rot, bool):
            inner = "hdd" if rot > 0 else "ssd"
            if usb_bridge:
                return f"external-{inner}"
            return "hdd" if rot > 0 else "ssd-sata"
        return None
    return None


def normalise(data, *, exit_code=None, tool_version=None):
    raw = data if isinstance(data, bytes) else str(data).encode("utf-8")
    try:
        return _normalise(raw, exit_code, tool_version)
    except (AttributeError, TypeError, KeyError, IndexError):
        # valid JSON with unexpected shapes (e.g. a number where smartctl writes an object)
        return SmartRecord("malformed", sha256=hashlib.sha256(raw).hexdigest(), raw=raw, exit_code=exit_code,
                           tool_version=tool_version, message="unexpected JSON structure")


def _normalise(raw, exit_code, tool_version):
    digest = hashlib.sha256(raw).hexdigest()
    try:
        doc = json.loads(raw.decode("utf-8-sig"))
    except (ValueError, UnicodeDecodeError):
        return SmartRecord("malformed", sha256=digest, raw=raw, exit_code=exit_code, tool_version=tool_version)
    known = ("json_format_version", "smartctl", "device", "model_name", "serial_number", "user_capacity",
             "smart_status")
    if not isinstance(doc, dict) or not any(k in doc for k in known):
        return SmartRecord("malformed", sha256=digest, raw=raw, doc=doc, exit_code=exit_code,
                           tool_version=tool_version)
    sm = doc.get("smartctl") if isinstance(doc.get("smartctl"), dict) else None
    messages = [m.get("string", "") for m in (sm or {}).get("messages", []) if isinstance(m, dict)]
    if exit_code is None and sm is not None:
        exit_code = sm.get("exit_status")
    if tool_version is None and sm and isinstance(sm.get("version"), list):
        tool_version = ".".join(str(x) for x in sm["version"])
    status = classify_collection(exit_code, messages) if sm is not None else "unknown"
    identity = _identity(doc)
    health = _health(doc)
    flags = exit_flags(exit_code) if sm is not None else frozenset()
    if status == "collection_failed" and isinstance(exit_code, int) and exit_code & 0b111 == 0b100 \
            and health.get("overall_passed") is not None and (health.get("attributes") or
                                                              doc.get("nvme_smart_health_information_log")):
        # bit 2 only ("some SMART or ATA command failed") with SMART data present: usable, flagged
        # [UNVERIFIED that -x sets bit 2 for unsupported optional logs; data presence decides]
        status = "ok"
        flags = flags | {"some_command_failed"}
    if status == "ok" and health.get("overall_passed") is None and "attributes" not in health \
            and doc.get("nvme_smart_health_information_log") is None:
        status = "not_exposed"
    return SmartRecord(
        collection_status=status, flags=flags,
        message=" | ".join(messages) or None, identity=identity, health_fields=health,
        detected_class=detect_class(identity), sha256=digest, raw=raw, doc=doc, exit_code=exit_code,
        tool_version=tool_version)


def has_smart(rec):
    return rec is not None and rec.collection_status == "ok"
