"""Final status (spec Phase 5): PASS only with the evidence the device class requires, gathered after the last
closed R2 gate (post-recovery window). A successful format is never evidence (spec §8). Refusal lists every
missing item by name. History is kept; the latest verdict is the effective one.
"""
from . import session as sess
from . import store as st
from .collect import class_conflict, device_row, load_snapshot_record
from .datastate import mapfile_complete
from .delta import delta
from .errors import Refused, UsageError
from .health import verdict as health_verdict
from .ingest import current_parsed

CAPACITY_COVERAGE = 0.9  # f3read verified bytes / device bytes needed for a flash PASS (parameter)
VERIFY_KINDS = ("f3write-f3read", "h2testw", "f3probe", "f3probe-destructive")  # writes = the test (amendment 04)
HDD = ("hdd", "external-hdd")
SSD = ("ssd-sata", "nvme", "external-ssd")
FLASH = ("usb-flash-or-card", "sd")
HDD_COUNTERS = ("attr_5", "attr_187", "attr_197", "attr_198")
SSD_COUNTERS = HDD_COUNTERS + ("media_errors",)


def _pass_window_ts(store, device_id):
    """Like last_write_ts, but a successful verification gate counts from its confirm: its writes are the capacity
    test, so evidence ingested inside it counts (amendment 04 B1-B3). Data-state rules keep last_write_ts."""
    from .actions import CATALOG

    kinds = [k for k, act in CATALOG.items() if act.writes_source]
    marks = ",".join("?" * len(kinds))
    rows = store.query(f"SELECT kind, state, outcome, confirmed_ts, closed_ts FROM gates WHERE device_id = ? AND "
                       f"kind IN ({marks}) AND (state = 'closed' OR (state = 'aborted' AND confirmed_ts IS NOT NULL))",
                       (device_id, *kinds))
    ts = [r["confirmed_ts"] if (r["kind"] in VERIFY_KINDS and r["state"] == "closed" and r["outcome"] == "success"
                                and r["confirmed_ts"]) else r["closed_ts"] for r in rows]
    ts = [t for t in ts if t]
    return max(ts) if ts else None


def _window_start(store, s, device_id):
    """Post-recovery window: after the last write on this device in ANY session (verification gates: their
    confirm), never before this session started."""
    lw = _pass_window_ts(store, device_id)
    if lw and lw > s["created_ts"]:
        return lw, True
    return s["created_ts"], bool(lw)


def _snaps(store, s, device_id):
    rows = store.query("SELECT * FROM snapshots WHERE device_id = ? AND session_id = ? ORDER BY ts, rowid",
                       (device_id, s["id"]))
    return [load_snapshot_record(store, r) for r in rows]


ATA_HOURS_WRAP = 65536  # ATA self-test log stores lifetime hours in 16 bits


def _entry_passed(row):
    """True / False / None (not a verdict). smartctl sets `passed: true` even for "in progress" (0xF) and unknown
    nibbles (ataprint.cpp), so the ATA status nibble decides: 0 pass; 3-8 fail; 1, 2, 9-15 not counted."""
    status = row.get("status") if isinstance(row.get("status"), dict) else {}
    if isinstance(status.get("value"), int) and not isinstance(status.get("value"), bool):
        nibble = status["value"] >> 4
        return True if nibble == 0 else False if 3 <= nibble <= 8 else None
    if isinstance(status.get("passed"), bool):
        return status["passed"]
    s = str(status.get("string") or "").lower()
    return "without error" in s if s else None


def selftest_window(table, latest_poh, since_hours):
    """Pure (amendment 02 E): True iff a passed entry inside the window has no failed entry at or after it.
    Inside: (latest_poh - h) % 65536 <= latest_poh - since_hours; "after" = smaller distance, never raw hours."""
    if not isinstance(latest_poh, int) or not isinstance(since_hours, int) or latest_poh < since_hours:
        return False
    window = latest_poh - since_hours
    inside = []
    for row in table or []:
        if not isinstance(row, dict) or not isinstance(row.get("lifetime_hours"), int):
            continue
        h = row["lifetime_hours"]
        if latest_poh < ATA_HOURS_WRAP and h > latest_poh:
            continue  # cannot be in the future of a counter that never wrapped
        dist = (latest_poh - h) % ATA_HOURS_WRAP
        if dist <= window:
            inside.append((dist, _entry_passed(row)))
    passes = [d for d, ok in inside if ok is True]
    if not passes:
        return False
    newest_pass = min(passes)
    return not any(ok is False and d <= newest_pass for d, ok in inside)


def _selftest_ok(rec, since_hours):
    """A completed-without-error test inside the window and no failed test at or after it.
    ATA logs store lifetime hours in 16 bits: an entry's age is (latest_poh - h) mod 65536 (amendment 02 E)."""
    latest = (rec.health_fields or {}).get("power_on_hours")
    doc = rec.doc if isinstance(getattr(rec, "doc", None), dict) else {}
    table = (((doc.get("ata_smart_self_test_log") or {}).get("standard") or {}).get("table")) or []
    return selftest_window(table if isinstance(table, list) else [], latest, since_hours)


def pass_missing(store, s, device_id):
    """Every missing item for PASS (empty list = PASS allowed)."""
    dev = device_row(store, device_id)
    missing = []
    live = store.query("SELECT id FROM gates WHERE device_id = ? AND state IN ('pending', 'open')", (device_id,))
    if live:
        missing.append("gate-in-progress")
    if store.one("SELECT id FROM gates WHERE device_id = ? AND identity_drift = 1", (device_id,)):
        missing.append("unresolved-identity-drift")
    start, after_gate = _window_start(store, s, device_id)
    obs = store.query("SELECT * FROM observations WHERE device_id = ? AND session_id = ? AND ts > ? AND "
                      "match IN ('exact', 'probable', 'linked') ORDER BY ts", (device_id, s["id"], start))
    bytes_ok = [o for o in obs if st.loads(o["data"]).get("bytes") == dev["fingerprint"].get("bytes")]
    if not any(o["after_replug"] for o in bytes_ok):
        missing.append("replug-observation-missing")
    if len(bytes_ok) < 2:
        missing.append("stable-observations-missing")
    weak = store.one("SELECT 1 FROM observations WHERE device_id = ? AND session_id = ? AND ts > ? AND match = 'weak'",
                     (device_id, s["id"], start))
    if weak and not bytes_ok:
        # card in a reader without an on-media id: re-plugging cannot prove it is the same card
        missing.append("identity-weak")

    cls = dev["detected_class"]
    if not cls or class_conflict(s.get("device_type"), cls):
        missing.append("classify-device-first")
        return missing

    snaps = _snaps(store, s, device_id)
    post = [r for r in snaps if r.snapshot_ts > start]
    pre = [r for r in snaps if r.snapshot_ts <= start]
    evidence = store.query("SELECT * FROM evidence WHERE device_id = ? AND session_id = ? ORDER BY ts",
                           (device_id, s["id"]))
    for e in evidence:
        e["parsed"] = current_parsed(store, e) or {}  # current parser, not the stored copy (amendment 06 F5)
    post_ev = [e for e in evidence if e["ts"] > start]

    if cls in FLASH:
        def capacity_ok(e):
            p = e["parsed"]
            if e["kind"] == "attested":
                return p.get("tool") == "h2testw" and p.get("result") == "pass"
            if e["kind"] == "f3read" and p.get("result") == "pass":
                ok_bytes, total = p.get("data_ok_bytes"), dev["fingerprint"].get("bytes")
                return isinstance(ok_bytes, int) and isinstance(total, int) and ok_bytes >= CAPACITY_COVERAGE * total
            return False
        good = [e for e in post_ev if capacity_ok(e)]
        if not good:
            missing.append("evidence-before-recovery" if any(capacity_ok(e) for e in evidence)
                           else "capacity-verify-missing")
        elif not any(e["kind"] != "f3read" or _f3read_after_replug(store, s, dev, e, evidence, start) for e in good):
            missing.append("f3read-not-after-replug")
        return missing

    latest = post[-1] if post else None
    if latest is None:
        missing.append("post-snapshot-missing")
        return missing
    prev = pre[-1] if pre else (post[0] if len(post) > 1 else None)
    hv = health_verdict(latest, prev)
    if hv.verdict not in ("healthy", "watch"):
        missing.append("post-health-not-ok")
    counters = HDD_COUNTERS if cls in HDD else SSD_COUNTERS
    if prev is None:
        missing.append("delta-missing")
    else:
        d = delta(prev, latest)
        if not d.valid:
            missing.append("delta-invalid")
        elif any(f in d.rising for f in counters):
            missing.append("counters-rising")
    if cls in HDD:
        start_hours = (prev or latest).health_fields.get("power_on_hours")
        if not _selftest_ok(latest, start_hours):
            missing.append("selftest-missing")
    elif cls in SSD:
        cw = latest.health_fields.get("critical_warning")
        if isinstance(cw, int) and cw != 0:
            missing.append("critical-warning-set")

        def read_ok(e):
            p = e["parsed"]
            return (e["kind"] == "ddrescue" and mapfile_complete(p, dev["fingerprint"].get("bytes"))[0]) or \
                (e["kind"] == "f3read" and p.get("result") == "pass" and isinstance(p.get("data_ok_bytes"), int)
                 and isinstance(dev["fingerprint"].get("bytes"), int)
                 and p["data_ok_bytes"] >= CAPACITY_COVERAGE * dev["fingerprint"]["bytes"]) or \
                (e["kind"] == "attested" and p.get("result") == "pass")
        good = [e for e in post_ev if read_ok(e)]
        if not good:
            missing.append("read-verify-missing")
        elif not any(e["kind"] != "f3read" or _f3read_after_replug(store, s, dev, e, evidence, start) for e in good):
            missing.append("f3read-not-after-replug")
    return missing


def _f3read_after_replug(store, s, dev, e, evidence, start):
    """f3read right after f3write reads the host cache (real runs 2026-10-19/20: 158-276 MB/s vs 17 MB/s uncached):
    an `inventory --after-replug` observation must lie between the anchor and the f3read ingest (amendment 07 G1).
    Anchor: last f3write ingest before it, else the confirm of the verification gate open then, else window start."""
    writes = [x["ts"] for x in evidence if x["kind"] == "f3write" and x["ts"] < e["ts"]]
    anchor = max(writes) if writes else None
    if anchor is None:
        marks = ",".join("?" * len(VERIFY_KINDS))
        g = store.one(f"SELECT confirmed_ts FROM gates WHERE device_id = ? AND kind IN ({marks}) AND confirmed_ts IS "
                      "NOT NULL AND confirmed_ts <= ? AND (closed_ts IS NULL OR closed_ts >= ?) "
                      "ORDER BY confirmed_ts DESC LIMIT 1", (dev["id"], *VERIFY_KINDS, e["ts"], e["ts"]))
        anchor = g["confirmed_ts"] if g else start
    rows = store.query("SELECT data FROM observations WHERE device_id = ? AND session_id = ? AND after_replug = 1 AND "
                       "match IN ('exact', 'probable', 'linked') AND ts > ? AND ts < ?",
                       (dev["id"], s["id"], anchor, e["ts"]))
    return any(st.loads(r["data"]).get("bytes") == dev["fingerprint"].get("bytes") for r in rows)


def cmd_set(ctx, a):
    s = sess.load(ctx.store, a.session)
    device_row(ctx.store, a.device)
    if a.status == "PASS":
        missing = pass_missing(ctx.store, s, a.device)
        if missing:
            raise Refused("PASS refused, missing: " + ", ".join(missing), missing)
    elif a.status == "PASS_LIMITED":
        if not a.limitation:
            raise UsageError("PASS_LIMITED needs --limitation <text> (what it may and may not be used for)")
        snaps = _snaps(ctx.store, s, a.device)
        has_ev = ctx.store.one("SELECT id FROM evidence WHERE device_id = ? AND session_id = ?", (a.device, s["id"]))
        if not snaps and not has_ev:
            raise Refused("PASS_LIMITED needs at least one snapshot or ingested evidence", ["no-post-evidence"])
        if snaps:
            prev = snaps[-2] if len(snaps) > 1 else None
            if health_verdict(snaps[-1], prev).verdict == "failing":
                raise Refused("PASS_LIMITED refused: latest health is failing", ["health-failing"])
    elif not a.reason:
        raise UsageError(f"{a.status} needs --reason <text>")
    vid = st.new_id("V")
    ts = ctx.store.now()
    ctx.store.execute("INSERT INTO verdicts (id, ts, session_id, device_id, status, reason, limitation) "
                      "VALUES (?,?,?,?,?,?,?)", (vid, ts, a.session, a.device, a.status, a.reason, a.limitation))
    extra = " - never use for unique or critical data" if a.status == "PASS_LIMITED" else ""
    return ctx.reply({"verdict": {"id": vid, "status": a.status, "ts": ts}},
                     f"verdict {a.status} recorded for {a.device}{extra}")


def history(store, session_id, device_id):
    return store.query("SELECT id, status, ts, reason, limitation FROM verdicts WHERE session_id = ? AND device_id = ? "
                       "ORDER BY ts DESC, rowid DESC", (session_id, device_id))


def cmd_show(ctx, a):
    sess.load(ctx.store, a.session)
    device_row(ctx.store, a.device)
    vs = history(ctx.store, a.session, a.device)
    eff = vs[0]["status"] if vs else None
    text = "\n".join(f"{v['ts']}  {v['status']}" + (f"  reason: {v['reason']}" if v["reason"] else "")
                     + (f"  limitation: {v['limitation']}" if v["limitation"] else "") for v in vs)
    return ctx.reply({"verdicts": vs, "effective": eff}, text or "UNRESOLVED (no verdict recorded)")
