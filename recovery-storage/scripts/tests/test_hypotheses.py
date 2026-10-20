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


# ---------------- C17d (amendment 09): an event naming drive letter L goes to the device of the observation showing L
# nearest in time to the event (any device, any session); a tie goes to nobody.
# Real run 2026-10-20: 25 x Ntfs 55 on E: logged while a 32 GB card held E:, blamed on a 4 GB card seen hours later.
# Stand-in for "another medium on E:": the usb-stick capture with Disk 2's partition on E: (single-field derivation).
import datetime as dt  # noqa: E402
import json  # noqa: E402

from conftest import UTC, fx_json  # noqa: E402

STICK_ON_E = {"win-disks": f"{USB_STICK}/win-disks.stick-e.derived.json"}
EV_CAPTURE = NTFS55_X3["win-events"]          # events 2026-10-19T23:30 / 23:31 / 23:32 Z, volume E:
LATE = dt.datetime(2026, 10, 20, 7, 0, tzinfo=UTC)   # every collect / assess: hours after every placed inventory


def _t(day, hour, minute):
    return dt.datetime(2026, 10, day, hour, minute, tzinfo=UTC)


def _event_evidence(a):
    """Every evidence item of the assessment (health, triage, hypotheses) whose path is an OS event fact."""
    items = list(a["health"].get("evidence") or []) + list(a["triage"].get("evidence") or [])
    items += [e for h in a["hypotheses"] for e in h["evidence"]]
    return [e for e in items if str(e.get("path", "")).startswith("observation.events.")]


def _shape(a):
    return sorted((h["category"], h["confidence"], json.dumps(h["evidence"], sort_keys=True)) for h in a["hypotheses"])


def _timeline(cli, placed, events=EV_CAPTURE, stick_disks=STICK_ON_E):
    """`placed` = {"stick": datetime, "card": datetime}: each device's inventory runs at that moment (in its own
    session, both sessions opened before the first inventory). Then, at LATE, both are collected with the `events`
    capture (None = the real usb-sd capture, no events) and assessed. Returns ({who: assessment}, {who: device id})."""
    over_ev = {} if events is None else {"win-events": events}
    sticks = dict(stick_disks or {})
    cli.clock.now = min(placed.values()) - dt.timedelta(minutes=10)
    sid = {who: new_session(cli) for who in ("stick", "card")}
    dev = {}
    for who, when in sorted(placed.items(), key=lambda kv: kv[1]):
        cli.clock.now = when
        if who == "stick":
            dev[who] = device_at(cli, USB_STICK, sid[who], "/dev/pd2", sticks or None)
        else:
            dev[who] = device_at(cli, USB_SD, sid[who], "/dev/pd3")
    cli.clock.now = LATE
    collect(cli, USB_SD, sid["card"], dev["card"], override=over_ev or None)
    collect(cli, USB_STICK, sid["stick"], dev["stick"], override={**sticks, **over_ev} or None)
    return {who: assess(cli, sid[who], dev[who]) for who in ("stick", "card")}, dev, sid


# (case id, inventory times, which device the nearest E: observation belongs to)
NEAREST_CASES = [
    ("origin-other-after", {"stick": _t(19, 23, 35), "card": _t(20, 6, 0)}, "stick"),
    ("other-before", {"stick": _t(19, 23, 25), "card": _t(20, 6, 0)}, "stick"),
    ("card-before-far-other-after", {"card": _t(19, 18, 0), "stick": _t(19, 23, 35)}, "stick"),
    ("card-after", {"card": _t(19, 23, 33), "stick": _t(20, 6, 0)}, "card"),
    ("card-before", {"card": _t(19, 23, 25), "stick": _t(20, 6, 0)}, "card"),
    ("other-before-far-card-after", {"stick": _t(19, 18, 0), "card": _t(19, 23, 36)}, "card"),
]


@pytest.mark.parametrize("who", ["card", "stick"])
@pytest.mark.parametrize("case,placed,nearest", NEAREST_CASES, ids=[c[0] for c in NEAREST_CASES])
def test_C17d_letter_event_goes_to_the_nearest_holder_of_the_letter(cli, case, placed, nearest, who):
    """Amendment 09 E1 + E4 (assess). Both devices show E: in one observation each; the 3 Ntfs 55 events on E: are
    evidence only for the device whose E: observation is nearest in time (before or after). That device keeps the
    amendment 05 R5 item (`Ntfs 55`, count 3); the other has no `observation.events.*` item anywhere and its
    hypotheses equal the same timeline without events.
    Mutations caught: match by letter alone (today: both devices get the item) -> red on the far device; only
    observations after the event count -> red on other-before / card-before; latest holder at or before the event ->
    red on card-before-far-other-after / other-before-far-card-after; drop letter events once two devices ever held
    the letter -> red on the nearest device; observations of other sessions ignored -> red on origin-other-after."""
    got, _, _ = _timeline(cli, placed)
    a = got[who]
    if who == nearest:
        h = hyps(a).get("partition-or-filesystem")
        assert h is not None, (case, who, a["hypotheses"])
        items = [e for e in h["evidence"] if e["path"] == FS_CORRUPTION]
        assert len(items) == 1 and items[0]["value"] == "Ntfs 55" and items[0].get("count") == 3, (case, who, items)
    else:
        assert _event_evidence(a) == [], (case, who, _event_evidence(a))
        control, _, _ = _timeline(Cli(cli.home.parent / "control"), placed, events=None)
        assert _shape(a) == _shape(control[who]), (case, who, a["hypotheses"], control[who]["hypotheses"])
        if who == "card":
            assert "partition-or-filesystem" not in hyps(a), a["hypotheses"]   # C17c: no event supports it


def test_C17d_other_device_without_the_letter_does_not_take_the_events(cli):
    """Amendment 09 E1 (only observations SHOWING the letter compete). Origin timeline, but the stick's observation
    is the real usb-stick capture (its partition has no drive letter): the card is the only holder of E: and keeps
    the item with count 3. One field differs from test_C17d_..._nearest_holder[origin-other-after-card].
    Mutation caught: nearest observation of any removable device / any device, letter ignored -> red."""
    got, _, _ = _timeline(cli, {"stick": _t(19, 23, 35), "card": _t(20, 6, 0)}, stick_disks=None)
    items = [e for e in hyps(got["card"]).get("partition-or-filesystem", {"evidence": []})["evidence"]
             if e["path"] == FS_CORRUPTION]
    assert len(items) == 1 and items[0]["value"] == "Ntfs 55" and items[0].get("count") == 3, got["card"]["hypotheses"]
    assert _event_evidence(got["stick"]) == [], _event_evidence(got["stick"])


def test_C17d_sole_holder_keeps_events_however_far_in_time(cli):
    """Amendment 09 E1: with the card the only device ever showing E:, its observation is the nearest whatever the
    distance: the card inventoried 2.5 days after the events still gets the item (count 3).
    Mutation caught: a maximum time distance between event and observation -> red."""
    cli.clock.now = _t(22, 11, 0)
    sid = new_session(cli)
    dev = device_at(cli, USB_SD, sid, "/dev/pd3")
    collect(cli, USB_SD, sid, dev, override=NTFS55_X3)
    items = [e for e in hyps(assess(cli, sid, dev)).get("partition-or-filesystem", {"evidence": []})["evidence"]
             if e["path"] == FS_CORRUPTION]
    assert len(items) == 1 and items[0].get("count") == 3, items


def _first_observation_ts(cli, dev):
    hist = [h for h in cli("device", "show", dev).data["history"] if h["type"] == "observation"]
    return min(dt.datetime.fromisoformat(h["ts"].replace("Z", "+00:00")) for h in hist)


def _one_event_at(home, when):
    """The ntfs55x3 capture reduced to its first event with only `time` changed (in-test derivation, written to a
    temp file and served as the win-events answer). 7 fractional digits as Get-WinEvent writes them."""
    doc = fx_json(EV_CAPTURE)
    doc["events"] = [dict(doc["events"][0], time=when.strftime("%Y-%m-%dT%H:%M:%S.%f") + "0Z")]
    p = home.parent / "win-events.one.json"
    p.write_text(json.dumps(doc), encoding="utf-8")
    return {"stdout": p.read_bytes(), "exit_code": 0}


@pytest.mark.parametrize("offset_s,owner", [(0, None), (-1, "stick"), (1, "card")],
                         ids=["tie-nobody", "1s-nearer-stick", "1s-nearer-card"])
def test_C17d_equal_distance_is_attributed_to_nobody(cli, offset_s, owner):
    """Amendment 09 E1 'equal distance to observations of different devices: not attributed'. Stick on E: seen at
    ~23:29, card at ~23:33 (exact ts read back from `device show`); one Ntfs 55 on E: at their midpoint -> neither
    device has an event item; moved 1 s toward one device -> only that device has it.
    Mutations caught: letter alone (today: both) -> red in all three; tie to the assessed device (`<=`) -> red on
    tie-nobody; distance at minute granularity -> red on the 1 s cases."""
    cli.clock.now = _t(19, 23, 0)
    sid = {who: new_session(cli) for who in ("stick", "card")}
    cli.clock.now = _t(19, 23, 29)
    stick_dev = device_at(cli, USB_STICK, sid["stick"], "/dev/pd2", STICK_ON_E)
    cli.clock.now = _t(19, 23, 33)
    card_dev = device_at(cli, USB_SD, sid["card"], "/dev/pd3")
    t_stick, t_card = _first_observation_ts(cli, stick_dev), _first_observation_ts(cli, card_dev)
    assert t_stick < t_card, (t_stick, t_card)
    when = t_stick + (t_card - t_stick) / 2 + dt.timedelta(seconds=offset_s)
    ev = {"win-events": _one_event_at(cli.home, when)}
    cli.clock.now = LATE
    collect(cli, USB_SD, sid["card"], card_dev, override=ev)
    collect(cli, USB_STICK, sid["stick"], stick_dev, override={**STICK_ON_E, **ev})
    got = {"card": assess(cli, sid["card"], card_dev), "stick": assess(cli, sid["stick"], stick_dev)}
    for who, a in got.items():
        ev_items = _event_evidence(a)
        if who == owner:
            assert [(e["path"], e["value"]) for e in ev_items] == [(FS_CORRUPTION, "Ntfs 55")], (when, who, ev_items)
        else:
            assert ev_items == [], (when, who, ev_items)


def test_C17d_report_drops_the_misattributed_hypothesis(cli):
    """Amendment 09 E4 (report). Origin timeline: the card's report section 4 (JSON item text and markdown) has no
    `observation.events.fs_corruption` and no `partition-or-filesystem` hypothesis.
    Mutation caught: report re-derives hypotheses from the raw events by letter (or shows a stale assessment) -> red;
    today the item `hypothesis partition-or-filesystem: evidence observation.events.fs_corruption=Ntfs 55 (x3)` -> red."""
    _, dev, sid = _timeline(cli, {"stick": _t(19, 23, 35), "card": _t(20, 6, 0)})
    res = cli("report", sid["card"], "--device", dev["card"])
    assert res.code == 0, res
    d = next(x for x in res.data["devices"] if x["device_id"] == dev["card"])
    s4 = [str(i.get("text")) for s in d["sections"] if s["number"] == 4 for i in s["items"]]
    assert not [t for t in s4 if FS_CORRUPTION in t or "partition-or-filesystem" in t], s4
    md = cli("report", sid["card"], "--device", dev["card"], json_out=False)
    assert md.code == 0, md
    bad = [ln for ln in md.out.splitlines() if FS_CORRUPTION in ln or "hypothesis partition-or-filesystem" in ln]
    assert bad == [], bad


def _section3_event_lines(cli, sid, dev):
    """Section 3 JSON item texts and markdown lines that list one of the captured Ntfs 55 events on E:."""
    res = cli("report", sid, "--device", dev)
    assert res.code == 0, res
    d = next(x for x in res.data["devices"] if x["device_id"] == dev)
    hit = lambda t: "OS event Ntfs 55" in t and "volume E:" in t   # noqa: E731
    js = [str(i.get("text")) for s in d["sections"] if s["number"] == 3 for i in s["items"] if hit(str(i.get("text")))]
    md = cli("report", sid, "--device", dev, json_out=False)
    assert md.code == 0, md
    return js, [ln for ln in md.out.splitlines() if hit(ln)]


def test_C17d_report_section3_lists_the_events_only_for_the_nearest_holder(cli):
    """Amendment 09 E4 'disappear from D's ... evidence' (test-designer reading: report section 3 'Triệu chứng và bằng
    chứng' is the device's evidence section). Origin timeline: the card's section 3 (JSON item text and markdown)
    lists none of the three `OS event Ntfs 55 ... volume E:` lines; the stick's section 3 still lists all three.
    Events on a letter no observation shows (E2) are not asserted either way.
    Mutations caught: section 3 keeps the snapshot's whole host-wide event list (today: 3 lines on the card) -> red;
    every letter-named event dropped from every report -> red on the stick."""
    _, dev, sid = _timeline(cli, {"stick": _t(19, 23, 35), "card": _t(20, 6, 0)})
    card_js, card_md = _section3_event_lines(cli, sid["card"], dev["card"])
    assert card_js == [] and card_md == [], (card_js, card_md)
    stick_js, stick_md = _section3_event_lines(cli, sid["stick"], dev["stick"])
    assert len(stick_js) == 3 and len(stick_md) == 3, (stick_js, stick_md)
