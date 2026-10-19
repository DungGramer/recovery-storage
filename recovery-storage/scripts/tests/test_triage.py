"""Phase 03 triage (C13-C17c) through `assess` (black box). Spec: phase-03 Requirements 'Triage class' rules 1-5,
'Constraints', decision Q5, C13-C17c."""
import pytest

from conftest import (BASELINE, REAL_SMART, USB_SD, USB_STICK, assess, device_at, ev_text, ingest_smart,
                      ingested_assessment, inventory, new_session, prepared)

FAIL_HDD = "smartctl/scrutiny-usbjmicron-hdd-failing.json"


def tri(a):
    return a["triage"]


def rule_id_for(outcome, branch):
    from rslib.triage import RULES

    ids = [r.id for r in RULES if r.outcome == outcome and getattr(r, "branch", None) == branch]
    assert len(ids) == 1, ids
    return ids[0]


# ---------------- C13 STOP_UNSAFE
@pytest.mark.parametrize("symptom", ["mechanical-noise", "not-spinning"])
@pytest.mark.parametrize("name", REAL_SMART)
def test_C13_mechanical_symptom_stop_unsafe_regardless_of_smart(cli, name, symptom):
    """C13. Mutation: evaluate SMART rules before symptoms (healthy disk -> SOFTWARE) -> red."""
    _, _, a = ingested_assessment(cli, f"smartctl/{name}", "--goal", "diagnosis-only", "--symptom", symptom)
    assert tri(a)["class"] == "STOP_UNSAFE"


@pytest.mark.parametrize("symptom", ["burning-smell", "physical-damage", "liquid-damage", "overheating"])
def test_C13_other_rule1_symptoms_stop_unsafe(cli, symptom):
    """Triage rule 1 symptom list. Mutation: only mechanical symptoms handled -> red."""
    _, _, a = ingested_assessment(cli, "smartctl/nvme-990pro-x.json", "--goal", "diagnosis-only", "--symptom", symptom)
    assert tri(a)["class"] == "STOP_UNSAFE"


def test_C13_temperature_at_critical_limit_stop_unsafe(cli):
    """C13 (derived temp85 == critical_limit_max 85). Mutation: `>` instead of `>=` -> red."""
    _, _, a = ingested_assessment(cli, "smartctl/nvme-990pro-x.temp85.derived.json")
    assert tri(a)["class"] == "STOP_UNSAFE"


def test_C13_temperature_below_critical_not_stop(cli):
    """C13 counter-case (real 990 at 47 C). Mutation: compare against op_limit 82 -> red only if >= ... keeps SOFTWARE."""
    _, _, a = ingested_assessment(cli, "smartctl/nvme-990pro-x.json")
    assert tri(a)["class"] == "SOFTWARE_RECOVERY_CANDIDATE"


# ---------------- C14 isolation
def _absent_device(cli, *flags):
    sid = new_session(cli, "--goal", "diagnosis-only", *flags)
    dev = device_at(cli, USB_STICK, sid, "/dev/pd2")
    inventory(cli, cli.runner(BASELINE), sid)  # stick gone
    return sid, dev


@pytest.mark.parametrize("symptom", ["not-detected", "disconnects-repeatedly"])
def test_C14_not_detected_with_two_isolation_facts_hardware(cli, symptom):
    """C14 (branch a). Mutation: require all four isolation facts, or ignore absence -> red."""
    sid, dev = _absent_device(cli, "--symptom", symptom, "--tried", "other-port", "--tried", "other-cable")
    t = tri(assess(cli, sid, dev))
    assert t["class"] == "HARDWARE_DIAGNOSIS_REQUIRED"
    assert t["branch"] == "a"


@pytest.mark.parametrize("tried", [[], ["other-port"]])
def test_C14_fewer_than_two_isolation_facts_undetermined(cli, tried):
    """C14. Mutation: one isolation fact enough -> HARDWARE -> red; next_test must list the missing steps."""
    flags = ["--symptom", "not-detected"]
    for t in tried:
        flags += ["--tried", t]
    sid, dev = _absent_device(cli, *flags)
    t = tri(assess(cli, sid, dev))
    assert t["class"] == "UNDETERMINED"
    for missing in {"other-port", "other-cable", "other-host", "other-os"} - set(tried):
        assert missing in (t["next_test"] or ""), (missing, t["next_test"])


# ---------------- C15 CONTROLLER
@pytest.mark.parametrize("rel", ["smartctl/scrutiny-ata-ssd-healthy.satafirm.derived.json",
                                 "smartctl/scrutiny-ata-ssd-healthy.bytes0.derived.json"])
def test_C15_safe_mode_identity_or_zero_bytes_controller(cli, rel):
    """C15. Mutation: SATAFIRM S11 / 0 bytes not checked -> SOFTWARE -> red."""
    _, _, a = ingested_assessment(cli, rel)
    assert tri(a)["class"] == "CONTROLLER_RECOVERY_CANDIDATE"
    assert "image-before-any-write" in tri(a)["constraints"]
    assert "controller-or-firmware" in {h["category"] for h in a["hypotheses"]}


def test_C15_nvme_media_read_only_controller_and_write_locked(cli):
    """C15 (derived critical_warning 8). Mutation: bit 3 only lowers health, no triage/hypothesis -> red."""
    _, _, a = ingested_assessment(cli, "smartctl/nvme-990pro-x.cw8.derived.json")
    assert tri(a)["class"] == "CONTROLLER_RECOVERY_CANDIDATE"
    assert "write-locked" in {h["category"] for h in a["hypotheses"]}


@pytest.mark.parametrize("nominal,cls", [("2TB", "CONTROLLER_RECOVERY_CANDIDATE"), ("1TB", "SOFTWARE_RECOVERY_CANDIDATE")])
def test_C15_gross_capacity_mismatch_half_nominal_boundary(cli, nominal, cls):
    """Triage rule 3 'bytes < 0.5 x nominal' (860 EVO 500107862016 B: < 1e12, but > 5e11).
    Mutation: `<=`/wrong factor, or nominal ignored -> one side red."""
    _, _, a = ingested_assessment(cli, "smartctl/scrutiny-ata-ssd-healthy.json", "--goal", "diagnosis-only",
                                  "--nominal", nominal)
    assert tri(a)["class"] == cls


# ---------------- C16 risk-based (Q5)
def test_C16_failing_hdd_default_software_with_image_first_constraints(cli):
    """C16. Mutation: failing health -> HARDWARE by default (pre-Q5 rule) -> red; constraint set exact."""
    _, _, a = ingested_assessment(cli, FAIL_HDD, "--goal", "diagnosis-only", "--preserve-data", "yes")
    t = tri(a)
    assert t["class"] == "SOFTWARE_RECOVERY_CANDIDATE"
    assert set(t["constraints"]) == {"image-before-any-write", "no-fs-repair-on-source", "minimise-power-on",
                                     "stop-if-read-rate-collapses"}


def test_C16b_irreplaceable_and_low_tolerance_hardware_branch_b(cli):
    """C16b. Mutation: branch (b) checks stored data_value instead of effective -> SOFTWARE -> red."""
    _, _, a = ingested_assessment(cli, FAIL_HDD, "--goal", "diagnosis-only", "--preserve-data", "yes",
                                  "--risk-tolerance", "low")
    t = tri(a)
    assert t["class"] == "HARDWARE_DIAGNOSIS_REQUIRED"
    assert t["branch"] == "b"
    rid = rule_id_for("HARDWARE_DIAGNOSIS_REQUIRED", "b")
    assert t["rule_id"] == rid
    assert rid in ev_text(t["evidence"])


@pytest.mark.parametrize("flags", [
    ["--preserve-data", "yes", "--data-value", "replaceable", "--risk-tolerance", "low"],
    ["--preserve-data", "no", "--risk-tolerance", "low"],
])
def test_C16b_replaceable_data_low_tolerance_stays_software(cli, flags):
    """C16b. Mutation: branch (b) fires on tolerance low alone -> red."""
    _, _, a = ingested_assessment(cli, FAIL_HDD, "--goal", "diagnosis-only", *flags)
    assert tri(a)["class"] == "SOFTWARE_RECOVERY_CANDIDATE"


def test_C16c_counters_rising_within_session_hardware_branch_c(cli):
    """C16c (derived 197 8 -> 12, POH +1, same session, tolerance high). Mutation: branch (c) missing -> red."""
    sid = new_session(cli, "--goal", "diagnosis-only", "--risk-tolerance", "high")
    dev = ingest_smart(cli, sid, FAIL_HDD).data["device_id"]
    assert ingest_smart(cli, sid, "smartctl/scrutiny-usbjmicron-hdd-failing.p197-12.derived.json").data["device_id"] == dev
    t = tri(assess(cli, sid, dev))
    assert t["class"] == "HARDWARE_DIAGNOSIS_REQUIRED"
    assert t["branch"] == "c"


def test_C16c_pair_split_across_sessions_no_branch_c_but_health_sees_delta(cli):
    """C16c. Mutation: branch (c) uses snapshots from any session -> HARDWARE -> red; or health ignores prev -> red."""
    s1 = new_session(cli, "--goal", "diagnosis-only", "--risk-tolerance", "high")
    dev = ingest_smart(cli, s1, FAIL_HDD).data["device_id"]
    s2 = new_session(cli, "--goal", "diagnosis-only", "--risk-tolerance", "high")
    assert ingest_smart(cli, s2, "smartctl/scrutiny-usbjmicron-hdd-failing.p197-12.derived.json").data["device_id"] == dev
    a = assess(cli, s2, dev)
    assert tri(a)["class"] != "HARDWARE_DIAGNOSIS_REQUIRED"
    assert tri(a)["class"] == "SOFTWARE_RECOVERY_CANDIDATE"
    assert any(str(e.get("path", "")).startswith("delta.") and "197" in str(e.get("path"))
               for e in a["health"]["evidence"]), a["health"]["evidence"]


def test_C16d_healthy_disk_low_tolerance_irreplaceable_software(cli):
    """C16d. Mutation: branch (b) ignores health -> HARDWARE -> red."""
    _, _, a = ingested_assessment(cli, "smartctl/scrutiny-ata-hdd-healthy.json", "--goal", "diagnosis-only",
                                  "--preserve-data", "yes", "--risk-tolerance", "low")
    assert tri(a)["class"] == "SOFTWARE_RECOVERY_CANDIDATE"


def test_constraint_keep_original_enclosure_for_bridge_and_encrypted(cli):
    """Constraints 'bridge present -> keep-original-enclosure when symptom encrypted-locked'. Mutation: never added -> red."""
    _, _, a = ingested_assessment(cli, FAIL_HDD, "--goal", "diagnosis-only", "--symptom", "encrypted-locked")
    assert "keep-original-enclosure" in tri(a)["constraints"]
    _, _, b = ingested_assessment(cli, "smartctl/nvme-990pro-x.json", "--goal", "diagnosis-only",
                                  "--symptom", "encrypted-locked")
    assert "keep-original-enclosure" not in tri(b)["constraints"]  # no bridge


def test_constraint_preserve_alone_adds_image_first(cli):
    """Constraints 'health failing/degraded or preserve=yes -> image-before-any-write'. Mutation: health-only trigger -> red."""
    _, _, a = ingested_assessment(cli, "smartctl/nvme-990pro-x.json", "--goal", "data-recovery")
    assert {"image-before-any-write", "no-fs-repair-on-source"} <= set(tri(a)["constraints"])
    _, _, b = ingested_assessment(cli, "smartctl/nvme-990pro-x.json", "--goal", "device-recovery", "--preserve-data", "no")
    assert "image-before-any-write" not in tri(b)["constraints"]


# ---------------- C17
def test_C17_open_failed_without_os_identity_undetermined(cli):
    """C17. Mutation: SMART-failure-only path -> SOFTWARE -> red."""
    _, _, a = ingested_assessment(cli, "smartctl/scrutiny-open-failed.json")
    assert tri(a)["class"] == "UNDETERMINED"


def test_C17b_usb_stick_software_unknown_partition_hypothesis(cli):
    """C17b. Mutation: needs_elevation lowers to UNDETERMINED, or fs_unrecognised unused -> red."""
    _, _, a = prepared(cli, USB_STICK, "/dev/pd2")
    assert tri(a)["class"] == "SOFTWARE_RECOVERY_CANDIDATE"
    assert a["health"]["verdict"] == "unknown"
    hyps = {h["category"]: h for h in a["hypotheses"]}
    h = hyps["partition-or-filesystem"]
    assert h["confidence"] == "medium"
    txt = ev_text(h["evidence"]).lower()
    assert "mbrtype" in txt.replace("_", "") and "7" in txt
    assert "controller returns garbage / fake-capacity wrap corrupted the fs" in h["alternative"].lower()
    assert "image or read-only inspect, then capacity verify after data is secured" in h["next_test"].lower()
    fake = hyps.get("fake-capacity-or-counterfeit")
    assert fake is None or fake["confidence"] == "low"


def test_C17c_usb_sd_software_unknown_no_partition_hypothesis(cli):
    """C17c. Mutation: emit partition-or-filesystem for every USB device -> red."""
    _, _, a = prepared(cli, USB_SD, "/dev/pd3")
    assert tri(a)["class"] == "SOFTWARE_RECOVERY_CANDIDATE"
    assert a["health"]["verdict"] == "unknown"
    assert "partition-or-filesystem" not in {h["category"] for h in a["hypotheses"]}


def test_triage_class_enum(cli):
    """Spec Phase 1 classes only. Mutation: invent a class name -> red."""
    from conftest import TRIAGE_CLASSES

    _, _, a = ingested_assessment(cli, "smartctl/nvme-990pro-x.json")
    assert tri(a)["class"] in TRIAGE_CLASSES
