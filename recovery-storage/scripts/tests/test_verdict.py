"""Phase 04 verdict evidence matrix (D21-D27). Spec: phase-04 Requirements 'Verdict', 'PASS requires', decision Q3,
spec §2 Phase 5 + §8 'format success is not recovery' + D21-D27."""
import pytest

from conftest import (BASELINE, MAP_990, MAP_FINISHED, USB_STICK, close, collect, confirm, fx, gate_ok, ingest_smart,
                      inventory, new_session, ok, prepared)

DEVREC = ("--goal", "device-recovery", "--preserve-data", "no", "--ceiling", "R2")


def formatted_stick(cli, *flags):
    sid, dev, _ = prepared(cli, USB_STICK, "/dev/pd2", *(flags or DEVREC))
    g, _ = gate_ok(cli, USB_STICK, sid, dev, "format")
    assert confirm(cli, USB_STICK, g, "8054112256").code == 0
    assert close(cli, USB_STICK, g, "success").code == 0
    return sid, dev


def attest(cli, sid, dev, tmp_path, result="pass", name="h2testw.txt"):
    f = tmp_path / name
    f.write_bytes(b"operator attachment: H2testw result window transcript (" + name.encode() + b")")
    return ok(cli("ingest", "attested", sid, dev, "--tool", "h2testw", "--result", result, "--file", f,
                  answers=["YES"]))  # amendment 01 A: the human attests


def replug(cli, sid):
    inventory(cli, cli.runner(USB_STICK), sid, after_replug=True)
    inventory(cli, cli.runner(USB_STICK), sid)


def test_D21_format_success_is_not_evidence(cli):
    """D21 + §8. Mutation: closed format gate with outcome success counted as verify -> PASS -> red."""
    sid, dev = formatted_stick(cli)
    res = cli("verdict", "set", sid, dev, "PASS")
    assert res.code == 3, res
    assert {"capacity-verify-missing", "replug-observation-missing"} <= res.reasons


def test_D22_attested_h2testw_after_gate_and_replug_pass(cli, tmp_path):
    """D22 via the attested H2testw path (decision Q3). Mutation: attested evidence not accepted for usb class -> red."""
    sid, dev = formatted_stick(cli)
    attest(cli, sid, dev, tmp_path)
    replug(cli, sid)
    res = cli("verdict", "set", sid, dev, "PASS")
    assert res.code == 0, res
    assert ok(cli("verdict", "show", sid, dev))["effective"] == "PASS"


def test_D22_evidence_before_last_r2_gate_refused(cli, tmp_path):
    """D22 'evidence dated before the last R2 gate -> evidence-before-recovery' (attested proxy; f3read case blocked).
    Mutation: evidence window ignores the gate time -> PASS -> red."""
    sid, dev, _ = prepared(cli, USB_STICK, "/dev/pd2", *DEVREC)
    attest(cli, sid, dev, tmp_path)
    g, _ = gate_ok(cli, USB_STICK, sid, dev, "format")
    assert confirm(cli, USB_STICK, g, "8054112256").code == 0
    assert close(cli, USB_STICK, g, "success").code == 0
    replug(cli, sid)
    res = cli("verdict", "set", sid, dev, "PASS")
    assert res.code == 3, res
    assert "evidence-before-recovery" in res.reasons


def test_D22_attested_fail_is_not_pass_evidence(cli, tmp_path):
    """Matrix 'attested H2testw pass'. Mutation: any attested record counts -> red."""
    sid, dev = formatted_stick(cli)
    attest(cli, sid, dev, tmp_path, result="fail")
    replug(cli, sid)
    res = cli("verdict", "set", sid, dev, "PASS")
    assert res.code == 3 and "capacity-verify-missing" in res.reasons, res


def test_D22_replug_observation_required(cli, tmp_path):
    """Common item 'at least one taken with inventory --after-replug'. Mutation: any 2 observations suffice -> red."""
    sid, dev = formatted_stick(cli)
    attest(cli, sid, dev, tmp_path)
    inventory(cli, cli.runner(USB_STICK), sid)
    inventory(cli, cli.runner(USB_STICK), sid)
    res = cli("verdict", "set", sid, dev, "PASS")
    assert res.code == 3 and "replug-observation-missing" in res.reasons, res


@pytest.mark.skip(reason="BLOCKED (open question F3-numbers): f3read pass with coverage >= 0.9 x device bytes needs a "
                         "real f3read output with Data OK amounts; research quotes labels only.")
def test_D22_f3read_pass_covering_90pct_after_gate_pass():
    """D22 'USB stick with f3read pass covering >= 0.9 x bytes after the last R2 gate + after-replug -> PASS'."""


@pytest.mark.skip(reason="BLOCKED (open question F3-numbers): f3read evidence dated before the last R2 gate; needs a "
                         "real f3read output.")
def test_D22_f3read_before_gate_evidence_before_recovery():
    """D22 'Same f3read evidence dated before the last R2 gate -> refused evidence-before-recovery'."""


def test_D23_hdd_without_new_selftest_refused(cli):
    """D23 (scrutiny-ata-hdd-healthy: newest self-test 1708 h < POH 1730). Mutation: accept any 'Completed without error' -> red."""
    sid = new_session(cli)
    dev = ingest_smart(cli, sid, "smartctl/scrutiny-ata-hdd-healthy.json").data["device_id"]
    res = cli("verdict", "set", sid, dev, "PASS")
    assert res.code == 3, res
    assert "selftest-missing" in res.reasons


def test_D23_hdd_counters_rising_refused(cli):
    """D23 (derived post snapshot 197 0 -> 1). Mutation: delta not checked for hdd -> red."""
    sid = new_session(cli)
    dev = ingest_smart(cli, sid, "smartctl/scrutiny-ata-hdd-healthy.json").data["device_id"]
    assert ingest_smart(cli, sid, "smartctl/scrutiny-ata-hdd-healthy.p197-1.derived.json").data["device_id"] == dev
    res = cli("verdict", "set", sid, dev, "PASS")
    assert res.code == 3, res
    assert "counters-rising" in res.reasons


def nvme0_flow(cli, post_override=None, mapfile=MAP_990):
    """990 PRO (/dev/pd0) + full-read ddrescue map (amendment 01 B: must cover the device) + replug + post snapshot."""
    sid, dev, _ = prepared(cli, BASELINE, "/dev/pd0", "--goal", "health-assessment")
    ok(cli("ingest", "ddrescue", sid, dev, fx(mapfile)))
    inventory(cli, cli.runner(BASELINE), sid, after_replug=True)
    collect(cli, BASELINE, sid, dev, override=post_override)
    return sid, dev


def test_D24_nvme_full_read_and_replug_pass(cli):
    """D24. Mutation: nvme class requires self-test like hdd, or ddrescue evidence ignored -> red."""
    sid, dev = nvme0_flow(cli)
    res = cli("verdict", "set", sid, dev, "PASS")
    assert res.code == 0, res


def test_D24_nvme_critical_warning_post_snapshot_refused(cli):
    """D24 (derived critical_warning 4 post snapshot). Mutation: matrix ignores critical_warning -> PASS -> red."""
    sid, dev = nvme0_flow(cli, {"pd0": f"{BASELINE}/smartctl-x-pd0.cw4.derived.json"})
    res = cli("verdict", "set", sid, dev, "PASS")
    assert res.code == 3, res


def test_D24b_nvme_floppy_mapfile_is_not_a_read_verify(cli):
    """Amendment 01 B 'Verdict SSD/NVMe read verify: a ddrescue record counts only when mapfile_complete is true for
    the device'. Same flow as D24 with the finished floppy map (1474560 of 1000204886016 B).
    Mutation: read verify = finished + bad 0 only (pre-amendment) -> PASS -> red."""
    sid, dev = nvme0_flow(cli, mapfile=MAP_FINISHED)
    res = cli("verdict", "set", sid, dev, "PASS")
    assert res.code == 3, res
    assert ok(cli("verdict", "show", sid, dev))["effective"] != "PASS"


def test_D24_nvme_without_read_verify_refused(cli):
    """Matrix ssd/nvme 'one read verify'. Mutation: read verify optional -> red."""
    sid, dev, _ = prepared(cli, BASELINE, "/dev/pd0", "--goal", "health-assessment")
    inventory(cli, cli.runner(BASELINE), sid, after_replug=True)
    collect(cli, BASELINE, sid, dev)
    res = cli("verdict", "set", sid, dev, "PASS")
    assert res.code == 3, res


def test_D25_class_unknown_classify_first(cli):
    """D25 (scrutiny-sat-partial: no rotation_rate -> class unknown). Mutation: default class hdd -> red."""
    sid = new_session(cli)
    dev = ingest_smart(cli, sid, "smartctl/scrutiny-sat-partial.json").data["device_id"]
    res = cli("verdict", "set", sid, dev, "PASS")
    assert res.code == 3, res
    assert "classify-device-first" in res.reasons


def test_D25_class_conflicting_with_declared_classify_first(cli, tmp_path):
    """Matrix 'class ... conflicting with declared: refused classify-device-first' (B18b conflict). Mutation: detected wins -> red."""
    sid, dev = formatted_stick(cli, "--goal", "device-recovery", "--preserve-data", "no", "--ceiling", "R2",
                               "--device-type", "hdd")
    attest(cli, sid, dev, tmp_path)
    replug(cli, sid)
    res = cli("verdict", "set", sid, dev, "PASS")
    assert res.code == 3, res
    assert "classify-device-first" in res.reasons


def test_D26_pass_limited_requires_limitation(cli):
    """D26. Mutation: limitation optional -> red."""
    sid = new_session(cli)
    dev = ingest_smart(cli, sid, "smartctl/nvme-990pro-x.json").data["device_id"]
    assert cli("verdict", "set", sid, dev, "PASS_LIMITED", json_out=False).code == 2
    assert cli("verdict", "set", sid, dev, "PASS_LIMITED", "--limitation", "read-only archive use").code == 0


def test_D26_pass_limited_refused_when_latest_health_failing(cli):
    """D26. Mutation: PASS_LIMITED ignores health -> red."""
    sid = new_session(cli)
    dev = ingest_smart(cli, sid, "smartctl/scrutiny-usbjmicron-hdd-failing.json").data["device_id"]
    res = cli("verdict", "set", sid, dev, "PASS_LIMITED", "--limitation", "spare only")
    assert res.code == 3, res


@pytest.mark.parametrize("status", ["FAIL", "REPAIR_REQUIRED", "UNRESOLVED", "RETIRED"])
def test_D26_other_statuses_require_reason(cli, status):
    """D26 'FAIL/RETIRED without --reason -> exit 2' (+ REPAIR_REQUIRED/UNRESOLVED per Requirements)."""
    sid = new_session(cli)
    dev = ingest_smart(cli, sid, "smartctl/nvme-990pro-x.json").data["device_id"]
    assert cli("verdict", "set", sid, dev, status, json_out=False).code == 2
    assert cli("verdict", "set", sid, dev, status, "--reason", "operator decision").code == 0


def test_verdict_status_enum(cli):
    """Spec Phase 5 final statuses only. Mutation: accept 'FIXED' -> red."""
    sid = new_session(cli)
    dev = ingest_smart(cli, sid, "smartctl/nvme-990pro-x.json").data["device_id"]
    assert cli("verdict", "set", sid, dev, "FIXED", "--reason", "x", json_out=False).code == 2


def test_D27_show_history_newest_first_latest_effective(cli):
    """D27. Mutation: oldest first, or effective = first set -> red."""
    sid = new_session(cli)
    dev = ingest_smart(cli, sid, "smartctl/nvme-990pro-x.json").data["device_id"]
    ok(cli("verdict", "set", sid, dev, "FAIL", "--reason", "first"))
    ok(cli("verdict", "set", sid, dev, "RETIRED", "--reason", "second"))
    d = ok(cli("verdict", "show", sid, dev))
    assert [v["status"] for v in d["verdicts"]] == ["RETIRED", "FAIL"]
    assert d["effective"] == "RETIRED"
