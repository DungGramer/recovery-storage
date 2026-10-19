"""`rs.py rules`: rule tables, parameters and the wear whitelist rendered from the same objects the code evaluates
(thresholds live in code only; docs point here)."""
from . import health, triage, verdict, wear

PARAMETERS = [
    ("health.ENDURANCE_WATCH", health.ENDURANCE_WATCH, "% endurance used -> watch; NVMe Percentage Used semantics"),
    ("health.ENDURANCE_DEGRADED", health.ENDURANCE_DEGRADED, "% endurance used -> degraded (rated endurance consumed)"),
    ("health.MEDIA_ATTRS", ",".join(map(str, health.MEDIA_ATTRS)), "Backblaze-predictive SMART counters (researcher-05 §1)"),
    ("health.LINK_ATTRS", ",".join(map(str, health.LINK_ATTRS)), "link/cable/bridge counters, never a media verdict"),
    ("triage.ISOLATION_MIN", triage.ISOLATION_MIN, "isolation steps needed before 'not detected' means hardware"),
    ("triage.NOMINAL_MISMATCH_FACTOR", triage.NOMINAL_MISMATCH_FACTOR,
     "reported bytes below this share of nominal = gross capacity mismatch"),
    ("triage.SAFE_MODE_MODELS", ",".join(triage.SAFE_MODE_MODELS), "controller safe-mode identity (vendor-lab sources)"),
    ("verdict.CAPACITY_COVERAGE", verdict.CAPACITY_COVERAGE, "f3read verified share of device bytes for a flash PASS"),
    ("wear.NVME_DATA_UNIT_BYTES", wear.NVME_DATA_UNIT_BYTES, "NVMe Data Unit size (smartmontools nvmeprint.cpp)"),
]


def _rule(r):
    d = {"id": r.id, "outcome": r.outcome, "required_fields": list(r.required_fields), "source": r.source}
    if hasattr(r, "branch"):
        d["branch"] = r.branch
    return d


def cmd_rules(ctx, a):
    data = {
        "health_rules": [_rule(r) for r in health.RULES],
        "triage_rules": [_rule(r) for r in triage.RULES],
        "parameters": [{"name": n, "value": v, "source": s} for n, v, s in PARAMETERS],
        "wear_whitelist": [{"id": i, "name": n} for i, n in wear.WEAR_WHITELIST],
    }
    lines = ["health rules (first match wins):"]
    lines += [f"  {r['id']}: {r['outcome']} - {r['source']}" for r in data["health_rules"]]
    lines.append("triage rules (first match wins):")
    lines += [f"  {r['id']}: {r['outcome']}" + (f" (branch {r['branch']})" if r.get("branch") else "")
              + f" - {r['source']}" for r in data["triage_rules"]]
    lines.append("parameters:")
    lines += [f"  {p['name']} = {p['value']}  ({p['source']})" for p in data["parameters"]]
    lines.append("wear whitelist (normalised VALUE = % remaining):")
    lines += [f"  {w['id']} {w['name']}" for w in data["wear_whitelist"]]
    return ctx.reply(data, "\n".join(lines))
