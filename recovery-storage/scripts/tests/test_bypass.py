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
