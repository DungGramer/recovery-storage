"""Health verdict per snapshot: healthy | watch | degraded | failing | unknown (first matching rule wins).

Every signal found is listed as evidence (path, value, strength) even when an earlier rule decides.
A clean SMART report is not proof of health: Backblaze found 23.3% of failed drives with none of the five
key counters raised (researcher-05 §1), so `healthy` is capped at confidence medium and always names a next test.
Missing data never defaults to 0/false; it lands in `missing` and leads to `unknown`.
"""
from dataclasses import dataclass, field

from .delta import delta
from .wear import _devstat

ENDURANCE_WATCH = 80     # % used: approaching rated endurance (NVMe Percentage Used semantics)
ENDURANCE_DEGRADED = 100  # % used: rated endurance consumed (may exceed 100)
MEDIA_ATTRS = (5, 187, 197, 198)  # Backblaze-predictive media counters (researcher-05 §1)
LINK_ATTRS = (188, 199)           # command timeout / interface CRC: link, cable, bridge (weak)


@dataclass(frozen=True)
class Rule:
    id: str
    outcome: str
    confidence: str
    required_fields: tuple
    source: str


RULES = (
    Rule("H1-failing", "failing", "high",
         ("smart_status.passed", "ata_smart_attributes[*].value/thresh/when_failed",
          "nvme_smart_health_information_log.critical_warning", "available_spare/available_spare_threshold",
          "ata_smart_self_test_log", "delta"),
         "smartctl FAILED status / pre-fail threshold tripped; NVMe Base Spec critical warning bits 0 and 3; "
         "researcher-05 §3, §6"),
    Rule("H2-degraded", "degraded", "medium",
         ("ata_smart_attributes[5,187,197,198].raw", "nvme_smart_health_information_log.media_errors",
          "critical_warning bits 2,4,5", "percentage_used / devstat endurance", "delta"),
         "Backblaze SMART 5/187/197/198 raw > 0 (researcher-05 §1); NVMe media errors and warning bits"),
    Rule("H3-watch", "watch", "low",
         ("percentage_used / devstat endurance", "temperature.op_limit_max", "ata_smart_attributes[188,199].raw",
          "num_err_log_entries", "smartctl exit bits 5-7"),
         "endurance >= 80%, link/cable counters, historical error logs (researcher-05 §2-§4)"),
    Rule("H4-healthy", "healthy", "medium",
         ("smart_status.passed", "user_capacity.bytes", "protocol rule fields"),
         "collection ok, PASSED, required fields clean; capped at medium (Backblaze 23.3% silent failures)"),
    Rule("H5-unknown", "unknown", "low", (), "collection failed, SMART not exposed, protocol without rules, or "
                                                "overall status absent"),
)
RULE_BY_OUTCOME = {r.outcome: r for r in RULES}

NEXT_TESTS = {
    "healthy": "run an extended self-test or a full surface read (read-only), then re-collect and compare",
    "watch": "re-collect after the next use and compare the counters (compare --device)",
    "degraded": "secure the data first (image with ddrescue + mapfile), then re-collect and compare counters",
    "failing": "stop non-essential use; image the data first (ddrescue, mapfile) and re-collect to see if "
               "counters keep rising",
    "needs_elevation": "re-run collect from an elevated shell (Administrator / sudo)",
    "unsupported_bridge": "re-run collect elevated or with --dtype for the bridge; SMART may not be exposed by this "
                          "USB bridge",
    "not_exposed": "SMART is not exposed by this device; use a capacity/read verify (F3/H2testw) after data is "
                   "secured",
    "collection_failed": "check the connection and the device path, then re-run collect",
    "tool_missing": "install smartmontools and re-run collect",
    "timeout": "re-run collect; if the bridge hangs, try another port/enclosure",
    "malformed": "re-capture smartctl -j output and ingest it again",
    "standby": "re-run collect with --allow-spinup if spinning the disk up is acceptable",
    "unknown": "re-collect with smartctl 7.x JSON output",
    "no_rules": "no health rules for this protocol in v1; read the vendor tool output",
}


@dataclass
class HealthVerdict:
    verdict: str
    confidence: str
    evidence: list = field(default_factory=list)
    missing: list = field(default_factory=list)
    reason: str = ""
    next_test: str = ""
    rule_id: str = ""

    def to_dict(self):
        return {"verdict": self.verdict, "confidence": self.confidence, "evidence": self.evidence,
                "missing": self.missing, "reason": self.reason, "next_test": self.next_test, "rule_id": self.rule_id}


def _ev(path, value, strength):
    return {"path": path, "value": value, "strength": strength}


def _int(v):
    return v if isinstance(v, int) and not isinstance(v, bool) else None


def _protocol(rec):
    h = rec.health_fields or {}
    if any(k in h for k in ("critical_warning", "media_errors", "percentage_used")) or \
            (rec.identity or {}).get("protocol") == "NVMe":
        return "nvme"
    if h.get("attributes"):
        return "ata"
    return (rec.identity or {}).get("protocol") or None


def selftest_entries(rec):
    """[(path, status string, lifetime hours, failed)] from the ATA and NVMe self-test logs.
    failed = smartctl's `passed: false`, else a status naming a failure/error (electrical, servo, read, ...)."""
    out = []
    doc = rec.doc if isinstance(getattr(rec, "doc", None), dict) else {}
    ata = (((doc.get("ata_smart_self_test_log") or {}).get("standard") or {}).get("table")) or []
    for i, row in enumerate(ata if isinstance(ata, list) else []):
        if not isinstance(row, dict):
            continue
        status = row.get("status") if isinstance(row.get("status"), dict) else {}
        s = str(status.get("string") or "")
        low = s.lower()
        if isinstance(status.get("passed"), bool):
            failed = status["passed"] is False and "aborted by host" not in low and "interrupted" not in low
        else:  # older smartctl without `passed`: read the text, "Completed without error" is a pass
            failed = "without error" not in low and any(w in low for w in ("fail", "error"))
        out.append((f"ata_smart_self_test_log.standard.table[{i}].status.string", s, row.get("lifetime_hours"),
                    failed))
    nv = (doc.get("nvme_self_test_log") or {}).get("table") or []
    for i, row in enumerate(nv if isinstance(nv, list) else []):
        if not isinstance(row, dict):
            continue
        res = row.get("self_test_result") if isinstance(row.get("self_test_result"), dict) else {}
        s = str(res.get("string") or "")
        failed = res.get("value") not in (None, 0) and "abort" not in s.lower()
        out.append((f"nvme_self_test_log.table[{i}].self_test_result.string", s, row.get("power_on_hours"), failed))
    return out


def _selftest_failures(rec):
    return [_ev(path, s, "strong") for path, s, _, failed in selftest_entries(rec) if failed]


def verdict(rec, prev=None):
    st = rec.collection_status
    h = rec.health_fields or {}
    ev, missing = [], []
    hits = {"failing": [], "degraded": [], "watch": []}
    proto = _protocol(rec)

    passed = h.get("overall_passed")
    if passed is not None:
        ev.append(_ev("smart_status.passed", passed, "strong" if passed is False else "medium"))
        if passed is False:
            hits["failing"].append("smart_status.passed")

    attrs = h.get("attributes") or {}
    for aid in sorted(attrs):
        a = attrs[aid]
        val, thr, raw = _int(a.get("value")), _int(a.get("thresh")), _int(a.get("raw"))
        tripped = (thr is not None and thr > 0 and val is not None and val <= thr) or a.get("when_failed") == "now"
        if tripped:
            ev.append(_ev(f"ata_smart_attributes[{aid}].when_failed", a.get("when_failed") or "now", "strong"))
            ev.append(_ev(f"ata_smart_attributes[{aid}].value", val, "strong"))
            ev.append(_ev(f"ata_smart_attributes[{aid}].thresh", thr, "strong"))
            hits["failing"].append(f"attr {aid} tripped")
        if aid in MEDIA_ATTRS:
            ev.append(_ev(f"ata_smart_attributes[{aid}].raw", raw, "strong" if raw else "medium"))
            if raw:
                hits["degraded"].append(f"attr {aid} raw {raw}")
        elif aid in LINK_ATTRS:
            ev.append(_ev(f"ata_smart_attributes[{aid}].raw", raw, "weak"))
            if raw:
                hits["watch"].append(f"attr {aid} raw {raw}")
    # vendors expose different subsets (Samsung SSDs lack 197/198, WD HDDs lack 187): only 5 is required
    if proto == "ata" and 5 not in attrs:
        missing.append("ata_smart_attributes[5]")

    st_fail = _selftest_failures(rec)
    if st_fail:
        ev += st_fail
        hits["failing"].append("self-test read failure")

    nv = "nvme_smart_health_information_log"
    cw = _int(h.get("critical_warning"))
    if cw is not None:
        ev.append(_ev(f"{nv}.critical_warning", cw, "strong" if cw else "medium"))
        if cw & 0b1001:
            hits["failing"].append("critical_warning bit 0/3")
        if cw & 0b110100:
            hits["degraded"].append("critical_warning bit 2/4/5")
        if cw & 0b10:
            hits["watch"].append("critical_warning bit 1 (temperature)")
    spare, thr = _int(h.get("available_spare")), _int(h.get("available_spare_threshold"))
    if spare is not None:
        ev.append(_ev(f"{nv}.available_spare", spare, "medium"))
    if thr is not None:
        ev.append(_ev(f"{nv}.available_spare_threshold", thr, "weak"))
    if spare is not None and thr is not None and spare < thr:
        hits["failing"].append("available_spare below threshold")
    me = _int(h.get("media_errors"))
    if me is not None:
        ev.append(_ev(f"{nv}.media_errors", me, "strong" if me else "medium"))
        if me:
            hits["degraded"].append("media_errors > 0")
    nel = _int(h.get("num_err_log_entries"))
    if nel is not None:
        ev.append(_ev(f"{nv}.num_err_log_entries", nel, "weak"))
        if nel:
            hits["watch"].append("error log entries")
    if proto == "nvme":
        for k in ("critical_warning", "available_spare", "available_spare_threshold", "media_errors"):
            if h.get(k) is None:
                missing.append(f"{nv}.{k}")

    used = _int(h.get("percentage_used"))
    used_path = f"{nv}.percentage_used"
    if used is None:
        used = _devstat(rec, "Percentage Used Endurance Indicator")
        used_path = "ata_device_statistics.Percentage Used Endurance Indicator"
    if used is not None:
        ev.append(_ev(used_path, used, "medium"))
        if used >= ENDURANCE_DEGRADED:
            hits["degraded"].append("endurance consumed")
        elif used >= ENDURANCE_WATCH:
            hits["watch"].append("endurance >= 80%")

    temp, lim = _int(h.get("temperature")), _int(h.get("temperature_op_limit_max"))
    if temp is not None:
        ev.append(_ev("temperature.current", temp, "weak"))
        if lim is not None and temp >= lim:
            ev.append(_ev("temperature.op_limit_max", lim, "weak"))
            hits["watch"].append("temperature at/above operating limit")

    hist = sorted(f for f in rec.flags if f in ("attribute_failed_in_past", "error_log_has_records",
                                                "selftest_log_has_errors"))
    for f in hist:
        ev.append(_ev("smartctl.exit_status", f, "weak"))
    if hist:
        hits["watch"].append("smartctl history bits")

    if prev is not None and st == "ok" and prev.collection_status == "ok":
        d = delta(prev, rec)
        if d.valid:
            for f in d.rising:
                ev.append(_ev(f"delta.{f}", d.fields[f], "strong"))
            if len(d.rising) >= 2:
                hits["failing"].append("two or more media counters rising")
            elif d.rising:
                hits["degraded"].append("media counter rising")

    if (rec.identity or {}).get("bytes") is None:
        missing.append("user_capacity.bytes")
    if passed is None:
        missing.append("smart_status.passed")

    def done(outcome, reason="", next_key=None, confidence=None):
        r = RULE_BY_OUTCOME[outcome]
        return HealthVerdict(outcome, confidence or r.confidence, ev, sorted(set(missing)), reason,
                             NEXT_TESTS[next_key or outcome], r.id)

    if st not in ("ok",):
        return done("unknown", st, st if st in NEXT_TESTS else "unknown")
    for outcome in ("failing", "degraded"):
        if hits[outcome]:
            return done(outcome, "; ".join(hits[outcome]))
    if hits["watch"]:
        strong_watch = any("endurance" in x or "temperature" in x for x in hits["watch"])
        return done("watch", "; ".join(hits["watch"]), confidence="medium" if strong_watch else "low")
    if proto not in ("ata", "nvme"):
        return done("unknown", "no_rules", "no_rules")
    if passed is None or "user_capacity.bytes" in missing:
        return done("unknown", "overall status or capacity absent", "unknown")
    if missing:
        return done("unknown", "required fields absent: " + ", ".join(sorted(set(missing))), "unknown")
    return done("healthy", "collection ok, PASSED, required fields clean")
