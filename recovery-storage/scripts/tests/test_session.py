"""Phase 01 - sessions (A5-A11, A9b). Spec: phase-01 Requirements "session new|show|list|set|note" + A5-A11."""
import json
import re

import pytest

from conftest import GOALS, SYMPTOMS, new_session, ok


def show(cli, sid):
    return ok(cli("session", "show", sid))


def test_A5_two_goals_default_ceiling_R0_preserve_yes(cli):
    """A5. Mutation: keep only the last --goal, or default ceiling R1 -> red."""
    d = ok(cli("session", "new", "--goal", "data-recovery", "--goal", "diagnosis-only"))
    sid = d["session"]["id"]
    assert sid
    s = show(cli, sid)["session"]
    assert sorted(s["goals"]) == ["data-recovery", "diagnosis-only"]
    assert s["ceiling"] == "R0"
    assert s["preserve_data"] == "yes"


def test_A5_text_mode_prints_new_session_id(cli):
    """A5 'prints new session id'. Mutation: print nothing on success -> red."""
    res = cli("session", "new", "--goal", "diagnosis-only", json_out=False)
    assert res.code == 0, res
    sid = ok(cli("session", "list"))["sessions"][0]["id"]
    assert str(sid) in res.out


def test_A6_unknown_goal_exit_2_lists_all_six(cli):
    """A6. Mutation: accept any goal string, or list only some goals -> red."""
    res = cli("session", "new", "--goal", "foo", json_out=False)
    assert res.code == 2, res
    for g in GOALS:
        assert g in res.text, g


@pytest.mark.parametrize("bad", ["R4", "r9", "X"])
def test_A6_ceiling_outside_R0_R3_exit_2(cli, bad):
    """A6. Mutation: accept R4 -> red."""
    res = cli("session", "new", "--goal", "diagnosis-only", "--ceiling", bad, json_out=False)
    assert res.code == 2, res


def test_A6_ceiling_R3_accepted(cli):
    """A6 boundary (R3 is the top valid ceiling). Mutation: off-by-one rejecting R3 -> red."""
    d = ok(cli("session", "new", "--goal", "diagnosis-only", "--ceiling", "R3"))
    assert d["session"]["ceiling"] == "R3"


def test_A7_data_recovery_forces_preserve_yes_with_reason_and_audit(cli):
    """A7. Mutation: store preserve=no as given, or force silently (no 'forced', no audit) -> red."""
    res = cli("session", "new", "--goal", "data-recovery", "--preserve-data", "no", json_out=False)
    assert res.code == 0, res
    assert "forced" in res.out.lower()
    assert "data-recovery" in res.out
    sid = ok(cli("session", "list"))["sessions"][0]["id"]
    d = show(cli, sid)
    assert d["session"]["preserve_data"] == "yes"
    assert d["session"]["preserve_forced"] is True
    assert any(e["field"] in ("preserve_data", "preserve") for e in d["events"]), d["events"]


def test_A7_forensic_preservation_also_forces_preserve(cli):
    """Requirement 'Goals data-recovery or forensic-preservation force preserve=yes'. Mutation: only data-recovery forces -> red."""
    d = ok(cli("session", "new", "--goal", "forensic-preservation", "--preserve-data", "no"))
    assert d["session"]["preserve_data"] == "yes"
    assert d["session"]["preserve_forced"] is True


def test_A7_other_goal_keeps_preserve_no(cli):
    """A7 counter-case: device-recovery does not force. Mutation: force preserve for every goal -> red."""
    d = ok(cli("session", "new", "--goal", "device-recovery", "--preserve-data", "no"))
    assert d["session"]["preserve_data"] == "no"
    assert d["session"]["preserve_forced"] is False


@pytest.mark.parametrize("given,expected", [
    ("64GB", 64000000000),
    ("1TB", 1000000000000),
    ("500107862016", 500107862016),
    ("64GiB", 68719476736),
])
def test_A8_nominal_capacity_parsed_to_bytes(cli, given, expected):
    """A8. Mutation: treat GB as GiB (or GiB as GB) -> red."""
    d = ok(cli("session", "new", "--goal", "diagnosis-only", "--nominal", given))
    assert d["session"]["nominal_bytes"] == expected


@pytest.mark.parametrize("bad", ["abc", "0"])
def test_A8_nominal_invalid_exit_2(cli, bad):
    """A8. Mutation: accept 0 as a capacity -> red."""
    res = cli("session", "new", "--goal", "diagnosis-only", "--nominal", bad, json_out=False)
    assert res.code == 2, res


def test_A9_symptom_in_enum_accepted(cli):
    """A9. Mutation: drop mechanical-noise from the enum -> red."""
    d = ok(cli("session", "new", "--goal", "diagnosis-only", "--symptom", "mechanical-noise"))
    assert d["session"]["symptoms"] == ["mechanical-noise"]


def test_A9_symptom_enum_is_exactly_the_frozen_list(cli):
    """A9 frozen enum: every listed symptom is accepted. Mutation: remove/rename one code -> red."""
    args = ["session", "new", "--goal", "diagnosis-only"]
    for s in SYMPTOMS:
        args += ["--symptom", s]
    d = ok(cli(*args))
    assert sorted(d["session"]["symptoms"]) == sorted(SYMPTOMS)


def test_A9_unknown_symptom_exit_2_lists_enum(cli):
    """A9. Mutation: accept free-text symptoms -> red."""
    res = cli("session", "new", "--goal", "diagnosis-only", "--symptom", "clicking-noise", json_out=False)
    assert res.code == 2, res
    for s in SYMPTOMS:
        assert s in res.text, s


def test_A9_isolation_facts_repeatable_and_enumerated(cli):
    """A9 isolation facts: --tried other-port|other-cable|other-host|other-os repeatable. Mutation: keep last only -> red."""
    d = ok(cli("session", "new", "--goal", "diagnosis-only", "--tried", "other-port", "--tried", "other-cable",
               "--tried", "other-host", "--tried", "other-os"))
    assert sorted(d["session"]["tried"]) == ["other-cable", "other-host", "other-os", "other-port"]
    res = cli("session", "new", "--goal", "diagnosis-only", "--tried", "other-planet", json_out=False)
    assert res.code == 2, res


TRIED_ORDER = ["other-port", "other-cable", "other-host", "other-os", "reseat-media", "other-reader"]  # amendment 03 A1


def test_A9c_removable_media_isolation_values_accepted(cli):
    """Amendment 03 A1: --tried reseat-media / other-reader accepted, stored and shown. Mutation: values missing from
    the enum (exit 2), or dropped on store -> red."""
    d = ok(cli("session", "new", "--goal", "diagnosis-only", "--device-type", "sd", "--symptom", "not-detected",
               "--tried", "other-host", "--tried", "reseat-media", "--tried", "other-reader"))
    assert sorted(d["session"]["tried"]) == ["other-host", "other-reader", "reseat-media"]
    assert sorted(show(cli, d["session"]["id"])["session"]["tried"]) == ["other-host", "other-reader", "reseat-media"]


def test_A9c_all_six_isolation_values_together(cli):
    """Amendment 03 A1: the four old values keep working next to the two new ones. Mutation: replace an old value
    by a new one -> red."""
    args = ["session", "new", "--goal", "diagnosis-only"]
    for t in TRIED_ORDER:
        args += ["--tried", t]
    assert sorted(ok(cli(*args))["session"]["tried"]) == sorted(TRIED_ORDER)


def test_A9c_usage_lists_isolation_values_old_first_new_appended(cli):
    """Amendment 03 A1 'existing values unchanged and keep their order; the new ones are appended' (exit-2 text lists
    the valid values, CONTRACT sec. 2). Mutation: new values prepended / inserted, or an old value renamed -> red."""
    res = cli("session", "new", "--goal", "diagnosis-only", "--tried", "other-planet", json_out=False)
    assert res.code == 2, res
    idx = [res.text.find(v) for v in TRIED_ORDER]
    assert all(i >= 0 for i in idx), dict(zip(TRIED_ORDER, idx))
    assert idx == sorted(idx), dict(zip(TRIED_ORDER, idx))


@pytest.mark.parametrize("flag,bad", [("--data-value", "priceless"), ("--risk-tolerance", "extreme")])
def test_A9b_risk_fields_outside_enum_exit_2(cli, flag, bad):
    """A9b. Mutation: accept any string -> red."""
    res = cli("session", "new", "--goal", "diagnosis-only", flag, bad, json_out=False)
    assert res.code == 2, res


def test_A9b_defaults_unknown_and_medium(cli):
    """A9b + plan R1. Mutation: default tolerance low -> red."""
    d = ok(cli("session", "new", "--goal", "diagnosis-only", "--preserve-data", "no"))
    assert d["session"]["data_value"] == "unknown"
    assert d["session"]["risk_tolerance"] == "medium"


@pytest.mark.parametrize("preserve,effective", [("yes", "irreplaceable"), ("unknown", "irreplaceable"),
                                                ("no", "replaceable")])
def test_A9b_effective_data_value(cli, preserve, effective):
    """A9b (+ 'unknown behaves as yes'). Mutation: effective = stored value, or unknown preserve -> replaceable -> red."""
    sid = new_session(cli, "--goal", "diagnosis-only", "--preserve-data", preserve)
    s = show(cli, sid)["session"]
    assert s["data_value"] == "unknown"
    assert s["effective_data_value"] == effective


def test_A9b_show_text_prints_stored_and_effective(cli):
    """A9b 'session show prints stored and effective value'. Mutation: print only one of them -> red."""
    sid = new_session(cli, "--goal", "diagnosis-only", "--preserve-data", "yes")
    res = cli("session", "show", sid, json_out=False)
    assert res.code == 0, res
    assert "unknown" in res.out and "irreplaceable" in res.out


def test_A9b_explicit_data_value_not_overridden(cli):
    """A9b: only `unknown` is mapped. Mutation: map every value through preserve -> red."""
    sid = new_session(cli, "--goal", "diagnosis-only", "--preserve-data", "yes", "--data-value", "replaceable")
    assert show(cli, sid)["session"]["effective_data_value"] == "replaceable"


@pytest.mark.parametrize("flag,value,field", [("--data-value", "important", "data_value"),
                                              ("--risk-tolerance", "low", "risk_tolerance")])
def test_A9b_set_writes_audit_event(cli, flag, value, field):
    """A9b. Mutation: update in place without an event -> red."""
    sid = new_session(cli)
    ok(cli("session", "set", sid, flag, value))
    d = show(cli, sid)
    assert d["session"][field] == value
    assert any(e["field"] == field and e["new"] == value for e in d["events"]), d["events"]


def test_A10_set_ceiling_audit_line_with_timestamp(cli):
    """A10. Mutation: overwrite ceiling without audit, or audit without timestamp -> red."""
    sid = new_session(cli)
    ok(cli("session", "set", sid, "--ceiling", "R2"))
    d = show(cli, sid)
    assert d["session"]["ceiling"] == "R2"
    ev = [e for e in d["events"] if e["field"] == "ceiling"]
    assert ev and ev[-1]["old"] == "R0" and ev[-1]["new"] == "R2" and ev[-1]["ts"]
    assert ev[-1]["who"] in ("operator", "agent")
    res = cli("session", "show", sid, json_out=False)
    assert re.search(r"ceiling\s+R0\s*->\s*R2", res.out), res.out
    assert re.search(r"\d{4}-\d{2}-\d{2}", res.out)


@pytest.mark.parametrize("cmd", [("session", "set", "S-nope", "--ceiling", "R1"), ("session", "show", "S-nope")])
def test_A10_unknown_session_exit_2(cli, cmd):
    """A10. Mutation: create on unknown id or exit 0/4 -> red."""
    new_session(cli)
    res = cli(*cmd, json_out=False)
    assert res.code == 2, res
    assert "unknown session" in res.text.lower()


def test_A11_json_on_every_session_command_is_one_object(cli):
    """A11. Mutation: print a banner/extra line before the JSON -> json.loads fails -> red."""
    outs = []
    r = cli("session", "new", "--goal", "diagnosis-only")
    outs.append(r)
    sid = json.loads(r.out)["session"]["id"]
    outs.append(cli("session", "show", sid))
    outs.append(cli("session", "list"))
    outs.append(cli("session", "set", sid, "--ceiling", "R1"))
    outs.append(cli("session", "note", sid, "operator note text"))
    for r in outs:
        assert r.code == 0, r
        obj = json.loads(r.out)
        assert isinstance(obj, dict)
        assert obj["ok"] is True and obj["exit_code"] == 0
