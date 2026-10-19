"""GĐ3 over existing rows: device list (+ deterministic grouping), device show (history), compare (deltas).

Grouping is a deterministic key (latest triage class / primary hypothesis category / latest verdict), not clustering.
"""
from . import store as st
from .collect import device_row, load_snapshot_record
from .errors import UsageError

CONF_RANK = {"high": 0, "medium": 1, "low": 2}


def latest_assessment(store, device_id, session_id=None):
    sql = "SELECT * FROM assessments WHERE device_id = ?" + (" AND session_id = ?" if session_id else "") + \
          " ORDER BY ts DESC, rowid DESC LIMIT 1"
    r = store.one(sql, (device_id, session_id) if session_id else (device_id,))
    if r:
        r["data"] = st.loads(r["data"])
    return r


def medium_scoped(store, v):
    """Verdict recorded while the latest observation had no medium or a weak match: it judged the card inside a
    reader, not the reader device (amendment 05 R4); fleet views skip it."""
    o = store.one("SELECT match, data FROM observations WHERE device_id = ? AND session_id = ? AND ts <= ? "
                  "ORDER BY ts DESC, rowid DESC LIMIT 1", (v["device_id"], v["session_id"], v["ts"]))
    return bool(o) and (o["match"] == "weak" or bool((st.loads(o["data"]) or {}).get("no_media")))


def latest_verdict(store, device_id, session_id=None):
    if session_id:
        return store.one("SELECT * FROM verdicts WHERE device_id = ? AND session_id = ? ORDER BY ts DESC, rowid DESC "
                         "LIMIT 1", (device_id, session_id))
    for v in store.query("SELECT * FROM verdicts WHERE device_id = ? ORDER BY ts DESC, rowid DESC", (device_id,)):
        if not medium_scoped(store, v):
            return v
    return None


def primary_category(assessment):
    hyps = (assessment or {}).get("data", {}).get("hypotheses") or []
    if not hyps:
        return None
    return sorted(hyps, key=lambda h: (CONF_RANK.get(h.get("confidence"), 9), h.get("category")))[0]["category"]


def _last_seen(store, device_id):
    vals = [r["ts"] for r in (store.one("SELECT MAX(ts) AS ts FROM observations WHERE device_id = ?", (device_id,)),
                              store.one("SELECT MAX(ts) AS ts FROM snapshots WHERE device_id = ?", (device_id,)))
            if r and r["ts"]]
    return max(vals) if vals else None


def device_summary(store, row):
    fp = st.loads(row["fingerprint"]) if isinstance(row["fingerprint"], str) else row["fingerprint"]
    a = latest_assessment(store, row["id"])
    v = latest_verdict(store, row["id"])
    return {
        "device_id": row["id"], "model": fp.get("model"), "bytes": fp.get("bytes"), "class": row["detected_class"],
        "triage": a["data"]["triage"]["class"] if a else None, "health": a["data"]["health"]["verdict"] if a else None,
        "category": primary_category(a), "verdict": v["status"] if v else None, "last_seen": _last_seen(store, row["id"]),
    }


def cmd_device_list(ctx, a):
    rows = ctx.store.query("SELECT * FROM devices ORDER BY id")
    devices = [device_summary(ctx.store, r) for r in rows]
    data = {"devices": devices}
    lines = [f"{d['device_id']}  {d['model']}  {d['bytes']}  class={d['class'] or '-'}  triage={d['triage'] or '-'}  "
             f"health={d['health'] or '-'}  verdict={d['verdict'] or '-'}  last_seen={d['last_seen'] or '-'}"
             for d in devices]
    if a.group_by:
        groups = {}
        for d in devices:
            if d["triage"] is None:
                key = "unassessed"
            elif a.group_by == "triage":
                key = d["triage"]
            elif a.group_by == "category":
                key = d["category"] or "no-hypothesis"
            else:
                key = d["verdict"] or "no-verdict"
            groups.setdefault(key, []).append(d["device_id"])
        data["groups"] = [{"key": k, "device_ids": sorted(v)} for k, v in sorted(groups.items())]
        lines = []
        for g in data["groups"]:
            lines.append(f"[{g['key']}]")
            lines += [f"  {i}" for i in g["device_ids"]]
    return ctx.reply(data, "\n".join(lines) or "no devices")


def cmd_device_show(ctx, a):
    row = device_row(ctx.store, a.device)
    q = ctx.store.query
    hist = []
    for r in q("SELECT id, ts, session_id, match, os_path FROM observations WHERE device_id = ?", (a.device,)):
        hist.append({"ts": r["ts"], "session_id": r["session_id"], "type": "observation", "id": r["id"],
                     "detail": f"{r['match']} at {r['os_path']}"})
    for r in q("SELECT id, ts, session_id, source, collection_status FROM snapshots WHERE device_id = ?", (a.device,)):
        hist.append({"ts": r["ts"], "session_id": r["session_id"], "type": "snapshot", "id": r["id"],
                     "detail": f"{r['source']} {r['collection_status']}"})
    for r in q("SELECT id, ts, session_id, data FROM assessments WHERE device_id = ?", (a.device,)):
        d = st.loads(r["data"])
        hist.append({"ts": r["ts"], "session_id": r["session_id"], "type": "assessment", "id": r["id"],
                     "detail": f"{d['triage']['class']} / health {d['health']['verdict']}"})
    for r in q("SELECT id, ts, session_id, kind, level FROM evidence WHERE device_id = ?", (a.device,)):
        hist.append({"ts": r["ts"], "session_id": r["session_id"], "type": "evidence", "id": r["id"],
                     "detail": f"{r['kind']} ({r['level']})"})
    for r in q("SELECT id, ts, session_id, kind, state, outcome FROM gates WHERE device_id = ?", (a.device,)):
        hist.append({"ts": r["ts"], "session_id": r["session_id"], "type": "gate", "id": r["id"],
                     "detail": f"{r['kind']} {r['state']}" + (f" {r['outcome']}" if r["outcome"] else "")})
    for r in q("SELECT id, ts, session_id, state FROM data_states WHERE device_id = ?", (a.device,)):
        hist.append({"ts": r["ts"], "session_id": r["session_id"], "type": "data-state", "id": str(r["id"]),
                     "detail": r["state"]})
    for r in q("SELECT id, ts, session_id, status FROM verdicts WHERE device_id = ?", (a.device,)):
        hist.append({"ts": r["ts"], "session_id": r["session_id"], "type": "verdict", "id": r["id"],
                     "detail": r["status"]})
    hist.sort(key=lambda h: (h["ts"], h["type"], h["id"]))
    summary = device_summary(ctx.store, ctx.store.one("SELECT * FROM devices WHERE id = ?", (a.device,)))
    device = dict(summary, fingerprint=row["fingerprint"], created_ts=row["created_ts"])
    text = "\n".join([f"device {a.device}: {summary['model']} {summary['bytes']} bytes class={summary['class']}"] +
                     [f"  {h['ts']}  {h['session_id'] or '-'}  {h['type']}  {h['id']}  {h['detail']}" for h in hist])
    return ctx.reply({"device": device, "history": hist}, text)


def _snapshot(store, snap_id):
    r = store.one("SELECT * FROM snapshots WHERE id = ?", (snap_id,))
    if r is None:
        raise UsageError(f"unknown snapshot {snap_id!r}")
    return load_snapshot_record(store, r)


def cmd_compare(ctx, a):
    from .delta import delta

    if a.device:
        rows = ctx.store.query("SELECT * FROM snapshots WHERE device_id = ? ORDER BY ts DESC, rowid DESC LIMIT 2",
                               (a.device,))
        if len(rows) < 2:
            raise UsageError(f"device {a.device} has fewer than two snapshots")
        older, newer = (load_snapshot_record(ctx.store, r) for r in reversed(rows))
    elif len(a.snapshots) == 2:
        older, newer = (_snapshot(ctx.store, s) for s in a.snapshots)
    else:
        raise UsageError("compare needs two snapshot ids or --device <id>")
    r = delta(older, newer)
    head = f"compare {older.snapshot_id} -> {newer.snapshot_id}"
    if not r.valid:
        return ctx.reply({"valid": False, "reason": r.reason, "fields": {}, "rising": []},
                         f"{head}\nINVALID COMPARISON: {r.reason}")

    def fmt(v):
        return v if v == "n/a" else f"{v:+d}"

    lines = [head] + [f"  {k}: {fmt(v)}" for k, v in r.fields.items()]
    if r.rising:
        lines.append("  rising: " + ", ".join(r.rising))
    return ctx.reply({"valid": True, "reason": r.reason, "fields": r.fields, "rising": r.rising}, "\n".join(lines))
