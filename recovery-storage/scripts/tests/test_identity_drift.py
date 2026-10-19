"""Amendment 02 A (2026-10-19, findings N1, N4, N16): identity changes only by the operator.
Spec: plans/20261019-1726-recovery-storage-skill/amendment-02-review-round-2.md section A; contract in
tests/CONTRACT.md "Amendment 02". Reproduction: reviewer scratchpad scen.py scenarios 1 and 3.

Fixture: the look-alike stick = windows/usb-stick capture with only Disk 2's MBR Signature changed
(win-disks.othersig.derived.json, G3). Every assertion reads CLI JSON (gate close keys, inventory match, verdict
reasons), never store internals."""
import pytest

from conftest import (BASELINE, OTHERSIG, STICK_PHRASE, USB_STICK, close, device_at, gate_open_state, inventory, link,
                      new_session, nvme1, obs_for, ok, phrase_980, printed_link_command, stick)

DEVREC = ("--goal", "device-recovery", "--preserve-data", "no", "--ceiling", "R2")
SWAP = {"pd1": f"{BASELINE}/smartctl-x-pd1.serial-swap.derived.json"}
TWIN = {"win-disks": f"{USB_STICK}/win-disks.twin.derived.json",
        "win-pnp-chain": f"{USB_STICK}/win-pnp-chain.twin.derived.json",
        "pd3": f"{USB_STICK}/smartctl-x-pd3.from-pd2.derived.json",
        "sat-pd3": f"{USB_STICK}/smartctl-x-sat-pd3.from-pd2.derived.json"}


def stick_format_open(cli):
    """Stick A, format gate open (confirmed with the byte-count phrase)."""
    sid, dev = stick(cli, *DEVREC)
    g = gate_open_state(cli, USB_STICK, sid, dev, "format", STICK_PHRASE)
    return sid, dev, g


def lookalike_close(cli):
    """N1: the look-alike (same hardware, other MBR signature) answers at close."""
    sid, dev, g = stick_format_open(cli)
    res = close(cli, USB_STICK, g, "success", override=OTHERSIG)
    assert res.code == 0, res
    return sid, dev, g, res


def drift_unresolved(cli, sid, dev):
    v = cli("verdict", "set", sid, dev, "PASS")
    assert v.code == 3, v  # PASS needs far more than identity here; only the drift reason is inspected
    return "unresolved-identity-drift" in v.reasons


# ---------------- D15b: close records drift and never changes the fingerprint
def test_D15b_media_id_changed_at_close_is_drift_with_operator_command(cli):
    """Amendment 02 A: 'only its on-media id differs' -> closed with identity_drift and drift_reason
    `media-id-changed` (exactly one attached disk is the same hardware with another MBR signature); the close output
    prints `device link <observation> <device>`. Mutation: close accepts the look-alike silently (pre-amendment N1)
    -> drift false -> red; drift_reason not computed -> red; no operator command printed -> red."""
    sid, dev, g, res = lookalike_close(cli)
    gate = res.data["gate"]
    assert gate["state"] == "closed"
    assert gate["identity_drift"] is True
    assert gate["drift_reason"] == "media-id-changed"
    assert printed_link_command(res, dev), res
    assert drift_unresolved(cli, sid, dev)


def test_D15b_close_never_changes_the_fingerprint(cli):
    """Amendment 02 A '`gate close` never changes a device fingerprint'. After the look-alike close the stored stick
    still resolves the ORIGINAL capture, and the look-alike is still not resolved to it (G3: exit 5, unlinked).
    Mutation: close learns the new signature (replace -> original no longer resolves; add -> look-alike resolves to
    the stored device) -> red."""
    sid, dev, _, _ = lookalike_close(cli)
    orig = inventory(cli, cli.runner(USB_STICK), sid)
    assert obs_for(orig, "/dev/pd2")["device_id"] == dev
    look = cli("inventory", "--session", sid, runner=cli.runner(USB_STICK, OTHERSIG))
    assert obs_for(look, "/dev/pd2")["device_id"] != dev, look


def test_D15b_other_hardware_at_close_is_device_changed(cli):
    """Amendment 02 A drift_reason 'else `device-changed`' (derived serial swap on pd1: other hardware, not an on-media
    id). Mutation: every drift labelled media-id-changed -> red."""
    sid, dev = nvme1(cli, "--goal", "diagnosis-only", "--ceiling", "R1")
    g = gate_open_state(cli, BASELINE, sid, dev, "smart-selftest-short", phrase_980())
    res = close(cli, BASELINE, g, "success", override=SWAP)
    assert res.code == 0, res
    assert res.data["gate"]["identity_drift"] is True
    assert res.data["gate"]["drift_reason"] == "device-changed"


def test_D15b_not_attached_at_close_is_device_changed(cli):
    """Amendment 02 A 'not attached' -> drift, `device-changed' (reviewer scen.py scenario 3: stick unplugged at close).
    Mutation: a missing device at close closes clean (no drift) -> red."""
    sid, dev = stick(cli, "--goal", "diagnosis-only", "--ceiling", "R1")
    g = gate_open_state(cli, USB_STICK, sid, dev, "disk-offline", STICK_PHRASE)
    res = close(cli, BASELINE, g, "success")
    assert res.code == 0, res
    assert res.data["gate"]["state"] == "closed"
    assert res.data["gate"]["identity_drift"] is True
    assert res.data["gate"]["drift_reason"] == "device-changed"


def test_D15b_ambiguous_at_close_is_drift(cli):
    """Amendment 02 A 'ambiguous' -> drift. Two identical sticks attached (derived twin, same signature as the stored
    one, so no disk carries ANOTHER signature -> `device-changed`). Mutation: pick the first candidate at close -> no
    drift -> red."""
    sid, dev = stick(cli, "--goal", "diagnosis-only", "--ceiling", "R1")
    g = gate_open_state(cli, USB_STICK, sid, dev, "disk-offline", STICK_PHRASE)
    res = close(cli, USB_STICK, g, "success", override=TWIN)
    assert res.code == 0, res
    assert res.data["gate"]["identity_drift"] is True
    assert res.data["gate"]["drift_reason"] == "device-changed"


def test_D15b_unchanged_close_has_no_drift_reason(cli):
    """Counter-case. Mutation: drift_reason filled on a clean close -> red."""
    sid, dev = nvme1(cli, "--goal", "diagnosis-only", "--ceiling", "R1")
    g = gate_open_state(cli, BASELINE, sid, dev, "smart-selftest-short", phrase_980())
    res = close(cli, BASELINE, g, "success")
    assert res.code == 0, res
    assert res.data["gate"]["identity_drift"] is False
    assert not res.data["gate"].get("drift_reason")


# ---------------- D15c: the operator link clears drift and learns the on-media id
def test_D15c_printed_link_command_clears_drift_and_learns_media_id(cli):
    """Amendment 02 A: following the printed `device link <observation> <device>` (operator answers YES) learns the
    observation's on-media ids (hardware matches) and clears identity_drift of the gate closed before it.
    Mutation: link does not learn (look-alike still unresolved, exit 5) -> red; drift not cleared -> PASS still lists
    unresolved-identity-drift -> red."""
    sid, dev, _, res = lookalike_close(cli)
    obs = printed_link_command(res, dev)
    assert obs, res
    lk = link(cli, obs, dev)
    assert lk.code == 0, lk
    assert lk.data["device_id"] == dev and lk.data["created"] is False
    look = inventory(cli, cli.runner(USB_STICK, OTHERSIG), sid)
    assert obs_for(look, "/dev/pd2")["device_id"] == dev
    assert not drift_unresolved(cli, sid, dev)


def test_D15c_link_of_a_later_observation_clears_drift(cli):
    """Amendment 02 A 'clears identity_drift on every closed gate of that device whose close happened before the linked
    observation' (observation taken by a fresh inventory after the close). Mutation: drift cleared only via the close's
    own observation / never -> red."""
    sid, dev, _, _ = lookalike_close(cli)
    look = inventory(cli, cli.runner(USB_STICK, OTHERSIG), sid, expect=5)
    obs = obs_for(look, "/dev/pd2")["observation_id"]
    assert link(cli, obs, dev).code == 0
    assert not drift_unresolved(cli, sid, dev)


def test_D15c_link_does_not_clear_a_gate_closed_after_the_observation(cli):
    """Amendment 02 A, same rule, other side: the observation is taken while the gate is open, the drifting close comes
    after it, so linking that observation leaves the drift. Mutation: link clears every drift of the device regardless
    of time -> red."""
    sid, dev, g = stick_format_open(cli)
    look = inventory(cli, cli.runner(USB_STICK, OTHERSIG), sid, expect=5)
    obs = obs_for(look, "/dev/pd2")["observation_id"]
    res = close(cli, USB_STICK, g, "success", override=OTHERSIG)
    assert res.code == 0 and res.data["gate"]["identity_drift"] is True, res
    assert link(cli, obs, dev).code == 0
    assert drift_unresolved(cli, sid, dev)


# ---------------- D15d: link to other hardware refused
def test_D15d_link_to_device_with_other_hardware_refused(cli):
    """Amendment 02 A 'A link to a device with different hardware is refused exit 3 hardware-mismatch (use --new)':
    the look-alike stick observation offered to the 980 PRO device (other model, bytes, no USB ids). The operator says
    YES, so only the hardware rule decides. Mutation: link without the hardware comparison -> exit 0 and the NVMe
    learns the stick's ids -> red."""
    sid = new_session(cli)
    stick_dev = device_at(cli, USB_STICK, sid, "/dev/pd2")
    nvme = device_at(cli, USB_STICK, sid, "/dev/pd1")
    n = len(ok(cli("device", "list"))["devices"])
    look = inventory(cli, cli.runner(USB_STICK, OTHERSIG), sid, expect=5)
    obs = obs_for(look, "/dev/pd2")["observation_id"]
    res = link(cli, obs, nvme)
    assert res.code == 3, res
    assert "hardware-mismatch" in res.reasons, res
    again = cli("inventory", "--session", sid, runner=cli.runner(USB_STICK, OTHERSIG))
    assert again.code == 5 and obs_for(again, "/dev/pd2")["device_id"] is None, again
    assert obs_for(again, "/dev/pd1")["device_id"] == nvme
    assert len(ok(cli("device", "list"))["devices"]) == n
    assert stick_dev != nvme
    new = link(cli, obs, "--new")
    assert new.code == 0 and new.data["created"] is True, new
