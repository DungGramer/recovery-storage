"""Phase 03 hypotheses (C2, C3, C9, C18, C19) + environment-fact rule. Spec: phase-03 Key Insights, Requirements
'Hypotheses', C2/C3/C9/C17b/C18/C19."""
import pytest

from conftest import (CATEGORIES, FIX, USB_SD, USB_STICK, Cli, assess, device_at, collect, ingest_smart,
                      ingested_assessment, new_session)


def hyps(a):
    return {h["category"]: h for h in a["hypotheses"]}


def test_C2_media_errors_bad_sectors_hypothesis(cli):
    """C2. Mutation: no alternative/next test text, or category nand-degradation -> red."""
    _, _, a = ingested_assessment(cli, "smartctl/scrutiny-nvme-media-errors.json")
    h = hyps(a)["bad-sectors-io"]
    assert "historical errors, now stable" in h["alternative"].lower()
    assert "re-collect after a full read, compare media_errors delta" in h["next_test"].lower()
    assert h["evidence"]


def test_C3_crc199_connection_hypothesis(cli):
    """C3. Mutation: 199 mapped to bad-sectors-io -> red."""
    _, _, a = ingested_assessment(cli, "smartctl/scrutiny-ata-ssd-crc199.json")
    h = hyps(a)["connection-cable-power-bridge"]
    nt = h["next_test"].lower()
    assert "cable" in nt and "port" in nt and "199" in nt
    assert "bad-sectors-io" not in hyps(a)


@pytest.mark.parametrize("rel", ["smartctl/scrutiny-open-failed.json", "smartctl/missing-device.json"])
def test_C9_environment_failures_raise_no_hardware_hypothesis(cli, rel):
    """C9 + Key insight 'environment facts never raise a hardware hypothesis'. Mutation: open failure -> physical-hardware -> red."""
    _, _, a = ingested_assessment(cli, rel)
    assert not {"physical-hardware", "controller-or-firmware"} & set(hyps(a))


def test_C9_needs_elevation_usb_no_hardware_hypothesis(cli):
    """C9 on the real USB capture (needs_elevation). Mutation: needs_elevation -> controller-or-firmware -> red."""
    sid = new_session(cli)
    dev = device_at(cli, USB_STICK, sid, "/dev/pd2")
    collect(cli, USB_STICK, sid, dev)
    a = assess(cli, sid, dev)
    assert not {"physical-hardware", "controller-or-firmware"} & set(hyps(a))


def test_physical_hardware_from_mechanical_symptom(cli):
    """Hypothesis categories: mechanical-noise -> physical-hardware with evidence (G1 group 9 at unit level)."""
    _, _, a = ingested_assessment(cli, "smartctl/scrutiny-ata-hdd-healthy.json", "--goal", "diagnosis-only",
                                  "--symptom", "mechanical-noise")
    assert hyps(a)["physical-hardware"]["evidence"]


def test_vid_pid_never_a_rule_input(cli):
    """Requirements 'VID/PID values are never rule inputs' (in-test VID mutation ABCD -> 05E3 keeps the result).
    Mutation: ABCD -> counterfeit hint raises a hypothesis -> results differ -> red."""
    import json

    from conftest import fx_json, fx_text

    sid1, d1, a1 = None, None, None
    sid1 = new_session(cli)
    d1 = device_at(cli, USB_STICK, sid1, "/dev/pd2")
    collect(cli, USB_STICK, sid1, d1)
    a1 = assess(cli, sid1, d1)
    other = Cli(cli.home.parent / "home-vid")
    pnp = fx_json(f"{USB_STICK}/win-pnp-chain.json")
    for d in pnp["disks"]:
        for n in d["Chain"]:
            n["InstanceId"] = n["InstanceId"].replace("VID_ABCD&PID_1234", "VID_05E3&PID_0751")
    tmp = cli.home.parent / "pnp-vid.json"
    tmp.write_text(json.dumps(pnp), encoding="utf-8")
    over = {"win-pnp-chain": {"stdout": tmp.read_bytes(), "exit_code": 0}}
    sid2 = new_session(other)
    d2 = device_at(other, USB_STICK, sid2, "/dev/pd2", override=over)
    collect(other, USB_STICK, sid2, d2, override=over)
    a2 = assess(other, sid2, d2)
    strip = lambda a: sorted((h["category"], h["confidence"]) for h in a["hypotheses"])
    assert strip(a1) == strip(a2)
    assert a1["triage"]["class"] == a2["triage"]["class"]


# ---------------- C18 / C19 properties over every fixture run
def _smart_rels():
    return sorted(f"smartctl/{p.name}" for p in (FIX / "smartctl").glob("*.json"))


@pytest.fixture(scope="module")
def corpus(tmp_path_factory):
    runners = []
    out = []
    for i, rel in enumerate(_smart_rels()):
        for flags in (("--goal", "diagnosis-only"), ("--goal", "data-recovery", "--symptom", "mechanical-noise"),
                      ("--goal", "diagnosis-only", "--symptom", "encrypted-locked")):
            c = Cli(tmp_path_factory.mktemp(f"h{i}"), runners)
            sid = new_session(c, *flags)
            dev = ingest_smart(c, sid, rel).data["device_id"]
            out.append((rel, flags, assess(c, sid, dev)))
    for cap, path in ((USB_STICK, "/dev/pd2"), (USB_SD, "/dev/pd3")):
        c = Cli(tmp_path_factory.mktemp("cap"), runners)
        sid = new_session(c)
        dev = device_at(c, cap, sid, path)
        collect(c, cap, sid, dev)
        out.append((cap, (), assess(c, sid, dev)))
    assert not [r.unrecorded for r in runners if r.unrecorded]
    return out


def test_C18_every_hypothesis_complete(corpus):
    """C18 property. Mutation: emit a hypothesis without evidence or with empty alternative -> red."""
    bad = []
    for rel, flags, a in corpus:
        for h in a["hypotheses"]:
            if h["category"] not in CATEGORIES or not h["evidence"] or not (h["alternative"] or "").strip() \
                    or not (h["next_test"] or "").strip() or h["confidence"] not in ("low", "medium", "high"):
                bad.append((rel, flags, h))
    assert bad == []


def test_C19_no_counterfeit_above_low_without_f3(corpus):
    """C19 property. Mutation: identity strings (generic model, VID) give counterfeit medium -> red."""
    bad = [(rel, h) for rel, _, a in corpus for h in a["hypotheses"]
           if h["category"] == "fake-capacity-or-counterfeit" and h["confidence"] != "low"]
    assert bad == []


# ---------------- C18b (amendment 05 R5): identical evidence items once, with a count
NTFS55_X3 = {"win-events": f"{USB_SD}/win-events.ntfs55x3.derived.json"}   # 3 x Ntfs 55 on volume E: (the card)
FS_CORRUPTION = "observation.events.fs_corruption"


def _ntfs_card(cli):
    sid = new_session(cli, "--goal", "diagnosis-only")
    dev = device_at(cli, USB_SD, sid, "/dev/pd3", NTFS55_X3)
    collect(cli, USB_SD, sid, dev, override=NTFS55_X3)
    return sid, dev


def test_C18b_repeated_event_evidence_once_with_count_json(cli):
    """Amendment 05 R5 (assess --json): three matching System events -> one evidence item (path, value unchanged) with
    `count` 3. Mutation: one item per event (today: 3 identical items) -> red; count dropped -> red."""
    sid, dev = _ntfs_card(cli)
    h = hyps(assess(cli, sid, dev))["partition-or-filesystem"]
    items = [e for e in h["evidence"] if e["path"] == FS_CORRUPTION]
    assert len(items) == 1, h["evidence"]
    assert items[0]["value"] == "Ntfs 55"
    assert items[0].get("count") == 3, items[0]


def test_C18b_repeated_event_evidence_once_with_count_text_and_report(cli):
    """Amendment 05 R5 (assess text, report JSON item text, report markdown): `observation.events.fs_corruption=Ntfs 55
    (x3)` exactly once, no bare repeats. Mutation: text renders every item (today: 3 times) -> red; no '(x3)' -> red."""
    import re

    sid, dev = _ntfs_card(cli)
    assess(cli, sid, dev)
    want = re.compile(re.escape(f"{FS_CORRUPTION}=Ntfs 55") + r"\s*\(x3\)")
    txt = cli("assess", sid, dev, json_out=False)
    assert txt.code == 0, txt
    m = cli("report", sid, "--device", dev)
    d = next(x for x in m.data["devices"] if x["device_id"] == dev)
    s4 = " ".join(str(i.get("text")) for s in d["sections"] if s["number"] == 4 for i in s["items"])
    md = cli("report", sid, "--device", dev, json_out=False).out
    for where, text in (("assess text", txt.out), ("report json", s4), ("report md", md)):
        assert len(want.findall(text)) == 1, (where, text)
        assert text.count(f"{FS_CORRUPTION}=Ntfs 55") == 1, (where, text)


def test_C18b_single_items_carry_no_count_marker(cli):
    """Amendment 05 R5 'with a count IF more than one': distinct items stay as they are (stick: fs_unrecognised,
    mbr_type, symptom). Mutation: every item rendered '(x1)' or given count != 1 -> red."""
    sid = new_session(cli, "--goal", "diagnosis-only", "--symptom", "raw-or-unreadable-fs")
    dev = device_at(cli, USB_STICK, sid, "/dev/pd2")
    collect(cli, USB_STICK, sid, dev)
    a = assess(cli, sid, dev)
    for h in a["hypotheses"]:
        assert all(e.get("count", 1) == 1 for e in h["evidence"]), h["evidence"]
    assert "(x1)" not in cli("assess", sid, dev, json_out=False).out
    assert "(x1)" not in cli("report", sid, "--device", dev, json_out=False).out


def test_C18_corpus_is_not_vacuous(corpus):
    """Guard: the property runs saw hypotheses at all (a no-hypothesis implementation must not pass C18)."""
    cats = {h["category"] for _, _, a in corpus for h in a["hypotheses"]}
    assert {"bad-sectors-io", "physical-hardware", "partition-or-filesystem"} <= cats
