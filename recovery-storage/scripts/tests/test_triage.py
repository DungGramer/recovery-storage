"""Phase 03 triage (C13-C17c) through `assess` (black box). Spec: phase-03 Requirements 'Triage class' rules 1-5,
'Constraints', decision Q5, C13-C17c."""
import pytest

from conftest import (BASELINE, REAL_SMART, USB_SD, USB_STICK, assess, collect, device_at, ev_text, ingest_smart,
                      ingested_assessment, inventory, new_session, obs_for, prepared)

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


# ---------------- Amendment 03: card reader present, medium never detected (C14b, C14c, C14d)
# Spec: plans/.../amendment-03-real-run-card-reader.md, CONTRACT.md "Amendment 03".
SD_EMPTY = "windows/sd-reader-empty"   # real capture: reader Disk 3 Size 0, OperationalStatus "No Media"
SD_MEDIA_ONLINE = {"win-disks": f"{SD_EMPTY}/win-disks.media-online.derived.json"}   # same reader, status Online
ISOLATION_STEPS = ["other-port", "other-cable", "other-host", "other-os", "reseat-media", "other-reader"]
STOP_RULE = "T1-stop-unsafe"
T2A = "T2a-not-detected-isolated"
T5 = "T5-undetermined"


def _flags(symptoms=("not-detected",), tried=(), device_type="sd"):
    flags = ["--goal", "diagnosis-only"]
    if device_type:
        flags += ["--device-type", device_type]
    for s in symptoms:
        flags += ["--symptom", s]
    for t in tried:
        flags += ["--tried", t]
    return flags


def _empty_reader(cli, flags, collect_too=False, then=None):
    """session new -> inventory SD_EMPTY (-> collect) (-> inventory `then` override) -> assess the reader at /dev/pd3.
    Precondition asserted: the reader is present with `no_media` true (amendment 03 contract key)."""
    sid = new_session(cli, *flags)
    o = obs_for(inventory(cli, cli.runner(SD_EMPTY), sid), "/dev/pd3")
    assert o["device_id"] and o["no_media"] is True, o
    dev = o["device_id"]
    if collect_too:
        collect(cli, SD_EMPTY, sid, dev)
    if then is not None:
        o2 = obs_for(inventory(cli, cli.runner(SD_EMPTY, then), sid), "/dev/pd3")
        assert o2["device_id"] == dev and o2["no_media"] is False, o2
    return assess(cli, sid, dev)


def _ev(t, path):
    items = [e for e in t["evidence"] if e.get("path") == path]
    assert items, (path, t["evidence"])
    return items[0]


def _all_next_tests(a):
    return " ".join([tri(a)["next_test"] or ""] + [h["next_test"] or "" for h in a["hypotheses"]]).lower()


@pytest.mark.parametrize("tried,device_type,collect_too", [
    (["other-host", "reseat-media", "other-reader"], "sd", True),   # the 2026-10-19 real run
    (["reseat-media", "other-reader"], "sd", False),                # only the new removable-media steps
    (["other-host", "other-port"], None, False),                    # old steps only, no device type
], ids=["real-run", "new-steps-only", "old-steps-no-device-type"])
def test_C14b_reader_present_no_media_isolated_is_hardware_branch_a(cli, tried, device_type, collect_too):
    """Amendment 03 A2. Mutation: T2a keeps requiring the device ABSENT from inventory (reader present -> T5) -> red;
    new --tried values not counted as isolation steps -> red (new-steps-only); rule gated on --device-type -> red."""
    a = _empty_reader(cli, _flags(tried=tried, device_type=device_type), collect_too)
    t = tri(a)
    assert t["class"] == "HARDWARE_DIAGNOSIS_REQUIRED", t
    assert t["branch"] == "a"
    assert t["rule_id"] == T2A


def test_C14b_evidence_names_no_media_symptoms_and_tried(cli):
    """Amendment 03 A2 evidence. Mutation: T2a evidence without observation.no_media, or session facts dropped -> red."""
    tried = ["other-host", "other-port"]   # old values: red today for the triage reason, not for argparse
    t = tri(_empty_reader(cli, _flags(tried=tried)))
    assert t["rule_id"] == T2A, t
    assert _ev(t, "observation.no_media")["value"] is True
    assert "not-detected" in ev_text(_ev(t, "session.symptoms")["value"])
    tried_val = ev_text(_ev(t, "session.tried")["value"])
    for step in tried:
        assert step in tried_val, (step, tried_val)


def test_C14b_next_test_names_the_card_no_software_tool_lab(cli):
    """Amendment 03 A2 next_test (literals fixed in CONTRACT Amendment 03). Mutation: keep the T5 'insert or reseat'
    instruction after the steps were recorded, or point at software recovery -> red."""
    t = tri(_empty_reader(cli, _flags(tried=["other-host", "other-port"])))
    assert t["rule_id"] == T2A, t
    nt = (t["next_test"] or "").lower()
    assert "card" in nt, nt
    assert "no software tool" in nt, nt
    assert "lab" in nt, nt
    assert "insert or reseat" not in nt, nt


def test_C14b_stop_unsafe_still_wins_over_no_media_isolation(cli):
    """Amendment 03 A2 'STOP_UNSAFE (T1) still takes precedence'. Mutation: no_media T2a evaluated before T1 -> red."""
    t = tri(_empty_reader(cli, _flags(symptoms=("not-detected", "liquid-damage"), tried=["other-host", "other-port"])))
    assert t["class"] == "STOP_UNSAFE", t
    assert t["rule_id"] == STOP_RULE


@pytest.mark.parametrize("tried", [[], ["other-host"]], ids=["none", "one"])
def test_C14c_no_media_fewer_than_two_steps_stays_t5_with_reseat(cli, tried):
    """Amendment 03 A3. Mutation: ISOLATION_MIN not applied on the no_media path (one step -> HARDWARE), or the T5
    insert/reseat next test dropped -> red."""
    t = tri(_empty_reader(cli, _flags(tried=tried)))
    assert t["class"] == "UNDETERMINED", t
    assert t["rule_id"] == T5
    assert "reseat" in (t["next_test"] or "").lower(), t["next_test"]


def test_C14c_same_step_twice_counts_once(cli):
    """Amendment 03 A2 'distinct isolation steps'. Mutation: count len(tried) instead of distinct steps -> red."""
    t = tri(_empty_reader(cli, _flags(tried=["other-host", "other-host"])))
    assert t["class"] == "UNDETERMINED", t
    assert t["rule_id"] == T5


def test_C14c_no_media_without_detect_symptom_stays_t5(cli):
    """Amendment 03 A3 'no_media without a detect symptom -> T5 as today'. Mutation: no_media + 2 steps -> HARDWARE
    whatever the symptom, or no_media dropped so 0 bytes reads as a controller fault (T3) -> red."""
    t = tri(_empty_reader(cli, _flags(symptoms=("raw-or-unreadable-fs",), tried=["other-host", "other-port"])))
    assert t["class"] == "UNDETERMINED", t
    assert t["rule_id"] == T5
    assert "reseat" in (t["next_test"] or "").lower(), t["next_test"]


def test_C14c_only_the_latest_observation_counts(cli):
    """Amendment 03 A2 'the LATEST observation has no_media true' (derived: same reader, OperationalStatus Online).
    Mutation: any earlier no_media observation of the device triggers T2a -> red."""
    a = _empty_reader(cli, _flags(tried=["other-host", "other-port"]), then=SD_MEDIA_ONLINE)
    assert tri(a)["class"] != "HARDWARE_DIAGNOSIS_REQUIRED", tri(a)
    assert tri(a)["rule_id"] != T2A


def test_C14c_absent_device_path_unchanged(cli):
    """Amendment 03 A3 'absent-device T2a path unchanged' (C14 setup, rule id now asserted).
    Mutation: T2a rewritten to need no_media, losing the absent-device trigger -> red."""
    sid, dev = _absent_device(cli, "--symptom", "not-detected", "--tried", "other-port", "--tried", "other-cable")
    t = tri(assess(cli, sid, dev))
    assert t["class"] == "HARDWARE_DIAGNOSIS_REQUIRED", t
    assert t["branch"] == "a" and t["rule_id"] == T2A


@pytest.mark.parametrize("tried", [[], ["other-host"], ["reseat-media"]], ids=["none", "other-host", "reseat-media"])
def test_C14d_no_media_lists_missing_isolation_steps(cli, tried):
    """Amendment 03 A4: with no_media and < 2 steps, the triage next_test or a hypothesis next_test lists every missing
    isolation step, the new values included. Mutation: list only the four old steps, or nothing -> red."""
    a = _empty_reader(cli, _flags(tried=tried))
    assert tri(a)["class"] == "UNDETERMINED", tri(a)
    text = _all_next_tests(a)
    for missing in [s for s in ISOLATION_STEPS if s not in tried]:
        assert missing in text, (missing, text)


@pytest.mark.skip(reason="OPEN QUESTION (amendment 03 Q1): is `disconnects-repeatedly` a DETECT symptom for the no_media "
                         "path? A2 names only `not-detected`; the absent-device T2a accepts both.")
def test_C14b_open_disconnects_repeatedly_with_no_media():
    """Would assert HARDWARE/T2a (or T5) for disconnects-repeatedly + no_media + 2 steps once decided."""


@pytest.mark.skip(reason="OPEN QUESTION (amendment 03 Q2): do `reseat-media` / `other-reader` count as isolation steps "
                         "on the ABSENT-device T2a path? A3 says that path is unchanged; A2 counts them for no_media.")
def test_C14c_open_new_steps_on_absent_device_path():
    """Would assert the class for an absent USB stick with only reseat-media + other-reader recorded once decided."""
