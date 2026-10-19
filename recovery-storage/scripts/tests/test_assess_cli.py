"""Phase 03 ingest/assess commands (C24, C25). Spec: phase-03 Requirements 'Each ingested record ...', 'attested',
C24, C25; amendment 01 A (`ingest attested` needs the operator console and a typed `YES`)."""
import io
import sys

import pytest

from conftest import (BASELINE, assert_console_required, assess, db_rows, device_at, collect, fx, fx_bytes,
                      ingest_smart, new_session, ok, operator_state, sha256_hex)

MAP = "ingest/ddrescue-manual-1.30.map"


def _dev(cli):
    sid = new_session(cli)
    dev = device_at(cli, BASELINE, sid, "/dev/pd1")
    return sid, dev


def test_C24_same_file_twice_one_evidence_id(cli):
    """C24. Mutation: insert a new evidence row per ingest -> two ids -> red."""
    sid, dev = _dev(cli)
    a = ok(cli("ingest", "ddrescue", sid, dev, fx(MAP)))
    b = ok(cli("ingest", "ddrescue", sid, dev, fx(MAP)))
    assert a["evidence"]["id"] == b["evidence"]["id"]
    assert a["evidence"]["sha256"] == sha256_hex(fx_bytes(MAP))
    assert a["evidence"]["parsed"]["bad"] == 512 and a["evidence"]["parsed"]["finished"] is False


def test_C24_attested_without_file_exit_2(cli):
    """C24. Mutation: accept attestation without an attachment -> red."""
    sid, dev = _dev(cli)
    res = cli("ingest", "attested", sid, dev, "--tool", "h2testw", "--result", "pass", json_out=False,
              answers=["YES"])
    assert res.code == 2, res


def test_attested_evidence_level_and_sha(cli, tmp_path):
    """Requirements 'attested: stores sha256 of the attached file + operator text; evidence level attested'."""
    sid, dev = _dev(cli)
    att = tmp_path / "h2testw-operator-screenshot.txt"
    att.write_bytes(b"operator attachment for the test; not tool output")
    d = ok(cli("ingest", "attested", sid, dev, "--tool", "h2testw", "--result", "pass", "--file", att,
               "--note", "operator says pass", answers=["YES"]))
    assert d["evidence"]["level"] == "attested"
    assert d["evidence"]["kind"] == "attested"
    assert d["evidence"]["sha256"] == sha256_hex(att.read_bytes())


def test_C25_assessment_stores_rules_version_and_inputs(cli):
    """C25. Mutation: assessment without inputs/rules_version -> red."""
    sid, dev = _dev(cli)
    snap = collect(cli, BASELINE, sid, dev).data["snapshot"]["id"]
    ev = ok(cli("ingest", "ddrescue", sid, dev, fx(MAP)))["evidence"]["id"]
    a = assess(cli, sid, dev)
    assert a["rules_version"]
    assert snap in a["inputs"]["snapshot_ids"]
    assert ev in a["inputs"]["evidence_ids"]


def test_C25_assess_twice_identical_output(cli):
    """C25 'running it twice with no new inputs yields identical output' (strict: identical stdout).
    Mutation: non-deterministic ordering / timestamps in output -> red."""
    sid, dev = _dev(cli)
    collect(cli, BASELINE, sid, dev)
    r1 = cli("assess", sid, dev)
    r2 = cli("assess", sid, dev)
    assert r1.code == r2.code == 0
    assert r1.out == r2.out
    t1 = cli("assess", sid, dev, json_out=False)
    t2 = cli("assess", sid, dev, json_out=False)
    assert t1.out == t2.out


def test_C25_ingested_snapshot_feeds_assess(cli):
    """ingest smartctl + assess (the path used by WSL/live-Linux captures). Mutation: assess ignores ingested snapshots -> red."""
    sid = new_session(cli)
    d = ingest_smart(cli, sid, "smartctl/scrutiny-nvme-media-errors.json").data
    a = assess(cli, sid, d["device_id"])
    assert d["snapshot"]["id"] in a["inputs"]["snapshot_ids"]
    assert a["health"]["verdict"] == "degraded"


# ---------------- amendment 01 A: ingest attested needs the operator
def _att(tmp_path):
    f = tmp_path / "h2testw-operator.txt"
    f.write_bytes(b"operator attachment for amendment 01 cases")
    return f


@pytest.mark.parametrize("how", ["no-tty-console", "operator-out-of-answers"])
def test_C24b_attested_without_console_refused_store_unchanged(cli, tmp_path, monkeypatch, how):
    """Amendment 01 A: `ingest attested` without a console -> exit 3 operator-console-required, message has
    `python <abs>/rs.py ingest attested <s> <d> ...`, no evidence row written.
    Mutation: store the attestation without asking (pre-amendment) -> exit 0 -> red."""
    sid, dev = _dev(cli)
    before = operator_state(cli.home)
    argv = ("ingest", "attested", sid, dev, "--tool", "h2testw", "--result", "pass", "--file", _att(tmp_path))
    if how == "no-tty-console":
        monkeypatch.setattr(sys, "stdin", io.StringIO(""))
        res = cli(*argv, operator=None)
    else:
        res = cli(*argv, answers=[])
    assert_console_required(res, "ingest", "attested", sid, dev)
    assert operator_state(cli.home) == before


@pytest.mark.parametrize("answer", ["no", "yes", ""])
def test_C24c_attested_answer_other_than_YES_declined(cli, tmp_path, answer):
    """Amendment 01 A 'same rule': anything but `YES` -> exit 3 operator-declined, nothing stored.
    Mutation: case-insensitive answer, or any answer accepted -> red."""
    sid, dev = _dev(cli)
    before = operator_state(cli.home)
    res = cli("ingest", "attested", sid, dev, "--tool", "h2testw", "--result", "pass", "--file", _att(tmp_path),
              answers=[answer])
    assert res.code == 3, res
    assert "operator-declined" in res.reasons, res
    assert operator_state(cli.home) == before


@pytest.mark.parametrize("tool,result", [("h2testw", "pass"), ("other", "fail")])
def test_C24d_attested_prompt_names_tool_result_and_audit_who(cli, tmp_path, tool, result):
    """Amendment 01 A prompt `Type YES to attest <tool> <result> for <device>: `; `evidence.who = operator`.
    Mutation: prompt with a fixed tool/result text (human attests the wrong thing) -> red; who not recorded -> red."""
    sid, dev = _dev(cli)
    d = cli("ingest", "attested", sid, dev, "--tool", tool, "--result", result, "--file", _att(tmp_path),
            answers=["YES"])
    assert d.code == 0, d
    assert len(d.prompts) == 1, d.prompts
    p = d.prompts[0]
    assert "YES" in p and tool in p and result in p, p
    ev = d.data["evidence"]["id"]
    row = next(r for r in db_rows(cli.home, "evidence") if str(r["id"]) == str(ev))
    assert row["who"] == "operator"


def test_C24d_tool_ingest_needs_no_operator(cli):
    """Amendment 01 A lists only `ingest attested`; parsed tool output (ddrescue) is not asked.
    Mutation: ask the operator for every ingest -> empty ScriptedOperator -> exit 3 -> red."""
    sid, dev = _dev(cli)
    res = cli("ingest", "ddrescue", sid, dev, fx(MAP))
    assert res.code == 0, res
    assert res.prompts == []
