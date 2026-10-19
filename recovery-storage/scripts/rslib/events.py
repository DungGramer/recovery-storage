"""OS storage events: context evidence only. Only Ntfs 55 carries a semantic tag (verified provider message
"A corruption was discovered in the file system structure on volume"); no other id table exists on purpose."""
import json
import re
from dataclasses import dataclass, field

TAGS = {("ntfs", 55): "fs_corruption"}
LOOKBACK_HOURS = 72  # window before session start; bounded by allowlist.PS_ENV_BOUNDS
MAX_EVENTS = 50
MESSAGE_CHARS = 300


@dataclass
class EventsResult:
    status: str
    items: list = field(default_factory=list)


def _tag(provider, eid):
    return TAGS.get((str(provider or "").lower(), eid))


def parse_windows(text):
    try:
        doc = json.loads(text)
    except (ValueError, TypeError):
        return EventsResult("unavailable(unparseable output)")
    items = []
    events = doc.get("events") or []
    for e in events if isinstance(events, list) else [events]:
        items.append({"provider": e.get("provider"), "id": e.get("id"), "level": e.get("level"),
                      "time": e.get("time"), "message": (e.get("message") or "")[:MESSAGE_CHARS],
                      "tag": _tag(e.get("provider"), e.get("id"))})
    errors = doc.get("errors") or []
    errors = errors if isinstance(errors, list) else [errors]
    if errors:
        detail = "; ".join(f"{x.get('provider')}: {x.get('error')}" for x in errors)
        return EventsResult(f"partial({detail})", items)
    return EventsResult("ok", items)


# kernel lines worth keeping as storage context (the rest of the kernel log is not collected)
STORAGE_LINE = re.compile(r"(?i)(I/O error|blk_update_request|Buffer I/O|medium error|sense key|uas|usb-storage|"
                          r"reset (high|super)-speed|\bsd[a-z]+\b|nvme\d|mmcblk|ata\d|EXT4-fs error|FAT-fs|exfat|ntfs)")
SERIAL_IN_LINE = re.compile(r"(?i)(serial\s*(number)?\s*[:=]\s*)\S+")


def _kernel_item(msg, level, time):
    # USB enumeration lines carry other devices' serials: never keep them (spec §4 rule 10)
    return {"provider": "kernel", "id": None, "level": level, "time": time,
            "message": SERIAL_IN_LINE.sub(r"\1<removed>", msg)[:MESSAGE_CHARS], "tag": None}


def parse_journal(text):
    items = []
    for line in (text or "").splitlines():
        try:
            e = json.loads(line)
        except ValueError:
            continue
        msg = e.get("MESSAGE")
        if isinstance(msg, str) and STORAGE_LINE.search(msg):
            items.append(_kernel_item(msg, e.get("PRIORITY"), e.get("__REALTIME_TIMESTAMP")))
    return EventsResult("ok", items[-MAX_EVENTS:])


def parse_dmesg(text):
    items = [_kernel_item(ln, None, None) for ln in (text or "").splitlines() if ln.strip() and STORAGE_LINE.search(ln)]
    return EventsResult("ok", items[-MAX_EVENTS:])
