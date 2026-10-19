"""Phase 07 cross-phase scenarios (G1-G4, G7-G9), data-driven from tests/scenarios/<name>/{script.json, expected.json}.
Spec: phase-07 Requirements 'Scenario suite' + G1-G4, G7-G9; spec §6 GĐ4, §8.

script.json steps: {"cli": [...], "runner": {"capture", "override", "replace"}, "answers": [...], "exit": int|[int],
"reasons": [...], "expect": {path: value}, "save": {var: path}}. `answers` (amendment 01 A) = lines the human types at
the operator console (ScriptedOperator, in order); a step without it gets an empty operator (asking -> NoConsole). Tokens: `$var`, `@fx:<fixture rel>`, `@tmp:<name>` (operator
attachment file). Paths: dotted, `[k=v]` filter, `[N]` index, trailing `[]` = list contains.
"""
import json
import re

import pytest

from conftest import CATEGORIES, FIX, TESTS, TRIAGE_CLASSES, Cli

SCEN_DIR = TESTS / "scenarios"
NAMES = sorted(p.name for p in SCEN_DIR.iterdir() if (p / "script.json").is_file()) if SCEN_DIR.is_dir() else []
SEG = re.compile(r"^([\w-]+)?(?:\[([^\]]*)\])?$")


def load(name):
    d = SCEN_DIR / name
    return (json.loads((d / "script.json").read_text(encoding="utf-8")),
            json.loads((d / "expected.json").read_text(encoding="utf-8")))


def get(data, path):
    cur = data
    for seg in path.split("."):
        m = SEG.match(seg)
        assert m, f"bad path segment {seg!r}"
        name, filt = m.groups()
        if name:
            cur = cur[name]
        if filt is None:
            continue
        if filt == "":
            return ("__contains__", cur)
        if "=" in filt:
            k, v = filt.split("=", 1)
            cur = next(x for x in cur if str(x.get(k)) == v)
        else:
            cur = cur[int(filt)]
    return cur


def subst(tok, vars_, tmp):
    if tok.startswith("$"):
        assert tok[1:] in vars_, f"unset variable {tok}"
        return str(vars_[tok[1:]])
    if tok.startswith("@fx:"):
        return str(FIX / tok[4:])
    if tok.startswith("@tmp:"):
        p = tmp / tok[5:]
        p.write_bytes(b"operator attachment for scenario: " + tok[5:].encode())
        return str(p)
    return tok


def run_scenario(name, home, tmp, runners):
    sc, exp = load(name)
    cli = Cli(home, runners)
    vars_, assessments, log = {}, [], []
    for i, st in enumerate(sc["steps"]):
        args = [subst(str(t), vars_, tmp) for t in st["cli"]]
        runner = None
        if "runner" in st:
            r = st["runner"]
            replace = {(t, tuple(a)): rel for t, a, rel in r.get("replace", [])}
            runner = cli.runner(r["capture"], r.get("override"), replace=replace)
        answers = [subst(str(a), vars_, tmp) for a in st["answers"]] if "answers" in st else None
        res = cli(*args, runner=runner, answers=answers)
        want = st.get("exit", 0)
        want = want if isinstance(want, list) else [want]
        where = f"{name} step {i} {' '.join(st['cli'])}"
        assert res.code in want, f"{where}: {res}"
        if answers and res.code == 0:
            assert len(res.prompts) == len(answers), f"{where}: operator asked {res.prompts} for answers {answers}"
        for code in st.get("reasons", []):
            assert code in res.reasons, f"{where}: reason {code} missing in {res.reasons}"
        for path, value in st.get("expect", {}).items():
            got = get(res.data, path)
            if isinstance(got, tuple) and got and got[0] == "__contains__":
                assert value in got[1], f"{where}: {path} {got[1]} lacks {value}"
            else:
                assert got == value, f"{where}: {path} = {got!r}, want {value!r}"
        for var, path in st.get("save", {}).items():
            vars_[var] = get(res.data, path)
        if st["cli"][0] == "assess" and res.code == 0:
            assessments.append(res.data["assessment"])
        log.append((st["cli"], res.code))
    out = {"vars": vars_, "assessments": assessments, "log": log, "script": sc, "expected": exp}
    if "sid" in vars_:
        out["check"] = cli("report", vars_["sid"], "--check")
        if "dev" in vars_:
            out["verdict"] = cli("verdict", "show", vars_["sid"], vars_["dev"])
    out["gates"] = cli("gate", "list")
    return out


@pytest.fixture(scope="module")
def runs(tmp_path_factory):
    runners, results = [], {}
    for n in NAMES:
        home = tmp_path_factory.mktemp(f"scn-{n}")
        try:
            results[n] = run_scenario(n, home / "home", home, runners)
        except Exception as e:  # reported per scenario below
            results[n] = e
    results["__unrecorded__"] = [r.unrecorded for r in runners if r.unrecorded]
    return results


def test_scenario_dir_present():
    """Phase 07 Architecture: tests/scenarios/<name>/{script.json, expected.json}. Mutation: suite deleted -> red."""
    assert len(NAMES) >= 20
    for n in NAMES:
        sc, exp = load(n)
        assert sc["name"] == n and isinstance(sc["structural"], bool) and sc["steps"]


@pytest.mark.parametrize("name", NAMES)
def test_scenario_end_state(runs, name):
    """G1/G2/G3/G4/G9 per scenario: every step's exit/reasons/expect, then expected.json end state."""
    r = runs[name]
    if isinstance(r, Exception):
        raise r
    exp = r["expected"]
    assert r["assessments"], "scenario never assessed"
    last = r["assessments"][-1]
    assert last["triage"]["class"] == exp["triage"]
    hyps = {h["category"]: h for h in last["hypotheses"]}
    for cat in exp["hypotheses"]:
        assert cat in hyps and hyps[cat]["evidence"], (cat, list(hyps))
    for cat, conf in exp.get("hypothesis_confidence", {}).items():
        assert hyps[cat]["confidence"] == conf
    vals = [r["vars"][v] for v in exp.get("same_vars", [])]
    assert len(set(map(str, vals))) <= 1
    eff = r["verdict"].data.get("effective") if r.get("verdict") and r["verdict"].data else None
    assert eff == exp["verdict"], r.get("verdict")
    if "open_gates_only" in exp:
        open_ids = {g["id"] for g in r["gates"].data["gates"] if g["state"] == "open"}
        assert open_ids == {r["vars"][v] for v in exp["open_gates_only"]}


def test_scenarios_no_unrecorded_commands(runs):
    """A19 inside the scenario corpus."""
    assert runs["__unrecorded__"] == []


def test_G1_nine_cause_groups_each_have_a_scenario():
    """G1. Mutation: drop a cause-group scenario -> red. Structural ones are labelled."""
    covered = set()
    for n in NAMES:
        sc, exp = load(n)
        covered |= set(exp["hypotheses"])
        if sc["structural"]:
            assert sc.get("structural_reason"), n
    assert set(CATEGORIES) <= covered, set(CATEGORIES) - covered


def test_G2_each_triage_class_is_a_final_class():
    """G2. Mutation: no scenario ends CONTROLLER_RECOVERY_CANDIDATE -> red."""
    finals = {load(n)[1]["triage"] for n in NAMES}
    assert set(TRIAGE_CLASSES) <= finals


def test_G7_confidence_properties(runs):
    """G7: zero healthy/high; every high-confidence item has a STRONG evidence item; every hypothesis complete.
    Mutation: hypothesis 'high' backed only by weak signals -> red."""
    bad = []
    for n in NAMES:
        r = runs[n]
        if isinstance(r, Exception):
            continue
        for a in r["assessments"]:
            h = a["health"]
            if h["verdict"] == "healthy" and h["confidence"] == "high":
                bad.append((n, "healthy/high"))
            if h["confidence"] == "high" and not any(e.get("strength") == "strong" for e in h["evidence"]):
                bad.append((n, "health high without strong evidence"))
            for y in a["hypotheses"]:
                if not y["evidence"] or not (y["alternative"] or "").strip() or not (y["next_test"] or "").strip():
                    bad.append((n, "incomplete hypothesis", y["category"]))
                if y["confidence"] == "high" and not any(e.get("strength") == "strong" for e in y["evidence"]):
                    bad.append((n, "hypothesis high without strong evidence", y["category"]))
    assert bad == []
    ok_runs = [r for n, r in runs.items() if n in NAMES and not isinstance(r, Exception)]
    assert ok_runs, "no scenario ran"


def test_G8_report_check_matches_verdict_presence(runs):
    """G8. Mutation: --check passes without a verdict, or fails a finished scenario -> red."""
    bad = []
    for n in NAMES:
        r = runs[n]
        if isinstance(r, Exception) or "check" not in r:
            bad.append((n, "did not run"))
            continue
        chk = r["check"]
        if r["expected"]["verdict"]:
            if chk.code != 0:
                bad.append((n, chk.code, chk.data))
        else:
            if chk.code != 3 or 9 not in (chk.data or {}).get("check", {}).get("missing_sections", []):
                bad.append((n, chk.code, chk.data))
    assert bad == []


def _gate_steps(steps):
    """{gate var: kind} from successful `gate open` steps that save `gate.id`."""
    kinds = {}
    for st in steps:
        if st["cli"][:2] == ["gate", "open"] and st.get("exit", 0) == 0:
            for var, path in st.get("save", {}).items():
                if path == "gate.id":
                    kinds[var] = st["cli"][4]
    return kinds


def test_G9_full_flow_scenarios_exist():
    """G9: the full data-recovery flow is scripted (NVMe real capture; HDD structural); data is secured before the
    source-writing gate is confirmed. Amendment 02 C: the secured step itself follows a closed image-ddrescue gate
    (the first `gate confirm` is now the image gate's, so the order check names the format gate).
    Mutation: flow removed, format confirmed before secured, or secured without an image gate -> red."""
    assert {"full-data-recovery-nvme", "full-data-recovery-hdd"} <= set(NAMES)
    steps = load("full-data-recovery-nvme")[0]["steps"]
    kinds = _gate_steps(steps)
    idx = {"secured": [], "format-confirm": [], "image-close": []}
    for i, st in enumerate(steps):
        c = st["cli"]
        if c[:2] == ["session", "data-state"] and "secured" in c and st.get("exit", 0) == 0:
            idx["secured"].append(i)
        if c[:2] in (["gate", "confirm"], ["gate", "close"]) and c[2].startswith("$"):
            kind = kinds.get(c[2][1:])
            if kind == "format" and c[1] == "confirm":
                idx["format-confirm"].append(i)
            if kind == "image-ddrescue" and c[1] == "close" and st.get("exit", 0) == 0:
                idx["image-close"].append(i)
    assert idx["secured"] and idx["format-confirm"] and idx["image-close"], idx
    assert min(idx["format-confirm"]) > min(idx["secured"])
    assert min(idx["image-close"]) < min(idx["secured"])


OPERATOR_STEPS = (["gate", "confirm"], ["ingest", "attested"], ["device", "link"])   # device link: amendment 02 A


def _needs_operator(cli_):
    if cli_[:2] in OPERATOR_STEPS:
        return True
    return cli_[:2] == ["session", "data-state"] and (cli_[4] in ("waived", "not-needed") or "--attested" in cli_)


def test_scenarios_operator_steps_use_the_console():
    """Amendment 01 A: no scenario passes `--phrase`; every operator command step carries `answers` (amendment 02 A
    adds `device link`). Mutation: a scenario left on the removed `--phrase` path -> red (it would fail at argparse
    with exit 2); a `device link` step without the operator's answer -> red."""
    bad = []
    for n in NAMES:
        for i, st in enumerate(load(n)[0]["steps"]):
            if "--phrase" in st["cli"]:
                bad.append((n, i, "--phrase"))
            if _needs_operator(st["cli"]) and not st.get("answers"):
                bad.append((n, i, "no answers"))
    assert bad == []
