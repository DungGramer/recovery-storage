"""Phase 04 gate open (D1-D11, D9b, D9c). Spec: phase-04 Requirements 'Gate open checks', 'Gate open success' + D1-D11."""
import pytest

from conftest import (BASELINE, USB_SD, USB_STICK, assess, close, collect, device_at, gate_ok,
                      gate_open_state, ingested_assessment, new_session, nvme1, ok, open_gate, phrase_980, prepared,
                      secure, serial_980, stick, STICK_PHRASE)
from test_actions_catalog import R1, R2, R3

TWIN = {"win-disks": f"{USB_STICK}/win-disks.twin.derived.json",
        "win-pnp-chain": f"{USB_STICK}/win-pnp-chain.twin.derived.json",
        "pd3": f"{USB_STICK}/smartctl-x-pd3.from-pd2.derived.json",
        "sat-pd3": f"{USB_STICK}/smartctl-x-sat-pd3.from-pd2.derived.json"}
SD_TWIN = {"win-disks": f"{USB_SD}/win-disks.sd-twin.derived.json",
           "win-pnp-chain": f"{USB_SD}/win-pnp-chain.sd-twin.derived.json",
           "pd4": f"{USB_SD}/smartctl-x-pd4.from-pd3.derived.json",
           "sat-pd4": f"{USB_SD}/smartctl-x-sat-pd4.from-pd3.derived.json"}


def test_D1_unknown_action_lists_kinds(cli):
    """D1. Mutation: accept free-form kinds -> red."""
    sid, dev = nvme1(cli, "--goal", "diagnosis-only", "--ceiling", "R3")
    res = open_gate(cli, BASELINE, sid, dev, "rm-rf")
    assert res.code == 3, res
    assert "unknown-action" in res.reasons
    for k in R1 + R2 + R3:
        assert k in res.text, k


def test_D2_r1_kind_above_ceiling_R0_refused(cli):
    """D2. Mutation: compare ceiling lexically wrong / skip check -> red."""
    sid, dev = nvme1(cli, "--goal", "diagnosis-only")
    res = open_gate(cli, BASELINE, sid, dev, "smart-selftest-short")
    assert res.code == 3, res
    assert "risk-above-ceiling" in res.reasons


def test_D2_ceiling_R1_opens_pending_with_phrase(cli):
    """D2. Mutation: open straight to `open` (skipping confirm) -> state != pending -> red."""
    sid, dev = nvme1(cli, "--goal", "diagnosis-only", "--ceiling", "R1")
    g, res = gate_ok(cli, BASELINE, sid, dev, "smart-selftest-short")
    assert res.data["confirmation"]["phrase"] == phrase_980()


@pytest.mark.parametrize("kind", ["smart-selftest-short", "format", "image-ddrescue"])
def test_D3_boot_system_disk_refused_any_kind_any_ceiling(cli, kind):
    """D3 (capture: Disk 0 IsBoot+IsSystem). Mutation: check only R2 kinds, or only IsBoot -> red."""
    sid, dev = prepared(cli, BASELINE, "/dev/pd0", "--goal", "device-recovery", "--preserve-data", "no",
                        "--ceiling", "R3")[:2]
    other = device_at(cli, BASELINE, sid, "/dev/pd1")
    extra = ["--dest-device", other] if kind == "image-ddrescue" else []
    res = open_gate(cli, BASELINE, sid, dev, kind, *extra)
    assert res.code == 3, res
    assert "boot-or-system-disk" in res.reasons


def test_D4_data_recovery_format_needs_secured_data(cli):
    """D4. Mutation: data-not-secured check ignores preserve forced by goal -> opens -> red."""
    sid, dev = nvme1(cli, "--goal", "data-recovery", "--goal", "device-recovery", "--ceiling", "R2")
    res = open_gate(cli, BASELINE, sid, dev, "format")
    assert res.code == 3, res
    assert "data-not-secured" in res.reasons
    _, sec = secure(cli, sid, dev)
    assert sec.code == 0, sec
    gate_ok(cli, BASELINE, sid, dev, "format")


def test_D5_forensic_goal_never_writes_source(cli):
    """D5. Mutation: secured data-state bypasses forensic-source-write -> red."""
    sid, dev = nvme1(cli, "--goal", "forensic-preservation", "--ceiling", "R2")
    assert secure(cli, sid, dev)[1].code == 0
    res = open_gate(cli, BASELINE, sid, dev, "format")
    assert res.code == 3, res
    assert "forensic-source-write" in res.reasons


def test_D5_forensic_goal_allows_imaging(cli):
    """D5. Mutation: forensic goal blocks every kind -> red."""
    sid, dev = nvme1(cli, "--goal", "forensic-preservation", "--ceiling", "R1")
    dest = device_at(cli, BASELINE, sid, "/dev/pd0")
    gate_ok(cli, BASELINE, sid, dev, "image-ddrescue", "--dest-device", dest)


def test_D6_stop_unsafe_refuses_r1_allows_r3(cli):
    """D6. Mutation: STOP_UNSAFE blocks R3 too, or not checked -> red."""
    sid, dev = nvme1(cli, "--goal", "diagnosis-only", "--symptom", "mechanical-noise", "--ceiling", "R3")
    dest = device_at(cli, BASELINE, sid, "/dev/pd0")
    res = open_gate(cli, BASELINE, sid, dev, "image-ddrescue", "--dest-device", dest)
    assert res.code == 3, res
    assert "stop-unsafe" in res.reasons
    gate_ok(cli, BASELINE, sid, dev, "hardware-lab")


def test_D7_no_assessment_refused(cli):
    """D7. Mutation: accept an assessment from another session -> red."""
    sid = new_session(cli, "--goal", "diagnosis-only", "--ceiling", "R1")
    dev = device_at(cli, BASELINE, sid, "/dev/pd1")
    collect(cli, BASELINE, sid, dev)
    res = open_gate(cli, BASELINE, sid, dev, "smart-selftest-short")
    assert res.code == 3 and "no-assessment" in res.reasons, res
    s2 = new_session(cli, "--goal", "diagnosis-only", "--ceiling", "R1")
    assess(cli, sid, dev)  # assessment exists, but in the first session only
    res2 = open_gate(cli, BASELINE, s2, dev, "smart-selftest-short")
    assert res2.code == 3 and "no-assessment" in res2.reasons, res2


def test_D8_all_failing_reasons_listed(cli):
    """D8. Mutation: return on the first failing check -> one reason only -> red."""
    sid, dev = nvme1(cli, "--goal", "data-recovery")
    res = open_gate(cli, BASELINE, sid, dev, "format")
    assert res.code == 3, res
    assert {"risk-above-ceiling", "data-not-secured"} <= res.reasons


def test_D9_device_absent_not_found(cli):
    """D9. Mutation: use the stored path without re-inventory -> red."""
    sid, dev = stick(cli, "--goal", "diagnosis-only", "--ceiling", "R1")
    res = open_gate(cli, BASELINE, sid, dev, "disk-offline")
    assert res.code == 3, res
    assert "device-not-found" in res.reasons


def test_D9_two_probable_candidates_ambiguous_exit_5(cli):
    """D9. Mutation: pick the first attached match -> wrong-device risk -> red."""
    sid, dev = stick(cli, "--goal", "diagnosis-only", "--ceiling", "R1")
    res = open_gate(cli, USB_STICK, sid, dev, "disk-offline", override=TWIN)
    assert res.code == 5, res
    assert res.reasons == {"ambiguous"}
    assert sorted(c["os_path"] for c in res.data["candidates"]) == ["/dev/pd2", "/dev/pd3"]


def test_D9b_sd_weak_single_opens_with_warning_and_byte_phrase(cli):
    """D9b. Mutation: weak treated as ambiguous (never opens), or phrase from junk serial "[" -> red."""
    sid, dev, _ = prepared(cli, USB_SD, "/dev/pd3", "--goal", "diagnosis-only", "--ceiling", "R1")
    res = open_gate(cli, USB_SD, sid, dev, "disk-offline")
    assert res.code == 0, res
    assert res.data["confirmation"]["phrase"] == "4026531840"
    assert res.data["confirmation"]["identity_level"] == "weak"
    assert res.data["gate"]["state"] == "pending"


def test_D9b_weak_warning_line_in_text_block(cli):
    """D9b text line. Mutation: omit the weak-identity warning -> red."""
    sid, dev, _ = prepared(cli, USB_SD, "/dev/pd3", "--goal", "diagnosis-only", "--ceiling", "R1")
    res = open_gate(cli, USB_SD, sid, dev, "disk-offline")
    res_txt = cli("gate", "abort", res.data["gate"]["id"], "--reason", "redo in text mode")
    assert res_txt.code == 0
    t = cli("gate", "open", sid, dev, "disk-offline", runner=cli.runner(USB_SD), json_out=False)
    assert t.code == 0, t
    assert "identity weak: same-size media in this reader cannot be told apart" in t.out.lower()
    assert "4026531840" in t.out


def test_D9b_weak_with_twin_reader_card_ambiguous(cli):
    """D9b. Mutation: weak usable even with a same model+bytes+vid/pid device attached -> red."""
    sid, dev, _ = prepared(cli, USB_SD, "/dev/pd3", "--goal", "diagnosis-only", "--ceiling", "R1")
    res = open_gate(cli, USB_SD, sid, dev, "disk-offline", override=SD_TWIN)
    assert res.code == 5, res
    assert "ambiguous" in res.reasons


def test_D9c_needs_elevation_before_state_recorded_not_blocking(cli):
    """D9c. Mutation: treat a failed before-snapshot as a refusal -> red."""
    sid, dev = stick(cli, "--goal", "diagnosis-only", "--ceiling", "R1")
    g, res = gate_ok(cli, USB_STICK, sid, dev, "disk-offline")
    assert res.data["before"]["observation_id"]
    assert res.data["before"]["collection_status"] == "needs_elevation"


def test_D10_image_requires_dest_device(cli):
    """D10. Mutation: optional --dest-device -> red."""
    sid, dev = nvme1(cli, "--goal", "diagnosis-only", "--ceiling", "R1")
    res = open_gate(cli, BASELINE, sid, dev, "image-ddrescue")
    assert res.code == 3 and "missing-requirement" in res.reasons, res


def test_D10_dest_equal_source_refused(cli):
    """D10. Mutation: no source/dest comparison -> red."""
    sid, dev = nvme1(cli, "--goal", "diagnosis-only", "--ceiling", "R1")
    res = open_gate(cli, BASELINE, sid, dev, "image-ddrescue", "--dest-device", dev)
    assert res.code == 3 and "dest-is-source" in res.reasons, res


@pytest.mark.parametrize("extra", [[], ["--controller-id", "PS2251-07"], ["--tool-source", "vendor site, sha256 x"]])
def test_D10_mptool_needs_controller_and_provenance(cli, extra):
    """D10. Mutation: require only one of the two -> red for that case."""
    sid, dev = nvme1(cli, "--goal", "device-recovery", "--preserve-data", "no", "--ceiling", "R2")
    res = open_gate(cli, BASELINE, sid, dev, "mptool-reflash", *extra)
    assert res.code == 3 and "missing-requirement" in res.reasons, res


def test_D10_f3probe_on_hdd_class_not_allowed(cli):
    """D10 (hdd known only via ingest -> also device-not-found; D8 says every reason is listed).
    Mutation: class check skipped -> red."""
    sid, dev, _ = ingested_assessment(cli, "smartctl/scrutiny-ata-hdd-healthy.json", "--goal", "device-recovery",
                                      "--preserve-data", "no", "--ceiling", "R2")
    res = cli("gate", "open", sid, dev, "f3probe", runner=cli.runner(BASELINE))
    assert res.code == 3, res
    assert "class-not-allowed" in res.reasons


def test_D10_f3probe_on_nvme_class_not_allowed(cli):
    """D10 on a present device. Mutation: class check skipped -> red."""
    sid, dev = nvme1(cli, "--goal", "device-recovery", "--preserve-data", "no", "--ceiling", "R2")
    res = open_gate(cli, BASELINE, sid, dev, "f3probe")
    assert res.code == 3 and "class-not-allowed" in res.reasons, res


def test_D11_confirmation_block_high_trust(cli):
    """D11. Mutation: truncate the serial in the block, or phrase 'yes' -> red."""
    sid, dev = nvme1(cli, "--goal", "diagnosis-only", "--ceiling", "R1")
    t = cli("gate", "open", sid, dev, "smart-selftest-short", runner=cli.runner(BASELINE), json_out=False)
    assert t.code == 0, t
    for s in ("Samsung SSD 980 PRO 2TB", serial_980(), "2000398934016", "/dev/pd1", "smart-selftest-short", "R1",
              phrase_980()):
        assert s in t.out, s
    from rslib.actions import CATALOG

    assert CATALOG["smart-selftest-short"].stop_criteria.strip() in t.out


def test_D11_confirmation_json_fields(cli):
    """D11 JSON. Mutation: drop os_paths or bytes from the block -> red."""
    sid, dev = nvme1(cli, "--goal", "diagnosis-only", "--ceiling", "R1")
    _, res = gate_ok(cli, BASELINE, sid, dev, "smart-selftest-short")
    c = res.data["confirmation"]
    assert c["model"] == "Samsung SSD 980 PRO 2TB"
    assert c["serial"] == serial_980()
    assert c["bytes"] == 2000398934016
    assert "/dev/pd1" in c["os_paths"]
    assert c["kind"] == "smart-selftest-short" and c["risk"] == "R1" and c["writes_source"] is False
    assert c["stop_criteria"]


def test_D11_junk_usb_serial_phrase_is_byte_count(cli):
    """D11 (verified junk serial "\\t"). Mutation: last 4 chars of junk serial -> red."""
    sid, dev = stick(cli, "--goal", "diagnosis-only", "--ceiling", "R1")
    _, res = gate_ok(cli, USB_STICK, sid, dev, "disk-offline")
    assert res.data["confirmation"]["phrase"] == "8054112256"


# ---------------- D4b (amendment 02 B, N2): secured / waived count only after the device's last write
DATAREC = ("--goal", "data-recovery", "--goal", "device-recovery", "--ceiling", "R2")


def _record(cli, sid, dev, state):
    if state == "secured":
        res = secure(cli, sid, dev)[1]
    else:
        res = cli("session", "data-state", sid, dev, "waived", "--reason", "owner says data is backed up",
                  answers=["YES"])
    assert res.code == 0 and res.data["data_state"] == state, res


def _format_closed(cli, sid, dev):
    g = gate_open_state(cli, BASELINE, sid, dev, "format", phrase_980())
    res = close(cli, BASELINE, g, "success")
    assert res.code == 0 and res.data["gate"]["identity_drift"] is False, res


@pytest.mark.parametrize("state", ["secured", "waived"])
def test_D4b_data_state_from_before_the_last_write_is_stale(cli, state):
    """Amendment 02 B 'secured / waived count for a write gate only if recorded after last_write_ts(device)'.
    Same session: state recorded, format gate closed (last write), second format gate -> data-not-secured; recording
    the state again after the write lets it open. Mutation: data state read without the last-write comparison ->
    second format opens -> red; rule applied to secured only -> waived row red."""
    sid, dev = nvme1(cli, *DATAREC)
    _record(cli, sid, dev, state)
    _format_closed(cli, sid, dev)
    res = open_gate(cli, BASELINE, sid, dev, "format")
    assert res.code == 3, res
    assert "data-not-secured" in res.reasons, res
    _record(cli, sid, dev, state)
    gate_ok(cli, BASELINE, sid, dev, "format")


def test_D4b_stale_secured_across_sessions_refused(cli):
    """Amendment 02 B scenario (reviewer scen2.py #2): S1 secured + format gate closed; S2 data-recovery on the same
    device -> format refused data-not-secured. Mutation: a device's secured state carried into later sessions without
    the last-write check -> opens -> red."""
    s1, dev = nvme1(cli, "--goal", "device-recovery", "--preserve-data", "yes", "--ceiling", "R2")
    assert secure(cli, s1, dev)[1].code == 0
    _format_closed(cli, s1, dev)
    s2 = new_session(cli, "--goal", "data-recovery", "--ceiling", "R2")
    collect(cli, BASELINE, s2, dev)
    assess(cli, s2, dev)
    res = open_gate(cli, BASELINE, s2, dev, "format")
    assert res.code == 3, res
    assert "data-not-secured" in res.reasons, res


def test_D4b_write_gate_aborted_after_confirm_is_a_write(cli):
    """Amendment 02 B 'closed_ts of an aborted gate whose kind writes the source and that had been confirmed'. The
    tool may have run between confirm and abort. Mutation: only closed gates count as writes -> second format opens
    -> red."""
    sid, dev = nvme1(cli, *DATAREC)
    _record(cli, sid, dev, "secured")
    g = gate_open_state(cli, BASELINE, sid, dev, "format", phrase_980())
    assert ok(cli("gate", "abort", g, "--reason", "format stopped midway"))["gate"]["state"] == "aborted"
    res = open_gate(cli, BASELINE, sid, dev, "format")
    assert res.code == 3 and "data-not-secured" in res.reasons, res


def test_D4c_verification_gate_close_is_still_the_last_write_for_data_state(cli):
    """Amendment 04 B4: only the PASS evidence window moves to a verification gate's confirm; for data state the last
    write of a verification gate is still its close. Stick, preserve yes: waived (to open the gate) -> f3write-f3read
    confirmed -> waived recorded AGAIN between confirm and close -> close success -> format -> data-not-secured.
    Mutation: last_write_ts uses confirmed_ts for verification kinds (the second waived counts) -> format opens -> red."""
    sid, dev = stick(cli, *DATAREC)
    _record(cli, sid, dev, "waived")
    g = gate_open_state(cli, USB_STICK, sid, dev, "f3write-f3read", STICK_PHRASE)
    _record(cli, sid, dev, "waived")   # after confirm, before close
    res = close(cli, USB_STICK, g, "success")
    assert res.code == 0 and res.data["gate"]["state"] == "closed", res
    res = open_gate(cli, USB_STICK, sid, dev, "format")
    assert res.code == 3, res
    assert "data-not-secured" in res.reasons, res


def test_D4b_unconfirmed_or_read_only_gates_are_not_writes(cli):
    """Amendment 02 B: a write gate aborted while still pending (never confirmed) and a closed gate whose kind does not
    write the source (smart-selftest-short, R1) leave the secured state valid. Mutation: every aborted gate, or every
    closed gate, counts as a write -> format refused -> red."""
    sid, dev = nvme1(cli, *DATAREC)
    _record(cli, sid, dev, "secured")
    g, _ = gate_ok(cli, BASELINE, sid, dev, "format")
    assert ok(cli("gate", "abort", g, "--reason", "changed plan before confirm"))["gate"]["state"] == "aborted"
    t = gate_open_state(cli, BASELINE, sid, dev, "smart-selftest-short", phrase_980())
    assert close(cli, BASELINE, t, "success").code == 0
    gate_ok(cli, BASELINE, sid, dev, "format")
