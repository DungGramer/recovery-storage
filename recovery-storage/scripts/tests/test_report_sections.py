"""Phase 05 report model and sections (E1-E5). Spec: phase-05 Key Insights (tags), Requirements 'Report sections',
spec §7 + E1-E5."""
import json

import pytest

from conftest import (REPORT_HEADINGS, USB_SD, USB_STICK, assess, close, collect, confirm, fx_json, gate_ok,
                      gate_open_state, ingest_smart, inventory, new_session, norm, obs_for, ok, prepared, sha256_hex)

FAIL_HDD = "smartctl/scrutiny-usbjmicron-hdd-failing.json"


def e1_session(cli):
    sid = new_session(cli, "--goal", "data-recovery")
    dev = ingest_smart(cli, sid, FAIL_HDD).data["device_id"]
    assess(cli, sid, dev)
    return sid, dev


def sections(model, dev=None):
    devs = model["devices"]
    d = devs[0] if dev is None else next(x for x in devs if x["device_id"] == dev)
    return {s["number"]: s for s in d["sections"]}


def sec_text(sec):
    return norm(" ".join(str(i.get("text", "")) for i in sec["items"]))


def test_E1_eleven_headings_in_order(cli):
    """E1. Mutation: reorder sections or drop 'Hạn chế còn tồn tại' -> red."""
    sid, _ = e1_session(cli)
    md = cli("report", sid, json_out=False)
    assert md.code == 0, md
    text = norm(md.out)
    pos = [text.find(norm(h)) for h in REPORT_HEADINGS]
    assert all(p >= 0 for p in pos), list(zip(REPORT_HEADINGS, pos))
    assert pos == sorted(pos)


def test_E1_model_numbers_and_headings(cli):
    """E1 (model). Mutation: section numbers off by one -> red."""
    sid, _ = e1_session(cli)
    m = ok(cli("report", sid))
    secs = sections(m)
    assert sorted(secs) == list(range(1, 12))
    for n, h in enumerate(REPORT_HEADINGS, start=1):
        assert norm(secs[n]["heading"]).endswith(norm(h)) or norm(h) in norm(secs[n]["heading"])


def test_E1_section_9_unresolved_without_verdict(cli):
    """E1. Mutation: leave section 9 empty or print PASS by default -> red."""
    sid, _ = e1_session(cli)
    assert "unresolved (no verdict recorded)" in sec_text(sections(ok(cli("report", sid)))[9])
    assert "unresolved (no verdict recorded)" in cli("report", sid, json_out=False).out.lower()


def test_E1_check_lists_sections_8_and_9(cli):
    """E1 --check. Mutation: --check exit 0 without verdict, or list only 9 -> red."""
    sid, _ = e1_session(cli)
    res = cli("report", sid, "--check")
    assert res.code == 3, res
    assert sorted(res.data["check"]["missing_sections"]) == [8, 9]
    t = cli("report", sid, "--check", json_out=False)
    assert t.code == 3 and "8" in t.text and "9" in t.text


def test_E2_inferred_items_carry_rule_and_confidence(cli):
    """E2. Mutation: hypothesis lines without rule id / confidence -> red."""
    sid, _ = e1_session(cli)
    s4 = sections(ok(cli("report", sid)))[4]
    inferred = [i for i in s4["items"] if i["tag"] == "[INFERRED]"]
    assert inferred
    for i in inferred:
        assert i["rule_id"] and i["confidence"] in ("low", "medium", "high"), i
    assert "[INFERRED]" in cli("report", sid, json_out=False).out


def test_E2_verified_smart_values_carry_tool_version_and_evidence(cli):
    """E2. Mutation: [VERIFIED] without tool/version/evidence id -> red."""
    sid, _ = e1_session(cli)
    s3 = sections(ok(cli("report", sid)))[3]
    verified = [i for i in s3["items"] if i["tag"] == "[VERIFIED]"]
    assert verified
    for i in verified:
        assert str(i["tool"]).startswith("smartctl 7."), i
        assert i["evidence_id"], i
    md = cli("report", sid, json_out=False).out
    assert "[VERIFIED]" in md and "smartctl 7.1" in md


def test_E2_missing_field_undetermined_not_reported(cli):
    """E2 (scrutiny-sat-partial lacks model / smart_status). Mutation: omit missing fields or print 0 -> red."""
    sid = new_session(cli)
    dev = ingest_smart(cli, sid, "smartctl/scrutiny-sat-partial.json").data["device_id"]
    assess(cli, sid, dev)
    s3 = sections(ok(cli("report", sid)))[3]
    und = [i for i in s3["items"] if i["tag"] == "[UNDETERMINED]"]
    assert und
    assert any(str(i["text"]).endswith("not reported") for i in und), und
    assert "not reported" in cli("report", sid, json_out=False).out


def test_E3_attested_tagged_attested_with_sha(cli, tmp_path):
    """E3. Mutation: attested evidence shown as [VERIFIED] -> red.
    Amendment 01 A: the JSON tag stays the epistemic tag `[ATTESTED]`; the rendered report shows
    `[ATTESTED by operator]`. Mutation: markdown keeps bare `[ATTESTED]` (who is lost) -> red."""
    sid, dev = e1_session(cli)
    f = tmp_path / "h2.txt"
    f.write_bytes(b"operator attachment E3")
    ok(cli("ingest", "attested", sid, dev, "--tool", "h2testw", "--result", "pass", "--file", f, answers=["YES"]))
    m = ok(cli("report", sid))
    sha = sha256_hex(f.read_bytes())
    items = [i for s in sections(m).values() for i in s["items"] if i.get("sha256") == sha or sha in str(i.get("text"))]
    assert items
    assert {i["tag"] for i in items} == {"[ATTESTED]"}
    md = cli("report", sid, json_out=False).out
    assert "[ATTESTED by operator]" in md and sha in md


def test_E4_closed_format_gate_in_5_and_7_section_8_still_missing_verify(cli):
    """E4 + §8 'format success is not recovery'. Mutation: format success fills section 8 -> red."""
    sid, dev, _ = prepared(cli, USB_STICK, "/dev/pd2", "--goal", "device-recovery", "--preserve-data", "no",
                           "--ceiling", "R2")
    g, _ = gate_ok(cli, USB_STICK, sid, dev, "format")
    assert confirm(cli, USB_STICK, g, "8054112256").code == 0
    assert close(cli, USB_STICK, g, "success").code == 0
    secs = sections(ok(cli("report", sid)))
    for n in (5, 7):
        t = sec_text(secs[n])
        assert "format" in t and "success" in t, (n, t)
    assert "capacity" in sec_text(secs[8])


def test_E5_pass_limited_sentence_and_limitation(cli):
    """E5. Mutation: missing the unique/critical-data warning -> red."""
    sid = new_session(cli)
    dev = ingest_smart(cli, sid, "smartctl/nvme-990pro-x.json").data["device_id"]
    assess(cli, sid, dev)
    ok(cli("verdict", "set", sid, dev, "PASS_LIMITED", "--limitation", "only for scratch files"))
    secs = sections(ok(cli("report", sid)))
    assert norm("không dùng cho dữ liệu duy nhất hoặc quan trọng") in sec_text(secs[11])
    assert "only for scratch files" in sec_text(secs[10])
    md = norm(cli("report", sid, json_out=False).out)
    assert norm("không dùng cho dữ liệu duy nhất hoặc quan trọng") in md


def test_report_tags_only_the_four(cli):
    """Key insight: every statement carries one of four epistemic tags. Mutation: untagged items -> red."""
    sid, _ = e1_session(cli)
    for s in sections(ok(cli("report", sid))).values():
        for i in s["items"]:
            assert i["tag"] in ("[VERIFIED]", "[ATTESTED]", "[INFERRED]", "[UNDETERMINED]", None, ""), i
            if s["number"] in (3, 4):
                assert i["tag"], i


# ================= Amendment 05 (2026-10-20): report fixes R1-R4 (E6b in test_report_redact.py, E8b in test_fleet.py)
# Spec: plans/.../amendment-05-report-fixes.md, CONTRACT.md "Amendment 05".
SD_EMPTY = "windows/sd-reader-empty"   # reader Disk 3 /dev/pd3: Size 0, No Media (real capture)
DEVREC = ("--goal", "device-recovery", "--preserve-data", "no", "--ceiling", "R2")
FS_SYMPTOM = ("--symptom", "raw-or-unreadable-fs")
NVME = "smartctl/nvme-990pro-x.json"


def dev_sections(cli, sid, dev, *extra):
    return sections(ok(cli("report", sid, "--device", dev, *extra)), dev)


def stick_pass_flow(cli, tmp_path):
    """Real run S-81ff60a59449 shape: stick + fs symptom -> assess -> format gate -> attested H2testw -> replug -> PASS.
    Returns (sid, dev, pre-verdict assessment)."""
    sid, dev, a = prepared(cli, USB_STICK, "/dev/pd2", *DEVREC, *FS_SYMPTOM)
    g, _ = gate_ok(cli, USB_STICK, sid, dev, "format")
    assert confirm(cli, USB_STICK, g, "8054112256").code == 0
    assert close(cli, USB_STICK, g, "success").code == 0
    f = tmp_path / "h2testw-stick.txt"
    f.write_bytes(b"operator attachment: H2testw result for the stick (amendment 05)")
    ok(cli("ingest", "attested", sid, dev, "--tool", "h2testw", "--result", "pass", "--file", f, answers=["YES"]))
    inventory(cli, cli.runner(USB_STICK), sid, after_replug=True)
    inventory(cli, cli.runner(USB_STICK), sid)
    ok(cli("verdict", "set", sid, dev, "PASS"))
    return sid, dev, a


def reader_retired_flow(cli, status="RETIRED"):
    """Real run S-4fdc1ba07b90 shape: empty reader, card never detected after isolation -> T2a -> RETIRED (neutral
    reason: the real reason text already said 'the reader itself is not judged'). Returns (sid, dev)."""
    sid = new_session(cli, "--goal", "diagnosis-only", "--device-type", "sd", "--symptom", "not-detected",
                      "--tried", "reseat-media", "--tried", "other-reader", "--tried", "other-host")
    o = obs_for(inventory(cli, cli.runner(SD_EMPTY), sid), "/dev/pd3")
    assert o["device_id"] and o["no_media"] is True, o
    dev = o["device_id"]
    collect(cli, SD_EMPTY, sid, dev)
    assess(cli, sid, dev)
    ok(cli("verdict", "set", sid, dev, status, "--reason", "operator decision recorded in the test"))
    return sid, dev


def note_events(cli, sid):
    return [e for e in ok(cli("session", "show", sid))["events"] if e["field"] == "note"]


def _ts_in(ts, text):
    """ISO timestamp shown to the second, 'T' or space separator (test-designer reading)."""
    return ts[:10] in text and ts[11:19] in text


# ---------------- E12 (R2): session notes in the report
def test_E12_session_notes_in_section_3_attested_with_who_and_ts_in_order(cli):
    """Amendment 05 R2: notes recorded with `session note` appear in section 3, tagged [ATTESTED], with who and
    timestamp, in time order. Mutation: notes not rendered (pre-amendment) -> red; tagged [VERIFIED] -> red; reversed
    order -> red; who / ts dropped -> red."""
    sid = new_session(cli, "--goal", "diagnosis-only")
    dev = ingest_smart(cli, sid, NVME).data["device_id"]
    assess(cli, sid, dev)
    ok(cli("session", "note", sid, "first note: reader LED blinks when the card is inserted"))
    ok(cli("session", "note", sid, "second note: tried the card in a phone, not detected"))
    evs = note_events(cli, sid)
    assert len(evs) == 2, evs
    items = dev_sections(cli, sid, dev)[3]["items"]
    idx = []
    for e in evs:
        hits = [k for k, i in enumerate(items) if e["new"] in str(i.get("text"))]
        assert hits, (e, items)
        it = items[hits[0]]
        assert it["tag"] == "[ATTESTED]", it
        blob = json.dumps(it, ensure_ascii=False)
        assert e["who"] in blob and _ts_in(e["ts"], blob), (e, it)
        idx.append(hits[0])
    assert idx == sorted(idx) and idx[0] != idx[1], idx
    md = cli("report", sid, "--device", dev, json_out=False).out
    for e in evs:
        line = next((ln for ln in md.splitlines() if e["new"] in ln), None)
        assert line and "[ATTESTED" in line and e["who"] in line and _ts_in(e["ts"], line), (e, line)


def test_E12_notes_of_another_session_do_not_appear(cli):
    """Amendment 05 R2 'notes from other sessions do not appear' (same device in both sessions).
    Mutation: notes selected by device or across all sessions -> red."""
    s1 = new_session(cli, "--goal", "diagnosis-only")
    dev = ingest_smart(cli, s1, NVME).data["device_id"]
    assess(cli, s1, dev)
    ok(cli("session", "note", s1, "note of session one"))
    s2 = new_session(cli, "--goal", "diagnosis-only")
    assert ingest_smart(cli, s2, NVME).data["device_id"] == dev
    assess(cli, s2, dev)
    ok(cli("session", "note", s2, "note of session two"))
    r1 = cli("report", s1, "--device", dev)
    assert "note of session one" in r1.out and "note of session two" not in r1.out, r1
    md2 = cli("report", s2, "--device", dev, json_out=False).out
    assert "note of session two" in md2 and "note of session one" not in md2


def test_E12_notes_shown_for_every_device_of_the_session(cli):
    """Amendment 05 R2, test-designer reading: notes are session-level -> section 3 of every device of that session's
    report. Mutation: notes attached to the first device only -> red."""
    sid = new_session(cli, "--goal", "diagnosis-only")
    d1 = ingest_smart(cli, sid, NVME).data["device_id"]
    d2 = ingest_smart(cli, sid, "smartctl/scrutiny-ata-hdd-healthy.json").data["device_id"]
    for d in (d1, d2):
        assess(cli, sid, d)
    ok(cli("session", "note", sid, "both disks came from the same NAS"))
    m = ok(cli("report", sid))
    for d in (d1, d2):
        assert norm("both disks came from the same NAS") in sec_text(sections(m, d)[3]), d


def test_E12_notes_pass_through_redaction(cli, home):
    """Amendment 05 R2 + R1: with --redact a note gets the same redaction as the rest: the device serial and the home
    path are masked, fixed words in the note ('serial not reported') are kept. Mutation: notes rendered raw under
    --redact (serial / home leak) -> red; serial pattern eats 'not' -> red."""
    sid = new_session(cli, "--goal", "diagnosis-only")
    dev = ingest_smart(cli, sid, NVME).data["device_id"]
    assess(cli, sid, dev)
    serial = fx_json(NVME)["serial_number"]
    keep = "serial not reported by the old enclosure"
    ok(cli("session", "note", sid, f"drive {serial} moved from {home} box; {keep}"))
    plain = cli("report", sid, "--device", dev, json_out=False).out
    assert serial in plain and keep in plain
    red_md = cli("report", sid, "--device", dev, "--redact", json_out=False).out
    red_js = cli("report", sid, "--device", dev, "--redact").out
    for red in (red_md, red_js):
        assert serial not in red
        assert str(home) not in red and home.as_posix() not in red
        assert keep in red


# ---------------- E13 (R3): pre-verdict hypotheses are not open items after PASS / PASS_LIMITED
def _pre_next_tests(a):
    out = [a["triage"].get("next_test")] + [h.get("next_test") for h in a["hypotheses"]]
    return [norm(t) for t in out if t and str(t).strip()]


def _hyp_items(sec, category):
    return [i for i in sec["items"] if category in str(i.get("text"))]


def _pass_limited_nvme(cli):
    sid = new_session(cli, "--goal", "diagnosis-only", *FS_SYMPTOM)
    dev = ingest_smart(cli, sid, NVME).data["device_id"]
    a = assess(cli, sid, dev)
    assert "partition-or-filesystem" in {h["category"] for h in a["hypotheses"]}, a["hypotheses"]
    ok(cli("verdict", "set", sid, dev, "PASS_LIMITED", "--limitation", "scratch use only"))
    return sid, dev, a


@pytest.mark.parametrize("flow", ["stick-pass", "nvme-pass-limited"])
def test_E13_pre_verdict_next_tests_not_shown_after_pass(cli, tmp_path, flow):
    """Amendment 05 R3 (decision: kept for history, marked resolved). Effective verdict PASS / PASS_LIMITED -> every
    next test of the pre-verdict assessment (triage and hypotheses) is absent from sections 4 and 11, and each
    pre-verdict hypothesis item says `resolved by verdict <STATUS>`. Mutation: sections 4 / 11 render the stale
    assessment as today (real report S-81ff60a59449) -> red."""
    if flow == "stick-pass":
        sid, dev, a = stick_pass_flow(cli, tmp_path)
        status = "PASS"
    else:
        sid, dev, a = _pass_limited_nvme(cli)
        status = "PASS_LIMITED"
    pre = _pre_next_tests(a)
    assert pre, a
    secs = dev_sections(cli, sid, dev)
    for n in (4, 11):
        txt = sec_text(secs[n])
        for nt in pre:
            assert nt not in txt, (n, nt)
    for h in a["hypotheses"]:
        items = _hyp_items(secs[4], h["category"])
        assert items, (h["category"], secs[4]["items"])
        assert all(norm(f"resolved by verdict {status}") in norm(i["text"]) for i in items), items
    assert norm(f"resolved by verdict {status}") in norm(cli("report", sid, "--device", dev, json_out=False).out)


def test_E13_fail_verdict_keeps_hypotheses_open(cli):
    """Amendment 05 R3 applies to PASS / PASS_LIMITED only. Mutation: any verdict resolves the hypotheses -> red."""
    sid = new_session(cli, "--goal", "diagnosis-only", *FS_SYMPTOM)
    dev = ingest_smart(cli, sid, NVME).data["device_id"]
    a = assess(cli, sid, dev)
    ok(cli("verdict", "set", sid, dev, "FAIL", "--reason", "operator decision"))
    s4 = dev_sections(cli, sid, dev)[4]
    h = next(x for x in a["hypotheses"] if x["category"] == "partition-or-filesystem")
    items = _hyp_items(s4, "partition-or-filesystem")
    assert items and norm(h["next_test"]) in sec_text(s4), s4["items"]
    assert not any("resolved by verdict" in norm(i["text"]) for i in items)


def test_E13_assessment_after_the_verdict_is_current(cli):
    """Amendment 05 R3 'from the PRE-verdict assessment': an assess run after PASS_LIMITED is shown as current.
    Mutation: hide / resolve every hypothesis whenever the effective verdict is PASS* -> red."""
    sid, dev, _ = _pass_limited_nvme(cli)
    b = assess(cli, sid, dev)
    h = next(x for x in b["hypotheses"] if x["category"] == "partition-or-filesystem")
    s4 = dev_sections(cli, sid, dev)[4]
    items = _hyp_items(s4, "partition-or-filesystem")
    assert items and norm(h["next_test"]) in sec_text(s4), s4["items"]
    assert not any("resolved by verdict" in norm(i["text"]) for i in items)


SD_PHRASE = "4026531840"   # usb-sd card: junk serial -> phrase = byte count (D11)


def _format_sd(cli, sid, dev):
    """usb-sd card (FAT32 volume recognised -> its fs hypothesis rests on the symptom alone) formatted, gate closed."""
    g = gate_open_state(cli, USB_SD, sid, dev, "format", SD_PHRASE)
    res = close(cli, USB_SD, g, "success")
    assert res.code == 0 and res.data["gate"]["state"] == "closed", res


def _conf(a, category):
    return next(h["confidence"] for h in a["hypotheses"] if h["category"] == category)


def test_E13b_symptom_only_hypothesis_after_a_write_is_low(cli):
    """Amendment 05 R3 (decision: downgrade to low, keep the category): after a write in this session (last_write_ts
    later than the session start) a hypothesis whose every evidence item is `session.*` has confidence low, in the
    assessment and in report section 4. Pre-write it stays as today (medium). Mutation: confidence ignores the write
    (real report: medium after format) -> red; universal 'symptom-only = low' -> pre-write assertion red."""
    sid, dev, a = prepared(cli, USB_SD, "/dev/pd3", *DEVREC, *FS_SYMPTOM)
    h = next(x for x in a["hypotheses"] if x["category"] == "partition-or-filesystem")
    assert all(str(e["path"]).startswith("session.") for e in h["evidence"]), h
    assert h["confidence"] == "medium"
    _format_sd(cli, sid, dev)
    b = assess(cli, sid, dev)
    assert _conf(b, "partition-or-filesystem") == "low", b["hypotheses"]
    items = _hyp_items(dev_sections(cli, sid, dev)[4], "partition-or-filesystem")
    assert items and all(i["confidence"] == "low" for i in items), items


def test_E13b_write_in_an_earlier_session_leaves_new_symptoms_as_is(cli):
    """Amendment 05 R3: symptoms recorded in a session that starts after the write describe the post-write state ->
    unchanged (medium). Mutation: any write ever on the device lowers symptom-only hypotheses -> red."""
    s1, dev, _ = prepared(cli, USB_SD, "/dev/pd3", *DEVREC)
    _format_sd(cli, s1, dev)
    s2 = new_session(cli, *DEVREC, *FS_SYMPTOM)
    assert obs_for(inventory(cli, cli.runner(USB_SD), s2), "/dev/pd3")["device_id"] == dev
    collect(cli, USB_SD, s2, dev)
    b = assess(cli, s2, dev)
    h = next(x for x in b["hypotheses"] if x["category"] == "partition-or-filesystem")
    assert all(str(e["path"]).startswith("session.") for e in h["evidence"]), h
    assert h["confidence"] == "medium"


# ---------------- E14 (R4): verdict on a reader with no medium is the card's
def test_E14_verdict_on_empty_reader_worded_as_the_card(cli):
    """Amendment 05 R4 (b): section 9 of that session's report says the verdict applies to the card in the reader, not
    the reader (literals `card in the reader`, `not the reader`). Mutation: plain 'RETIRED (...): reason' (today) -> red."""
    sid, dev = reader_retired_flow(cli)
    s9 = sec_text(dev_sections(cli, sid, dev)[9])
    assert "retired" in s9 and "card in the reader" in s9 and "not the reader" in s9, s9
    md = norm(cli("report", sid, "--device", dev, json_out=False).out)
    assert "card in the reader" in md and "not the reader" in md


def test_E14_verdict_still_effective_in_its_own_session(cli):
    """Amendment 05 R4 (a) 'shown in that session's report': verdict show of the recording session unchanged.
    Mutation: the scoped verdict hidden everywhere -> red."""
    sid, dev = reader_retired_flow(cli)
    assert ok(cli("verdict", "show", sid, dev))["effective"] == "RETIRED"
    assert "retired" in sec_text(dev_sections(cli, sid, dev)[9])
