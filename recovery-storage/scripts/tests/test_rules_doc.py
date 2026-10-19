"""Phase 06 `rs.py rules` (F8). Spec: phase-06 Requirements '`rs.py rules [--json]`' + F8; phase-03 Parameters."""
from conftest import ok


def test_F8_rules_json_lists_every_health_and_triage_rule(cli):
    """F8. Mutation: hand-written docs table drifting from RULES (missing or extra id) -> red."""
    from rslib.health import RULES as HR
    from rslib.triage import RULES as TR

    d = ok(cli("rules"))
    assert [r["id"] for r in d["health_rules"]] == [r.id for r in HR]
    assert [r["id"] for r in d["triage_rules"]] == [r.id for r in TR]
    for r in d["health_rules"] + d["triage_rules"]:
        assert isinstance(r["required_fields"], list)
        assert r["outcome"] and r["source"], r


def test_F8_outcomes_match_rule_tables(cli):
    """F8 'output equals what health.py / triage.py evaluate'. Mutation: docs outcome text differs from code -> red."""
    from rslib.health import RULES as HR
    from rslib.triage import RULES as TR

    d = ok(cli("rules"))
    assert {r["id"]: r["outcome"] for r in d["health_rules"]} == {r.id: r.outcome for r in HR}
    assert {r["id"]: r["outcome"] for r in d["triage_rules"]} == {r.id: r.outcome for r in TR}
    assert {r.outcome for r in TR} == {"STOP_UNSAFE", "HARDWARE_DIAGNOSIS_REQUIRED", "CONTROLLER_RECOVERY_CANDIDATE",
                                       "SOFTWARE_RECOVERY_CANDIDATE", "UNDETERMINED"}
    assert {"failing", "degraded", "watch", "healthy", "unknown"} <= {r.outcome for r in HR}


def test_F8_parameters_carry_endurance_constants_with_source(cli):
    """Phase 03 Parameters 'endurance watch 80, degraded 100' with rationale. Mutation: thresholds hidden in code only -> red."""
    d = ok(cli("rules"))
    values = {p["value"] for p in d["parameters"]}
    assert {80, 100} <= values
    for p in d["parameters"]:
        assert p["name"] and p["source"], p


def test_F8_wear_whitelist_exported(cli):
    """Phase 03 wear whitelist via `rs.py rules`. Mutation: whitelist not exported -> red."""
    d = ok(cli("rules"))
    rows = {(w["id"], w["name"]) for w in d["wear_whitelist"]}
    assert {(169, "Remaining_Lifetime_Perc"), (173, "Percent_Lifetime_Remain"), (202, "Percent_Lifetime_Remain"),
            (231, "Percent_Lifetime_Remain"), (231, "SSD_Life_Left"), (231, "Life_Remaining_Percent"),
            (233, "Remaining_Lifetime_Perc"), (177, "Lifetime_Remaining%")} == rows


def test_F8_rules_text_mode(cli):
    """`rs.py rules` without --json prints the tables. Mutation: text mode unimplemented -> red."""
    from rslib.health import RULES as HR

    t = cli("rules", json_out=False)
    assert t.code == 0, t
    assert all(r.id in t.out for r in HR)
