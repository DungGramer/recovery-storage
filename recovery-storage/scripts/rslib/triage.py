"""Phase-1 triage class (first match wins), constraints, and cause hypotheses (spec §2.3 nine groups).

Triage answers "may the software path continue, and under which constraints"; health answers "how bad".
Decision Q5 (2026-10-19, risk-based): a failing-but-readable disk without mechanical symptoms stays a software
(imaging) candidate with image-first constraints, unless data is irreplaceable AND risk tolerance is low, or media
counters rise within the session. Environment facts (needs_elevation, unsupported_bridge) are not device evidence.
VID/PID values are never rule inputs. Counterfeit above `low` needs F3 write/read evidence.
"""
import re
from dataclasses import dataclass

from . import session as sess

STOP_SYMPTOMS = ("mechanical-noise", "not-spinning", "burning-smell", "physical-damage", "liquid-damage",
                 "overheating")
DETECT_SYMPTOMS = ("not-detected", "disconnects-repeatedly")
ISOLATION_MIN = 2
NOMINAL_MISMATCH_FACTOR = 0.5  # reported bytes < half the nominal capacity = gross mismatch
# controller safe-mode identity (Phison SATAFIRM S11: vendor-lab sources, researcher-04 §4)
SAFE_MODE_MODELS = ("SATAFIRM S11",)
SOFTWARE_STATUSES = ("ok", "not_exposed", "unsupported_bridge", "needs_elevation")
ENV_STATUSES = ("not_exposed", "unsupported_bridge", "needs_elevation")
CONF_RANK = {"high": 0, "medium": 1, "low": 2}


@dataclass(frozen=True)
class Rule:
    id: str
    outcome: str
    branch: object
    required_fields: tuple
    source: str


RULES = (
    Rule("T1-stop-unsafe", "STOP_UNSAFE", None, ("session.symptoms", "temperature.current",
                                                  "temperature.critical_limit_max"),
         "spec §4 rule 9 (mechanical signs: stop early); device-reported critical temperature limit"),
    Rule("T2a-not-detected-isolated", "HARDWARE_DIAGNOSIS_REQUIRED", "a",
         ("session.symptoms", "session.tried", "inventory_runs", "observation.no_media"),
         "spec Phase 1: not recognised after port/cable/host/OS isolation; card reader present with no medium "
         "after reseat/reader/host isolation (amendment 03)"),
    Rule("T2b-irreplaceable-low-tolerance", "HARDWARE_DIAGNOSIS_REQUIRED", "b",
         ("health.verdict", "session.effective_data_value", "session.risk_tolerance"),
         "decision Q5 2026-10-19: failing/degraded + irreplaceable data + low risk tolerance -> lab"),
    Rule("T2c-rising-in-session", "HARDWARE_DIAGNOSIS_REQUIRED", "c", ("delta (same session)",),
         "decision Q5: media counters rising while being handled = active degradation"),
    Rule("T3-controller", "CONTROLLER_RECOVERY_CANDIDATE", None,
         ("identity.bytes", "session.nominal_bytes", "critical_warning bit 3", "identity.model"),
         "0 bytes / gross capacity mismatch / NVMe media read-only / controller safe-mode identity"),
    Rule("T4-software", "SOFTWARE_RECOVERY_CANDIDATE", None, ("identity", "collection_status"),
         "identity readable; SMART may be ok, not exposed or need elevation"),
    Rule("T5-undetermined", "UNDETERMINED", None, (), "not enough evidence (spec Phase 1)"),
)
RULE = {r.id: r for r in RULES}


def _ev(path, value, strength="medium"):
    return {"path": path, "value": value, "strength": strength}


class Inputs:
    """Everything triage needs, gathered by assess.py (pure data)."""

    def __init__(self, session, rec, observation, health, session_deltas, absent, evidence, events, observed):
        self.session, self.rec, self.obs, self.health = session, rec, observation, health
        self.session_deltas, self.absent, self.evidence, self.events = session_deltas, absent, evidence, events
        self.observed = observed  # device seen by an OS enumeration at least once


def _identity(inp):
    rid = (inp.rec.identity if inp.rec is not None else {}) or {}
    obs = inp.obs or {}
    model = rid.get("model") or obs.get("model")
    nbytes = rid.get("bytes") if rid.get("bytes") is not None else obs.get("bytes")
    usb = obs.get("usb") or {}
    return model, nbytes, usb


def _cw(inp):
    h = (inp.rec.health_fields if inp.rec is not None else {}) or {}
    v = h.get("critical_warning")
    return v if isinstance(v, int) else None


def _bridge(inp):
    dtype = ((inp.rec.identity if inp.rec is not None else {}) or {}).get("device_type") or ""
    return dtype.startswith(("usb", "snt")) or (inp.obs or {}).get("fingerprint", {}).get("bus") == "usb"


def classify(inp):
    s = inp.session
    symptoms = set(s.get("symptoms") or [])
    tried = list(s.get("tried") or [])
    model, nbytes, usb = _identity(inp)
    readable = bool(model or (usb.get("vid") and usb.get("pid")))
    h = inp.rec.health_fields if inp.rec is not None else {}
    health = inp.health.verdict
    ev = []

    def out(rule_id, next_test, evidence):
        r = RULE[rule_id]
        return {"class": r.outcome, "rule_id": r.id, "branch": r.branch, "evidence": evidence + [_ev("rule", r.id)],
                "next_test": next_test}

    stop = sorted(symptoms & set(STOP_SYMPTOMS))
    if stop:
        return out("T1-stop-unsafe", "stop software actions on this device; get a hardware assessment (lab) before "
                                     "powering it again", [_ev("session.symptoms", stop, "strong")])
    temp, crit = h.get("temperature"), h.get("temperature_critical_limit_max") or h.get("temperature_critical")
    if isinstance(temp, int) and isinstance(crit, int) and temp >= crit:
        return out("T1-stop-unsafe", "power the device down and let it cool; find the cause of overheating before "
                                     "any further reads",
                   [_ev("temperature.current", temp, "strong"), _ev("temperature.critical_limit_max", crit, "strong")])

    det = sorted(symptoms & set(DETECT_SYMPTOMS))
    if det and inp.absent and len(tried) >= ISOLATION_MIN:
        return out("T2a-not-detected-isolated", "hardware diagnosis: power, PCB/bridge, connector (lab)",
                   [_ev("session.symptoms", det, "strong"), _ev("session.tried", tried, "strong"),
                    _ev("observation.absent_in_latest_inventory", True, "strong")])
    no_media = bool((inp.obs or {}).get("no_media")) and not inp.absent
    if no_media and "not-detected" in symptoms and len(set(tried)) >= ISOLATION_MIN:
        # reader present, medium never seen after isolation (amendment 03 A2, real run 2026-10-19)
        return out("T2a-not-detected-isolated",
                   "the card itself is not detected in any reader or host: card electronics/controller fault; no "
                   "software tool applies; data only through a lab (monolithic card: lab read)",
                   [_ev("observation.no_media", True, "strong"), _ev("session.symptoms", det, "strong"),
                    _ev("session.tried", tried, "strong")])
    if health in ("failing", "degraded") and readable and sess.effective_data_value(s) == "irreplaceable" \
            and s.get("risk_tolerance") == "low":
        return out("T2b-irreplaceable-low-tolerance",
                   "hand the device to a data-recovery lab; do not run imaging passes yourself",
                   [_ev("health.verdict", health, "strong"),
                    _ev("session.effective_data_value", "irreplaceable", "strong"),
                    _ev("session.risk_tolerance", "low", "strong")])
    for d in inp.session_deltas:
        if d.valid and d.rising:
            return out("T2c-rising-in-session", "stop repeated reads; image once with ddrescue (mapfile) or hand to a "
                                                "lab - counters are rising while the device is handled",
                       [_ev(f"delta.{f}", d.fields[f], "strong") for f in d.rising])

    if no_media:
        # an empty card reader (or a removable drive without medium) reports 0 bytes: not a controller fault
        nt = ("the reader reports no media: insert or reseat the card (check the adapter and its lock switch), then "
              "re-run inventory")
        missing = [t for t in sess.TRIED if t not in tried]
        if "not-detected" in symptoms and missing:
            nt += "; isolation steps not yet recorded: " + ", ".join(missing) + " (record with session --tried)"
        return out("T5-undetermined", nt, [_ev("observation.no_media", True, "strong")])
    if readable and not inp.absent:
        nominal = s.get("nominal_bytes")
        cw = _cw(inp)
        reasons = []
        if model and any(m.lower() == str(model).strip().lower() for m in SAFE_MODE_MODELS):
            reasons.append(_ev("identity.model", model, "strong"))
        if nbytes == 0:
            reasons.append(_ev("identity.bytes", 0, "strong"))
        elif isinstance(nbytes, int) and nominal and nbytes < NOMINAL_MISMATCH_FACTOR * nominal:
            reasons += [_ev("identity.bytes", nbytes, "strong"), _ev("session.nominal_bytes", nominal, "medium")]
        if cw is not None and cw & 0b1000:
            reasons.append(_ev("nvme_smart_health_information_log.critical_warning", cw, "strong"))
        if reasons:
            return out("T3-controller", "identify the controller exactly (VID/PID, controller and flash ids) before "
                                        "any tool; secure readable data first", reasons)

    status = inp.rec.collection_status if inp.rec is not None else None
    if readable and not inp.absent and isinstance(nbytes, int) and nbytes > 0:
        if status == "ok" or (status in ENV_STATUSES and inp.obs):
            nt = inp.health.next_test
            return out("T4-software", nt, [_ev("identity.model", model), _ev("identity.bytes", nbytes),
                                           _ev("collection_status", status)])

    missing = [t for t in sess.TRIED_CONNECTION if t not in tried]
    if det or inp.absent:
        nt = ("device not attached at the latest inventory; isolation steps not yet recorded: " +
              ", ".join(missing) + " (record with session --tried), then re-run inventory") if missing else \
             "reconnect the device and re-run inventory"
    elif inp.rec is None:
        nt = "run collect for this device (R0) to read identity and SMART"
    else:
        nt = inp.health.next_test or "re-collect"
    return out("T5-undetermined", nt, [_ev("collection_status", status, "weak")] +
               ([_ev("observation.absent_in_latest_inventory", True)] if inp.absent else []))


def constraints(inp, cls):
    s = inp.session
    out = []
    health = inp.health.verdict
    if health in ("failing", "degraded") or sess.preserves(s) or cls == "CONTROLLER_RECOVERY_CANDIDATE":
        out += ["image-before-any-write", "no-fs-repair-on-source"]
    if health == "failing":
        out += ["minimise-power-on", "stop-if-read-rate-collapses"]
    if _bridge(inp) and "encrypted-locked" in (s.get("symptoms") or []):
        out.append("keep-original-enclosure")
    if cls == "STOP_UNSAFE":
        out.append("no-software-actions")
    return list(dict.fromkeys(out))


# ------------------------------------------------------------------ hypotheses
def _event_names_device(item, obs):
    """Drive letters of this disk, Harddisk<N>/PhysicalDrive<N>, or the Linux device name in the message."""
    msg = str(item.get("message") or "")
    path = str((obs or {}).get("os_path") or "")
    names = []
    m = re.match(r"^/dev/pd(\d+)$", path)
    if m:
        names += [rf"\bHarddisk{m.group(1)}\b", rf"\bPhysicalDrive{m.group(1)}\b"]
    elif path.startswith("/dev/"):
        names.append(rf"\b{re.escape(path[5:])}\d*\b")
    for p in (obs or {}).get("partitions") or []:
        if p.get("drive_letter"):
            names.append(rf"(?<![A-Za-z]){re.escape(p['drive_letter'])}:")
    return any(re.search(n, msg, re.I) for n in names)


def _hyp(cat, conf, evidence, alternative, next_test):
    return {"category": cat, "confidence": conf, "evidence": evidence, "alternative": alternative,
            "next_test": next_test}


def hypotheses(inp, tri):
    s = inp.session
    symptoms = set(s.get("symptoms") or [])
    rec = inp.rec
    h = (rec.health_fields if rec is not None else {}) or {}
    ok = rec is not None and rec.collection_status == "ok"
    out = []

    phys = sorted(symptoms & {"mechanical-noise", "not-spinning", "burning-smell", "physical-damage",
                              "liquid-damage"})
    if phys:
        out.append(_hyp("physical-hardware", "medium", [_ev("session.symptoms", phys, "strong")],
                        "operator-reported sign with another cause (enclosure fan, bridge, power supply)",
                        "do not power the device again; lab inspection of heads/motor/PCB"))
    if tri["branch"] == "a":
        out.append(_hyp("physical-hardware", "medium", [e for e in tri["evidence"] if e["path"] != "rule"],
                        "a host-side driver problem not covered by the isolation steps",
                        "test on a live Linux system; if still absent, lab diagnosis of PCB/bridge/power"))

    attrs = h.get("attributes") or {}
    link = [_ev(f"ata_smart_attributes[{a}].raw", attrs[a]["raw"], "medium") for a in (188, 199)
            if a in attrs and isinstance(attrs[a].get("raw"), int) and attrs[a]["raw"] > 0]
    if ok and link:
        out.append(_hyp("connection-cable-power-bridge", "medium", link,
                        "historical link errors from an earlier cable; the counter never resets",
                        "change the cable and port (or the enclosure/bridge), re-collect and compare the attribute "
                        "199 delta"))
    det = sorted(symptoms & set(DETECT_SYMPTOMS))
    if det:
        out.append(_hyp("connection-cable-power-bridge", "low" if tri["branch"] == "a" else "medium",
                        [_ev("session.symptoms", det)],
                        "failing device electronics rather than the connection",
                        "try another port, cable, host and OS; record each with session --tried"))

    bad = []
    if ok:
        bad += [_ev(f"ata_smart_attributes[{a}].raw", attrs[a]["raw"], "strong") for a in (5, 187, 197, 198)
                if a in attrs and isinstance(attrs[a].get("raw"), int) and attrs[a]["raw"] > 0]
        bad += [e for e in inp.health.evidence if "self_test_log" in e["path"]]
    nvme_bad = isinstance(h.get("media_errors"), int) and h["media_errors"] > 0 and ok
    if nvme_bad:
        bad.append(_ev("nvme_smart_health_information_log.media_errors", h["media_errors"], "strong"))
    bad += [e for e in inp.health.evidence if e["path"].startswith("delta.")]
    for e in inp.evidence:
        p = (e["data"] or {}).get("parsed") or {}
        if e["kind"] == "ddrescue" and p.get("bad"):
            bad.append(_ev("evidence.ddrescue.bad", p["bad"], "strong"))
    if "io-errors" in symptoms:
        bad.append(_ev("session.symptoms", ["io-errors"], "weak"))
    if bad:
        conf = "high" if inp.health.verdict == "failing" else "medium"
        if nvme_bad:
            alt, nt = "historical errors, now stable", "re-collect after a full read, compare media_errors delta"
        else:
            alt = "historical errors, now stable (remapped sectors that are no longer growing)"
            nt = "image with ddrescue (mapfile) once, then re-collect and compare the 5/197/198 delta"
        out.append(_hyp("bad-sectors-io", conf, bad, alt, nt))

    model, nbytes, _ = _identity(inp)
    ctl = [e for e in tri["evidence"] if tri["class"] == "CONTROLLER_RECOVERY_CANDIDATE" and e["path"] != "rule"]
    if ctl:
        out.append(_hyp("controller-or-firmware", "medium", ctl,
                        "a bridge/enclosure fault reporting wrong identity or capacity",
                        "connect directly (no bridge) or on another host; identify the controller before any tool"))

    cw = _cw(inp)
    locked = []
    if cw is not None and cw & 0b1000:
        locked.append(_ev("nvme_smart_health_information_log.critical_warning", cw, "strong"))
    if (inp.obs or {}).get("is_readonly") is True:
        locked.append(_ev("observation.is_readonly", True, "medium"))
    if "read-only" in symptoms:
        locked.append(_ev("session.symptoms", ["read-only"], "medium"))
    if locked:
        out.append(_hyp("write-locked", "high" if cw is not None and cw & 0b1000 else "medium", locked,
                        "an OS policy or write-protect switch rather than the device (check before blaming media)",
                        "check the physical switch, Get-Disk IsReadOnly / diskpart attributes, then the controller "
                        "lock; secure data while it is still readable"))

    nand = []
    used = h.get("percentage_used")
    if ok and isinstance(used, int) and used >= 80:
        nand.append(_ev("nvme_smart_health_information_log.percentage_used", used, "medium"))
    if ok and cw is not None and cw & 0b100:
        nand.append(_ev("nvme_smart_health_information_log.critical_warning", cw, "strong"))
    spare, thr = h.get("available_spare"), h.get("available_spare_threshold")
    if ok and isinstance(spare, int) and isinstance(thr, int) and spare < thr:
        nand.append(_ev("nvme_smart_health_information_log.available_spare", spare, "strong"))
    fake = []
    for e in inp.evidence:
        p = (e["data"] or {}).get("parsed") or {}
        if e["kind"] == "f3probe" and p.get("result") == "damaged":
            nand.append(_ev("evidence.f3probe.result", "damaged", "strong"))
        if e["kind"] == "f3probe" and p.get("result") == "fake":
            fake.append((_ev("evidence.f3probe.fake_type", p.get("fake_type"), "strong"), "high"))
        if e["kind"] == "f3read" and p.get("result") == "fail" and (p.get("overwritten_bytes") or 0) > 0:
            fake.append((_ev("evidence.f3read.overwritten_bytes", p["overwritten_bytes"], "strong"), "medium"))
        if e["kind"] == "attested" and p.get("result") == "fail":
            fake.append((_ev("evidence.attested.result", f"{p.get('tool')} fail", "weak"), "low"))
    if nand:
        out.append(_hyp("nand-degradation", "medium", nand, "a controller/firmware fault or a bad bridge",
                        "secure the data, then a full write/read verify (F3) when data loss is acceptable"))
    if "wrong-capacity" in symptoms:
        fake.append((_ev("session.symptoms", ["wrong-capacity"], "weak"), "low"))
    nominal = s.get("nominal_bytes")
    if isinstance(nbytes, int) and nominal and nbytes and nbytes < NOMINAL_MISMATCH_FACTOR * nominal:
        fake.append((_ev("identity.bytes", nbytes, "weak"), "low"))
    if fake:
        conf = sorted((c for _, c in fake), key=lambda c: CONF_RANK[c])[0]
        out.append(_hyp("fake-capacity-or-counterfeit", conf, [e for e, _ in fake],
                        "a genuine but failing device (damaged NAND or controller), not a counterfeit",
                        "full-capacity write/read verify with F3 (f3probe on Linux, or f3write/f3read / H2testw) "
                        "after data is secured"))

    if "encrypted-locked" in symptoms:
        out.append(_hyp("encryption-or-protection", "medium", [_ev("session.symptoms", ["encrypted-locked"])],
                        "filesystem damage that only looks like a locked volume",
                        "check BitLocker/LUKS/hardware encryption status read-only (manage-bde -status, header on an "
                        "image); keep bridge-encrypted drives in their original enclosure"))

    fs = []
    obs = inp.obs or {}
    if obs.get("fs_unrecognised"):
        fs.append(_ev("observation.fs_unrecognised", True, "medium"))
        for i, p in enumerate(obs.get("partitions") or []):
            if p.get("mbr_type") is not None:
                fs.append(_ev(f"observation.partitions[{i}].mbr_type", p["mbr_type"], "medium"))
    sym_fs = sorted(symptoms & {"raw-or-unreadable-fs", "missing-partition", "deleted-files"})
    if sym_fs:
        fs.append(_ev("session.symptoms", sym_fs, "medium"))
    for item in inp.events:
        # host-wide log: an event counts for this device only when its message names the device
        if item.get("tag") == "fs_corruption" and _event_names_device(item, obs):
            fs.append(_ev("observation.events.fs_corruption", f"{item.get('provider')} {item.get('id')}", "medium"))
    if fs:
        out.append(_hyp("partition-or-filesystem", "medium", fs,
                        "controller returns garbage / fake-capacity wrap corrupted the FS",
                        "image or read-only inspect, then capacity verify after data is secured"))

    merged = {}
    for x in out:
        cur = merged.get(x["category"])
        if cur is None:
            merged[x["category"]] = x
        else:
            cur["evidence"] += [e for e in x["evidence"] if e not in cur["evidence"]]
            if CONF_RANK[x["confidence"]] < CONF_RANK[cur["confidence"]]:
                cur["confidence"] = x["confidence"]
    for x in merged.values():
        x["evidence"] = _collapse(x["evidence"])
    return sorted(merged.values(), key=lambda x: (CONF_RANK[x["confidence"]], x["category"]))


def _collapse(items):
    """Same path + value once, with `count` when repeated (amendment 05 R5: one item per matching OS event)."""
    out, seen = [], {}
    for e in items:
        key = (e["path"], repr(e["value"]))
        if key in seen:
            seen[key]["count"] = seen[key].get("count", 1) + 1
        else:
            seen[key] = dict(e)
            out.append(seen[key])
    return out


def evidence_text(e, fmt=str):
    """`path=value`, plus ` (xN)` for a collapsed item (R5)."""
    return f"{e['path']}={fmt(e['value'])}" + (f" (x{e['count']})" if e.get("count", 1) > 1 else "")
