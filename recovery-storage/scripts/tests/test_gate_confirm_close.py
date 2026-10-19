"""Phase 04 gate confirm / close / abort (D12-D16, D9c after-state). Spec: phase-04 Requirements 'Gate confirm',
'Gate close', 'Gate abort', 'State machine' + D12-D16; amendment 01 A (phrase typed by the operator at a console,
no --phrase argument)."""
import io
import sys

import pytest

from conftest import (BASELINE, USB_STICK, assert_console_required, close, confirm, db_rows, gate_ok, gate_open_state,
                      nvme1, ok, open_gate, operator_state, phrase_980, stick)

SWAP = {"pd1": f"{BASELINE}/smartctl-x-pd1.serial-swap.derived.json"}
RENUMBER = {"win-disks": f"{USB_STICK}/win-disks.renumber3.derived.json",
            "win-pnp-chain": f"{USB_STICK}/win-pnp-chain.renumber3.derived.json",
            "pd2": None, "sat-pd2": None,
            "pd3": f"{USB_STICK}/smartctl-x-pd3.from-pd2.derived.json",
            "sat-pd3": f"{USB_STICK}/smartctl-x-sat-pd3.from-pd2.derived.json"}


def state(cli, gate):
    gates = {g["id"]: g for g in ok(cli("gate", "list"))["gates"]}
    return gates[gate]["state"]


def r1_gate(cli):
    sid, dev = nvme1(cli, "--goal", "diagnosis-only", "--ceiling", "R1")
    g, _ = gate_ok(cli, BASELINE, sid, dev, "smart-selftest-short")
    return sid, dev, g


def test_D12_wrong_phrase_stays_pending(cli):
    """D12. Mutation: accept any phrase / 'yes' -> red."""
    _, _, g = r1_gate(cli)
    for bad in ("yes", "0d9", phrase_980() + "X"):
        res = confirm(cli, BASELINE, g, bad)
        assert res.code == 3, res
        assert "wrong-phrase" in res.reasons, res  # amendment 01 A names the reason
    assert state(cli, g) == "pending"


def test_D12_right_phrase_opens_and_prints_path(cli):
    """D12. Mutation: no re-resolution path printed -> red."""
    _, _, g = r1_gate(cli)
    res = confirm(cli, BASELINE, g, phrase_980())
    assert res.code == 0, res
    assert res.data["gate"]["state"] == "open"
    assert res.data["os_path"] == "/dev/pd1"
    assert state(cli, g) == "open"


def test_D12_text_confirm_prints_path(cli):
    """D12 text. Mutation: path only in JSON -> red."""
    _, _, g = r1_gate(cli)
    t = confirm(cli, BASELINE, g, phrase_980(), json_out=False)
    assert t.code == 0, t
    assert "/dev/pd1" in t.out


def test_D13_device_disappears_before_confirm_aborted(cli):
    """D13. Mutation: confirm trusts the open-time resolution -> state open -> red."""
    sid, dev = stick(cli, "--goal", "diagnosis-only", "--ceiling", "R1")
    g, _ = gate_ok(cli, USB_STICK, sid, dev, "disk-offline")
    res = confirm(cli, BASELINE, g, "8054112256")
    assert res.code == 3, res
    assert res.data["gate"]["state"] == "aborted"
    assert res.data["gate"]["abort_reason"] == "device-changed"
    assert "device-changed" in res.reasons
    assert state(cli, g) == "aborted"
    # lock released: a new gate on the same device is not device-busy
    g2 = open_gate(cli, USB_STICK, sid, dev, "disk-offline")
    assert g2.code == 0, g2


def test_D13_replaced_by_same_model_size_other_serial_aborted(cli):
    """D13 (derived serial swap on pd1). Mutation: re-resolve on model+bytes -> open on the wrong disk -> red."""
    _, _, g = r1_gate(cli)
    res = confirm(cli, BASELINE, g, phrase_980(), override=SWAP)
    assert res.code == 3, res
    assert res.data["gate"]["state"] == "aborted"
    assert res.data["gate"]["abort_reason"] == "device-changed"


def test_D14_renumbered_device_confirm_prints_new_path(cli):
    """D14 (derived Disk 2 -> Disk 3). Mutation: print the open-time path /dev/pd2 -> red."""
    sid, dev = stick(cli, "--goal", "diagnosis-only", "--ceiling", "R1")
    g, opened = gate_ok(cli, USB_STICK, sid, dev, "disk-offline")
    assert "/dev/pd2" in opened.data["confirmation"]["os_paths"]
    res = confirm(cli, USB_STICK, g, "8054112256", override=RENUMBER)
    assert res.code == 0, res
    assert res.data["gate"]["state"] == "open"
    assert res.data["os_path"] == "/dev/pd3"


def test_D15_swap_between_confirm_and_close_identity_drift(cli):
    """D15. Mutation: close compares nothing -> drift false -> red; PASS later refused."""
    sid, dev, g = r1_gate(cli)
    assert confirm(cli, BASELINE, g, phrase_980()).code == 0
    res = close(cli, BASELINE, g, "success", override=SWAP)
    assert res.code == 0, res
    assert res.data["gate"]["state"] == "closed"
    assert res.data["gate"]["identity_drift"] is True
    t_warn = (res.data.get("message") or "") + " ".join(res.data.get("warnings") or [])
    assert "drift" in t_warn.lower() or "identity" in t_warn.lower()
    v = cli("verdict", "set", sid, dev, "PASS")
    assert v.code == 3, v
    assert "unresolved-identity-drift" in v.reasons


def test_D15_unchanged_close_no_drift(cli):
    """D15 counter-case. Mutation: always flag drift -> red."""
    _, _, g = r1_gate(cli)
    assert confirm(cli, BASELINE, g, phrase_980()).code == 0
    res = close(cli, BASELINE, g, "success")
    assert res.code == 0 and res.data["gate"]["identity_drift"] is False, res
    assert res.data["gate"]["outcome"] == "success"
    assert res.data["after"]["observation_id"] and res.data["after"]["snapshot_id"]


def test_D16_close_only_from_open(cli):
    """D16. Mutation: allow pending -> closed (skips confirm) -> red."""
    _, _, g = r1_gate(cli)
    res = close(cli, BASELINE, g, "success")
    assert res.code == 3, res
    assert state(cli, g) == "pending"
    assert confirm(cli, BASELINE, g, phrase_980()).code == 0
    assert close(cli, BASELINE, g, "success").code == 0
    again = close(cli, BASELINE, g, "success")
    assert again.code == 3, again


def test_D16_abort_from_pending_and_open_not_closed(cli):
    """D16 + state machine 'nothing leaves closed/aborted'. Mutation: abort a closed gate -> red."""
    _, _, g = r1_gate(cli)
    assert ok(cli("gate", "abort", g, "--reason", "operator changed plan"))["gate"]["state"] == "aborted"
    assert cli("gate", "abort", g, "--reason", "again").code == 3
    assert confirm(cli, BASELINE, g, phrase_980()).code == 3
    sid, dev = nvme1(cli, "--goal", "diagnosis-only", "--ceiling", "R1")
    g2 = gate_open_state(cli, BASELINE, sid, dev, "smart-selftest-short", phrase_980())
    assert ok(cli("gate", "abort", g2, "--reason", "stop"))["gate"]["state"] == "aborted"
    sid3, dev3 = nvme1(cli, "--goal", "diagnosis-only", "--ceiling", "R1")
    g3 = gate_open_state(cli, BASELINE, sid3, dev3, "smart-selftest-short", phrase_980())
    assert close(cli, BASELINE, g3, "failed").code == 0
    res = cli("gate", "abort", g3, "--reason", "too late")
    assert res.code == 3, res


def test_D16_abort_requires_reason(cli):
    """Requirements 'Gate abort --reason'. Mutation: optional reason -> red."""
    _, _, g = r1_gate(cli)
    assert cli("gate", "abort", g, json_out=False).code == 2


def test_D9c_needs_elevation_after_state_does_not_block_close(cli):
    """D9c (close side). Mutation: after-state collection failure blocks close -> red."""
    sid, dev = stick(cli, "--goal", "diagnosis-only", "--ceiling", "R1")
    g = gate_open_state(cli, USB_STICK, sid, dev, "disk-offline", "8054112256")
    res = close(cli, USB_STICK, g, "success")
    assert res.code == 0, res
    assert res.data["after"]["collection_status"] == "needs_elevation"


# ---------------- amendment 01 A: operator console
def test_D12b_phrase_argument_removed_exit_2(cli):
    """Amendment 01 A '`gate confirm <gate>`: no `--phrase` argument any more'. The right phrase is also offered at
    the prompt, so an implementation that still accepts --phrase exits 0 instead of 2.
    Mutation: keep `--phrase` on the confirm parser -> exit 0 -> red."""
    _, _, g = r1_gate(cli)
    res = cli("gate", "confirm", g, "--phrase", phrase_980(), runner=cli.runner(BASELINE), answers=[phrase_980()],
              json_out=False)
    assert res.code == 2, res
    assert state(cli, g) == "pending"


@pytest.mark.parametrize("how", ["no-tty-console", "operator-out-of-answers"])
def test_D12c_no_console_refused_with_command_line_store_unchanged(cli, monkeypatch, how):
    """Amendment 01 A 'No console (NoConsole) -> exit 3 operator-console-required, message contains
    `python <abs path>/rs.py gate confirm <gate>`; nothing is changed in the store'. no-tty-console: operator=None
    -> default ConsoleOperator with a non-TTY stdin; operator-out-of-answers: ScriptedOperator([]).
    Mutation: confirm without asking (or fall back to a phrase from argv/env) -> exit 0 -> red; message without the
    command line -> red; gate aborted/opened on NoConsole -> red."""
    _, _, g = r1_gate(cli)
    before = operator_state(cli.home)
    if how == "no-tty-console":
        monkeypatch.setattr(sys, "stdin", io.StringIO(""))  # isatty() False
        res = cli("gate", "confirm", g, runner=cli.runner(BASELINE), operator=None)
    else:
        res = cli("gate", "confirm", g, runner=cli.runner(BASELINE), answers=[])
    assert_console_required(res, "gate", "confirm", g)
    assert state(cli, g) == "pending"
    assert operator_state(cli.home) == before
    # the gate is still usable by the human afterwards
    assert confirm(cli, BASELINE, g, phrase_980()).code == 0


def test_D12d_prompt_asks_for_phrase_and_audit_names_operator(cli):
    """Amendment 01 A: CLI asks `Type the confirmation phrase: `; `gates` rows store `confirmed_by` = `operator`.
    Mutation: confirm without asking (prompt list empty) -> red; confirmed_by missing / 'agent' -> red."""
    _, _, g = r1_gate(cli)
    res = confirm(cli, BASELINE, g, phrase_980())
    assert res.code == 0, res
    assert len(res.prompts) == 1, res.prompts
    assert "confirmation phrase" in res.prompts[0].casefold()
    row = next(r for r in db_rows(cli.home, "gates") if str(r["id"]) == str(g))
    assert row["confirmed_by"] == "operator"


def test_D12e_wrong_phrase_store_keeps_gate_pending_unconfirmed(cli):
    """Amendment 01 A 'Wrong phrase -> exit 3 wrong-phrase, gate stays pending (as D12)'.
    Mutation: wrong phrase aborts the gate or records confirmed_by -> red."""
    _, _, g = r1_gate(cli)
    res = confirm(cli, BASELINE, g, "no")
    assert res.code == 3 and "wrong-phrase" in res.reasons, res
    row = next(r for r in db_rows(cli.home, "gates") if str(r["id"]) == str(g))
    assert row["state"] == "pending"
    assert not row["confirmed_by"]
