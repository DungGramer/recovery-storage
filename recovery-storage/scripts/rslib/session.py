"""Session (spec Phase 0): goals, risk ceiling, preserve-data, data value, risk tolerance, symptoms.

Every mutation appends an audit event (who, ts, field, old -> new); nothing is overwritten silently.
"""
import re

from . import store as st
from .errors import UsageError

GOALS = ["data-recovery", "device-recovery", "diagnosis-only", "authenticity-check", "health-assessment",
         "forensic-preservation"]
PRESERVE_GOALS = ("data-recovery", "forensic-preservation")
CEILINGS = ["R0", "R1", "R2", "R3"]
PRESERVE = ["yes", "no", "unknown"]
DATA_VALUES = ["irreplaceable", "important", "replaceable", "unknown"]
RISK_TOLERANCES = ["low", "medium", "high"]
DEFAULT_RISK_TOLERANCE = "medium"  # plan R1: keeps the approved default (software path + image-first)
SYMPTOMS = ["mechanical-noise", "burning-smell", "physical-damage", "liquid-damage", "overheating", "not-detected",
            "disconnects-repeatedly", "slow-io", "read-only", "wrong-capacity", "raw-or-unreadable-fs",
            "missing-partition", "deleted-files", "io-errors", "encrypted-locked", "not-spinning"]
TRIED = ["other-port", "other-cable", "other-host", "other-os"]
WHO = ["agent", "operator"]

_UNITS = {"": 1, "B": 1, "KB": 10 ** 3, "MB": 10 ** 6, "GB": 10 ** 9, "TB": 10 ** 12, "PB": 10 ** 15,
          "KIB": 2 ** 10, "MIB": 2 ** 20, "GIB": 2 ** 30, "TIB": 2 ** 40, "PIB": 2 ** 50}


def parse_size(text):
    m = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*([A-Za-z]*)\s*", str(text))
    unit = m.group(2).upper() if m else None
    if not m or unit not in _UNITS:
        raise UsageError(f"invalid size {text!r}: use bytes or a unit like 64GB, 1TB, 64GiB")
    value = round(float(m.group(1)) * _UNITS[unit])
    if value <= 0:
        raise UsageError(f"invalid size {text!r}: capacity must be > 0")
    return int(value)


def effective_data_value(s):
    if s["data_value"] != "unknown":
        return s["data_value"]
    # unknown value of data that must be preserved is treated as irreplaceable (phase 01 A9b)
    return "replaceable" if s["preserve_data"] == "no" else "irreplaceable"


def preserves(s):
    """preserve=unknown behaves as yes."""
    return s["preserve_data"] != "no"


def public(s):
    out = dict(s)
    out["effective_data_value"] = effective_data_value(s)
    return out


def _forced(goals):
    return [g for g in goals if g in PRESERVE_GOALS]


def load(store, sid):
    row = store.one("SELECT data FROM sessions WHERE id = ?", (sid,))
    if row is None:
        raise UsageError(f"unknown session {sid!r}", ["unknown-session"])
    return st.loads(row["data"])


def save(store, s):
    store.execute("UPDATE sessions SET data = ? WHERE id = ?", (st.dumps(s), s["id"]))


def event(store, sid, who, field, old, new, note=None):
    def text(v):
        return v if v is None or isinstance(v, str) else st.dumps(v)

    store.execute("INSERT INTO session_events (session_id, ts, who, field, old, new, note) VALUES (?,?,?,?,?,?,?)",
                  (sid, store.now(), who, field, text(old), text(new), note))


def events(store, sid):
    rows = store.query("SELECT ts, who, field, old, new, note FROM session_events WHERE session_id = ? ORDER BY id",
                       (sid,))
    return rows


# ------------------------------------------------------------------ commands
def cmd_new(ctx, a):
    goals = list(dict.fromkeys(a.goal))
    s = {
        "id": st.new_id("S"), "created_ts": ctx.store.now(), "goals": goals, "ceiling": a.ceiling or "R0",
        "preserve_data": a.preserve_data or "unknown", "preserve_forced": False,
        "data_value": a.data_value or "unknown", "risk_tolerance": a.risk_tolerance or DEFAULT_RISK_TOLERANCE,
        "nominal_bytes": parse_size(a.nominal) if a.nominal else None,
        "symptoms": list(dict.fromkeys(a.symptom or [])), "tried": list(dict.fromkeys(a.tried or [])),
        "device_type": a.device_type, "os": a.os, "notes": [a.note] if a.note else [],
    }
    lines = [f"session {s['id']} created: goals {', '.join(goals)}, ceiling {s['ceiling']}"]
    forced_by = _forced(goals)
    requested = s["preserve_data"]
    if forced_by and requested != "yes":
        s["preserve_data"], s["preserve_forced"] = "yes", True
    ctx.store.execute("INSERT INTO sessions (id, created_ts, data) VALUES (?,?,?)",
                      (s["id"], s["created_ts"], st.dumps(s)))
    event(ctx.store, s["id"], ctx.who, "created", None, s["id"])
    if s["preserve_forced"]:
        why = f"forced by goal {', '.join(forced_by)}: source data must be secured before any write"
        event(ctx.store, s["id"], ctx.who, "preserve_data", requested, "yes", why)
        lines.append(f"preserve-data {requested} -> yes ({why})")
    lines.append(f"preserve-data {s['preserve_data']}, data value {s['data_value']} "
                 f"(effective {effective_data_value(s)}), risk tolerance {s['risk_tolerance']}")
    return ctx.reply({"session": public(s)}, "\n".join(lines))


def _show_text(s, evs):
    lines = [
        f"session {s['id']} (created {s['created_ts']})",
        f"  goals: {', '.join(s['goals'])}",
        f"  ceiling: {s['ceiling']}",
        f"  preserve-data: {s['preserve_data']}" + (" (forced by goal)" if s["preserve_forced"] else ""),
        f"  data value: {s['data_value']} (effective: {effective_data_value(s)})",
        f"  risk tolerance: {s['risk_tolerance']}",
        f"  nominal bytes: {s['nominal_bytes'] if s['nominal_bytes'] is not None else 'not given'}",
        f"  device type (declared): {s['device_type'] or 'not given'}",
        f"  symptoms: {', '.join(s['symptoms']) or 'none'}",
        f"  isolation tried: {', '.join(s['tried']) or 'none'}",
        "  events:",
    ]
    for e in evs:
        lines.append(f"    {e['ts']} {e['who']} {e['field']} {e['old'] if e['old'] is not None else '-'} -> "
                     f"{e['new'] if e['new'] is not None else '-'}" + (f" ({e['note']})" if e.get("note") else ""))
    return "\n".join(lines)


def cmd_show(ctx, a):
    s = load(ctx.store, a.session)
    evs = events(ctx.store, a.session)
    return ctx.reply({"session": public(s), "events": evs}, _show_text(s, evs))


def cmd_list(ctx, a):
    rows = ctx.store.query("SELECT data FROM sessions ORDER BY created_ts DESC, rowid DESC")
    sessions = [public(st.loads(r["data"])) for r in rows]
    if not sessions:
        return ctx.reply({"sessions": []}, "no sessions")
    text = "\n".join(f"{s['id']}  {s['created_ts']}  goals={','.join(s['goals'])}  ceiling={s['ceiling']}"
                     for s in sessions)
    return ctx.reply({"sessions": sessions}, text)


def cmd_set(ctx, a):
    s = load(ctx.store, a.session)
    changes = []
    for field, value in (("ceiling", a.ceiling), ("data_value", a.data_value), ("risk_tolerance", a.risk_tolerance)):
        if value is not None and s[field] != value:
            changes.append((field, s[field], value))
            s[field] = value
    if a.goal:
        goals = list(dict.fromkeys(a.goal))
        if goals != s["goals"]:
            changes.append(("goals", s["goals"], goals))
            s["goals"] = goals
            if _forced(goals) and s["preserve_data"] != "yes":
                changes.append(("preserve_data", s["preserve_data"], "yes"))
                s["preserve_data"], s["preserve_forced"] = "yes", True
    save(ctx.store, s)
    lines = []
    for field, old, new in changes:
        event(ctx.store, s["id"], ctx.who, field, old, new)
        fmt = (lambda v: ",".join(v) if isinstance(v, list) else v)
        lines.append(f"{field} {fmt(old)} -> {fmt(new)}")
    return ctx.reply({"session": public(s), "changes": [list(c) for c in changes]},
                     "\n".join(lines) or "no change")


def cmd_note(ctx, a):
    s = load(ctx.store, a.session)
    s.setdefault("notes", []).append(a.text)
    save(ctx.store, s)
    event(ctx.store, s["id"], ctx.who, "note", None, a.text)
    return ctx.reply({"session": public(s)}, "note recorded")
