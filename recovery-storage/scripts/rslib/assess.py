"""`assess <session> <device>`: health + triage + constraints + hypotheses from stored evidence (pure rules).

Deterministic: the same inputs (snapshots, evidence, session state, latest inventory, rules version) return
the stored assessment unchanged instead of a new row.
"""
import hashlib

from . import session as sess
from . import store as st
from .collect import device_row, load_snapshot_record
from .delta import delta
from .health import NEXT_TESTS, RULE_BY_OUTCOME, HealthVerdict, verdict
from .ingest import evidence_rows
from .datastate import last_write_ts
from .events import attributable
from .triage import CONF_RANK, Inputs, classify, constraints, evidence_text, hypotheses
from .wear import assess as wear_assess, host_writes_bytes

RULES_VERSION = "2026.10.20-8"  # -2..-8: amendments 03-09 (see docs/project-changelog.md)


def _snapshots(store, device_id, session_id=None):
    sql = "SELECT * FROM snapshots WHERE device_id = ?" + (" AND session_id = ?" if session_id else "") + \
          " ORDER BY ts, rowid"
    return store.query(sql, (device_id, session_id) if session_id else (device_id,))


def _latest_observation(store, session_id, device_id):
    for sql, args in (("SELECT * FROM observations WHERE device_id = ? AND session_id = ? ORDER BY ts DESC, rowid DESC "
                       "LIMIT 1", (device_id, session_id)),
                      ("SELECT * FROM observations WHERE device_id = ? ORDER BY ts DESC, rowid DESC LIMIT 1",
                       (device_id,))):
        r = store.one(sql, args)
        if r:
            return r
    return None


def _absent(store, session_id, device_id):
    """Seen by an inventory of this session earlier, but missing from the latest one."""
    runs = store.query("SELECT * FROM inventory_runs WHERE session_id = ? ORDER BY ts, rowid", (session_id,))
    if not runs:
        return False
    seen_before = any(device_id in st.loads(r["device_ids"]) for r in runs)
    return seen_before and device_id not in st.loads(runs[-1]["device_ids"])


def gather(store, session_id, device_id):
    s = sess.load(store, session_id)
    device_row(store, device_id)
    rows = _snapshots(store, device_id, session_id)
    rec = load_snapshot_record(store, rows[-1]) if rows else None
    prev = None
    if rec is not None:
        older = [r for r in _snapshots(store, device_id) if (r["ts"], r["id"]) < (rows[-1]["ts"], rows[-1]["id"])
                 and r["collection_status"] == "ok"]
        prev = load_snapshot_record(store, older[-1]) if older else None
    health = verdict(rec, prev) if rec is not None else HealthVerdict(
        "unknown", "low", [], ["snapshot"], "no snapshot", "run collect for this device (R0) to read identity and "
        "SMART", RULE_BY_OUTCOME["unknown"].id)
    ok_recs = [load_snapshot_record(store, r) for r in rows if r["collection_status"] == "ok"]
    session_deltas = [delta(a, b) for a, b in zip(ok_recs, ok_recs[1:])]
    obs_row = _latest_observation(store, session_id, device_id)
    obs = st.loads(obs_row["data"]) if obs_row else None
    evidence = evidence_rows(store, session_id, device_id)
    events = []
    if rec is not None:
        events = ((getattr(rec, "extra", {}) or {}).get("events") or {}).get("items") or []
        events = attributable(store, device_id, events)  # drive letters are reused across media (amendment 09)
    inp = Inputs(s, rec, obs, health, session_deltas, _absent(store, session_id, device_id), evidence, events,
                 obs_row is not None)
    lw = last_write_ts(store, device_id)
    written = bool(lw and lw > s["created_ts"])  # source written since this session started (amendment 05 R3)
    # an assess after a verdict is a new assessment, shown as current by the report (amendment 05 R3)
    v = store.one("SELECT id FROM verdicts WHERE session_id = ? AND device_id = ? ORDER BY ts DESC, rowid DESC LIMIT 1",
                  (session_id, device_id))
    runs = store.query("SELECT id FROM inventory_runs WHERE session_id = ? ORDER BY ts, rowid", (session_id,))
    key_src = st.dumps({"rules": RULES_VERSION, "snapshots": [r["id"] for r in rows],
                        "prev": getattr(prev, "snapshot_id", None), "evidence": [e["id"] for e in evidence],
                        "session": {k: v for k, v in s.items() if k != "notes"},
                        "observation": obs_row["id"] if obs_row else None,
                        "run": runs[-1]["id"] if runs else None, "written": written,
                        "verdict": v["id"] if v else None})
    inp.written_in_session = written
    return inp, rows, evidence, hashlib.sha256(key_src.encode("utf-8")).hexdigest()


def compute(inp, rows, evidence):
    tri = classify(inp)
    tri["constraints"] = constraints(inp, tri["class"])
    hyps = hypotheses(inp, tri)
    if getattr(inp, "written_in_session", False):
        # operator symptom alone predates the write: it no longer supports the cause (amendment 05 R3)
        for x in hyps:
            if x["evidence"] and all(e["path"].startswith("session.") for e in x["evidence"]):
                x["confidence"] = "low"
        hyps.sort(key=lambda x: (CONF_RANK[x["confidence"]], x["category"]))
    rec = inp.rec
    return {
        "rules_version": RULES_VERSION,
        "inputs": {"snapshot_ids": [r["id"] for r in rows], "evidence_ids": [e["id"] for e in evidence]},
        "health": inp.health.to_dict(),
        "triage": tri,
        "hypotheses": hyps,
        "wear": wear_assess(rec) if rec is not None else None,
        "host_writes_bytes": host_writes_bytes(rec) if rec is not None else None,
    }


def _text(a):
    t, h = a["triage"], a["health"]
    lines = [f"assessment {a['id']} (rules {a['rules_version']})",
             f"health: {h['verdict']} (confidence {h['confidence']}, rule {h['rule_id']})"
             + (f" - {h['reason']}" if h["reason"] else ""),
             f"triage: {t['class']} (rule {t['rule_id']}" + (f", branch {t['branch']}" if t["branch"] else "") + ")",
             f"constraints: {', '.join(t['constraints']) or 'none'}",
             f"next test: {t['next_test']}"]
    if h["missing"]:
        lines.append(f"missing: {', '.join(h['missing'])}")
    for x in a["hypotheses"]:
        lines.append(f"hypothesis {x['category']} ({x['confidence']}): evidence "
                     + "; ".join(evidence_text(e) for e in x["evidence"]))
        lines.append(f"  alternative: {x['alternative']}")
        lines.append(f"  next test: {x['next_test']}")
    return "\n".join(lines)


def cmd_assess(ctx, a):
    inp, rows, evidence, key = gather(ctx.store, a.session, a.device)
    existing = ctx.store.one("SELECT * FROM assessments WHERE session_id = ? AND device_id = ? AND inputs_key = ? "
                             "AND rules_version = ? ORDER BY ts DESC, rowid DESC LIMIT 1",
                             (a.session, a.device, key, RULES_VERSION))
    if existing:
        data = st.loads(existing["data"])
    else:
        data = compute(inp, rows, evidence)
        data["id"] = st.new_id("A")
        ctx.store.execute("INSERT INTO assessments (id, ts, session_id, device_id, rules_version, inputs_key, data) "
                          "VALUES (?,?,?,?,?,?,?)", (data["id"], ctx.store.now(), a.session, a.device, RULES_VERSION,
                                                     key, st.dumps(data)))
        data = st.loads(st.dumps(data))  # same canonical form as a stored re-read (byte-identical output)
    return ctx.reply({"assessment": data}, _text(data))


__all__ = ["cmd_assess", "gather", "compute", "RULES_VERSION", "NEXT_TESTS"]
