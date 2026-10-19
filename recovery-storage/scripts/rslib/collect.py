"""R0 orchestration: inventory, re-resolution, collect, ingest smartctl, device link (phase 02).

Device ids are bound to fingerprints, never to Disk Number / dev path (recorded per observation only).
"""
import datetime as dt
import math
import pathlib

from . import allowlist, enum_linux, enum_windows, events as ev, session as sess, store as st
from .errors import EnvFailure, NeedsHuman, Refused, UsageError
from .identity import Fingerprint, fingerprint, match, windows_join
from .smart import SmartRecord, detect_class, has_smart, normalise

INSTALL_HINT = ("smartctl not found: install smartmontools (Windows: `winget install smartmontools.smartmontools` "
                "or `scoop install smartmontools`; Linux: package `smartmontools`), or set RS_SMARTCTL to its "
                "absolute path")
COLLECT_FAILED = ("tool_missing", "timeout", "collection_failed", "malformed", "unknown")
ELEVATION_HINT = "re-run elevated to try SAT passthrough; this is not a device fault"
CLASS_ALIASES = {
    "sd": {"sd", "usb-flash-or-card"}, "microsd": {"sd", "usb-flash-or-card"}, "card": {"sd", "usb-flash-or-card"},
    "usb": {"usb-flash-or-card"}, "usb-flash": {"usb-flash-or-card"}, "usb-flash-or-card": {"usb-flash-or-card", "sd"},
    "hdd": {"hdd", "external-hdd"}, "external-hdd": {"external-hdd", "hdd"},
    "ssd": {"ssd-sata", "external-ssd", "nvme"}, "ssd-sata": {"ssd-sata", "external-ssd"},
    "nvme": {"nvme", "external-ssd"}, "external-ssd": {"external-ssd", "ssd-sata", "nvme"},
    "external": {"external-hdd", "external-ssd"},
}


# ------------------------------------------------------------------ enumeration
class Seen:
    """One attached disk at this moment: OS view + smartctl identity probe + fingerprint."""

    def __init__(self, os_disk, smart, join, fp):
        self.os_disk, self.smart, self.join, self.fp = os_disk, smart, join, fp

    @property
    def os_path(self):
        return self.os_disk.os_path


def _smart_from_run(res):
    if res.tool_missing:
        return SmartRecord("tool_missing", tool_version=res.tool_version)
    if res.timed_out:
        return SmartRecord("timeout", tool_version=res.tool_version)
    return normalise(res.stdout or b"", exit_code=res.exit_code, tool_version=res.tool_version)


def _ps(ctx, script_id, env=None):
    res = ctx.runner.run("powershell", allowlist.ps_script_args(script_id), env=env)
    if res.tool_missing or res.timed_out or res.exit_code != 0 or not res.stdout:
        return None, res
    return (res.stdout.decode("utf-8-sig", "replace") if isinstance(res.stdout, bytes) else res.stdout), res


def _os_disks(ctx):
    if ctx.os_family == "windows":
        text, res = _ps(ctx, "win-disks")
        if text is None:
            raise EnvFailure(f"cannot enumerate disks: PowerShell win-disks failed (exit {res.exit_code}, "
                             f"missing={res.tool_missing}, timeout={res.timed_out})", ["enumeration-failed"])
        chain, _ = _ps(ctx, "win-pnp-chain")
        try:
            return enum_windows.parse(text, chain)
        except (ValueError, TypeError, AttributeError) as e:
            raise EnvFailure(f"cannot enumerate disks: unparseable win-disks output ({e})", ["enumeration-failed"])
    res = ctx.runner.run("lsblk", ["-J", "-O", "-b"])
    if res.tool_missing or res.timed_out or res.exit_code != 0:
        raise EnvFailure("cannot enumerate disks: lsblk failed", ["enumeration-failed"])
    try:
        disks = enum_linux.parse_lsblk((res.stdout or b"").decode("utf-8", "replace"))
    except (ValueError, TypeError, AttributeError) as e:
        raise EnvFailure(f"cannot enumerate disks: unparseable lsblk output ({e})", ["enumeration-failed"])
    for d in disks:
        name = pathlib.PurePosixPath(d.os_path or "").name
        try:
            d.usb = enum_linux.sysfs_usb(name)
            mmc = enum_linux.sysfs_mmc(name)
        except (ValueError, OSError):
            mmc = None
        if mmc:
            d.extra["mmc"] = mmc
            d.bus = "mmc"
    return disks


def enumerate_attached(ctx):
    disks = _os_disks(ctx)
    probes = []
    for d in disks:
        smart = None
        if d.os_path and allowlist.SMART_DEVICE.match(d.os_path):
            smart = _smart_from_run(ctx.runner.run("smartctl", ["-j", "-i", "-n", "standby", d.os_path]))
        elif d.os_path:
            d.extra["smart"] = "not probed: path outside the smartctl allow-list (zram, virtio, nbd ...)"
        join = windows_join(d, smart) if ctx.os_family == "windows" else "not_applicable"
        usable = smart if smart is not None and join != "join_conflict" and smart.identity.get("model") else None
        probes.append((d, smart, join, usable))
    seen = []
    for i, (d, smart, join, usable) in enumerate(probes):
        others = [fingerprint(os_disk=o[0], smart=o[3]) for j, o in enumerate(probes) if j != i]
        fp = fingerprint(os_disk=d, smart=usable, attached=[o.serial_norm for o in others if o.serial_norm])
        seen.append(Seen(d, smart, join, fp))
    return seen


def detected_class_for(os_disk, smart):
    if smart is not None and has_smart(smart):
        c = detect_class(smart.identity, os_disk.bus if os_disk is not None else None)
        if c:
            return c
    if os_disk is None:
        return smart.detected_class if smart is not None else None
    if os_disk.bus in ("sd", "mmc"):
        return "sd"
    if os_disk.bus == "usb":
        return "usb-flash-or-card"
    if os_disk.bus == "nvme":
        return "nvme"
    return None


# ------------------------------------------------------------------ device rows
def stored_devices(store):
    return {r["id"]: Fingerprint.from_dict(st.loads(r["fingerprint"]))
            for r in store.query("SELECT id, fingerprint FROM devices ORDER BY created_ts, rowid")}


def device_row(store, device_id):
    r = store.one("SELECT * FROM devices WHERE id = ?", (device_id,))
    if r is None:
        raise UsageError(f"unknown device {device_id!r}", ["unknown-device"])
    r["fingerprint"] = st.loads(r["fingerprint"])
    r["data"] = st.loads(r["data"]) or {}
    return r


def create_device(store, fp, detected_class=None):
    did = st.new_id("D")
    store.execute("INSERT INTO devices (id, created_ts, fingerprint, detected_class, data) VALUES (?,?,?,?,?)",
                  (did, store.now(), st.dumps(fp.to_dict()), detected_class, st.dumps({})))
    return did


def merge_fingerprint(store, device_id, fp):
    """Learn missing ids from an exact/probable match (never overwrite a known value)."""
    row = device_row(store, device_id)
    cur = dict(row["fingerprint"])
    new = fp.to_dict()
    changed = False
    for k, v in new.items():
        if k == "os_ids":
            if v and v != cur.get("os_ids"):
                cur["os_ids"], changed = v, True
        elif cur.get(k) in (None, "absent") and v not in (None, "absent"):
            if k == "serial_trust" and not new.get("serial_norm"):
                continue
            cur[k], changed = v, True
    if changed:
        store.execute("UPDATE devices SET fingerprint = ? WHERE id = ?", (st.dumps(cur), device_id))


def set_detected_class(store, device_id, cls):
    if cls:
        store.execute("UPDATE devices SET detected_class = ? WHERE id = ?", (cls, device_id))


# ------------------------------------------------------------------ observations
def _obs_public(oid, s, device_id, level, created, candidates, cls, store):
    cands = []
    for c in candidates:
        try:
            r = device_row(store, c)
            cands.append({"device_id": c, "model": r["fingerprint"].get("model"), "bytes": r["fingerprint"].get("bytes")})
        except UsageError:
            pass
    d = s.os_disk
    return {
        "observation_id": oid, "device_id": device_id, "match": level, "created": created, "os_path": d.os_path,
        "join": s.join, "model": s.fp.model, "bytes": s.fp.bytes, "is_boot": d.is_boot, "is_system": d.is_system,
        "is_readonly": d.is_readonly, "fs_unrecognised": d.fs_unrecognised, "no_media": d.no_media,
        "detected_class": cls, "usb": d.usb,
        "health_status": d.health_status, "collection_status": s.smart.collection_status if s.smart else None,
        "partitions": d.partitions, "partition_style": d.partition_style,
        "fingerprint": s.fp.to_dict(), "candidates": cands,
    }


def save_observation(store, session_id, s, device_id, level, after_replug, public):
    oid = public.get("observation_id") or st.new_id("O")
    public["observation_id"] = oid
    store.execute("INSERT INTO observations (id, ts, session_id, device_id, match, os_path, after_replug, fingerprint,"
                  " data) VALUES (?,?,?,?,?,?,?,?,?)",
                  (oid, store.now(), session_id, device_id, level, s.os_path, int(bool(after_replug)),
                   st.dumps(s.fp.to_dict()), st.dumps(public)))
    return oid


def observe(ctx, session_id=None, after_replug=False, create=True):
    """Enumerate, match every attached disk against stored devices, record observations."""
    seen = enumerate_attached(ctx)
    devices = stored_devices(ctx.store)
    results = []
    for i, s in enumerate(seen):
        attached = [o.fp for j, o in enumerate(seen) if j != i]
        results.append(match(s.fp, devices, attached=attached))
    # one stored device claimed by two attached disks: neither may be linked automatically (B16)
    claims = {}
    for i, r in enumerate(results):
        if r.level in ("exact", "probable", "weak"):
            claims.setdefault(r.device_ids[0], []).append(i)
    for dev, idxs in claims.items():
        if len(idxs) > 1:
            for i in idxs:
                results[i] = type(results[i])("ambiguous", [dev])
    out = []
    for s, r in zip(seen, results):
        created = False
        device_id = None
        if r.level in ("exact", "probable", "weak"):
            device_id = r.device_ids[0]
            if r.level in ("exact", "probable"):
                merge_fingerprint(ctx.store, device_id, s.fp)
        elif r.level in ("none", "conflict") and create:
            device_id = create_device(ctx.store, s.fp)
            created = True
        cls = detected_class_for(s.os_disk, s.smart)
        if device_id and cls and r.level != "weak":
            row = device_row(ctx.store, device_id)
            if not row["detected_class"]:
                set_detected_class(ctx.store, device_id, cls)
        cands = r.device_ids if r.level in ("ambiguous", "conflict") else []
        pub = _obs_public(None, s, device_id, r.level, created, cands, cls, ctx.store)
        save_observation(ctx.store, session_id, s, device_id, r.level, after_replug, pub)
        out.append((s, pub))
    ctx.store.execute("INSERT INTO inventory_runs (id, ts, session_id, after_replug, device_ids) VALUES (?,?,?,?,?)",
                      (st.new_id("R"), ctx.store.now(), session_id, int(bool(after_replug)),
                       st.dumps(sorted({o["device_id"] for _, o in out if o["device_id"]}))))
    return out


def _inventory_text(rows):
    lines = []
    for _, o in rows:
        fp = o["fingerprint"]
        lines.append(f"{o['os_path']}  {o['model']}  {o['bytes']} bytes  bus={fp.get('bus')}  "
                     f"serial={'yes' if fp.get('serial_norm') else 'none'}({fp.get('serial_trust')})  "
                     f"match={o['match']}  device={o['device_id'] or '-'}"
                     + ("  BOOT/SYSTEM" if o["is_boot"] or o["is_system"] else "")
                     + ("  fs-unrecognised" if o["fs_unrecognised"] else ""))
        for c in o["candidates"]:
            lines.append(f"    candidate {c['device_id']}: {c['model']} {c['bytes']} bytes")
    return "\n".join(lines) or "no disks"


def cmd_inventory(ctx, a):
    if a.session:
        sess.load(ctx.store, a.session)
    rows = observe(ctx, a.session, a.after_replug)
    obs = [o for _, o in rows]
    text = _inventory_text(rows)
    if any(o["match"] == "ambiguous" for o in obs):
        text += ("\nambiguous: these disks cannot be told apart automatically; resolve with "
                 "`device link <observation> <device>` or `device link <observation> --new`")
        return ctx.reply({"observations": obs}, text, code=5, reasons=["ambiguous"])
    return ctx.reply({"observations": obs}, text)


# ------------------------------------------------------------------ re-resolution
class Resolved:
    def __init__(self, seen, pub, level):
        self.seen, self.pub, self.level = seen, pub, level

    @property
    def os_path(self):
        return self.seen.os_path


def resolve(ctx, session_id, device_id, after_replug=False):
    """Find device_id among attached disks now. Raises Refused(device-not-found / identity-conflict) or
    NeedsHuman(ambiguous). Records the observations of this enumeration."""
    device_row(ctx.store, device_id)
    return pick(ctx, observe(ctx, session_id, after_replug, create=True), device_id)


def _same_hardware(fp, dev_fp):
    """Same model, bytes, USB ids and (when both trusted) serial / EUI / WWN, ignoring on-media ids."""
    def low(v):
        return v.strip().lower() if isinstance(v, str) and v.strip() else None

    if low(fp.get("model")) != low(dev_fp.get("model")) or fp.get("bytes") != dev_fp.get("bytes"):
        return False
    if (low(fp.get("vid")), low(fp.get("pid"))) != (low(dev_fp.get("vid")), low(dev_fp.get("pid"))):
        return False
    if fp.get("serial_trust") == "high" and dev_fp.get("serial_trust") == "high" and \
            fp.get("serial_norm") != dev_fp.get("serial_norm"):
        return False
    return all(not (low(fp.get(k)) and low(dev_fp.get(k))) or low(fp.get(k)) == low(dev_fp.get(k))
               for k in ("eui64", "wwn"))


def media_id_changed(ctx, rows, device_id):
    """After a gated write (format / repartition) the MBR signature or GPT guid changes. Accept the device when
    exactly one attached disk is the same hardware, update its on-media ids, and relink that observation."""
    dev = device_row(ctx.store, device_id)
    cands = [(s, o) for s, o in rows if _same_hardware(o["fingerprint"], dev["fingerprint"])]
    if len(cands) != 1:
        return None
    s, o = cands[0]
    fp = dict(dev["fingerprint"])
    old = {k: fp.get(k) for k in ("ptuuid", "mbr_signature")}
    fp["ptuuid"], fp["mbr_signature"] = o["fingerprint"].get("ptuuid"), o["fingerprint"].get("mbr_signature")
    data = dict(dev["data"])
    data.setdefault("media_id_history", []).append({"ts": ctx.store.now(), "old": old,
                                                    "new": {k: fp[k] for k in old}})
    ctx.store.execute("UPDATE devices SET fingerprint = ?, data = ? WHERE id = ?",
                      (st.dumps(fp), st.dumps(data), device_id))
    o = dict(o, device_id=device_id, match="media-id-changed")
    ctx.store.execute("UPDATE observations SET device_id = ?, match = ?, data = ? WHERE id = ?",
                      (device_id, "probable", st.dumps(o), o["observation_id"]))
    return Resolved(s, o, "probable")


def pick(ctx, rows, device_id):
    hits = [(s, o) for s, o in rows if o["device_id"] == device_id and o["match"] in ("exact", "probable", "weak")]
    amb = [(s, o) for s, o in rows if o["match"] == "ambiguous" and any(c["device_id"] == device_id
                                                                        for c in o["candidates"])]
    if amb:
        cands = [{"os_path": o["os_path"], "model": o["model"], "bytes": o["bytes"]} for _, o in amb]
        raise NeedsHuman(f"device {device_id} is ambiguous among attached disks: "
                         + ", ".join(f"{c['os_path']} {c['model']} {c['bytes']} bytes" for c in cands),
                         ["ambiguous"], {"candidates": cands})
    if len(hits) == 1:
        s, o = hits[0]
        return Resolved(s, o, o["match"])
    conflicts = [(s, o) for s, o in rows if o["match"] == "conflict" and device_id in
                 [c["device_id"] for c in o["candidates"]]]
    if conflicts:
        raise Refused(f"device {device_id}: an attached disk has the same model/size but a different strong id",
                      ["identity-conflict", "device-not-found"])
    raise Refused(f"device {device_id} not found among attached disks", ["device-not-found"])


# ------------------------------------------------------------------ snapshots
def save_snapshot(ctx, session_id, device_id, rec, source, raw, spinup=False, extra=None):
    sid_dir = ctx.store.evidence_subdir(session_id)
    digest, path = (None, None)
    if raw is not None:
        digest, path = ctx.store.write_blob(raw, sid_dir, ".json")
    snap_id = st.new_id("N")
    data = {
        "collection_status": rec.collection_status, "flags": sorted(rec.flags), "message": rec.message,
        "identity": rec.identity, "health_fields": rec.health_fields, "detected_class": rec.detected_class,
        "exit_code": rec.exit_code, "spinup": spinup, "source": source,
    }
    data.update(extra or {})
    ctx.store.execute("INSERT INTO snapshots (id, ts, session_id, device_id, source, collection_status, tool_version,"
                      " sha256, path, data) VALUES (?,?,?,?,?,?,?,?,?,?)",
                      (snap_id, ctx.store.now(), session_id, device_id, source, rec.collection_status,
                       rec.tool_version, digest or rec.sha256 or None, path, st.dumps(data)))
    return {"id": snap_id, "collection_status": rec.collection_status, "source": source,
            "tool_version": rec.tool_version, "spinup": spinup, "sha256": digest or rec.sha256 or None}


def load_snapshot_record(store, snap_row):
    """Rebuild a SmartRecord from a stored snapshot (raw file when available)."""
    data = st.loads(snap_row["data"]) or {}
    raw = None
    if snap_row.get("path"):
        try:
            raw = store.read_blob(snap_row["path"])
        except OSError:
            raw = None
    if raw is not None and data.get("collection_status") not in ("tool_missing", "timeout"):
        rec = normalise(raw, exit_code=data.get("exit_code"), tool_version=snap_row.get("tool_version"))
        rec.collection_status = snap_row["collection_status"]
    else:
        rec = SmartRecord(snap_row["collection_status"], identity=data.get("identity") or {},
                          health_fields=data.get("health_fields") or {}, tool_version=snap_row.get("tool_version"))
    rec.snapshot_id = snap_row["id"]
    rec.snapshot_ts = snap_row["ts"]
    rec.session_id = snap_row["session_id"]
    rec.device_id = snap_row["device_id"]
    rec.extra = data
    return rec


def _events(ctx, session_id):
    s = sess.load(ctx.store, session_id)
    start = dt.datetime.fromisoformat(s["created_ts"].replace("Z", "+00:00"))
    now = ctx.clock()
    lo, hi = allowlist.PS_ENV_BOUNDS["RS_LOOKBACK_HOURS"]
    hours = min(hi, max(lo, math.ceil((now - start).total_seconds() / 3600) + ev.LOOKBACK_HOURS))
    if ctx.os_family == "windows":
        env = {"RS_LOOKBACK_HOURS": str(hours), "RS_MAX_EVENTS": str(ev.MAX_EVENTS),
               "RS_MESSAGE_CHARS": str(ev.MESSAGE_CHARS)}
        text, res = _ps(ctx, "win-events", env)
        if text is None:
            why = "tool missing" if res.tool_missing else "timeout" if res.timed_out else f"exit {res.exit_code}"
            return ev.EventsResult(f"unavailable({why})")
        return ev.parse_windows(text)
    since = st.iso(now - dt.timedelta(hours=hours))
    res = ctx.runner.run("journalctl", ["-k", "-o", "json", "--since", since, "--no-pager"])
    if not res.tool_missing and not res.timed_out and res.exit_code == 0:
        return ev.parse_journal(res.stdout.decode("utf-8", "replace"))
    res2 = ctx.runner.run("dmesg", ["--time-format", "iso"])
    if not res2.tool_missing and not res2.timed_out and res2.exit_code == 0:
        return ev.parse_dmesg(res2.stdout.decode("utf-8", "replace"))
    return ev.EventsResult(f"unavailable(journalctl exit {res.exit_code}, dmesg exit {res2.exit_code})")


def class_conflict(declared, detected):
    if not declared or not detected:
        return False
    d = declared.strip().lower()
    allowed = CLASS_ALIASES.get(d, {d})
    return detected not in allowed


def take_snapshot(ctx, session_id, device_id, r, dtype=None, allow_spinup=False, with_events=True):
    """R0 smartctl -x on the resolved path (+ one -d sat retry for USB without SMART) -> stored snapshot."""
    path = r.os_path
    base = ["-j", "-x"] + ([] if allow_spinup else ["-n", "standby"])
    if not allowlist.SMART_DEVICE.match(path or ""):
        rec, raw = SmartRecord("unknown", message="device path outside the smartctl allow-list; not probed"), None
    else:
        res = ctx.runner.run("smartctl", base + (["-d", dtype] if dtype else []) + [path])
        rec = _smart_from_run(res)
        raw = res.stdout if not (res.tool_missing or res.timed_out) else None
    if rec.identity and (rec.identity.get("serial") or rec.identity.get("eui64") or rec.identity.get("wwn")):
        # the disk answering at this path must still be this device (a swap between enumerate and collect)
        if match(fingerprint(smart=rec), {device_id: Fingerprint.from_dict(device_row(ctx.store, device_id)
                                                                           ["fingerprint"])}).level == "conflict":
            raise Refused(f"device at {path} answered with another identity; nothing attached to {device_id}",
                          ["identity-conflict"])
    hints = []
    usb_without_smart = r.seen.os_disk.bus == "usb" and not dtype and not has_smart(rec)
    if usb_without_smart and rec.collection_status not in ("tool_missing", "timeout"):
        res2 = ctx.runner.run("smartctl", base + ["-d", "sat", path])
        rec, raw = _smart_from_run(res2), (res2.stdout if not (res2.tool_missing or res2.timed_out) else None)
    if rec.collection_status == "ok" and not has_smart(rec):
        rec.collection_status = "not_exposed"
    if rec.collection_status == "needs_elevation":
        hints.append(ELEVATION_HINT)
    if rec.collection_status == "unsupported_bridge":
        hints.append("smartctl does not know this USB bridge; SMART may not be exposed (`--dtype` can force a type)")
    cls = detected_class_for(r.seen.os_disk, rec)
    if cls:
        set_detected_class(ctx.store, device_id, cls)
    evs = _events(ctx, session_id) if with_events else None
    snap = save_snapshot(ctx, session_id, device_id, rec, "collected", raw, spinup=bool(allow_spinup),
                         extra={"os_path": path, "observation_id": r.pub["observation_id"],
                                "events": {"status": evs.status, "items": evs.items} if evs else None,
                                "detected_class": cls,
                                "os": {"bus": r.seen.os_disk.bus, "fs_unrecognised": r.seen.os_disk.fs_unrecognised,
                                       "is_readonly": r.seen.os_disk.is_readonly}})
    return rec, snap, hints, evs, cls


def cmd_collect(ctx, a):
    s = sess.load(ctx.store, a.session)
    if a.dtype is not None and a.dtype not in allowlist.SMART_DTYPES:
        raise UsageError(f"--dtype must be one of {sorted(allowlist.SMART_DTYPES)}")
    r = resolve(ctx, a.session, a.device)
    rec, snap, hints, evs, cls = take_snapshot(ctx, a.session, a.device, r, a.dtype, a.allow_spinup)
    declared = s.get("device_type")
    data = {"device_id": a.device, "snapshot": snap, "events": {"status": evs.status, "items": evs.items},
            "detected_class": cls, "declared_class": declared, "class_conflict": class_conflict(declared, cls),
            "os_path": r.os_path, "match": r.level}
    lines = [f"collected {a.device} at {r.os_path}: smartctl {rec.collection_status}"
             + (f" (tool {rec.tool_version})" if rec.tool_version else ""),
             f"class detected {cls or 'unknown'}" + (f", declared {declared}" if declared else "")
             + (" (CONFLICT: declared kept)" if data["class_conflict"] else ""),
             f"events: {evs.status}, {len(evs.items)} item(s)"] + hints
    if rec.collection_status in COLLECT_FAILED:
        msg = {"tool_missing": INSTALL_HINT, "timeout": "smartctl timed out"}.get(
            rec.collection_status, f"smartctl collection failed: {rec.collection_status}")
        raise EnvFailure(msg + "\n" + "\n".join(lines), [rec.collection_status], data)
    return ctx.reply(data, "\n".join(lines))


def cmd_ingest_smartctl(ctx, a):
    sess.load(ctx.store, a.session)
    p = pathlib.Path(a.file)
    try:
        raw = p.read_bytes()
    except OSError as e:
        raise UsageError(f"cannot read {p}: {e}")
    rec = normalise(raw)
    fp = fingerprint(smart=rec)
    r = match(fp, stored_devices(ctx.store))
    if r.level == "ambiguous":
        cands = [{"device_id": d, "model": device_row(ctx.store, d)["fingerprint"].get("model"),
                  "bytes": device_row(ctx.store, d)["fingerprint"].get("bytes")} for d in r.device_ids]
        raise NeedsHuman("ingested identity matches several stored devices; attach it with `device link`",
                         ["ambiguous"], {"candidates": cands, "match": "ambiguous"})
    created = False
    if r.level in ("exact", "probable", "weak"):
        device_id = r.device_ids[0]
        if r.level != "weak":
            merge_fingerprint(ctx.store, device_id, fp)
    else:
        device_id, created = create_device(ctx.store, fp, rec.detected_class), True
    if rec.detected_class:
        row = device_row(ctx.store, device_id)
        if not row["detected_class"]:
            set_detected_class(ctx.store, device_id, rec.detected_class)
    snap = save_snapshot(ctx, a.session, device_id, rec, "ingested", raw, extra={"file": p.name})
    data = {"device_id": device_id, "created": created, "match": r.level, "snapshot": snap}
    text = (f"ingested {p.name} -> device {device_id} ({'created' if created else r.level}), "
            f"collection {rec.collection_status}, sha256 {snap['sha256']}")
    return ctx.reply(data, text)


def cmd_device_link(ctx, a):
    row = ctx.store.one("SELECT * FROM observations WHERE id = ?", (a.observation,))
    if row is None:
        raise UsageError(f"unknown observation {a.observation!r}")
    if bool(a.device) == bool(a.new):
        raise UsageError("give either a device id or --new")
    fp = Fingerprint.from_dict(st.loads(row["fingerprint"]))
    created = False
    if a.new:
        device_id, created = create_device(ctx.store, fp), True
    else:
        dev = device_row(ctx.store, a.device)
        device_id = a.device
        new_fp = fp.to_dict()
        if _same_hardware(new_fp, dev["fingerprint"]) and any(
                new_fp.get(k) != dev["fingerprint"].get(k) for k in ("ptuuid", "mbr_signature")):
            # operator says it is the same device, re-partitioned: learn the new on-media ids (audited)
            cur = dict(dev["fingerprint"])
            hist = dict(dev["data"])
            hist.setdefault("media_id_history", []).append(
                {"ts": ctx.store.now(), "by": "device link", "observation": a.observation,
                 "old": {k: cur.get(k) for k in ("ptuuid", "mbr_signature")},
                 "new": {k: new_fp.get(k) for k in ("ptuuid", "mbr_signature")}})
            cur["ptuuid"], cur["mbr_signature"] = new_fp.get("ptuuid"), new_fp.get("mbr_signature")
            ctx.store.execute("UPDATE devices SET fingerprint = ?, data = ? WHERE id = ?",
                              (st.dumps(cur), st.dumps(hist), device_id))
    data = st.loads(row["data"])
    data["device_id"], data["match"] = device_id, "linked"
    ctx.store.execute("UPDATE observations SET device_id = ?, match = ?, data = ? WHERE id = ?",
                      (device_id, "linked", st.dumps(data), a.observation))
    return ctx.reply({"observation_id": a.observation, "device_id": device_id, "created": created},
                     f"observation {a.observation} linked to {device_id}" + (" (new device)" if created else ""))
