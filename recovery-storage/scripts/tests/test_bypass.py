"""Phase 07 bypass (G6). Spec: phase-07 Requirements 'Bypass' + G6: forbidden values via CLI flags refused before
spawn; no CLI path writes PASS without the matrix; no gate transition skips confirm."""
import pytest

from conftest import BASELINE, gate_ok, ingest_smart, new_session, nvme1, ok, prepared

BAD_DTYPE = ["sat,x", "sat;rm", "-t", "usbcypress,0x24", "nvme /dev/sda", "", "auto,x"]


def no_forbidden(runner):
    from rslib.allowlist import check

    for tool, args in runner.calls:
        check(tool, list(args))  # every answered call is allow-listed
        assert "-t" not in args and not any("," in a and a.endswith("x") for a in args)


@pytest.mark.parametrize("bad", BAD_DTYPE)
def test_G6_dtype_forbidden_refused_before_spawn(cli, bad):
    """G6 '--dtype "sat,x"'. Mutation: pass --dtype through unvalidated -> RecordedRunner sees it -> red."""
    sid, dev = nvme1(cli, "--goal", "diagnosis-only")
    runner = cli.runner(BASELINE)
    res = cli("collect", dev, "--session", sid, "--dtype", bad, runner=runner)
    assert res.code in (2, 3), res
    assert not [a for t, a in runner.calls if "-d" in a]
    no_forbidden(runner)


def test_G6_device_path_with_semicolon_refused(cli):
    """G6 'device path with ;' (the only CLI flag naming a device is --dest-device). Mutation: accept a raw path -> red."""
    sid, dev = nvme1(cli, "--goal", "diagnosis-only", "--ceiling", "R1")
    runner = cli.runner(BASELINE)
    res = cli("gate", "open", sid, dev, "image-ddrescue", "--dest-device", "/dev/sda;rm -rf /", runner=runner)
    assert res.code in (2, 3), res
    no_forbidden(runner)


@pytest.mark.parametrize("extra", [["--", "-t", "short"], ["-t", "short"], ["--smartctl-args", "-s on"]])
def test_G6_extra_args_rejected(cli, extra):
    """G6 'extra args'. Mutation: forward unknown args to smartctl -> red."""
    sid, dev = nvme1(cli, "--goal", "diagnosis-only")
    runner = cli.runner(BASELINE)
    res = cli("collect", dev, "--session", sid, *extra, runner=runner, json_out=False)
    assert res.code == 2, res
    no_forbidden(runner)


@pytest.mark.parametrize("flag", ["--force", "--skip-checks", "--no-matrix"])
def test_G6_no_flag_bypasses_pass_matrix(cli, flag):
    """G6 'no CLI command writes a verdict PASS without the matrix'. Mutation: hidden override flag -> red."""
    sid = new_session(cli)
    dev = ingest_smart(cli, sid, "smartctl/nvme-990pro-x.json").data["device_id"]
    res = cli("verdict", "set", sid, dev, "PASS", flag, json_out=False)
    assert res.code == 2, res
    assert cli("verdict", "set", sid, dev, "PASS").code == 3
    d = ok(cli("verdict", "show", sid, dev))
    assert d["effective"] != "PASS"


def test_G6_gate_subcommands_have_no_state_shortcut():
    """G6 'gate state machine has no transition skipping confirm'. Mutation: add `gate force-open` -> red."""
    import argparse

    from rslib.cli import build_parser

    def subs(p):
        for a in p._actions:
            if isinstance(a, argparse._SubParsersAction):
                return a.choices
        return {}

    assert set(subs(subs(build_parser())["gate"])) == {"open", "confirm", "close", "abort", "list"}


def test_G6_pending_gate_cannot_close(cli):
    """G6 (state machine). Mutation: pending -> closed allowed -> red."""
    sid, dev = nvme1(cli, "--goal", "diagnosis-only", "--ceiling", "R1")
    g, _ = gate_ok(cli, BASELINE, sid, dev, "smart-selftest-short")
    res = cli("gate", "close", g, "--outcome", "success", runner=cli.runner(BASELINE))
    assert res.code == 3, res


def test_G6_confirm_on_open_gate_does_not_reconfirm_other_device(cli):
    """Bypass: confirm must re-resolve the gate's own device, never another. Mutation: confirm by phrase only -> red."""
    from conftest import phrase_980

    sid, dev = nvme1(cli, "--goal", "diagnosis-only", "--ceiling", "R1")
    g, _ = gate_ok(cli, BASELINE, sid, dev, "smart-selftest-short")
    res = cli("gate", "confirm", g, runner=cli.runner(BASELINE), answers=["1000204886016"])
    assert res.code == 3, res  # 990 PRO byte count is not this gate's phrase
    assert cli("gate", "confirm", g, runner=cli.runner(BASELINE), answers=[phrase_980()]).code == 0


# ---------------- G6b (amendment 02 G, N5): no shell metacharacters in values echoed into an operator command
UNSAFE = [('"', "dquote"), ("$", "dollar"), ("`", "backtick"), (";", "semicolon"), ("&", "amp"), ("|", "pipe"),
          ("<", "lt"), (">", "gt"), ("\n", "newline")]
UNSAFE_IDS = [i for _, i in UNSAFE]
CONSOLE = [(["YES"], "operator-yes"), ([], "no-console")]
STATES = {"waived": ("waived",), "secured-attested": ("secured", "--attested")}


def _refused_unsafe(res, home, before):
    """exit 2 unsafe-characters, nothing stored, and no printed `rs.py` command line carries the payload."""
    from conftest import operator_state

    assert res.code == 2, res
    assert "unsafe-characters" in res.reasons or "unsafe-characters" in res.text, res
    assert operator_state(home) == before
    assert "INJECTED" not in str((res.data or {}).get("command") or "")
    lines = (res.out + "\n" + res.err).replace("\n", "\n").splitlines()
    assert not [ln for ln in lines if "rs.py" in ln and "INJECTED" in ln], res


@pytest.mark.parametrize("answers", [a for a, _ in CONSOLE], ids=[i for _, i in CONSOLE])
@pytest.mark.parametrize("state", sorted(STATES))
@pytest.mark.parametrize("ch", [c for c, _ in UNSAFE], ids=UNSAFE_IDS)
def test_G6b_reason_with_unsafe_character_exit_2(cli, ch, state, answers):
    """Amendment 02 G: `--reason` values that would be echoed into a printed operator command must not contain
    " $ ` ; & | < > or a newline: exit 2 unsafe-characters before anything is stored (reviewer scen2.py #1: the
    payload `x" ; echo INJECTED ; "` landed in the copy-paste command). no-console = the path that prints the command.
    Mutation, one per character: drop that character from the check -> exit 0 (YES) or exit 3 with the payload in
    the printed command (no console) -> red."""
    from conftest import operator_state

    sid, dev = nvme1(cli, "--goal", "data-recovery")
    before = operator_state(cli.home)
    res = cli("session", "data-state", sid, dev, *STATES[state], "--reason", f"backed up {ch} echo INJECTED",
              answers=answers)
    _refused_unsafe(res, cli.home, before)


@pytest.mark.parametrize("answers", [a for a, _ in CONSOLE], ids=[i for _, i in CONSOLE])
@pytest.mark.parametrize("ch", [c for c, _ in UNSAFE], ids=UNSAFE_IDS)
def test_G6b_file_with_unsafe_character_exit_2(cli, tmp_path, ch, answers):
    """Amendment 02 G for `--file` (echoed in the `ingest attested` operator command). Where the OS allows the name,
    the file exists, so only the character rule can refuse; on Windows `" | < >` and newline cannot be in a file
    name and the path does not exist (test-designer reading: the character rule decides first, CONTRACT amendment 02).
    Mutation: `--file` not checked -> exit 0 / payload in the printed command -> red."""
    from conftest import operator_state

    sid, dev = nvme1(cli, "--goal", "data-recovery")
    f = tmp_path / f"h2testw {ch} echo INJECTED.txt"
    try:
        f.write_bytes(b"operator attachment: H2testw transcript")
    except OSError:
        pass
    before = operator_state(cli.home)
    res = cli("ingest", "attested", sid, dev, "--tool", "h2testw", "--result", "pass", "--file", f, answers=answers)
    _refused_unsafe(res, cli.home, before)


@pytest.mark.parametrize("ch", [c for c, _ in UNSAFE], ids=UNSAFE_IDS)
def test_G6b_note_with_unsafe_character_exit_2(cli, tmp_path, ch):
    """Amendment 02 G for `--note` (ingest attested, echoed with the command). Mutation: `--note` not checked -> red."""
    from conftest import operator_state

    sid, dev = nvme1(cli, "--goal", "data-recovery")
    f = tmp_path / "h2testw.txt"
    f.write_bytes(b"operator attachment: H2testw transcript")
    before = operator_state(cli.home)
    res = cli("ingest", "attested", sid, dev, "--tool", "h2testw", "--result", "pass", "--file", f, "--note",
              f"seen {ch} echo INJECTED", answers=[])
    _refused_unsafe(res, cli.home, before)


def test_G6b_safe_text_still_accepted(cli, tmp_path):
    """Counter-case: ordinary text (spaces, commas, dots, parentheses, Vietnamese) passes. Mutation: reject every
    non-alphanumeric character -> red."""
    sid, dev = nvme1(cli, "--goal", "data-recovery")
    res = cli("session", "data-state", sid, dev, "waived", "--reason", "chủ máy đã sao lưu (2 bản), đã kiểm tra.",
              answers=["YES"])
    assert res.code == 0, res
    f = tmp_path / "h2testw-result.txt"
    f.write_bytes(b"operator attachment: H2testw transcript")
    res2 = cli("ingest", "attested", sid, dev, "--tool", "h2testw", "--result", "pass", "--file", f, "--note",
               "verified by owner, 2026-10-19", answers=["YES"])
    assert res2.code == 0, res2
