"""Phase 04 verdict evidence matrix (D21-D27). Spec: phase-04 Requirements 'Verdict', 'PASS requires', decision Q3,
spec §2 Phase 5 + §8 'format success is not recovery' + D21-D27."""
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
# H2testw (the f3read cases stay BLOCKED: no real f3read output with Data OK amounts is a fixture yet).
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


@pytest.mark.skip(reason="BLOCKED (open question F3-numbers): the real-run f3read pass (Data OK 8050743296 of 8054112256 B) "
                         "ingested inside the f3write-f3read gate needs the raw redacted f3read output as a fixture.")
def test_D22c_f3read_ingested_inside_the_verification_gate_passes():
    """Amendment 04 B1 with f3read evidence (the exact 2026-10-19 flow)."""


@pytest.mark.skip(reason="OPEN QUESTION (amendment 04 Q1): does B1 also move the OBSERVATION window (>= 2 observations, one "
                         "--after-replug) to the confirm? F3 guidance replugs between f3write and f3read, inside the gate.")
def test_D22c_open_replug_inside_the_verification_gate():
    """Would assert PASS (or replug-observation-missing) for a replug taken between confirm and close once decided."""


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
@pytest.mark.skip(reason="BLOCKED (open question F3-numbers, amendment 02 F): an f3read pass counts as SSD/NVMe read "
                         "verify only with coverage >= verdict.CAPACITY_COVERAGE x device bytes; testing it needs a real "
                         "f3read output with Data OK amounts, and research quotes the labels only.")
@pytest.mark.parametrize("cls", ["ssd-sata", "nvme", "external-ssd"])
def test_D24c_ssd_f3read_below_flash_coverage_is_not_read_verify(cls):
    """Amendment 02 F: f3read pass below coverage -> not a read verify (PASS refused); at/above coverage -> counts."""


def test_D24c_coverage_parameter_is_exposed():
    """Amendment 02 F names the parameter `verdict.CAPACITY_COVERAGE` (phase-04 D22: 0.9 x bytes for USB). Only the
    name and range are sourced; the f3read cases above stay BLOCKED. Mutation: parameter renamed/removed -> red."""
    from rslib import verdict

    assert 0 < verdict.CAPACITY_COVERAGE <= 1
