"""Phase 04 verdict evidence matrix (D21-D27). Spec: phase-04 Requirements 'Verdict', 'PASS requires', decision Q3,
spec §2 Phase 5 + §8 'format success is not recovery' + D21-D27."""
import datetime as dt
import json
import pathlib

import pytest

from conftest import (BASELINE, MAP_990, MAP_FINISHED, STICK_PHRASE, USB_STICK, close, collect, confirm, fx,
                      fx_json, gate_ok, ingest_smart, inventory, new_session, ok, prepared)

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


# Amendment 06: real F3 8.0 outputs (fixtures/f3, SOURCES.md). Stick 8054112256 B; Data OK 8050743296 B = 0.9996 x.
F3READ_PASS = "f3/f3read-stick-pass.txt"
F3READ_CARD_LOST = "f3/f3read-card-lost.txt"
F3WRITE_FULL = "f3/f3write-stick-volume-full.txt"


def ingest_f3(cli, sid, dev, kind, rel, code=0):
    """Amendment 08: the log is written when the run ends, i.e. now on the test clock. Ingest a temp copy (bytes
    unchanged) whose mtime is the current FakeClock time, so the f3read moment (min(ingest ts, output_mtime)) equals
    the ingest order the test scripts; the frozen fixture's checkout mtime never decides."""
    import os
    import shutil

    d = pathlib.Path(cli.home).parent / "f3-logs"
    d.mkdir(parents=True, exist_ok=True)
    p = d / pathlib.Path(rel).name
    shutil.copyfile(fx(rel), p)
    ts = cli.clock.now.timestamp()
    os.utime(p, (ts, ts))
    return ok(cli("ingest", kind, sid, dev, p, "--exit-code", code))["evidence"]


def test_D22_f3read_pass_covering_90pct_after_gate_pass(cli):
    """D22 'USB stick with f3read pass covering >= 0.9 x bytes after the last R2 gate + after-replug -> PASS'
    (unblocked by amendment 06 F4: real f3read pass). Mutation: f3read evidence not a capacity verify, or coverage
    computed in sectors instead of bytes -> capacity-verify-missing -> red."""
    sid, dev = formatted_stick(cli)
    replug(cli, sid)   # amendment 07 G1: the replug lies between the window anchor and the f3read ingest
    assert ingest_f3(cli, sid, dev, "f3read", F3READ_PASS)["parsed"]["result"] == "pass"
    res = cli("verdict", "set", sid, dev, "PASS")
    assert res.code == 0, res


def test_D22_f3read_before_gate_evidence_before_recovery(cli):
    """D22 'Same f3read evidence dated before the last R2 gate -> refused evidence-before-recovery' (amendment 06 F4).
    Mutation: evidence window ignores the format close for f3read records -> PASS -> red."""
    sid, dev, _ = prepared(cli, USB_STICK, "/dev/pd2", *DEVREC)
    ingest_f3(cli, sid, dev, "f3read", F3READ_PASS)
    g, _ = gate_ok(cli, USB_STICK, sid, dev, "format")
    assert confirm(cli, USB_STICK, g, STICK_PHRASE).code == 0
    assert close(cli, USB_STICK, g, "success").code == 0
    replug(cli, sid)
    res = cli("verdict", "set", sid, dev, "PASS")
    assert res.code == 3, res
    assert "evidence-before-recovery" in res.reasons, res


def test_D22e_verdict_uses_the_current_parser_not_the_stored_parse(cli, home):
    """Amendment 06 F5 (decision: re-parse on read): a stick f3read row whose stored parse came from an older parser
    (stored `inconclusive`) is re-parsed from its blob by `verdict set` -> the real pass counts -> PASS. Amendment 07
    G1: the replug comes before the f3read ingest (anchor = window start after the format).
    Mutation: verdict reads the stored parse -> capacity-verify-missing -> red."""
    from conftest import F3READ_OLD_INCONCLUSIVE, make_parsed_stale

    sid, dev = formatted_stick(cli)
    replug(cli, sid)
    ev = ingest_f3(cli, sid, dev, "f3read", F3READ_PASS)
    make_parsed_stale(home, ev["id"], F3READ_OLD_INCONCLUSIVE)
    res = cli("verdict", "set", sid, dev, "PASS")
    assert res.code == 0, res


@pytest.mark.parametrize("code", [0, 1])
def test_D22d_f3read_with_data_lost_never_satisfies_capacity_verify(cli, code):
    """Amendment 06 F3: the real card f3read (exit 0, 7079816 sectors lost) is a fail record and never a capacity
    verify, after the gate and replug. Mutation: exit 0 + Data OK > 0 read as pass -> PASS -> red."""
    sid, dev = formatted_stick(cli)
    assert ingest_f3(cli, sid, dev, "f3read", F3READ_CARD_LOST, code)["parsed"]["result"] == "fail"
    replug(cli, sid)
    res = cli("verdict", "set", sid, dev, "PASS")
    assert res.code == 3, res
    assert "capacity-verify-missing" in res.reasons, res


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


# ---------------- D22b (amendment 02 B, N9): a confirmed-then-aborted write gate moves the verdict window
def test_D22b_write_gate_aborted_after_confirm_moves_the_window(cli, tmp_path):
    """Amendment 02 B 'Verdict window start = max(session start, last_write_ts(device))', last_write_ts including an
    aborted write gate that had been confirmed. The H2testw attestation precedes that aborted format gate.
    Mutation: aborted gates ignored for the window (reviewer scen2.py #3) -> PASS -> red."""
    sid, dev = formatted_stick(cli)
    attest(cli, sid, dev, tmp_path)
    g, _ = gate_ok(cli, USB_STICK, sid, dev, "format")
    assert confirm(cli, USB_STICK, g, "8054112256").code == 0
    assert ok(cli("gate", "abort", g, "--reason", "format stopped midway"))["gate"]["state"] == "aborted"
    replug(cli, sid)
    res = cli("verdict", "set", sid, dev, "PASS")
    assert res.code == 3, res
    assert "evidence-before-recovery" in res.reasons, res


def test_D22b_write_gate_aborted_while_pending_leaves_the_window(cli, tmp_path):
    """Counter-case: aborted before confirm (`confirmed_ts` unset) is not a write, so the D22 PASS flow still passes.
    Mutation: every aborted gate moves the window -> evidence-before-recovery -> red."""
    sid, dev = formatted_stick(cli)
    attest(cli, sid, dev, tmp_path)
    g, _ = gate_ok(cli, USB_STICK, sid, dev, "format")
    assert ok(cli("gate", "abort", g, "--reason", "changed plan"))["gate"]["state"] == "aborted"
    replug(cli, sid)
    res = cli("verdict", "set", sid, dev, "PASS")
    assert res.code == 0, res


# ---------------- D22c (amendment 04): a verification gate's writes ARE the capacity test
# Spec: plans/.../amendment-04-verification-gate-window.md, CONTRACT.md "Amendment 04". Capacity evidence = attested
# H2testw; the f3read form uses the real F3 8.0 output of amendment 06.
VERIFY_KINDS = ["f3write-f3read", "h2testw", "f3probe", "f3probe-destructive"]
OTHER_WRITE_KINDS = [("format", ()), ("partition-write", ()), ("fs-repair-on-source", ()), ("clear-disk", ()),
                     ("firmware-update", ("--controller-id", "vendor-ctrl-1", "--tool-source", "vendor site")),
                     ("mptool-reflash", ("--controller-id", "vendor-ctrl-1", "--tool-source", "vendor site"))]


def _confirmed(cli, sid, dev, kind, *extra):
    g, _ = gate_ok(cli, USB_STICK, sid, dev, kind, *extra)
    res = confirm(cli, USB_STICK, g, STICK_PHRASE)
    assert res.code == 0 and res.data["gate"]["state"] == "open", res
    return g


def _closed(cli, g, outcome="success", *extra):
    res = close(cli, USB_STICK, g, outcome, *extra)
    assert res.code == 0 and res.data["gate"]["state"] == "closed", res
    return res


def _pass(cli, sid, dev):
    replug(cli, sid)
    return cli("verdict", "set", sid, dev, "PASS")


@pytest.mark.parametrize("kind", VERIFY_KINDS)
def test_D22c_capacity_evidence_ingested_inside_the_verification_gate_passes(cli, tmp_path, kind):
    """Amendment 04 B1 (real run 2026-10-19, stick, gate f3write-f3read): open -> confirm -> run tool -> ingest -> close
    success [--evidence id] -> replug -> PASS. Window start = the gate's confirmed_ts, not its close.
    Mutation: window start stays the close of every writes-source gate (pre-amendment) -> evidence-before-recovery
    -> red; credit given to f3write-f3read only -> other kinds red."""
    sid, dev, _ = prepared(cli, USB_STICK, "/dev/pd2", *DEVREC)
    g = _confirmed(cli, sid, dev, kind)
    ev = attest(cli, sid, dev, tmp_path, name=f"h2testw-{kind}.txt")["evidence"]["id"]
    _closed(cli, g, "success", "--evidence", ev)
    res = _pass(cli, sid, dev)
    assert res.code == 0, res
    assert ok(cli("verdict", "show", sid, dev))["effective"] == "PASS"


def test_D22c_verification_after_an_earlier_format_passes(cli, tmp_path):
    """Amendment 04 B1 + B2: format closed (write), then a verification gate with evidence after its confirm. The
    window start is the max over writes; the verification gate contributes its confirmed_ts (later than the format
    close). Mutation: confirm credit only when the verification gate is the device's only write -> red."""
    sid, dev = formatted_stick(cli)
    g = _confirmed(cli, sid, dev, "f3write-f3read")
    attest(cli, sid, dev, tmp_path)
    _closed(cli, g)
    res = _pass(cli, sid, dev)
    assert res.code == 0, res


@pytest.mark.parametrize("kind,extra", OTHER_WRITE_KINDS, ids=[k for k, _ in OTHER_WRITE_KINDS])
def test_D22c_other_write_gate_close_still_starts_the_window(cli, tmp_path, kind, extra):
    """Amendment 04 B2: any other writes-source gate keeps today's rule (its close is the window start); evidence
    ingested between its confirm and close -> evidence-before-recovery. Mutation: confirm credit applied to every
    writes-source kind -> PASS -> red."""
    sid, dev, _ = prepared(cli, USB_STICK, "/dev/pd2", *DEVREC)
    g = _confirmed(cli, sid, dev, kind, *extra)
    attest(cli, sid, dev, tmp_path)
    _closed(cli, g)
    res = _pass(cli, sid, dev)
    assert res.code == 3, res
    assert "evidence-before-recovery" in res.reasons, res


@pytest.mark.parametrize("end", ["failed", "interrupted", "abort"])
def test_D22c_unsuccessful_verification_gate_gives_no_credit(cli, tmp_path, end):
    """Amendment 04 B3: verification gate closed failed / interrupted, or aborted after confirm -> its close / abort is
    the window start; evidence ingested after the confirm -> evidence-before-recovery. Mutation: credit for any
    confirmed verification gate regardless of outcome -> PASS -> red."""
    sid, dev, _ = prepared(cli, USB_STICK, "/dev/pd2", *DEVREC)
    g = _confirmed(cli, sid, dev, "f3write-f3read")
    attest(cli, sid, dev, tmp_path)
    if end == "abort":
        assert ok(cli("gate", "abort", g, "--reason", "f3write stopped midway"))["gate"]["state"] == "aborted"
    else:
        _closed(cli, g, end)
    res = _pass(cli, sid, dev)
    assert res.code == 3, res
    assert "evidence-before-recovery" in res.reasons, res


def test_D22c_later_format_moves_the_window_past_f3_evidence(cli, tmp_path):
    """Amendment 04 B5: verification gate success with evidence, then a format gate closed -> the format close is the
    window start again -> evidence-before-recovery. Mutation: window start = latest verification confirm, ignoring
    later writes -> PASS -> red."""
    sid, dev, _ = prepared(cli, USB_STICK, "/dev/pd2", *DEVREC)
    g = _confirmed(cli, sid, dev, "f3write-f3read")
    attest(cli, sid, dev, tmp_path)
    _closed(cli, g)
    f = _confirmed(cli, sid, dev, "format")
    _closed(cli, f)
    res = _pass(cli, sid, dev)
    assert res.code == 3, res
    assert "evidence-before-recovery" in res.reasons, res


@pytest.mark.parametrize("when", ["before-open", "between-open-and-confirm"])
def test_D22c_evidence_before_the_verification_confirm_does_not_count(cli, tmp_path, when):
    """Amendment 04 B6: evidence ingested before the verification gate was confirmed does not count.
    Mutation: window start = the gate's open (created) time -> between-open-and-confirm PASS -> red; window start =
    session start / no window for verification gates -> both red."""
    sid, dev, _ = prepared(cli, USB_STICK, "/dev/pd2", *DEVREC)
    if when == "before-open":
        attest(cli, sid, dev, tmp_path)
    g, _ = gate_ok(cli, USB_STICK, sid, dev, "f3write-f3read")
    if when == "between-open-and-confirm":
        attest(cli, sid, dev, tmp_path)
    res = confirm(cli, USB_STICK, g, STICK_PHRASE)
    assert res.code == 0 and res.data["gate"]["state"] == "open", res
    _closed(cli, g)
    res = _pass(cli, sid, dev)
    assert res.code == 3, res
    assert "evidence-before-recovery" in res.reasons, res


def test_D22c_f3read_ingested_inside_the_verification_gate_passes(cli):
    """Amendment 04 B1 with f3read evidence (amendment 06 F4), amended by 07 G1: gate f3write-f3read confirmed ->
    ingest f3write (volume full, F2 inconclusive) -> replug (inventory --after-replug + inventory, inside the gate) ->
    ingest f3read (pass) -> close success --evidence <f3read> -> PASS with no replug after the close (resolves
    amendment 04 Q1: observations after the confirm count). Mutation: window starts at the close, an f3write record
    that is not a pass blocks the f3read pass, or the observation window ignores the replug inside the gate -> red."""
    sid, dev, _ = prepared(cli, USB_STICK, "/dev/pd2", *DEVREC)
    g = _confirmed(cli, sid, dev, "f3write-f3read")
    ingest_f3(cli, sid, dev, "f3write", F3WRITE_FULL)
    replug(cli, sid)
    ev = ingest_f3(cli, sid, dev, "f3read", F3READ_PASS)
    assert ev["parsed"]["result"] == "pass"
    _closed(cli, g, "success", "--evidence", ev["id"])
    res = cli("verdict", "set", sid, dev, "PASS")
    assert res.code == 0, res


# ---------------- D22f (amendment 07 G1): an f3read pass counts only when read after a replug
# Anchor = the last f3write ingest of the device in the session before the f3read ingest, else the confirm of the
# verification gate the f3read was ingested in, else the PASS evidence window start (CONTRACT "Amendment 07").
F3_REASON = "f3read-not-after-replug"


def _f3_gate(cli):
    sid, dev, _ = prepared(cli, USB_STICK, "/dev/pd2", *DEVREC)
    return sid, dev, _confirmed(cli, sid, dev, "f3write-f3read")


def _refused_f3(res):
    assert res.code == 3, res
    assert F3_REASON in res.reasons, res
    assert F3_REASON in res.message, res


def test_D22f_real_run_without_replug_between_write_and_read_refused(cli):
    """Amendment 07 G1, the real 2026-10-19 flow (stick 275.95 MB/s = host cache): f3write ingest -> f3read ingest ->
    close -> replug -> PASS refused `f3read-not-after-replug`, named in the refusal. Mutation: no ordering rule
    (today: PASS) -> red; a replug after the f3read accepted -> red."""
    sid, dev, g = _f3_gate(cli)
    ingest_f3(cli, sid, dev, "f3write", F3WRITE_FULL)
    ev = ingest_f3(cli, sid, dev, "f3read", F3READ_PASS)
    _closed(cli, g, "success", "--evidence", ev["id"])
    _refused_f3(_pass(cli, sid, dev))


def test_D22f_replug_before_the_last_f3write_does_not_count(cli):
    """Amendment 07 G1 anchor: with an f3write ingested, the replug must follow the LAST f3write ingest; a replug after
    the confirm but before the f3write ingest does not count. Mutation: anchor = gate confirm even when an f3write
    was ingested -> PASS -> red."""
    sid, dev, g = _f3_gate(cli)
    replug(cli, sid)
    ingest_f3(cli, sid, dev, "f3write", F3WRITE_FULL)
    ev = ingest_f3(cli, sid, dev, "f3read", F3READ_PASS)
    _closed(cli, g, "success", "--evidence", ev["id"])
    _refused_f3(cli("verdict", "set", sid, dev, "PASS"))


def test_D22f_second_f3write_after_the_replug_moves_the_anchor(cli):
    """Amendment 07 G1 'the LAST f3write ingest': f3write, replug, f3write again (another run), f3read -> refused.
    Mutation: anchor = the first f3write ingest -> PASS -> red."""
    sid, dev, g = _f3_gate(cli)
    ingest_f3(cli, sid, dev, "f3write", F3WRITE_FULL)
    replug(cli, sid)
    ingest_f3(cli, sid, dev, "f3write", "f3/f3write-stick-volume-full.free1mb.derived.txt")
    ev = ingest_f3(cli, sid, dev, "f3read", F3READ_PASS)
    _closed(cli, g, "success", "--evidence", ev["id"])
    _refused_f3(cli("verdict", "set", sid, dev, "PASS"))


@pytest.mark.parametrize("order,passes", [("replug-then-f3read", True), ("f3read-then-replug", False)])
def test_D22f_no_f3write_ingested_anchor_is_the_gate_confirm(cli, order, passes):
    """Amendment 07 G1 'else after the gate confirm': no f3write ingested; replug after the confirm and before the
    f3read ingest -> PASS; f3read ingested before the replug -> refused. Mutation: rule only applied when an f3write
    exists -> second row PASS -> red; replug required after the f3read -> first row red."""
    sid, dev, g = _f3_gate(cli)
    if order == "replug-then-f3read":
        replug(cli, sid)
        ev = ingest_f3(cli, sid, dev, "f3read", F3READ_PASS)
    else:
        ev = ingest_f3(cli, sid, dev, "f3read", F3READ_PASS)
        replug(cli, sid)
    _closed(cli, g, "success", "--evidence", ev["id"])
    res = cli("verdict", "set", sid, dev, "PASS")
    if passes:
        assert res.code == 0, res
    else:
        _refused_f3(res)


# ---------------- D22g (amendment 08 H1-H3): the f3read moment = min(ingest ts, output_mtime)
def copy_with_mtime(tmp_path, rel, when):
    """Temp copy of a frozen fixture (bytes unchanged) whose mtime is `when` (aware datetime, whole seconds)."""
    import os
    import shutil

    p = tmp_path / pathlib.Path(rel).name
    shutil.copyfile(fx(rel), p)
    ts = when.timestamp()
    os.utime(p, (ts, ts))
    return p


def _ingest_path(cli, sid, dev, kind, path, code=0):
    return ok(cli("ingest", kind, sid, dev, path, "--exit-code", code))["evidence"]


def _f3read_log_written(cli, tmp_path, before_replug):
    """confirm -> ingest f3write -> [log written] -> replug -> [log written] -> ingest f3read (always after the replug)."""
    sid, dev, g = _f3_gate(cli)
    ingest_f3(cli, sid, dev, "f3write", F3WRITE_FULL)
    if before_replug:
        when = cli.clock.now + dt.timedelta(seconds=1)
        cli.clock.advance(seconds=2)
        replug(cli, sid)
    else:
        replug(cli, sid)
        cli.clock.advance(seconds=2)
        when = cli.clock.now
    p = copy_with_mtime(tmp_path, F3READ_PASS, when.replace(microsecond=0))
    ev = _ingest_path(cli, sid, dev, "f3read", p)
    _closed(cli, g, "success", "--evidence", ev["id"])
    return sid, dev, ev


def test_D22g_f3read_log_written_before_the_replug_refused(cli, tmp_path):
    """Amendment 08 H2 (amendment 07 Q2): the f3read log's mtime is before the replug, the ingest after it ->
    refused `f3read-not-after-replug`. Mutation: G1 keeps using the ingest ts only (today: PASS) -> red."""
    sid, dev, _ = _f3read_log_written(cli, tmp_path, before_replug=True)
    _refused_f3(cli("verdict", "set", sid, dev, "PASS"))


def test_D22g_f3read_log_written_after_the_replug_passes(cli, tmp_path):
    """Amendment 08 H2 counter-case: mtime after the replug and before the ingest -> PASS. Mutation: the mtime replaces
    the anchor / any mtime refuses -> red."""
    sid, dev, _ = _f3read_log_written(cli, tmp_path, before_replug=False)
    res = cli("verdict", "set", sid, dev, "PASS")
    assert res.code == 0, res


def test_D22g_row_without_output_mtime_keeps_the_ingest_ts(cli, tmp_path, home):
    """Amendment 08 H3: a row ingested before this amendment (no `output_mtime`; simulated by removing the key from the
    row's JSON) keeps amendment 07 behaviour: ingest ts after the replug -> PASS even though the file's mtime was
    earlier. Mutation: a missing output_mtime refuses, or the file is re-stat'ed at verdict time -> red."""
    import sqlite3

    sid, dev, ev = _f3read_log_written(cli, tmp_path, before_replug=True)
    con = sqlite3.connect(pathlib.Path(home) / "rs.sqlite")
    try:
        cols = [r[1] for r in con.execute("PRAGMA table_info(evidence)")]
        row = con.execute("SELECT * FROM evidence WHERE id = ?", (ev["id"],)).fetchone()
        for col, val in zip(cols, row):
            try:
                doc = json.loads(val) if isinstance(val, str) else None
            except ValueError:
                doc = None
            if isinstance(doc, dict) and "output_mtime" in doc:
                doc.pop("output_mtime")
                con.execute(f"UPDATE evidence SET {col} = ? WHERE id = ?", (json.dumps(doc), ev["id"]))
        con.commit()
    finally:
        con.close()
    res = cli("verdict", "set", sid, dev, "PASS")
    assert res.code == 0, res


def test_D22f_plain_inventory_is_not_a_replug(cli):
    """Amendment 07 G1 'an after-replug observation (`inventory --after-replug`)': two plain inventories between the
    f3write and the f3read do not count. Mutation: any observation in between counts -> PASS -> red."""
    sid, dev, g = _f3_gate(cli)
    ingest_f3(cli, sid, dev, "f3write", F3WRITE_FULL)
    inventory(cli, cli.runner(USB_STICK), sid)
    inventory(cli, cli.runner(USB_STICK), sid)
    ev = ingest_f3(cli, sid, dev, "f3read", F3READ_PASS)
    _closed(cli, g, "success", "--evidence", ev["id"])
    replug(cli, sid)
    _refused_f3(cli("verdict", "set", sid, dev, "PASS"))


def test_D22f_f3read_after_format_without_replug_before_it_refused(cli):
    """Amendment 07 G1 anchor 'else the PASS evidence window start': no f3write, no verification gate (format closed);
    f3read ingested before the replug -> refused (the amendment 06 order of test_D22_f3read_pass_covering_...).
    Mutation: rule only inside verification gates -> PASS -> red."""
    sid, dev = formatted_stick(cli)
    ingest_f3(cli, sid, dev, "f3read", F3READ_PASS)
    replug(cli, sid)
    _refused_f3(cli("verdict", "set", sid, dev, "PASS"))


# ---------------- D23b (amendment 02 E, N8): ATA self-test lifetime hours are 16-bit
def _entry(passed, hours):
    return {"type": {"value": 1, "string": "Short offline"},
            "status": {"value": 0 if passed else 121,
                       "string": "Completed without error" if passed else "Completed: read failure",
                       "passed": passed},
            "lifetime_hours": hours}


def window_ok(table, latest_poh, since_hours):
    from rslib.verdict import selftest_window

    return selftest_window(table, latest_poh, since_hours)


@pytest.mark.parametrize("table,latest,since,want", [
    # amendment E case 1: since 70000, pass logged at 10000 (60000 h ago, latest = 70000) -> not counted
    ([_entry(True, 10000)], 70000, 70000, False),
    # amendment E case 2: fail at raw 4564 (= 70100) after a pass at raw 4500 (= 70036) -> refused; pass listed first
    ([_entry(True, 4500), _entry(False, 4564)], 70100, 70000, False),
    # the pass at raw 4500 alone, same window -> counted
    ([_entry(True, 4500)], 70100, 70000, True),
    # boundary: distance == latest - since is inside ('<='); one hour older is outside
    ([_entry(True, 70000 % 65536)], 70100, 70000, True),
    ([_entry(True, 69999 % 65536)], 70100, 70000, False),
    # ordering across the wrap: fail at raw 30 (= 65566, 34 h ago) is newer than the pass at raw 65530 (70 h ago)
    ([_entry(True, 65530), _entry(False, 30)], 65600, 65500, False),
    # a pass newer than the fail is not refused ('no failed entry after it', phase-04 matrix)
    ([_entry(False, 65530), _entry(True, 30)], 65600, 65500, True),
], ids=["E1-stale-60000h", "E2-fail-after-pass", "pass-in-wrapped-window", "boundary-equal-in",
        "boundary-one-hour-out", "wrap-order-fail-newer", "wrap-order-pass-newer"])
def test_D23b_selftest_window_wraps_at_65536(table, latest, since, want):
    """Amendment 02 E: entry inside the window when (latest_poh - h) % 65536 <= latest_poh - since_hours; 'after'
    ordering uses that distance. Contract: rslib.verdict.selftest_window(table, latest_poh, since_hours) -> bool
    (a passed entry inside the window with no failed entry after it). Mutations, one per row: compare h with
    since % 65536 (E1 accepted); compare raw h >= since (pass-in-wrapped-window refused); order by list position
    (E2 accepted); '<' instead of '<=' (boundary-equal-in refused); off by one the other way (boundary-one-hour-out
    accepted); order by raw hours (wrap-order rows flipped)."""
    assert window_ok(table, latest, since) is want


@pytest.mark.parametrize("since,want", [(65578, True), (65579, False), (65540, True)])
def test_D23b_selftest_window_on_real_wrapped_log(since, want):
    """Amendment 02 E on a real wrapped log: scrutiny-usbjmicron-hdd-failing (POH 65592; newest entries logged at 42,
    18, 4 = read failure, 65530 ...). 65578: the pass at raw 42 is 14 h old, window 14 -> counted; 65579: window 13 ->
    nothing inside; 65540: window 52 holds 42 (pass), 18 (pass), 4 (fail, older) -> the newest pass has no fail after
    it. Mutation: no wrap (raw 42 < 65578) -> first row refused; '<' -> first row refused; 'any failure in the window
    refuses' -> third row refused."""
    doc = fx_json("smartctl/scrutiny-usbjmicron-hdd-failing.json")
    table = doc["ata_smart_self_test_log"]["standard"]["table"]
    assert doc["power_on_time"]["hours"] == 65592
    assert window_ok(table, 65592, since) is want


@pytest.mark.parametrize("rel,missing", [
    ("smartctl/scrutiny-ata-hdd-healthy.poh67236.derived.json", True),
    ("smartctl/scrutiny-ata-hdd-healthy.poh67244.derived.json", False),
], ids=["poh-67236-newest-test-65528h-old", "poh-67244-newest-test-0h-old"])
def test_D23b_verdict_set_uses_the_wrapped_window(cli, rel, missing):
    """Amendment 02 E through `verdict set` (D23 flow, one snapshot: window start POH = latest POH, width 0).
    POH 67236 (= 65536 + 1700): the newest entry, raw 1708, is (67236 - 1708) % 65536 = 65528 h old -> outside ->
    `selftest-missing` listed. POH 67244 (= 65536 + 1708): distance 0 -> inside -> not listed.
    Mutation: verdict keeps the pre-amendment comparison of raw hours with POH % 65536 (1708 >= 1700 accepted) ->
    first row red; raw hours vs full POH without wrap (1708 < 67244) -> second row red; selftest_window exists but
    `verdict set` does not use it -> first row red."""
    sid = new_session(cli)
    dev = ingest_smart(cli, sid, rel).data["device_id"]
    res = cli("verdict", "set", sid, dev, "PASS")
    assert res.code == 3, res
    assert ("selftest-missing" in res.reasons) is missing, res


# ---------------- D24c (amendment 02 F, N13): SSD read verify by f3read needs flash coverage
@pytest.mark.skip(reason="BLOCKED (amendment 02 F, partly unblocked by amendment 06): the nvme below-coverage case runs in "
                         "test_D24c_nvme_f3read_pass_below_flash_coverage_is_not_read_verify; ssd-sata / external-ssd and "
                         "the at/above-coverage half need an attached SSD of those classes and an f3read output of its "
                         "size.")
@pytest.mark.parametrize("cls", ["ssd-sata", "nvme", "external-ssd"])
def test_D24c_ssd_f3read_below_flash_coverage_is_not_read_verify(cls):
    """Amendment 02 F: f3read pass below coverage -> not a read verify (PASS refused); at/above coverage -> counts."""


def test_D24c_nvme_f3read_pass_below_flash_coverage_is_not_read_verify(cli):
    """Amendment 02 F with the real f3read pass of amendment 06: 8050743296 B verified on the 990 PRO (1000204886016 B)
    is far below CAPACITY_COVERAGE x bytes -> not a read verify -> PASS refused (D24 flow with f3read in place of the
    full-read map). Mutation: any f3read pass counts as SSD/NVMe read verify -> PASS -> red."""
    sid, dev, _ = prepared(cli, BASELINE, "/dev/pd0", "--goal", "health-assessment")
    assert ingest_f3(cli, sid, dev, "f3read", F3READ_PASS)["parsed"]["result"] == "pass"
    inventory(cli, cli.runner(BASELINE), sid, after_replug=True)
    collect(cli, BASELINE, sid, dev)
    res = cli("verdict", "set", sid, dev, "PASS")
    assert res.code == 3, res
    assert ok(cli("verdict", "show", sid, dev))["effective"] != "PASS"


def test_D24c_coverage_parameter_is_exposed():
    """Amendment 02 F names the parameter `verdict.CAPACITY_COVERAGE` (phase-04 D22: 0.9 x bytes for USB). Only the
    name and range are sourced; the f3read cases above stay BLOCKED. Mutation: parameter renamed/removed -> red."""
    from rslib import verdict

    assert 0 < verdict.CAPACITY_COVERAGE <= 1
