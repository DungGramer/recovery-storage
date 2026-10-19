"""Phase 02 commands through the CLI with a RecordedRunner (B15-B22, B18b).
Spec: phase-02 Requirements (collect, events, ingest smartctl, device link, class detection) + B15-B22."""
import pytest

from conftest import (BASELINE, USB_SD, USB_STICK, collect, device_at, fx, fx_bytes, inventory, make_runner,
                      new_session, obs_for, ok, sha256_hex)

X = ["-j", "-x", "-n", "standby"]
SAT = ["-j", "-x", "-n", "standby", "-d", "sat"]


def calls_for(runner, dev):
    return [a for t, a in runner.calls if t == "smartctl" and a and a[-1] == dev and ("-x" in a)]


# ---------------- B15
def test_B15_inventory_first_run_creates_then_reuses(cli):
    """B15. Mutation: create a new device on every run (duplicates) or key on Disk Number -> red."""
    sid = new_session(cli)
    r1 = inventory(cli, make_runner(USB_SD), sid)
    obs1 = {o["os_path"]: o for o in r1.data["observations"]}
    assert set(obs1) == {"/dev/pd0", "/dev/pd1", "/dev/pd2", "/dev/pd3"}
    for o in obs1.values():
        assert o["created"] is True and o["match"] == "none" and o["device_id"]
        assert o["fingerprint"]["bytes"] == o["bytes"] and o["model"]
    r2 = inventory(cli, make_runner(USB_SD), sid)
    obs2 = {o["os_path"]: o for o in r2.data["observations"]}
    for p in obs1:
        assert obs2[p]["device_id"] == obs1[p]["device_id"], p
        assert obs2[p]["created"] is False
    assert obs2["/dev/pd0"]["match"] == "exact"
    assert obs2["/dev/pd1"]["match"] == "exact"
    assert obs2["/dev/pd2"]["match"] == "probable"
    assert obs2["/dev/pd3"]["match"] == "weak"
    assert len(ok(cli("device", "list"))["devices"]) == 4


def test_B15_text_lists_fingerprint_match_and_path(cli):
    """B15 'lists each disk with fingerprint, match level, OS path' (text mode). Mutation: print ids only -> red."""
    sid = new_session(cli)
    inventory(cli, make_runner(BASELINE), sid)
    res = cli("inventory", "--session", sid, runner=make_runner(BASELINE), json_out=False)
    assert res.code == 0, res
    for s in ("/dev/pd0", "/dev/pd1", "Samsung SSD 990 PRO 1TB", "1000204886016", "exact"):
        assert s in res.out, s


def test_B15_nvme_canonical_identity_from_smartctl(cli):
    """Key insight 'canonical identity = smartctl' + B10 join on this machine's capture. Mutation: OS serial (EUI) as serial -> red."""
    sid = new_session(cli)
    res = inventory(cli, make_runner(BASELINE), sid)
    o = obs_for(res, "/dev/pd1")
    assert o["join"] == "joined"
    assert o["fingerprint"]["serial_norm"] == "4QPHHGYUSU50D9Z"
    assert o["fingerprint"]["serial_trust"] == "high"
    assert o["fingerprint"]["eui64"].lower() == "002538ff31f9f701"
    assert o["is_boot"] is False
    assert obs_for(res, "/dev/pd0")["is_boot"] is True and obs_for(res, "/dev/pd0")["is_system"] is True


# ---------------- B16
TWIN = {"win-disks": f"{USB_STICK}/win-disks.twin.derived.json",
        "win-pnp-chain": f"{USB_STICK}/win-pnp-chain.twin.derived.json",
        "pd3": f"{USB_STICK}/smartctl-x-pd3.from-pd2.derived.json",
        "sat-pd3": f"{USB_STICK}/smartctl-x-sat-pd3.from-pd2.derived.json"}


def test_B16_ambiguous_exit_5_no_link_then_device_link(cli):
    """B16 'a stored device now matches ambiguously' (stored stick; derived capture with two identical sticks).
    Mutation: auto-link both observations to the stored device -> red."""
    sid = new_session(cli)
    d_a = device_at(cli, USB_STICK, sid, "/dev/pd2")
    res = cli("inventory", "--session", sid, runner=make_runner(USB_STICK, TWIN))
    assert res.code == 5, res
    assert "ambiguous" in res.reasons
    for p in ("/dev/pd2", "/dev/pd3"):
        o = obs_for(res, p)
        assert o["match"] == "ambiguous" and o["device_id"] is None
        cands = {c["device_id"]: c for c in o["candidates"]}
        assert d_a in cands
        assert cands[d_a]["model"] == "General UDisk" and cands[d_a]["bytes"] == 8054112256
    assert obs_for(res, "/dev/pd0")["match"] == "exact"  # unaffected disks still matched
    o2, o3 = obs_for(res, "/dev/pd2")["observation_id"], obs_for(res, "/dev/pd3")["observation_id"]
    lk = ok(cli("device", "link", o2, d_a))
    assert lk["device_id"] == d_a and lk["created"] is False
    new = ok(cli("device", "link", o3, "--new"))
    assert new["created"] is True and new["device_id"] != d_a


def test_B16_ambiguous_text_shows_candidates(cli):
    """B16 'prints candidates with model/size/os path'. Mutation: print only 'ambiguous' -> red."""
    sid = new_session(cli)
    device_at(cli, USB_STICK, sid, "/dev/pd2")
    res = cli("inventory", "--session", sid, runner=make_runner(USB_STICK, TWIN), json_out=False)
    assert res.code == 5, res
    for s in ("General UDisk", "8054112256", "/dev/pd2", "/dev/pd3"):
        assert s in res.out, s


# ---------------- B17
def test_B17_collect_runs_exactly_x_n_standby_and_stores_snapshot(cli):
    """B17. Mutation: run `-a`, drop `-n standby`, or retry -d sat on NVMe -> red."""
    sid = new_session(cli)
    dev = device_at(cli, BASELINE, sid, "/dev/pd1")
    runner = make_runner(BASELINE)
    res = cli("collect", dev, "--session", sid, runner=runner)
    assert res.code == 0, res
    assert calls_for(runner, "/dev/pd1") == [tuple(X + ["/dev/pd1"])]
    snap = res.data["snapshot"]
    assert snap["collection_status"] == "ok"
    assert snap["tool_version"] == "7.5"
    assert snap["source"] == "collected"
    assert snap["sha256"] == sha256_hex(fx_bytes(f"{BASELINE}/smartctl-x-pd1.json"))
    assert res.data["device_id"] == dev


def test_B17_device_absent_exit_3_nothing_stored(cli):
    """B17. Mutation: collect whatever disk now sits at the old path -> red."""
    sid = new_session(cli)
    stick = device_at(cli, USB_STICK, sid, "/dev/pd2")
    runner = make_runner(BASELINE)
    res = cli("collect", stick, "--session", sid, runner=runner)
    assert res.code == 3, res
    assert "device-not-found" in res.reasons
    assert [a for t, a in runner.calls if "-x" in a] == []
    hist = ok(cli("device", "show", stick))["history"]
    assert not [h for h in hist if h["type"] == "snapshot"]


# ---------------- B18 / B18b
def test_B18_usb_unknown_bridge_one_sat_retry_needs_elevation(cli):
    """B18. Mutation: no retry, retry twice, or report needs_elevation as a device fault -> red."""
    sid = new_session(cli)
    dev = device_at(cli, USB_STICK, sid, "/dev/pd2")
    runner = make_runner(USB_STICK)
    res = cli("collect", dev, "--session", sid, runner=runner, json_out=False)
    assert res.code == 0, res
    assert calls_for(runner, "/dev/pd2") == [tuple(X + ["/dev/pd2"]), tuple(SAT + ["/dev/pd2"])]
    assert "re-run elevated to try sat passthrough; this is not a device fault" in res.text.lower()
    j = cli("device", "show", dev)
    snaps = [h for h in j.data["history"] if h["type"] == "snapshot"]
    assert snaps
    r2 = cli("collect", dev, "--session", sid, runner=make_runner(USB_STICK))
    assert r2.data["snapshot"]["collection_status"] == "needs_elevation"


def test_B18_retry_without_smart_and_without_error_is_not_exposed(cli):
    """B18 (derived sat-pd2.no-error). Mutation: call it ok or collection_failed -> red."""
    sid = new_session(cli)
    dev = device_at(cli, USB_STICK, sid, "/dev/pd2")
    over = {"sat-pd2": f"{USB_STICK}/smartctl-x-sat-pd2.no-error.derived.json"}
    res = cli("collect", dev, "--session", sid, runner=make_runner(USB_STICK, over))
    assert res.code == 0, res
    assert res.data["snapshot"]["collection_status"] == "not_exposed"


@pytest.mark.parametrize("capture,path", [(USB_STICK, "/dev/pd2"), (USB_SD, "/dev/pd3")])
def test_B18b_usb_devices_detected_usb_flash_or_card(cli, capture, path):
    """B18b. Mutation: classify USB without SMART as external-hdd or sd -> red."""
    sid = new_session(cli)
    dev = device_at(cli, capture, sid, path)
    res = collect(cli, capture, sid, dev)
    assert res.data["detected_class"] == "usb-flash-or-card"


def test_B18b_declared_sd_vs_usb_flash_is_not_conflict(cli):
    """B18b. Mutation: strict string compare declared != detected -> red."""
    sid = new_session(cli, "--goal", "diagnosis-only", "--device-type", "sd")
    dev = device_at(cli, USB_SD, sid, "/dev/pd3")
    res = collect(cli, USB_SD, sid, dev)
    assert res.data["declared_class"] == "sd"
    assert res.data["class_conflict"] is False


def test_B18b_declared_hdd_vs_usb_flash_is_conflict_and_declared_kept(cli):
    """B18b + Requirements 'declared never overwritten'. Mutation: overwrite declared with detected -> red."""
    sid = new_session(cli, "--goal", "diagnosis-only", "--device-type", "hdd")
    dev = device_at(cli, USB_STICK, sid, "/dev/pd2")
    res = collect(cli, USB_STICK, sid, dev)
    assert res.data["class_conflict"] is True
    assert res.data["declared_class"] == "hdd"
    assert ok(cli("session", "show", sid))["session"]["device_type"] == "hdd"


# ---------------- B19
@pytest.mark.skip(reason="BLOCKED (open question B19): no real or sourced smartctl standby output; the JSON shape "
                         "of `power_mode` with -n standby is unsourced in research. Needs a real capture of a "
                         "sleeping HDD (fixtures/SOURCES.md 'No real sample yet').")
def test_B19_standby_snapshot_not_spun_up():
    """B19 standby -> snapshot `standby, not spun up`, exit 0."""


def test_B19_allow_spinup_drops_n_standby_and_records_spinup(cli):
    """B19 second half. Mutation: keep -n standby with --allow-spinup, or not record spinup -> red."""
    sid = new_session(cli)
    dev = device_at(cli, BASELINE, sid, "/dev/pd1")
    runner = make_runner(BASELINE)
    res = cli("collect", dev, "--session", sid, "--allow-spinup", runner=runner)
    assert res.code == 0, res
    assert calls_for(runner, "/dev/pd1") == [("-j", "-x", "/dev/pd1")]
    assert res.data["snapshot"]["spinup"] is True
    plain = collect(cli, BASELINE, sid, dev)
    assert plain.data["snapshot"]["spinup"] is False


def test_collect_dtype_inserts_d_before_device(cli):
    """Requirements '--dtype <type> from the allow-list'. Mutation: append -d after the device -> red."""
    sid = new_session(cli)
    dev = device_at(cli, BASELINE, sid, "/dev/pd1")
    from conftest import recording

    runner = make_runner(BASELINE, extra=[recording("smartctl", ["-j", "-x", "-n", "standby", "-d", "nvme", "/dev/pd1"],
                                                    f"{BASELINE}/smartctl-x-pd1.json")])
    res = cli("collect", dev, "--session", sid, "--dtype", "nvme", runner=runner)
    assert res.code == 0, res
    assert ("-j", "-x", "-n", "standby", "-d", "nvme", "/dev/pd1") in calls_for(runner, "/dev/pd1")


# ---------------- B20
def _all_smartctl(capture, **kw):
    from conftest import capture_files

    return {k: dict(kw) for k in capture_files(capture) if k.startswith(("pd", "sat-pd")) or k == "scan-open"}


@pytest.mark.parametrize("mode,status", [("tool_missing", "tool_missing"), ("timed_out", "timeout")])
def test_B20_smartctl_missing_or_timeout_exit_4(cli, mode, status):
    """B20. Mutation: exit 0 on missing tool, or status 'collection_failed' -> red."""
    over = _all_smartctl(BASELINE, **{mode: True, "exit_code": None, "stdout": b""})
    sid = new_session(cli)
    inv = cli("inventory", "--session", sid, runner=make_runner(BASELINE, over))
    assert inv.code in (0, 4), inv
    dev = obs_for(inv, "/dev/pd1")["device_id"]
    assert dev
    res = cli("collect", dev, "--session", sid, runner=make_runner(BASELINE, over), json_out=False)
    assert res.code == 4, res
    j = cli("collect", dev, "--session", sid, runner=make_runner(BASELINE, over))
    assert j.code == 4 and j.data["snapshot"]["collection_status"] == status
    if mode == "tool_missing":
        low = res.text.lower()
        assert "winget install smartmontools.smartmontools" in low
        assert "scoop install smartmontools" in low


# ---------------- B21 at the CLI
def test_B21_collect_tags_ntfs55_exit_0(cli):
    """B21. Mutation: drop events on collect -> red."""
    sid = new_session(cli)
    dev = device_at(cli, BASELINE, sid, "/dev/pd1")
    res = collect(cli, BASELINE, sid, dev, override={"win-events": f"{BASELINE}/win-events.ntfs55.derived.json"})
    ev = res.data["events"]
    assert ev["status"] == "ok"
    assert [e["tag"] for e in ev["items"] if e["provider"] == "Ntfs" and e["id"] == 55] == ["fs_corruption"]


def test_B21_events_unavailable_still_exit_0(cli):
    """B21 'access denied -> events unavailable with reason; collect still exit 0'. Mutation: exit 4 -> red."""
    sid = new_session(cli)
    dev = device_at(cli, BASELINE, sid, "/dev/pd1")
    res = collect(cli, BASELINE, sid, dev, override={"win-events": {"exit_code": 1, "stdout": b""}})
    assert res.data["events"]["status"].startswith("unavailable")
    assert len(res.data["events"]["status"]) > len("unavailable")  # carries a reason
    assert res.data["snapshot"]["collection_status"] == "ok"


# ---------------- B22
def test_B22_ingest_matching_device_attaches_snapshot(cli):
    """B22. Mutation: always create a new device on ingest -> red."""
    sid = new_session(cli)
    dev = device_at(cli, BASELINE, sid, "/dev/pd1")
    res = cli("ingest", "smartctl", fx("smartctl/nvme-980pro-x.json"), "--session", sid)
    d = ok(res)
    assert d["device_id"] == dev and d["created"] is False
    assert d["snapshot"]["source"] == "ingested"
    assert d["snapshot"]["sha256"] == sha256_hex(fx_bytes("smartctl/nvme-980pro-x.json"))


def test_B22_ingest_no_match_creates_device(cli):
    """B22. Mutation: refuse unknown identities -> red."""
    sid = new_session(cli)
    d = ok(cli("ingest", "smartctl", fx("smartctl/scrutiny-ata-hdd-healthy.json"), "--session", sid))
    assert d["created"] is True and d["device_id"]
    again = ok(cli("ingest", "smartctl", fx("smartctl/scrutiny-ata-hdd-healthy.json"), "--session", sid))
    assert again["device_id"] == d["device_id"] and again["created"] is False


def test_B22_ingest_ambiguous_exit_5(cli):
    """B22 (derived scsi no-serial: only model+bytes match). Mutation: attach to the only model+bytes candidate -> red."""
    sid = new_session(cli)
    ok(cli("ingest", "smartctl", fx("smartctl/scrutiny-scsi-no-smartctl-block.json"), "--session", sid))
    res = cli("ingest", "smartctl", fx("smartctl/scrutiny-scsi-no-smartctl-block.no-serial.derived.json"),
              "--session", sid)
    assert res.code == 5, res
    assert "ambiguous" in res.reasons
