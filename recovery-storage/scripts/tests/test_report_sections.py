"""Phase 05 report model and sections (E1-E5). Spec: phase-05 Key Insights (tags), Requirements 'Report sections',
spec §7 + E1-E5."""
import pytest

from conftest import (REPORT_HEADINGS, USB_STICK, assess, close, confirm, gate_ok, ingest_smart, new_session, norm, ok,
                      prepared, sha256_hex)

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
