"""Phase 03 F3 parsers (C22, C23) + their hypotheses via `assess`. Spec: phase-03 Requirements 'f3probe', 'f3write',
'f3read' + C22/C23. Inputs: only lines quoted verbatim in researcher-03 §1 (fixtures/ingest/*.verbatim.txt)."""
import pytest

from conftest import USB_STICK, assess, collect, device_at, fx, fx_text, new_session

GOOD = "ingest/f3probe-good.verbatim.txt"
DAMAGED = "ingest/f3probe-damaged.verbatim.txt"
WRAP = "ingest/f3probe-wraparound.verbatim.txt"
NOSPACE = "ingest/f3write-no-space.verbatim.txt"


def probe(rel, code):
    from rslib.ingest import parse_f3probe

    return parse_f3probe(fx_text(rel), code)


def test_C22_exit_0_good_news_is_good():
    """C22. Mutation: ignore exit code and read text only (still good) / map 0 to inconclusive -> red."""
    assert probe(GOOD, 0)["result"] == "good"


def test_C22_exit_103_wraparound_is_fake():
    """C22. Mutation: map 103 to limbo (off-by-one in 100+type) -> red."""
    r = probe(WRAP, 103)
    assert r["result"] == "fake" and r["fake_type"] == "wraparound"


def test_C22_exit_101_damaged():
    """C22. Mutation: 101 treated as tool error -> inconclusive -> red."""
    assert probe(DAMAGED, 101)["result"] == "damaged"


@pytest.mark.parametrize("code", [1, 2, 105, 255])
def test_C22_other_nonzero_is_inconclusive(code):
    """C22 'exit 1 -> inconclusive' (+ any other non 0/101-104). Mutation: code >= 100 -> fake -> red for 105."""
    assert probe(GOOD, code)["result"] == "inconclusive"


def test_C22_code_text_disagree_inconclusive():
    """C22 'exit 103 with Good news -> inconclusive (code/text disagree)'. Mutation: trust the code alone -> red."""
    r = probe(GOOD, 103)
    assert r["result"] == "inconclusive"
    assert "disagree" in (r["reason"] or "")


def test_C22_wraparound_text_with_limbo_code_disagree():
    """C22 'Bad news ... counterfeit of type X must agree with the code' (102 limbo vs text wraparound)."""
    assert probe(WRAP, 102)["result"] == "inconclusive"


def test_C23_f3write_no_space_inconclusive():
    """C23. Mutation: `No space!` treated as write failure -> fail -> red."""
    from rslib.ingest import parse_f3write

    r = parse_f3write(fx_text(NOSPACE), 1)
    assert r["result"] == "inconclusive"
    assert "nothing written" in (r["reason"] or "")


@pytest.mark.skip(reason="BLOCKED (open question F3-numbers): research quotes f3read labels (`Data OK:`, `Data LOST:`, "
                         "`Overwritten:`) without values; no sourced f3read output with numbers exists, and the task "
                         "forbids inventing device output. Needs a real f3read capture (SOURCES.md 'No real sample yet').")
def test_C23_f3read_exit0_data_lost_zero_pass():
    """C23 'f3read exit 0 with Data LOST zero -> pass'."""


@pytest.mark.skip(reason="BLOCKED (open question F3-numbers): needs a real f3read output with non-zero Overwritten.")
def test_C23_f3read_exit1_overwritten_fail_and_fake_capacity_medium():
    """C23 'exit 1 with non-zero Overwritten -> fail, hypothesis fake-capacity medium'."""


# ---------------- hypotheses after ingest (CLI)
def _stick(cli):
    sid = new_session(cli, "--goal", "authenticity-check", "--preserve-data", "no")
    dev = device_at(cli, USB_STICK, sid, "/dev/pd2")
    collect(cli, USB_STICK, sid, dev)
    return sid, dev


@pytest.mark.parametrize("rel,code,category,confidence", [
    (WRAP, 103, "fake-capacity-or-counterfeit", "high"),
    (DAMAGED, 101, "nand-degradation", "medium"),
])
def test_C22_f3probe_ingest_drives_hypothesis(cli, rel, code, category, confidence):
    """C22 hypotheses. Mutation: f3 evidence not fed to hypotheses -> red."""
    sid, dev = _stick(cli)
    res = cli("ingest", "f3probe", sid, dev, fx(rel), "--exit-code", code)
    assert res.code == 0, res
    assert res.data["evidence"]["kind"] == "f3probe"
    assert res.data["evidence"]["level"] == "parsed"
    a = assess(cli, sid, dev)
    h = {x["category"]: x for x in a["hypotheses"]}
    assert h[category]["confidence"] == confidence
    assert h[category]["evidence"]
    assert res.data["evidence"]["id"] in a["inputs"]["evidence_ids"]


def test_C22_good_f3probe_no_counterfeit_above_low(cli):
    """C19 with an f3 record: a GOOD probe never raises counterfeit. Mutation: any f3 record -> counterfeit -> red."""
    sid, dev = _stick(cli)
    assert cli("ingest", "f3probe", sid, dev, fx(GOOD), "--exit-code", 0).code == 0
    a = assess(cli, sid, dev)
    for h in a["hypotheses"]:
        if h["category"] == "fake-capacity-or-counterfeit":
            assert h["confidence"] == "low"


def test_f3_ingest_requires_exit_code(cli):
    """Requirements 'exit code (operator-provided --exit-code)'. Mutation: default exit code 0 -> 'good' from text -> red."""
    sid, dev = _stick(cli)
    res = cli("ingest", "f3probe", sid, dev, fx(GOOD), json_out=False)
    assert res.code == 2, res
