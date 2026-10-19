"""Spec §7 report per device. Every statement carries an epistemic tag:
[VERIFIED] read from a tool output we hold (tool + version + evidence id + sha256), [ATTESTED] operator statement or
attachment, [INFERRED] rule output (rule id + confidence), [UNDETERMINED] not reported / not yet known.
`--check`: a section counts as filled only by items that are not [UNDETERMINED]; sections 5 and 7 may read "none".
"""
import os
import platform
import pathlib
import re

from . import session as sess
from . import store as st
from .actions import CATALOG
from .collect import device_row, load_snapshot_record
from .errors import Refused, UsageError
from .fleet import latest_assessment
from .verdict import history, pass_missing

HEADINGS = ["Mục tiêu xử lý", "Thông tin nhận dạng", "Triệu chứng và bằng chứng", "Chẩn đoán và mức độ tin cậy",
            "Phương án đã thử", "Công cụ, phiên bản, kết quả", "Thay đổi đã thực hiện", "Kiểm định sau phục hồi",
            "Trạng thái cuối cùng", "Hạn chế còn tồn tại", "Khuyến nghị sử dụng"]
NONE_OK = (5, 7)
PASS_LIMITED_WARNING = "Không dùng cho dữ liệu duy nhất hoặc quan trọng"
V, A, I, U = "[VERIFIED]", "[ATTESTED]", "[INFERRED]", "[UNDETERMINED]"
TRI_CONF = {"STOP_UNSAFE": "high", "HARDWARE_DIAGNOSIS_REQUIRED": "high", "CONTROLLER_RECOVERY_CANDIDATE": "medium",
            "SOFTWARE_RECOVERY_CANDIDATE": "medium", "UNDETERMINED": "low"}


def item(tag, text, rule_id=None, confidence=None, tool=None, evidence_id=None, sha256=None, by=None):
    return {"tag": tag, "text": text, "rule_id": rule_id, "confidence": confidence, "tool": tool,
            "evidence_id": evidence_id, "sha256": sha256, "by": by}


def _devices_in_session(store, sid):
    ids = set()
    for table in ("snapshots", "evidence", "assessments", "gates", "verdicts", "data_states"):
        ids |= {r["device_id"] for r in store.query(f"SELECT DISTINCT device_id FROM {table} WHERE session_id = ?",
                                                    (sid,)) if r["device_id"]}
    return sorted(ids)


def _fmt(v):
    return "true" if v is True else "false" if v is False else str(v)


def build_device(store, s, device_id):
    dev = device_row(store, device_id)
    fp = dev["fingerprint"]
    secs = {n: [] for n in range(1, 12)}

    secs[1] += [item(None, f"goals: {', '.join(s['goals'])}"), item(None, f"risk ceiling: {s['ceiling']}"),
                item(None, f"preserve data: {s['preserve_data']}" + (" (forced by goal)" if s["preserve_forced"]
                                                                     else "")),
                item(None, f"data value: {s['data_value']} (effective {sess.effective_data_value(s)}), "
                           f"risk tolerance: {s['risk_tolerance']}")]

    obs = store.one("SELECT * FROM observations WHERE device_id = ? AND session_id = ? ORDER BY ts DESC, rowid DESC "
                    "LIMIT 1", (device_id, s["id"]))
    o = st.loads(obs["data"]) if obs else {}
    secs[2] += [item(None, f"model: {fp.get('model') or 'not reported'}"),
                item(None, f"serial: {fp.get('serial_norm') or 'not reported'} (trust {fp.get('serial_trust')})"),
                item(None, f"capacity: {fp.get('bytes')} bytes"),
                item(None, f"bus: {fp.get('bus') or 'not reported'}"
                     + (f", USB VID:PID {fp.get('vid')}:{fp.get('pid')}" if fp.get("vid") else ""))]
    for k in ("eui64", "wwn", "ptuuid"):
        if fp.get(k):
            secs[2].append(item(None, f"{k}: {fp[k]}"))
    secs[2].append(item(None, f"class detected: {dev['detected_class'] or 'unknown'}, declared: "
                              f"{s.get('device_type') or 'not given'}"))
    if obs:
        secs[2].append(item(None, f"latest OS observation: {o.get('os_path')} (match {obs['match']}, "
                                  f"{obs['ts']})"))

    for sym in s.get("symptoms") or []:
        secs[3].append(item(A, f"symptom reported by operator: {sym}"))
    for t in s.get("tried") or []:
        secs[3].append(item(A, f"isolation step done by operator: {t}"))
    if obs:
        os_tool = "win-disks/win-pnp-chain (PowerShell)" if str(o.get("os_path", "")).startswith("/dev/pd") else "lsblk"
        facts = [f"OS sees {o.get('model')} {o.get('bytes')} bytes at {o.get('os_path')} (bus {fp.get('bus')}, "
                 f"health status {o.get('health_status') or 'n/a'}, read-only {o.get('is_readonly')})"]
        if o.get("fs_unrecognised"):
            facts.append("OS reports a data partition without a recognised filesystem: "
                         + ", ".join(f"partition {p.get('number')} type {p.get('type')} mbr_type {p.get('mbr_type')}"
                                     for p in o.get("partitions") or []))
        for f in facts:
            secs[3].append(item(V, f, tool=os_tool, evidence_id=obs["id"]))
    snaps = store.query("SELECT * FROM snapshots WHERE device_id = ? AND session_id = ? ORDER BY ts, rowid",
                        (device_id, s["id"]))
    a = latest_assessment(store, device_id, s["id"])
    for r in snaps:
        tool = f"smartctl {r['tool_version']}" if r["tool_version"] else "smartctl (version unknown)"
        if r["collection_status"] != "ok":
            secs[3].append(item(U, f"SMART not available in snapshot {r['id']}: {r['collection_status']}",
                                evidence_id=r["id"], sha256=r["sha256"]))
        secs[6].append(item(V if r["sha256"] else U, f"{r['source']} snapshot {r['id']}: {tool}, collection "
                                                       f"{r['collection_status']}", tool=tool, evidence_id=r["id"],
                            sha256=r["sha256"]))
    if snaps:
        last = snaps[-1]
        tool = f"smartctl {last['tool_version']}" if last["tool_version"] else None
        if a and last["collection_status"] == "ok":
            for e in a["data"]["health"]["evidence"]:
                if e["path"].startswith("delta."):
                    continue
                secs[3].append(item(V, f"{e['path']} = {_fmt(e['value'])} ({e['strength']})", tool=tool,
                                    evidence_id=last["id"], sha256=last["sha256"]))
        if a:
            for m in a["data"]["health"]["missing"]:
                secs[3].append(item(U, f"smartctl {m}: not reported"))
        ev_items = ((st.loads(last["data"]) or {}).get("events") or {})
        for e in ev_items.get("items") or []:
            secs[3].append(item(V, f"OS event {e['provider']} {e['id']} at {e['time']}: {e['message'][:120]}",
                                tool="Get-WinEvent (frozen script win-events)", evidence_id=last["id"]))
    evidence = store.query("SELECT * FROM evidence WHERE device_id = ? AND session_id = ? ORDER BY ts, rowid",
                           (device_id, s["id"]))
    for e in evidence:
        p = (st.loads(e["data"]) or {}).get("parsed") or {}
        if e["level"] == "attested":
            secs[3].append(item(A, f"attested by {e.get('who') or 'unknown'}: {p.get('tool')} result {p.get('result')} "
                                   f"(attachment sha256 {e['sha256']})", evidence_id=e["id"], sha256=e["sha256"],
                                by=e.get("who")))
        else:
            summary = ", ".join(f"{k}={_fmt(v)}" for k, v in sorted(p.items()) if v is not None)
            secs[3].append(item(V, f"{e['kind']} result: {p.get('result') or summary}", tool=e["kind"],
                                evidence_id=e["id"], sha256=e["sha256"]))
            secs[6].append(item(V, f"ingested {e['kind']} output: {summary}", tool=e["kind"], evidence_id=e["id"],
                                sha256=e["sha256"]))

    if a:
        d = a["data"]
        h, t = d["health"], d["triage"]
        secs[4].append(item(I, f"health {h['verdict']}: {h['reason']}", rule_id=h["rule_id"],
                            confidence=h["confidence"]))
        secs[4].append(item(I, f"triage {t['class']}" + (f" (branch {t['branch']})" if t["branch"] else "")
                            + f"; next test: {t['next_test']}", rule_id=t["rule_id"],
                            confidence=TRI_CONF[t["class"]]))
        if t["constraints"]:
            secs[4].append(item(I, "constraints: " + ", ".join(t["constraints"]), rule_id=t["rule_id"],
                                confidence=TRI_CONF[t["class"]]))
        for x in d["hypotheses"]:
            secs[4].append(item(I, f"hypothesis {x['category']}: evidence "
                                   + "; ".join(f"{e['path']}={_fmt(e['value'])}" for e in x["evidence"])
                                   + f"; alternative: {x['alternative']}; next test: {x['next_test']}",
                                rule_id=f"hyp:{x['category']}", confidence=x["confidence"]))
    else:
        secs[4].append(item(U, "no assessment recorded (run assess)"))

    gates = store.query("SELECT * FROM gates WHERE device_id = ? AND session_id = ? ORDER BY ts, rowid",
                        (device_id, s["id"]))
    for g in gates:
        secs[5].append(item(None, f"{g['kind']} ({g['risk']}): {g['state']}" + (f", outcome {g['outcome']}"
                                                                                  if g["outcome"] else "")
                            + (f", aborted: {g['abort_reason']}" if g["abort_reason"] else "")))
        if g["state"] == "closed" and CATALOG.get(g["kind"]) and CATALOG[g["kind"]].writes_source:
            before, after = st.loads(g["before_json"]) or {}, st.loads(g["after_json"]) or {}
            secs[7].append(item(None, f"{g['kind']} wrote the source ({g['outcome']} success" if g["outcome"] ==
                                "success" else f"{g['kind']} wrote the source (outcome {g['outcome']}"))
            secs[7][-1]["text"] += (f"); before snapshot {before.get('snapshot_id')}, after snapshot "
                                    f"{after.get('snapshot_id')}, identity drift {bool(g['identity_drift'])}")
    if not gates:
        secs[5].append(item(None, "none"))
    if not secs[7]:
        secs[7].append(item(None, "none"))
    for ds in store.query("SELECT * FROM data_states WHERE device_id = ? AND session_id = ? ORDER BY ts",
                          (device_id, s["id"])):
        secs[5].append(item(A if ds["attested"] else None, f"data state {ds['state']}"
                            + (f" (evidence {ds['evidence_id']})" if ds["evidence_id"] else "")
                            + (f": {ds['reason']}" if ds["reason"] else "")))

    vs = history(store, s["id"], device_id)
    latest = vs[0] if vs else None
    missing = pass_missing(store, s, device_id)
    if latest and latest["status"] == "PASS":
        secs[8].append(item(V, "post-recovery verification complete for the device class (verdict PASS accepted)"))
    elif latest:
        secs[8].append(item(None, f"post-recovery PASS matrix not applied: verdict {latest['status']}"))
    for m in missing:
        secs[8].append(item(U, f"missing for PASS: {m}" + (" (capacity write/read verify after the last write)"
                                                          if m == "capacity-verify-missing" else "")))
    for e in evidence:
        if e["level"] == "attested":
            secs[8].append(item(A, f"attested (by {e.get('who') or 'unknown'}) {e['kind']} evidence sha256 "
                                   f"{e['sha256']}", evidence_id=e["id"], sha256=e["sha256"], by=e.get("who")))

    if latest:
        secs[9].append(item(None, f"{latest['status']} ({latest['ts']})"
                            + (f": {latest['reason']}" if latest["reason"] else "")))
    else:
        secs[9].append(item(U, "UNRESOLVED (no verdict recorded)"))

    if latest and latest["limitation"]:
        secs[10].append(item(None, f"limitation: {latest['limitation']}"))
    if latest and latest["reason"]:
        secs[10].append(item(None, f"reason: {latest['reason']}"))
    if latest and not latest["limitation"] and not latest["reason"]:
        secs[10].append(item(None, f"no limitation recorded with verdict {latest['status']}; unknowns below still "
                                   "apply (SMART not exposed means future wear cannot be monitored)"
                             if a and a["data"]["health"]["verdict"] == "unknown"
                             else f"no limitation recorded with verdict {latest['status']}"))
    if a:
        for c in a["data"]["triage"]["constraints"]:
            secs[10].append(item(I, f"constraint in force: {c}", rule_id=a["data"]["triage"]["rule_id"],
                                 confidence=TRI_CONF[a["data"]["triage"]["class"]]))
        for m in a["data"]["health"]["missing"]:
            secs[10].append(item(U, f"unknown: {m}"))
    if not secs[10]:
        secs[10].append(item(U, "no limitation recorded"))

    status = latest["status"] if latest else None
    if status == "PASS_LIMITED":
        secs[11].append(item(None, f"{PASS_LIMITED_WARNING}; dùng trong giới hạn: {latest['limitation']}"))
    elif status == "PASS":
        secs[11].append(item(None, "dùng được; vẫn giữ bản sao lưu cho dữ liệu quan trọng"))
    elif status in ("FAIL", "RETIRED"):
        secs[11].append(item(None, "loại khỏi sử dụng; không ghi dữ liệu mới lên thiết bị"))
    elif status == "REPAIR_REQUIRED":
        secs[11].append(item(None, "chuyển cho đơn vị sửa chữa/cứu dữ liệu chuyên môn; không thử thêm bằng phần mềm"))
    if a:
        secs[11].append(item(I, f"next step: {a['data']['triage']['next_test']}",
                             rule_id=a["data"]["triage"]["rule_id"], confidence=TRI_CONF[a["data"]["triage"]["class"]]))
    if not secs[11]:
        secs[11].append(item(U, "no recommendation: assess the device first"))

    sections = [{"number": n, "heading": f"{n}. {HEADINGS[n - 1]}", "items": secs[n]} for n in range(1, 12)]
    return {"device_id": device_id, "model": fp.get("model"), "sections": sections}


def check(dev_model):
    missing = []
    for sec in dev_model["sections"]:
        filled = [i for i in sec["items"] if i["tag"] != U and str(i["text"]).strip()]
        if not filled:
            missing.append(sec["number"])
    return missing


def render(s, devices):
    out = [f"# Báo cáo phiên {s['id']}", ""]
    for d in devices:
        out += [f"## Thiết bị {d['device_id']}: {d['model'] or 'unknown model'}", ""]
        for sec in d["sections"]:
            out.append(f"### {sec['heading']}")
            for i in sec["items"]:
                meta = [x for x in (f"rule {i['rule_id']}" if i["rule_id"] else None,
                                    f"confidence {i['confidence']}" if i["confidence"] else None,
                                    i["tool"], f"evidence {i['evidence_id']}" if i["evidence_id"] else None,
                                    f"sha256 {i['sha256']}" if i["sha256"] else None) if x]
                tag = i["tag"]
                if tag and i.get("by"):
                    tag = f"{tag[:-1]} by {i['by']}]"  # [ATTESTED] -> [ATTESTED by operator] (markdown only)
                out.append(f"- {tag + ' ' if tag else ''}{i['text']}" + (f" ({'; '.join(meta)})" if meta else ""))
            out.append("")
    return "\n".join(out)


def _mask(v):
    return "****" + v[-4:] if len(v) > 4 else "****"


def _secrets(store, device_ids):
    out = set()
    for did in device_ids:
        fp = device_row(store, did)["fingerprint"]
        for k in ("serial_norm", "eui64", "wwn", "ptuuid"):
            if fp.get(k):
                out.add(str(fp[k]))
        for r in store.query("SELECT * FROM snapshots WHERE device_id = ?", (did,)):
            rec = load_snapshot_record(store, r)
            for k in ("serial", "eui64", "wwn"):
                v = (rec.identity or {}).get(k)
                if v:
                    out.add(str(v).strip())
    return {x for x in out if len(x) >= 4}


def redact(obj, secrets, home):
    user = os.environ.get("USERNAME") or os.environ.get("USER") or pathlib.Path.home().name
    host = os.environ.get("COMPUTERNAME") or os.environ.get("HOSTNAME") or platform.node()
    homes = {str(home), pathlib.Path(home).as_posix()}

    def fix(text):
        for h in sorted(homes, key=len, reverse=True):
            text = text.replace(h, "~")
        for sec in sorted(secrets, key=len, reverse=True):
            text = re.sub(re.escape(sec), _mask(sec), text, flags=re.I)
        # identifiers of other devices / the host that may sit in OS event text
        text = re.sub(r"(?i)(serial\s*(number)?\s*[:=]\s*)(\S+)", lambda m: m.group(1) + _mask(m.group(3)), text)
        text = re.sub(r"\{?[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}\}?", "<guid>",
                      text)
        if host and len(host) >= 3:
            text = re.sub(re.escape(host), "<host>", text, flags=re.I)
        if user and len(user) >= 3:
            text = re.sub(re.escape(user), "<user>", text, flags=re.I)
        return text

    def walk(x):
        if isinstance(x, str):
            return fix(x)
        if isinstance(x, list):
            return [walk(v) for v in x]
        if isinstance(x, dict):
            return {k: walk(v) for k, v in x.items()}
        return x
    return walk(obj)


def cmd_report(ctx, a):
    s = sess.load(ctx.store, a.session)
    ids = [a.device] if a.device else _devices_in_session(ctx.store, a.session)
    if a.device:
        device_row(ctx.store, a.device)
    devices = [build_device(ctx.store, s, d) for d in ids]
    missing = sorted({n for d in devices for n in check(d)})
    chk = {"ok": not missing, "missing_sections": missing}
    data = {"devices": devices, "check": chk}
    md = render(s, devices)
    if a.redact:
        secrets = _secrets(ctx.store, ids)
        data = redact(data, secrets, ctx.store.home)
        md = redact(md, secrets, ctx.store.home)
    if a.check and missing:
        raise Refused(f"report check failed: sections without content: {', '.join(map(str, missing))}",
                      ["report-incomplete"], data)
    if a.out:
        out = pathlib.Path(a.out)
        if out.exists() and not a.force:
            raise Refused(f"{out} exists; use --force to overwrite", ["out-exists"])
        try:
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(md + "\n", encoding="utf-8", newline="\n")
        except OSError as e:
            raise UsageError(f"cannot write {out}: {e}")
        data["out"] = str(out)
        return ctx.reply(data, f"report written to {out}" + ("" if chk["ok"] else
                                                             f" (sections without content: {missing})"))
    return ctx.reply(data, md)
