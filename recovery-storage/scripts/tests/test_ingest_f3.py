"""Phase 03 F3 parsers (C22, C23) + their hypotheses via `assess`. Spec: phase-03 Requirements 'f3probe', 'f3write',
'f3read' + C22/C23. Inputs: only lines quoted verbatim in researcher-03 §1 (fixtures/ingest/*.verbatim.txt)."""
import pathlib

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


def test_C23_f3read_exit0_data_lost_zero_pass():
    """C23 'f3read exit 0 with Data LOST zero -> pass' (amendment 06: real F3 8.0 output, stick, 15724108 sectors OK).
    Mutation: summary not parsed -> inconclusive -> red; sectors not converted to bytes (x512) -> red."""
    r = f3read(STICK_PASS, 0)
    assert r["result"] == "pass", r
    assert r["data_ok_bytes"] == 15724108 * 512
    assert r["data_lost_bytes"] == 0
    assert r["corrupted_bytes"] == 0 and r["changed_bytes"] == 0 and r["overwritten_bytes"] == 0, r


@pytest.mark.skip(reason="BLOCKED (open question F3-numbers): needs a real f3read output with non-zero Overwritten "
                         "(the real card output of amendment 06 is corrupted only, Overwritten 0).")
def test_C23_f3read_exit1_overwritten_fail_and_fake_capacity_medium():
    """C23 'exit 1 with non-zero Overwritten -> fail, hypothesis fake-capacity medium'."""


# ---------------- C23b (amendment 06): real F3 8.0 outputs (WSL drvfs), result from the parsed summary
STICK_PASS = "f3/f3read-stick-pass.txt"          # exit 0, Data OK 15724108 sectors, LOST 0
STICK_ABORT = "f3/f3read-stick-abort134.txt"     # exit 134, assertion abort, no summary
CARD_LOST = "f3/f3read-card-lost.txt"            # exit 0, OK 592999, LOST 7079816 (all corrupted)
W_FULL = "f3/f3write-stick-volume-full.txt"      # Write failure on the last file, final Free space: 0.00 Byte
W_FULL_LEFT = "f3/f3write-stick-volume-full.free1mb.derived.txt"   # same, final Free space: 1.00 MB
W_REMOVED = "f3/f3write-card-removed.txt"        # Write failure + Can't create file, no final Free space line


def f3read(rel, code):
    from rslib.ingest import parse_f3read

    return parse_f3read(fx_text(rel), code)


def f3write(rel, code):
    from rslib.ingest import parse_f3write

    return parse_f3write(fx_text(rel), code)


@pytest.mark.parametrize("code", [0, 1])
def test_C23b_f3read_data_lost_is_fail_whatever_the_exit_code(code):
    """Amendment 06 F1 (real card: f3read 8.0 exits 0 with 7079816 sectors lost): Data LOST > 0 -> fail; reason names
    the lost bytes and the corrupted / changed / overwritten split. Mutation: exit 0 + summary -> 'inconclusive (summary
    not parsed)' (today) or pass -> red."""
    r = f3read(CARD_LOST, code)
    assert r["result"] == "fail", r
    assert r["data_ok_bytes"] == 592999 * 512
    assert r["data_lost_bytes"] == 7079816 * 512
    assert r["corrupted_bytes"] == 7079816 * 512 and r["changed_bytes"] == 0 and r["overwritten_bytes"] == 0, r
    reason = (r["reason"] or "").lower()
    assert str(7079816 * 512) in reason, reason
    for word in ("corrupted", "changed", "overwritten"):
        assert word in reason, (word, reason)


def test_C23b_nonzero_exit_with_clean_summary_keeps_the_summary_result():
    """Amendment 06 F1 'a non-zero exit code with a summary is recorded but does not flip the summary result'
    (test-designer reading). Mutation: exit 1 -> fail regardless of the summary (today) -> red; exit code not recorded
    -> red."""
    r = f3read(STICK_PASS, 1)
    assert r["result"] == "pass", r
    assert r["exit_code"] == 1


@pytest.mark.parametrize("code", [134, 0])
def test_C23b_f3read_without_summary_inconclusive(code):
    """Amendment 06 F1 'no parsable summary -> inconclusive whatever the exit code' (real exit 134 assertion abort).
    Mutation: exit 0 -> pass without a summary -> red."""
    r = f3read(STICK_ABORT, code)
    assert r["result"] == "inconclusive", r
    assert r["data_ok_bytes"] is None and r["data_lost_bytes"] is None


def test_C23b_f3write_failure_when_the_volume_became_full_inconclusive():
    """Amendment 06 F2 (real WSL drvfs: EIO instead of ENOSPC on the last file, final 'Free space: 0.00 Byte'):
    inconclusive, reason says the volume became full and to verify with f3read. Mutation: every 'Write failure' -> fail
    (today) -> red."""
    r = f3write(W_FULL, 0)
    assert r["result"] == "inconclusive", r
    reason = (r["reason"] or "").lower()
    assert "volume became full" in reason and "f3read" in reason, reason


@pytest.mark.parametrize("rel", [W_FULL_LEFT, W_REMOVED], ids=["free-space-left", "card-removed-no-final-line"])
def test_C23b_f3write_failure_with_space_left_still_fail(rel):
    """Amendment 06 F2 'Write failure with free space left > 0: fail as today'; test-designer reading: no final
    'Free space' line (card removed mid-run) is not the volume-full case -> fail. Mutation: any Write failure followed
    by any 'Free space' line, or every Write failure -> inconclusive -> red."""
    assert f3write(rel, 0)["result"] == "fail"


def _evidence_items(cli, sid, dev, ev_id):
    m = cli("report", sid, "--device", dev)
    assert m.code == 0, m
    d = next(x for x in m.data["devices"] if x["device_id"] == dev)
    return [i for s in d["sections"] for i in s["items"] if i.get("evidence_id") == ev_id]


def test_C23c_stale_parsed_row_is_reparsed_on_reingest_and_in_the_report(cli, home):
    """Amendment 06 F5 (decision: re-parse on read): the card f3read row written by the old parser (stored result
    inconclusive, live store E-0fa5fe3226ed) is re-parsed from its stored blob: re-ingesting the same bytes returns the
    SAME row (id, sha256) with the current result `fail`, and the report shows `fail`, not `inconclusive`.
    Mutation: dedup returns the stored parse (today) -> red; report reads the stored parse -> red; the row is replaced
    (new id / sha) instead of re-parsed -> red."""
    from conftest import F3READ_OLD_INCONCLUSIVE, db_rows, make_parsed_stale, sha256_hex

    sid, dev = _stick(cli)
    first = cli("ingest", "f3read", sid, dev, fx(CARD_LOST), "--exit-code", 0)
    assert first.code == 0, first
    ev = first.data["evidence"]
    make_parsed_stale(home, ev["id"], F3READ_OLD_INCONCLUSIVE)
    again = cli("ingest", "f3read", sid, dev, fx(CARD_LOST), "--exit-code", 0)
    assert again.code == 0, again
    ev2 = again.data["evidence"]
    assert ev2["id"] == ev["id"] and ev2["sha256"] == ev["sha256"] == sha256_hex(fx(CARD_LOST).read_bytes())
    assert ev2["parsed"]["result"] == "fail", ev2["parsed"]
    assert ev2["parsed"]["corrupted_bytes"] == 7079816 * 512
    items = _evidence_items(cli, sid, dev, ev["id"])
    assert items, "report shows the evidence"
    txt = " ".join(str(i.get("text")) for i in items).lower()
    assert "fail" in txt and "inconclusive" not in txt, txt
    rows = [r for r in db_rows(home, "evidence") if r["id"] == ev["id"]]
    assert len(rows) == 1 and rows[0]["sha256"] == ev["sha256"]


# ---------------- C23d (amendment 07): read rate, full volume below one f3 block, real f3probe limbo
CARD_CACHED = "f3/f3read-card-partition-cached.txt"            # 158.61 MB/s, read right after f3write (host cache)
CARD_AFTER_REPLUG = "f3/f3read-card-partition-after-replug.txt"  # 17.38 MB/s, same card after a replug
W_FULL_4K = "f3/f3write-card-partition-full4k.txt"             # Write failure, final Free space: 4.00 KB
PROBE_LIMBO = "f3/f3probe-card-limbo.txt"                       # exit 102, counterfeit of type limbo


@pytest.mark.parametrize("rel,rate", [(CARD_CACHED, "158.61 MB/s"), (CARD_AFTER_REPLUG, "17.38 MB/s"),
                                      (STICK_PASS, "275.95 MB/s")])
def test_C23d_f3read_records_the_read_rate_text(rel, rate):
    """Amendment 07 G2: `read_rate` = the text of the 'Average reading speed' line; informational (no rule): both card
    reads stay pass. Mutation: rate not parsed, or the number without its unit -> red."""
    r = f3read(rel, 0)
    assert r["read_rate"] == rate, r
    assert r["result"] == "pass"


def test_C23d_f3read_without_summary_has_no_read_rate():
    """Amendment 07 G2 boundary (aborted run prints no 'Average reading speed'). Mutation: default '0' -> red."""
    assert f3read(STICK_ABORT, 134)["read_rate"] is None


def test_C23d_report_shows_the_read_rate(cli):
    """Amendment 07 G2 'the report shows it'. Mutation: parsed but not rendered -> red."""
    sid, dev = _stick(cli)
    ev = cli("ingest", "f3read", sid, dev, fx(CARD_AFTER_REPLUG), "--exit-code", 0)
    assert ev.code == 0, ev
    md = cli("report", sid, "--device", dev, json_out=False).out
    assert "17.38 MB/s" in md
    txt = " ".join(str(i.get("text")) for i in _evidence_items(cli, sid, dev, ev.data["evidence"]["id"]))
    assert "17.38 MB/s" in txt, txt


def test_C23d_f3write_full_volume_below_one_block_inconclusive():
    """Amendment 07 G3 (real card partition: drvfs EIO with final 'Free space: 4.00 KB', less than one 1 MiB f3 block)
    -> inconclusive (volume became full). Mutation: amendment 06 'exactly 0.00 Byte' kept (today: fail) -> red;
    number compared without its unit (4 >= 1) -> red."""
    r = f3write(W_FULL_4K, 0)
    assert r["result"] == "inconclusive", r
    assert "volume became full" in (r["reason"] or "").lower()


def test_C23d_f3probe_real_limbo_is_fake_with_sizes():
    """Real f3probe 8.0 (exit 102, 'counterfeit of type limbo') -> fake / limbo; phase-03 'Parse *Usable* size: /
    Announced size: when present' -> `usable_size` / `announced_size` text (test-designer reading of the existing keys)
    carry the block counts. Mutation: tab-indented '*Usable* size:' line not matched (today: None) -> red."""
    r = probe(PROBE_LIMBO, 102)
    assert r["result"] == "fake" and r["fake_type"] == "limbo", r
    assert "603959" in str(r.get("usable_size")), r
    assert "63246336" in str(r.get("announced_size")), r


def test_C23d_f3probe_real_limbo_drives_counterfeit_high(cli):
    """C22 hypotheses on the real limbo output (as wraparound in C22). Mutation: only wraparound raises the
    counterfeit hypothesis -> red."""
    sid, dev = _stick(cli)
    res = cli("ingest", "f3probe", sid, dev, fx(PROBE_LIMBO), "--exit-code", 102)
    assert res.code == 0, res
    h = {x["category"]: x for x in assess(cli, sid, dev)["hypotheses"]}
    assert h["fake-capacity-or-counterfeit"]["confidence"] == "high"


# ---------------- C23e (amendment 08 H1): output_mtime recorded at ingest
@pytest.mark.parametrize("kind,rel", [("f3read", STICK_PASS), ("f3write", W_FULL)])
def test_C23e_ingest_records_output_mtime(cli, tmp_path, kind, rel):
    """Amendment 08 H1: `ingest f3read|f3write` records the file's mtime as `evidence.output_mtime`, UTC ISO in the store
    timestamp format (`YYYY-MM-DDTHH:MM:SS.ffffffZ`). Temp copy, fixture untouched. Mutation: mtime not recorded, or
    local time / another format -> red."""
    import datetime as dt
    import os
    import shutil

    sid, dev = _stick(cli)
    when = dt.datetime(2026, 10, 19, 23, 21, 7, tzinfo=dt.timezone.utc)
    p = tmp_path / pathlib.Path(rel).name
    shutil.copyfile(fx(rel), p)
    os.utime(p, (when.timestamp(), when.timestamp()))
    res = cli("ingest", kind, sid, dev, p, "--exit-code", 0)
    assert res.code == 0, res
    assert res.data["evidence"]["output_mtime"] == "2026-10-19T23:21:07.000000Z", res.data["evidence"]


def test_C23b_ingest_f3read_cli_records_the_summary_result(cli):
    """Amendment 06 F1 through `ingest f3read ... --exit-code 0` (the real card call). Mutation: CLI passes another
    exit code or skips the parser -> red."""
    sid, dev = _stick(cli)
    res = cli("ingest", "f3read", sid, dev, fx(CARD_LOST), "--exit-code", 0)
    assert res.code == 0, res
    p = res.data["evidence"]["parsed"]
    assert p["result"] == "fail" and p["data_lost_bytes"] == 7079816 * 512, p


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
