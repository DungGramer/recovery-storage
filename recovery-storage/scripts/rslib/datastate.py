"""Data-first as a state with evidence (phase 04, amendment 01).

secured needs a ddrescue mapfile of THIS device that covers the whole device (start 0, contiguous, ends at the
device byte count, finished, nothing bad or unfinished), or the operator's attestation with a reason; waived needs a
reason; not-needed only when the session does not preserve data. Attestations, waivers and not-needed are typed by
the operator at an interactive console (the agent cannot give them).
"""
from . import session as sess
from . import store as st
from .collect import device_row
from .errors import Refused, UsageError

STATES = ("none", "secured", "waived", "not-needed")


def last_write_ts(store, device_id):
    """Latest moment the source may have been written (amendment 02): close of a writes-source gate, or abort of
    one that had been confirmed; across all sessions. None if never."""
    from .actions import CATALOG

    kinds = [k for k, act in CATALOG.items() if act.writes_source]
    marks = ",".join("?" * len(kinds))
    r = store.one(f"SELECT MAX(closed_ts) AS ts FROM gates WHERE device_id = ? AND kind IN ({marks}) AND "
                  "(state = 'closed' OR (state = 'aborted' AND confirmed_ts IS NOT NULL))", (device_id, *kinds))
    return r["ts"] if r and r["ts"] else None


def secured_after_last_write(store, device_id, session_id=None):
    """A secured / waived data state recorded after the last write (any session, or the given one)."""
    lw = last_write_ts(store, device_id) or ""
    sql = "SELECT 1 FROM data_states WHERE device_id = ? AND state IN ('secured', 'waived') AND ts > ?"
    args = [device_id, lw]
    if session_id:
        sql += " AND session_id = ?"
        args.append(session_id)
    return store.one(sql, tuple(args)) is not None


def current(store, session_id, device_id):
    r = store.one("SELECT * FROM data_states WHERE session_id = ? AND device_id = ? ORDER BY ts DESC, id DESC LIMIT 1",
                  (session_id, device_id))
    return r["state"] if r else "none"


def mapfile_complete(parsed, device_bytes):
    """(ok, reason). reason in image-incomplete / image-not-contiguous / image-does-not-cover-device.
    `parsed`: the parse_mapfile result (MapSummary) or its stored dict form."""
    if hasattr(parsed, "to_dict"):
        parsed = parsed.to_dict()
    if not parsed:
        return False, "image-incomplete"
    unfinished = (parsed.get("non_tried") or 0) + (parsed.get("non_trimmed") or 0) + (parsed.get("non_scraped") or 0)
    if parsed.get("finished") is not True or parsed.get("bad") != 0 or unfinished:
        return False, "image-incomplete"
    if parsed.get("contiguous") is not True:
        return False, "image-not-contiguous"
    if not isinstance(device_bytes, int) or parsed.get("start") != 0 or parsed.get("end") != device_bytes:
        return False, "image-does-not-cover-device"
    return True, ""


def operator_yes(ctx, what, argv_tail):
    answer = ctx.ask_operator(f"Type YES to {what}: ", argv_tail)
    if answer != "YES":
        raise Refused(f"operator did not confirm ({what})", ["operator-declined"])


def cmd_data_state(ctx, a):
    from .operator import require_echo_safe

    require_echo_safe(reason=a.reason, home=ctx.home_flag)
    s = sess.load(ctx.store, a.session)
    dev = device_row(ctx.store, a.device)
    fp = dev["fingerprint"]
    evidence_id = None
    tail = ["session", "data-state", a.session, a.device, a.state]
    if a.state == "secured":
        if a.evidence:
            ev = ctx.store.one("SELECT * FROM evidence WHERE id = ?", (a.evidence,))
            if ev is None:
                raise UsageError(f"unknown evidence {a.evidence!r}")
            if ev["device_id"] != a.device or ev["session_id"] != a.session:
                raise Refused(f"evidence {a.evidence} belongs to another device/session", ["evidence-other-device"])
            if ev["kind"] != "ddrescue":
                raise Refused("secured --evidence needs an ingested ddrescue mapfile", ["evidence-not-image"])
            # the mapfile must come from a gated imaging run of this device (amendment 02: no hand-written maps)
            img = ctx.store.one("SELECT id FROM gates WHERE device_id = ? AND session_id = ? AND kind = 'image-ddrescue' "
                                "AND state = 'closed' AND outcome = 'success' AND confirmed_ts < ? "
                                "ORDER BY closed_ts DESC LIMIT 1", (a.device, a.session, ev["ts"]))
            reasons, notes = [], []
            if img is None:
                reasons.append("image-gate-missing")
                notes.append("needs a closed, successful image-ddrescue gate on this device in this session, "
                             "confirmed before the mapfile was ingested")
            from .ingest import current_parsed

            parsed = current_parsed(ctx.store, ev) or {}
            ok, why = mapfile_complete(parsed, fp.get("bytes"))
            if not ok:
                reasons.append(why)
                notes.append(f"{why}: rescued {parsed.get('rescued')} of {fp.get('bytes')} device bytes, bad "
                             f"{parsed.get('bad')}, finished {parsed.get('finished')}, blocks "
                             f"{parsed.get('start')}..{parsed.get('end')} contiguous {parsed.get('contiguous')}")
            if reasons:  # every failing reason at once (as gate open, D8)
                raise Refused("secured refused: " + "; ".join(notes) + "; continue ddrescue over the whole device "
                              "under an image-ddrescue gate, or let the operator record "
                              f"`session data-state {a.session} {a.device} waived --reason <text>`", reasons)
            evidence_id = a.evidence
        elif a.attested:
            if not a.reason:
                raise UsageError("secured --attested needs --reason (what was copied and how it was verified)")
            operator_yes(ctx, f"attest that the data of {a.device} ({fp.get('model')}, {fp.get('bytes')} bytes) is "
                              f"secured: {a.reason}", tail + ["--attested", "--reason", f'"{a.reason}"'])
        else:
            raise UsageError("secured needs --evidence <ddrescue evidence id> or --attested --reason <text>")
    elif a.state == "waived":
        if not a.reason:
            raise UsageError("waived needs --reason")
        operator_yes(ctx, f"record data state waived for {a.device} ({fp.get('model')}, {fp.get('bytes')} bytes): "
                          f"{a.reason}", tail + ["--reason", f'"{a.reason}"'])
    elif a.state == "not-needed":
        if sess.preserves(s):
            raise Refused("data must be preserved in this session (preserve-data yes/unknown): use secured or waived",
                          ["preserve-required"])
        operator_yes(ctx, f"record data state not-needed for {a.device} ({fp.get('model')}, {fp.get('bytes')} bytes)",
                     tail)
    old = current(ctx.store, a.session, a.device)
    who = "operator" if (a.attested or a.state in ("waived", "not-needed")) else ctx.who
    ctx.store.execute("INSERT INTO data_states (ts, session_id, device_id, state, evidence_id, attested, reason, who) "
                      "VALUES (?,?,?,?,?,?,?,?)", (ctx.store.now(), a.session, a.device, a.state, evidence_id,
                                                   int(bool(a.attested)), a.reason, who))
    sess.event(ctx.store, a.session, who, f"data_state:{a.device}", old, a.state, a.reason)
    return ctx.reply({"data_state": a.state, "device_id": a.device},
                     f"data state {old} -> {a.state}" + (f" (evidence {evidence_id})" if evidence_id else "")
                     + (" (attested by operator)" if a.attested else ""))
