"""Phase 04 data state (D20). Spec: phase-04 Requirements 'Data state' + D20; Key insight '"Data first" must be a
state with evidence'. Amendment 01: A (waived / secured --attested / not-needed need the operator console, `YES`),
B (a mapfile secures data only when it covers the whole device)."""
import io
import sys

import pytest

from conftest import (BASELINE, BYTES_980, FLOPPY_BYTES, MAP_980, MAP_990, MAP_FINISHED, MAP_PARTIAL,
                      OPERATOR_REASONS, assert_console_required, db_rows, device_at, fx, fx_text, new_session, nvme1,
                      ok, open_gate, operator_state, prepared, secure)

GAP_LINE = "0x00117200  0x00001000  +"   # third block line of the derived maps (SOURCES.md in-test mutations)
FIRST_LINE = "0x00000000  0x00117000  +"


def _lines(rel):
    return fx_text(rel).splitlines(keepends=True)


def gap_text(rel=MAP_980):
    """Full-coverage map with its third block removed: start 0, end = device bytes, but a 0x1000 hole."""
    lines = _lines(rel)
    hit = [i for i, ln in enumerate(lines) if ln.strip() == GAP_LINE]
    assert len(hit) == 1
    del lines[hit[0]]
    return "".join(lines)


def shifted_start_text(rel=MAP_980):
    """Full-coverage map whose first block starts at 512 (contiguous, ends at the device byte count)."""
    t = fx_text(rel)
    assert t.count(FIRST_LINE) == 1
    return t.replace(FIRST_LINE, "0x00000200  0x00116E00  +", 1)


def write(tmp_path, name, text):
    p = tmp_path / name
    p.write_bytes(text.encode("utf-8"))
    return p


def secure_text(cli, sid, dev, tmp_path, name, text):
    ev = ok(cli("ingest", "ddrescue", sid, dev, write(tmp_path, name, text)))["evidence"]["id"]
    return cli("session", "data-state", sid, dev, "secured", "--evidence", ev)


def test_D20_incomplete_mapfile_refused_with_hint(cli):
    """D20 (verbatim 1.30 map: bad 512, unfinished). Mutation: accept any ingested mapfile -> red.
    Amendment 01 B: the verbatim map is also a floppy image; `image-incomplete` is still required here (kept case,
    see CONTRACT.md amendment 01 'precedence')."""
    sid, dev = nvme1(cli, "--goal", "data-recovery")
    _, res = secure(cli, sid, dev, MAP_PARTIAL)
    assert res.code == 3, res
    assert "image-incomplete" in res.reasons
    assert "waived --reason" in res.text.lower()


def test_D20_complete_mapfile_secures(cli):
    """D20 on the full-coverage 980 PRO map (amendment 01 B). Mutation: secured requires non-existent extra flag /
    state not stored -> red."""
    sid, dev = nvme1(cli, "--goal", "data-recovery")
    _, res = secure(cli, sid, dev, MAP_980)
    assert res.code == 0, res
    assert res.data["data_state"] == "secured"


def test_D20_mapfile_of_another_device_refused(cli):
    """Requirements 'belongs to this device'. The map is the 980 PRO full-coverage one, so the only failing rule is
    ownership (pd0 evidence offered for pd1). Mutation: evidence id not checked against device -> secured -> red."""
    sid, dev = nvme1(cli, "--goal", "data-recovery")
    other = device_at(cli, BASELINE, sid, "/dev/pd0")
    ev = ok(cli("ingest", "ddrescue", sid, other, fx(MAP_980)))["evidence"]["id"]
    res = cli("session", "data-state", sid, dev, "secured", "--evidence", ev)
    assert res.code == 3, res


def test_D20_secured_attested_needs_reason(cli):
    """Requirements 'secured --attested --reason <text>'. Mutation: attested without reason accepted -> red.
    Amendment 01 A: both calls carry the operator's YES, so only the missing reason decides the first one."""
    sid, dev = nvme1(cli, "--goal", "data-recovery")
    assert cli("session", "data-state", sid, dev, "secured", "--attested", json_out=False, answers=["YES"]).code == 2
    d = ok(cli("session", "data-state", sid, dev, "secured", "--attested", "--reason", "files copied and verified",
               answers=["YES"]))
    assert d["data_state"] == "secured"


def test_D20_waived_without_reason_exit_2(cli):
    """D20. Mutation: reason optional -> red. (Amendment 01 A: YES given to both calls.)"""
    sid, dev = nvme1(cli, "--goal", "data-recovery")
    assert cli("session", "data-state", sid, dev, "waived", json_out=False, answers=["YES"]).code == 2
    assert ok(cli("session", "data-state", sid, dev, "waived", "--reason", "owner says data is backed up",
                  answers=["YES"]))["data_state"] == "waived"


def test_D20_not_needed_only_when_preserve_no(cli):
    """D20. Mutation: not-needed allowed with preserve=yes -> data-first bypass -> red.
    Amendment 01 A: the operator says YES, so the refusal must come from the preserve rule, not the console."""
    sid, dev = nvme1(cli, "--goal", "data-recovery")
    res = cli("session", "data-state", sid, dev, "not-needed", answers=["YES"])
    assert res.code == 3, res
    assert not (OPERATOR_REASONS & res.reasons), res
    s2 = new_session(cli, "--goal", "device-recovery", "--preserve-data", "no")
    assert ok(cli("session", "data-state", s2, dev, "not-needed", answers=["YES"]))["data_state"] == "not-needed"


def test_D20_secured_without_evidence_or_attested_exit_2(cli):
    """Requirements: secured needs --evidence or --attested. Mutation: bare 'secured' flips the flag -> red."""
    sid, dev = nvme1(cli, "--goal", "data-recovery")
    res = cli("session", "data-state", sid, dev, "secured", json_out=False, answers=["YES"])
    assert res.code in (2, 3), res
    assert res.code != 0


# ---------------- amendment 01 B: full-coverage mapfiles
def test_D20b_floppy_finished_map_on_nvme_does_not_cover_device(cli):
    """Amendment 01 B 'The verbatim 1.30 floppy mapfile on an NVMe device -> refused image-does-not-cover-device'
    (finished, bad 0, contiguous, but ends at 1474560 of 2000398934016 B). Mutation: secured on finished + bad 0
    alone (pre-amendment rule) -> exit 0 -> red."""
    sid, dev = nvme1(cli, "--goal", "data-recovery", "--goal", "device-recovery", "--ceiling", "R2")
    _, res = secure(cli, sid, dev, MAP_FINISHED)
    assert res.code == 3, res
    assert "image-does-not-cover-device" in res.reasons, res
    assert "waived --reason" in res.text.lower()
    g = open_gate(cli, BASELINE, sid, dev, "format")
    assert g.code == 3 and "data-not-secured" in g.reasons, g


def test_D20b_gap_map_not_contiguous(cli, tmp_path):
    """Amendment 01 B 'A mapfile with a gap -> image-not-contiguous' (start 0, end = device bytes, one 0x1000 hole).
    Mutation: coverage judged from start/end only, or from the sum of sizes vs end -> secured -> red."""
    sid, dev = nvme1(cli, "--goal", "data-recovery")
    res = secure_text(cli, sid, dev, tmp_path, "gap.map", gap_text())
    assert res.code == 3, res
    assert "image-not-contiguous" in res.reasons, res
    assert "waived --reason" in res.text.lower()


def test_D20b_map_not_starting_at_zero_does_not_cover(cli, tmp_path):
    """Amendment 01 B 'first block starts at 0' (contiguous, ends at the device byte count, starts at 512).
    Mutation: only the end is compared with the device bytes -> secured -> red."""
    sid, dev = nvme1(cli, "--goal", "data-recovery")
    res = secure_text(cli, sid, dev, tmp_path, "shifted.map", shifted_start_text())
    assert res.code == 3, res
    assert "image-does-not-cover-device" in res.reasons, res


def test_D20b_map_ending_past_device_does_not_cover(cli):
    """Amendment 01 B 'last block ends exactly at the device byte count': the 980 PRO map (2000398934016) on the 990 PRO
    (1000204886016). Mutation: `end >= device bytes` instead of `==` -> secured -> red."""
    sid, dev, _ = prepared(cli, BASELINE, "/dev/pd0", "--goal", "data-recovery")
    _, res = secure(cli, sid, dev, MAP_980)
    assert res.code == 3, res
    assert "image-does-not-cover-device" in res.reasons, res
    _, res2 = secure(cli, sid, dev, MAP_990)
    assert res2.code == 0, res2


def _complete(text, device_bytes):
    from rslib.datastate import mapfile_complete
    from rslib.ingest import parse_mapfile

    return mapfile_complete(parse_mapfile(text), device_bytes)


@pytest.mark.parametrize("case,want", [
    ("980-on-980", (True, None)),
    ("980-bytes-unknown", (False, "image-does-not-cover-device")),
    ("980-device-512-larger", (False, "image-does-not-cover-device")),
    ("980-device-512-smaller", (False, "image-does-not-cover-device")),
    ("floppy-finished-on-980", (False, "image-does-not-cover-device")),
    ("floppy-finished-on-floppy", (True, None)),
    ("floppy-partial-on-floppy", (False, "image-incomplete")),
    ("gap-on-980", (False, "image-not-contiguous")),
    ("shifted-start-on-980", (False, "image-does-not-cover-device")),
])
def test_D20b_mapfile_complete_reasons(case, want):
    """Amendment 01 B `rslib.datastate.mapfile_complete(parsed, device_bytes) -> (bool, reason)`. Each case has
    exactly one failing condition, so the reason is fixed by the spec. Mutations caught, one per row: drop the
    `== device bytes` check (980-device-512-*), treat None bytes as 'unknown = ok' (bytes-unknown), forget the
    start-at-0 check (shifted-start), forget contiguity (gap), forget the finished/bad check (floppy-partial),
    hard-code a minimum size (floppy-finished-on-floppy)."""
    texts = {"980": fx_text(MAP_980), "floppy-finished": fx_text(MAP_FINISHED), "floppy-partial": fx_text(MAP_PARTIAL),
             "gap": gap_text(), "shifted-start": shifted_start_text()}
    sizes = {"980": BYTES_980, "floppy": FLOPPY_BYTES, "bytes-unknown": None, "device-512-larger": BYTES_980 + 512,
             "device-512-smaller": BYTES_980 - 512}
    if case.startswith("980-") and not case.startswith("980-on"):
        text, size = texts["980"], sizes[case[4:]]
    else:
        left, right = case.split("-on-")
        text, size = texts[left], sizes[right]
    ok_, reason = _complete(text, size)
    assert ok_ is want[0], (case, ok_, reason)
    if want[1] is not None:
        assert reason == want[1], (case, reason)


# ---------------- amendment 01 A: operator console for data-state
OPERATOR_STATES = {
    "waived": ("waived", "--reason", "owner says data is backed up"),
    "secured-attested": ("secured", "--attested", "--reason", "files copied and verified"),
    "not-needed": ("not-needed",),
}


def _session_for(cli, which):
    """data-recovery session (preserve forced yes) for waived/secured; preserve=no session for not-needed."""
    sid, dev = nvme1(cli, "--goal", "data-recovery", "--goal", "device-recovery", "--ceiling", "R2")
    if which == "not-needed":
        sid = new_session(cli, "--goal", "device-recovery", "--preserve-data", "no", "--ceiling", "R2")
    return sid, dev


@pytest.mark.parametrize("which", sorted(OPERATOR_STATES))
@pytest.mark.parametrize("how", ["no-tty-console", "operator-out-of-answers"])
def test_D20c_operator_states_without_console_refused_store_unchanged(cli, monkeypatch, which, how):
    """Amendment 01 A: waived / secured --attested / not-needed need the human; NoConsole -> exit 3
    operator-console-required, message has `python <abs>/rs.py session data-state <s> <d> <state>`, store unchanged.
    Mutation: record the state without asking (pre-amendment behaviour) -> exit 0 -> red; partial write before the
    ask -> store differs -> red."""
    sid, dev = _session_for(cli, which)
    before = operator_state(cli.home)
    argv = ("session", "data-state", sid, dev, *OPERATOR_STATES[which])
    if how == "no-tty-console":
        monkeypatch.setattr(sys, "stdin", io.StringIO(""))
        res = cli(*argv, operator=None)
    else:
        res = cli(*argv, answers=[])
    assert_console_required(res, "session", "data-state", sid, dev, OPERATOR_STATES[which][0])
    assert operator_state(cli.home) == before
    if which != "not-needed":
        g = open_gate(cli, BASELINE, sid, dev, "format")
        assert g.code == 3 and "data-not-secured" in g.reasons, g


@pytest.mark.parametrize("which", sorted(OPERATOR_STATES))
@pytest.mark.parametrize("answer", ["no", "yes", "", "Y"])
def test_D20d_operator_answer_other_than_YES_declined(cli, which, answer):
    """Amendment 01 A 'anything but `YES` -> exit 3 operator-declined' (lowercase `yes` included).
    Mutation: case-insensitive / prefix match on the answer, or any answer accepted -> exit 0 -> red."""
    sid, dev = _session_for(cli, which)
    before = operator_state(cli.home)
    res = cli("session", "data-state", sid, dev, *OPERATOR_STATES[which], answers=[answer])
    assert res.code == 3, res
    assert "operator-declined" in res.reasons, res
    assert operator_state(cli.home) == before


@pytest.mark.parametrize("which", sorted(OPERATOR_STATES))
def test_D20e_prompt_names_state_model_bytes_and_audit_who_operator(cli, which):
    """Amendment 01 A prompt `Type YES to record data state <state> for <device> (<model>, <bytes> bytes): ` and
    audit `data_states.who = operator`. Mutation: prompt without model/bytes (human cannot tell the disk) -> red;
    who recorded as agent / not recorded -> red."""
    sid, dev = _session_for(cli, which)
    res = cli("session", "data-state", sid, dev, *OPERATOR_STATES[which], answers=["YES"])
    assert res.code == 0, res
    state = OPERATOR_STATES[which][0]
    assert res.data["data_state"] == state
    assert len(res.prompts) == 1, res.prompts
    p = res.prompts[0]
    assert "YES" in p and state in p and "Samsung SSD 980 PRO 2TB" in p and str(BYTES_980) in p, p
    rows = [r for r in db_rows(cli.home, "data_states") if str(sid) in map(str, r.values())]
    assert rows and rows[-1]["who"] == "operator", rows


def test_D20e_secured_with_evidence_needs_no_operator(cli):
    """Amendment 01 A lists only waived / secured --attested / not-needed; `secured --evidence` is tool evidence.
    Mutation: ask the operator for --evidence too -> empty ScriptedOperator -> exit 3 -> red."""
    sid, dev = nvme1(cli, "--goal", "data-recovery")
    _, res = secure(cli, sid, dev, MAP_980)
    assert res.code == 0, res
    assert res.prompts == []
