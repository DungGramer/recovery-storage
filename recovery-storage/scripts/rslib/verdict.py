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
from .health import selftest_entries, verdict as health_verdict

CAPACITY_COVERAGE = 0.9  # f3read verified bytes / device bytes needed for a flash PASS (parameter)
HDD = ("hdd", "external-hdd")
SSD = ("ssd-sata", "nvme", "external-ssd")
FLASH = ("usb-flash-or-card", "sd")
HDD_COUNTERS = ("attr_5", "attr_187", "attr_197", "attr_198")
SSD_COUNTERS = HDD_COUNTERS + ("media_errors",)


def _window_start(store, s, device_id):
    """Post-recovery window: after the last closed R2 gate on this device in ANY session, never before this
    session started."""
    r = store.one("SELECT closed_ts FROM gates WHERE device_id = ? AND state = 'closed' AND risk = 'R2' "
                  "ORDER BY closed_ts DESC LIMIT 1", (device_id,))
    if r and r["closed_ts"] > s["created_ts"]:
        return r["closed_ts"], True
    return s["created_ts"], bool(r)


def _snaps(store, s, device_id):
    rows = store.query("SELECT * FROM snapshots WHERE device_id = ? AND session_id = ? ORDER BY ts, rowid",
                       (device_id, s["id"]))
    return [load_snapshot_record(store, r) for r in rows]


ATA_HOURS_WRAP = 65536  # ATA self-test log stores lifetime hours in 16 bits


def _selftest_ok(rec, since_hours):
    """A completed-without-error test at or after `since_hours`, and no failed test after it."""
    if since_hours is None:
        return False
    entries = [(path, st_, h, failed) for path, st_, h, failed in selftest_entries(rec) if isinstance(h, int)]

    def after(h):
        if h >= since_hours:
            return True
        # 16-bit wrap: compare within the same 65536-hour cycle
        return since_hours >= ATA_HOURS_WRAP and h < ATA_HOURS_WRAP and h >= since_hours % ATA_HOURS_WRAP

    good = [h for _, s_, h, failed in entries if not failed and "without error" in s_.lower() and after(h)]
    if not good:
        return False
    best = max(good)
    return not any(failed and h >= best for _, _, h, failed in entries)


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
        e["parsed"] = (st.loads(e["data"]) or {}).get("parsed") or {}
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
        if not any(capacity_ok(e) for e in post_ev):
            missing.append("evidence-before-recovery" if any(capacity_ok(e) for e in evidence)
                           else "capacity-verify-missing")
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
                (e["kind"] == "f3read" and p.get("result") == "pass") or \
                (e["kind"] == "attested" and p.get("result") == "pass")
        if not any(read_ok(e) for e in post_ev):
            missing.append("read-verify-missing")
    return missing


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
