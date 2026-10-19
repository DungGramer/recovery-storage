"""Gate: identity re-check + human confirmation around a risky action (phase 04, amendment 01).

State machine: pending -> open -> closed; pending|open -> aborted; nothing leaves closed/aborted. Every transition
is a conditional UPDATE on the expected state (a concurrent abort cannot be overwritten).
`open` evaluates every check and lists every failing reason. `confirm` asks the operator at an interactive console
for the phrase (the agent cannot), re-resolves the device immediately before the action and prints the only OS path
to use. Locks are partial unique indexes in SQLite (gates_global on lock_slot for R2, gates_device per device).
The skill never runs the action itself; the guard hook (phase 08) lets destructive commands through only while a
gate is `open`.
"""
import hashlib
import sqlite3

from . import session as sess
from . import store as st
from .actions import CATALOG, RISK_ORDER
from .collect import class_conflict, device_row, media_id_changed, observe, pick, resolve, take_snapshot
from .datastate import current as data_state
from .errors import CommandError, NeedsHuman, Refused, UsageError
from .fleet import latest_assessment

LIVE = ("pending", "open")
WEAK_WARNING = "identity weak: same-size media in this reader cannot be told apart"


def _hash(phrase):
    return hashlib.sha256(phrase.strip().encode("utf-8")).hexdigest()


def expected_phrase(fp):
    """Last 4 chars of the normalised serial when trusted, else the exact byte count."""
    if fp.get("serial_trust") == "high" and fp.get("serial_norm"):
        return fp["serial_norm"][-4:]
    return str(fp.get("bytes"))


def _gate(store, gid):
    g = store.one("SELECT * FROM gates WHERE id = ?", (gid,))
    if g is None:
        raise UsageError(f"unknown gate {gid!r}")
    g["data"] = st.loads(g["data"]) or {}
    return g


def _pub(g, **extra):
    out = {"id": g["id"], "state": g["state"], "kind": g["kind"], "risk": g["risk"], "device_id": g["device_id"],
           "session_id": g["session_id"], "outcome": g.get("outcome"), "abort_reason": g.get("abort_reason"),
           "identity_drift": bool(g.get("identity_drift")), "confirmed_by": g.get("confirmed_by"),
           "writes_source": CATALOG[g["kind"]].writes_source if g["kind"] in CATALOG else None}
    out.update(extra)
    return out


def _transition(store, gid, expected, sql_set, params):
    """UPDATE ... WHERE id = ? AND state IN expected; refuse if another process changed the state first."""
    marks = ",".join("?" * len(expected))
    cur = store.execute(f"UPDATE gates SET {sql_set} WHERE id = ? AND state IN ({marks})",
                        tuple(params) + (gid,) + tuple(expected))
    if cur.rowcount != 1:
        g = _gate(store, gid)
        raise Refused(f"gate {gid} changed state concurrently (now {g['state']})", ["gate-state-changed"],
                      {"gate": _pub(g)})


def _live_gates(store, device_id=None, r2=False):
    sql = "SELECT * FROM gates WHERE state IN ('pending', 'open')"
    args = []
    if device_id:
        sql += " AND device_id = ?"
        args.append(device_id)
    if r2:
        sql += " AND lock_slot = 'R2'"
    return store.query(sql, args)


def _before_after(ctx, session_id, device_id, r):
    try:
        rec, snap, _, _, _ = take_snapshot(ctx, session_id, device_id, r, with_events=False)
        return {"observation_id": r.pub["observation_id"], "snapshot_id": snap["id"],
                "collection_status": rec.collection_status}
    except CommandError as e:  # collection failure is recorded, never blocking (D9c)
        return {"observation_id": r.pub["observation_id"], "snapshot_id": None,
                "collection_status": f"error: {e.message}"}


def _preserving_sessions(store, device_id, current):
    """Sessions that touched this device and must keep its data (data-first spans sessions)."""
    ids = {current["id"]}
    for t in ("snapshots", "evidence", "assessments", "data_states", "observations"):
        ids |= {r["session_id"] for r in store.query(f"SELECT DISTINCT session_id FROM {t} WHERE device_id = ?",
                                                     (device_id,)) if r["session_id"]}
    out = []
    for sid in sorted(ids):
        try:
            s = current if sid == current["id"] else sess.load(store, sid)
        except UsageError:
            continue
        if sess.preserves(s) and (sid == current["id"] or store.one(
                "SELECT 1 FROM snapshots WHERE device_id = ? AND session_id = ? UNION "
                "SELECT 1 FROM evidence WHERE device_id = ? AND session_id = ? UNION "
                "SELECT 1 FROM assessments WHERE device_id = ? AND session_id = ?",
                (device_id, sid) * 3)):
            out.append(sid)
    return out


def _secured_anywhere(store, device_id):
    rows = store.query("SELECT session_id, state FROM data_states WHERE device_id = ? ORDER BY ts, id", (device_id,))
    last = {}
    for r in rows:
        last[r["session_id"]] = r["state"]
    return any(v in ("secured", "waived") for v in last.values())


def _resolve_dest(ctx, session_id, dest):
    try:
        return resolve(ctx, session_id, dest), None
    except NeedsHuman:
        return None, "dest-ambiguous"
    except Refused:
        return None, "dest-not-found"


def cmd_open(ctx, a):
    s = sess.load(ctx.store, a.session)
    dev = device_row(ctx.store, a.device)
    reasons, notes = [], []
    action = CATALOG.get(a.kind)
    if action is None:
        reasons.append("unknown-action")
        notes.append("valid kinds: " + ", ".join(CATALOG))
    assessment = latest_assessment(ctx.store, a.device, a.session)
    if assessment is None:
        reasons.append("no-assessment")
        notes.append(f"run `assess {a.session} {a.device}` first")
    dest_r = None
    if action is not None:
        if RISK_ORDER[action.risk] > RISK_ORDER[s["ceiling"]]:
            reasons.append("risk-above-ceiling")
            notes.append(f"{a.kind} is {action.risk}, session ceiling is {s['ceiling']} (session set --ceiling)")
        tri = (assessment or {}).get("data", {}).get("triage", {}).get("class")
        if tri == "STOP_UNSAFE" and action.risk in ("R1", "R2"):
            reasons.append("stop-unsafe")
            notes.append("triage STOP_UNSAFE: only hardware-lab (R3) is allowed")
        if action.writes_source and "forensic-preservation" in s["goals"]:
            reasons.append("forensic-source-write")
            notes.append("goal forensic-preservation never writes the source (change goals to proceed)")
        if action.writes_source:
            keepers = _preserving_sessions(ctx.store, a.device, s)
            if keepers and not _secured_anywhere(ctx.store, a.device) and \
                    data_state(ctx.store, a.session, a.device) not in ("secured", "waived"):
                reasons.append("data-not-secured")
                notes.append("data must be preserved (sessions " + ", ".join(keepers) + "): secure it first "
                             "(session data-state ... secured --evidence <full mapfile>) or have the operator waive it")
        cls = dev["detected_class"]
        if not action.allows(cls) or (class_conflict(s.get("device_type"), cls) and action.classes != "all"):
            reasons.append("class-not-allowed")
            notes.append(f"{a.kind} is not allowed for class {cls or 'unknown'}")
        given = {"--dest-device": a.dest_device, "--controller-id": a.controller_id, "--tool-source": a.tool_source}
        missing = [f for f in action.requires if not given.get(f)]
        if missing:
            reasons.append("missing-requirement")
            notes.append("missing " + ", ".join(missing))
        if a.dest_device:
            if a.dest_device == a.device:
                reasons.append("dest-is-source")
                notes.append("--dest-device must be another device")
            elif ctx.store.one("SELECT id FROM devices WHERE id = ?", (a.dest_device,)) is None:
                reasons.append("missing-requirement")
                notes.append(f"unknown --dest-device {a.dest_device}")
    busy = _live_gates(ctx.store, device_id=a.device)
    if busy:
        reasons.append("device-busy")
        notes.append(f"device has a live gate {busy[0]['id']} ({busy[0]['state']})")
    if action is not None and action.risk == "R2":
        held = _live_gates(ctx.store, r2=True)
        if held:
            reasons.append("global-lock-held")
            notes.append(f"R2 lock held by gate {held[0]['id']} (device {held[0]['device_id']}, session "
                         f"{held[0]['session_id']}): close or abort it first")
    resolved, candidates = None, []
    try:
        resolved = resolve(ctx, a.session, a.device)
    except NeedsHuman as e:
        reasons.append("ambiguous")
        candidates = e.data.get("candidates", [])
        notes.append(e.message)
    except Refused as e:
        reasons += [r for r in e.reasons if r not in reasons]
        notes.append(e.message)
    if resolved is not None:
        o = resolved.pub
        if o.get("is_boot") or o.get("is_system"):
            reasons.append("boot-or-system-disk")
            notes.append(f"{resolved.os_path} is the boot/system disk")
    if a.dest_device and a.dest_device != a.device and "missing-requirement" not in reasons:
        dest_r, why = _resolve_dest(ctx, a.session, a.dest_device)
        if why:
            reasons.append(why)
            notes.append(f"destination {a.dest_device}: {why}")
    reasons = list(dict.fromkeys(reasons))
    if reasons:
        msg = "gate refused: " + "; ".join(notes)
        if reasons == ["ambiguous"]:
            raise NeedsHuman(msg, reasons, {"candidates": candidates})
        raise Refused(msg, reasons, {"candidates": candidates} if candidates else {})

    fp = dev["fingerprint"]
    phrase = expected_phrase(fp)
    gid = st.new_id("G")
    gate_data = {"dest_device": a.dest_device, "controller_id": a.controller_id, "tool_source": a.tool_source,
                 "identity_level": resolved.level, "os_path_at_open": resolved.os_path,
                 "dest_path_at_open": dest_r.os_path if dest_r else None}
    try:
        ctx.store.execute(
            "INSERT INTO gates (id, ts, session_id, device_id, kind, risk, state, lock_slot, phrase_hash, data, "
            "opened_ts) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (gid, ctx.store.now(), a.session, a.device, a.kind, action.risk, "pending",
             "R2" if action.risk == "R2" else None, _hash(phrase), st.dumps(gate_data), ctx.store.now()))
    except sqlite3.IntegrityError as e:
        ctx.store.con.rollback()
        reason = "global-lock-held" if "lock_slot" in str(e) or "gates_global" in str(e) else "device-busy"
        raise Refused(f"gate refused: another live gate won the race ({e})", [reason])
    before = _before_after(ctx, a.session, a.device, resolved)
    ctx.store.execute("UPDATE gates SET before_json = ? WHERE id = ?", (st.dumps(before), gid))
    tri = (assessment or {}).get("data", {}).get("triage", {})
    usb = resolved.pub.get("usb") or {}
    conf = {"model": fp.get("model"), "serial": _serial(fp), "bytes": fp.get("bytes"),
            "bus": fp.get("bus"), "vid": usb.get("vid"), "pid": usb.get("pid"), "os_paths": [resolved.os_path],
            "kind": a.kind, "risk": action.risk, "writes_source": action.writes_source,
            "stop_criteria": action.stop_criteria, "constraints": tri.get("constraints") or [], "phrase": phrase,
            "identity_level": resolved.level, "dest_path": dest_r.os_path if dest_r else None}
    b = fp.get("bytes")
    lines = ["CONFIRM THE TARGET DEVICE BEFORE ANY ACTION",
             f"  model:     {conf['model']}",
             f"  serial:    {conf['serial'] or '(none / untrusted)'}",
             f"  size:      {b} bytes" + (f" ({b / 1e9:.2f} GB, {b / 2 ** 30:.2f} GiB)" if isinstance(b, int) else ""),
             f"  bus:       {conf['bus']}" + (f"  VID:PID {conf['vid']}:{conf['pid']}" if conf["vid"] else ""),
             f"  OS path:   {resolved.os_path} (valid now; confirm re-checks it)",
             f"  action:    {a.kind} ({action.risk}, writes source: {action.writes_source})",
             f"  stop criteria: {action.stop_criteria}",
             f"  constraints: {', '.join(conf['constraints']) or 'none'}"]
    if dest_r:
        lines.append(f"  destination: {a.dest_device} at {dest_r.os_path}")
    if resolved.level == "weak":
        lines.append(f"  WARNING: {WEAK_WARNING}; make sure only this card is in the reader")
    if resolved.level == "probable":
        lines.append("  NOTE: identity rests on the on-media id (MBR signature / GPT guid); keep lookalike devices "
                     "unplugged")
    lines += [f"gate {gid} pending. The OPERATOR confirms in their own terminal and types the phrase {phrase}:",
              f"  rs.py gate confirm {gid}"]
    return ctx.reply({"gate": _pub(_gate(ctx.store, gid)), "confirmation": conf, "before": before}, "\n".join(lines))


def _serial(fp):
    """Full serial for the human block (reports redact it on request)."""
    return fp.get("serial_norm") if fp.get("serial_trust") in ("high", "low") else None


def cmd_confirm(ctx, a):
    g = _gate(ctx.store, a.gate)
    if g["state"] != "pending":
        raise Refused(f"gate {a.gate} is {g['state']}, only a pending gate can be confirmed", ["gate-not-pending"],
                      {"gate": _pub(g)})
    fp = device_row(ctx.store, g["device_id"])["fingerprint"]
    prompt = (f"Gate {g['id']}: {g['kind']} ({g['risk']}) on {fp.get('model')}, {fp.get('bytes')} bytes, serial "
              f"{_serial(fp) or 'none'}.\nType the confirmation phrase shown by gate open: ")
    answer = ctx.ask_operator(prompt, ["gate", "confirm", g["id"]])
    if _hash(answer) != g["phrase_hash"]:
        raise Refused("wrong confirmation phrase; the gate stays pending", ["wrong-phrase"], {"gate": _pub(g)})
    data = g["data"]
    try:
        r = resolve(ctx, g["session_id"], g["device_id"])
        if data.get("dest_device"):
            dest = resolve(ctx, g["session_id"], data["dest_device"])
            data["dest_path_at_confirm"] = dest.os_path
    except (Refused, NeedsHuman) as e:
        _transition(ctx.store, g["id"], ("pending",), "state = 'aborted', abort_reason = ?, closed_ts = ?",
                    ("device-changed", ctx.store.now()))
        g = _gate(ctx.store, g["id"])
        raise Refused(f"device changed since the gate was opened ({e.message}); gate aborted, open a new one",
                      ["device-changed"], {"gate": _pub(g)})
    data["os_path_at_confirm"] = r.os_path
    _transition(ctx.store, g["id"], ("pending",), "state = 'open', confirmed_ts = ?, confirmed_by = ?, data = ?",
                (ctx.store.now(), "operator", st.dumps(data)))
    g = _gate(ctx.store, g["id"])
    dest = f"; destination {data['dest_path_at_confirm']}" if data.get("dest_path_at_confirm") else ""
    text = (f"gate {g['id']} OPEN for {g['kind']} on {r.os_path}{dest}\n"
            f"Run the action now against {r.os_path} only; then `rs.py gate close {g['id']} --outcome ...`")
    return ctx.reply({"gate": _pub(g), "os_path": r.os_path, "dest_path": data.get("dest_path_at_confirm")}, text)


def cmd_close(ctx, a):
    g = _gate(ctx.store, a.gate)
    if g["state"] != "open":
        raise Refused(f"gate {a.gate} is {g['state']}, only an open gate can be closed", ["gate-not-open"],
                      {"gate": _pub(g)})
    warnings = []
    drift = False
    after = {"observation_id": None, "snapshot_id": None, "collection_status": None}
    writes = bool(CATALOG.get(g["kind"]) and CATALOG[g["kind"]].writes_source)
    try:
        rows = observe(ctx, g["session_id"])
        try:
            r = pick(ctx, rows, g["device_id"])
        except (Refused, NeedsHuman) as e:
            r = media_id_changed(ctx, rows, g["device_id"]) if writes else None
            if r is None:
                raise
            warnings.append("on-media id changed by the action (MBR signature / GPT guid): device fingerprint "
                            "updated; same hardware confirmed by model, bytes and USB/serial ids")
        after = _before_after(ctx, g["session_id"], g["device_id"], r)
    except (Refused, NeedsHuman) as e:
        drift = True
        warnings.append(f"identity drift: the device at close is not the one confirmed ({e.message}); "
                        "a PASS verdict is refused until this is resolved")
    except CommandError as e:  # environment failure: the gate is still closed (never left open)
        drift = True
        after["collection_status"] = f"error: {e.message}"
        warnings.append(f"after-state not recorded ({e.message}); identity unverified, treated as drift")
    data = g["data"]
    data.update({"note": a.note, "evidence": a.evidence or [], "warnings": warnings})
    _transition(ctx.store, g["id"], ("open",), "state = 'closed', outcome = ?, identity_drift = ?, after_json = ?, "
                "closed_ts = ?, data = ?", (a.outcome, int(drift), st.dumps(after), ctx.store.now(), st.dumps(data)))
    g = _gate(ctx.store, g["id"])
    text = f"gate {g['id']} closed ({a.outcome})" + ("".join("\nWARNING: " + w for w in warnings))
    return ctx.reply({"gate": _pub(g), "after": after, "warnings": warnings,
                      "message": " ".join(warnings)}, text)


def cmd_abort(ctx, a):
    g = _gate(ctx.store, a.gate)
    if g["state"] not in LIVE:
        raise Refused(f"gate {a.gate} is {g['state']}; only pending/open gates can be aborted", ["gate-not-live"],
                      {"gate": _pub(g)})
    _transition(ctx.store, g["id"], LIVE, "state = 'aborted', abort_reason = ?, closed_ts = ?",
                (a.reason, ctx.store.now()))
    g = _gate(ctx.store, g["id"])
    return ctx.reply({"gate": _pub(g)}, f"gate {g['id']} aborted: {a.reason}")


def cmd_list(ctx, a):
    rows = ctx.store.query("SELECT * FROM gates ORDER BY ts, rowid")
    gates = [_pub(dict(r, data=st.loads(r["data"]))) for r in rows]
    text = "\n".join(f"{g['id']}  {g['state']}  {g['kind']} ({g['risk']})  device {g['device_id']}  "
                     f"session {g['session_id']}" for g in gates) or "no gates"
    return ctx.reply({"gates": gates}, text)
