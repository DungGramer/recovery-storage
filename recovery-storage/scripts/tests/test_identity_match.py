"""Phase 02 identity: serial normalisation, trust, match table, Windows join (B7-B10).
Spec: phase-02 Architecture "Serial normalisation", "serial_trust", "Match", B7-B10. Fingerprints here are pure inputs."""
import json

import pytest

from conftest import BASELINE, fx_json, fx_text

M, B = "Some Model X", 64000000000


def FP(**kw):
    from rslib.identity import Fingerprint

    return Fingerprint(**kw)


def match(fp, cands, attached=()):
    from rslib.identity import match as m

    return m(fp, cands, attached=list(attached))


# ---------------- B7
def test_B7_serial_trimmed_uppercased_trailing_dot_dropped():
    """B7. Mutation: keep the trailing dot or the spaces -> red."""
    from rslib.identity import normalise_serial

    r = normalise_serial("  ABC123XYZ.  ")
    assert r["serial_norm"] == "ABC123XYZ"
    assert r["eui64"] is None
    assert r["raw"] == "  ABC123XYZ.  "


def test_B7_lowercase_serial_uppercased():
    """B7 'uppercase'. Mutation: no case folding -> red."""
    from rslib.identity import normalise_serial

    assert normalise_serial("abc123xyz")["serial_norm"] == "ABC123XYZ"


def test_B7_windows_nvme_eui_form_is_eui64_not_serial():
    """B7. Mutation: treat `1111_2222_3333_4444.` as a serial -> wrong-key join trap -> red."""
    from rslib.identity import normalise_serial

    r = normalise_serial("1111_2222_3333_4444.")
    assert r["serial_norm"] is None
    assert r["eui64"].lower() == "1111222233334444"


# ---------------- B8
@pytest.mark.parametrize("raw", ["", "\t", "[", None, "   ", "--"])
def test_B8_trust_absent(raw):
    """B8 (+ 'no alphanumeric character'). Mutation: length check only (misses "--") -> red."""
    from rslib.identity import serial_trust

    assert serial_trust(raw) == "absent"


def test_B8_trust_low_repeated_char():
    """B8. Mutation: repeated-char rule missing -> high -> red."""
    from rslib.identity import serial_trust

    assert serial_trust("0000000000") == "low"


def test_B8_trust_low_when_another_attached_device_shares_serial():
    """B8. Mutation: ignore other attached devices -> high -> red."""
    from rslib.identity import serial_trust

    assert serial_trust("ABC123", other_attached=["ABC123"]) == "low"
    assert serial_trust("ABC123", other_attached=["  abc123. "]) == "low"  # compared normalised


def test_B8_trust_high_alone():
    """B8. Mutation: everything low -> red."""
    from rslib.identity import serial_trust

    assert serial_trust("WDXYZ12345") == "high"
    assert serial_trust("WDXYZ12345", other_attached=["OTHER999"]) == "high"


# ---------------- B9 match table
def hi(**kw):
    base = dict(model=M, serial_norm="SER12345", serial_trust="high", bytes=B)
    base.update(kw)
    return FP(**base)


def usb(**kw):
    base = dict(model=M, serial_norm=None, serial_trust="absent", bytes=B, bus="usb", vid="ABCD", pid="1234")
    base.update(kw)
    return FP(**base)


def test_B9_exact():
    """B9 exact. Mutation: require eui64 even when absent -> red."""
    r = match(hi(), {"d1": hi()})
    assert r.level == "exact" and list(r.device_ids) == ["d1"]


def test_B9_exact_with_equal_eui64():
    """B9 exact (+ eui64 equal when both present). Mutation: drop exact when eui present -> red."""
    r = match(hi(eui64="0025380e45914fa6"), {"d1": hi(eui64="0025380E45914FA6")})
    assert r.level == "exact"


def test_B9_conflict_when_eui_differs():
    """B9 conflict. Mutation: ignore eui64 once serial/model/bytes agree -> exact -> red."""
    r = match(hi(eui64="0025380e45914fa6"), {"d1": hi(eui64="0025380e45914fa7")})
    assert r.level == "conflict"


def test_B9_conflict_when_high_serial_differs():
    """B9 conflict ('serial with trust high' is a strong id). Mutation: fall back to model+bytes -> ambiguous -> red."""
    r = match(hi(serial_norm="OTHER9999"), {"d1": hi()})
    assert r.level == "conflict"


def test_B9_conflict_when_wwn_differs():
    """B9 conflict (wwn strong id). Mutation: wwn not compared -> red."""
    r = match(hi(wwn="5000cca123"), {"d1": hi(wwn="5000cca124")})
    assert r.level == "conflict"


def test_B9_probable_by_ptuuid():
    """B9 probable. Mutation: ptuuid ignored -> weak -> red."""
    r = match(usb(ptuuid="1f2e3d4c"), {"d1": usb(ptuuid="1f2e3d4c")})
    assert r.level == "probable" and list(r.device_ids) == ["d1"]


def test_B9_probable_by_mbr_signature():
    """B9 probable (signature 1859593249). Mutation: signature ignored -> weak -> red."""
    r = match(usb(mbr_signature=1859593249), {"d1": usb(mbr_signature=1859593249)})
    assert r.level == "probable"


def test_B9_probable_needs_vid_pid_equal():
    """B9 probable requires model+bytes+vid/pid. Mutation: skip vid/pid compare -> probable -> red."""
    r = match(usb(mbr_signature=1859593249), {"d1": usb(mbr_signature=1859593249, pid="9999")})
    assert r.level not in ("exact", "probable", "weak")


def test_B9_signature_zero_never_counts_weak():
    """B9: signature 0 on both -> weak. Mutation: 0 == 0 treated as on-media id -> probable -> red."""
    r = match(usb(mbr_signature=0), {"d1": usb(mbr_signature=0)})
    assert r.level == "weak" and list(r.device_ids) == ["d1"]


def test_B9_weak_with_second_attached_twin_is_ambiguous():
    """B9. Mutation: ignore other attached devices for weak -> weak -> red."""
    r = match(usb(mbr_signature=0), {"d1": usb(mbr_signature=0)}, attached=[usb(mbr_signature=0)])
    assert r.level == "ambiguous"


def test_B9_weak_with_unrelated_attached_device_stays_weak():
    """B9 counter-case: an attached device of another model does not make it ambiguous. Mutation: any attached -> ambiguous -> red."""
    r = match(usb(mbr_signature=0), {"d1": usb(mbr_signature=0)}, attached=[usb(model="Other", mbr_signature=0)])
    assert r.level == "weak"


def test_B9_two_stored_probable_candidates_ambiguous():
    """B9. Mutation: pick the first candidate -> probable -> red."""
    r = match(usb(mbr_signature=1859593249),
              {"d1": usb(mbr_signature=1859593249), "d2": usb(mbr_signature=1859593249)})
    assert r.level == "ambiguous"
    assert sorted(r.device_ids) == ["d1", "d2"]


def test_B9_only_model_and_bytes_ambiguous():
    """B9. Mutation: model+bytes alone treated as weak/probable -> red."""
    r = match(FP(model=M, bytes=B, serial_trust="absent"), {"d1": FP(model=M, bytes=B, serial_trust="absent")})
    assert r.level == "ambiguous"


def test_B9_nothing_matches_none():
    """B9 none. Mutation: always return the closest candidate -> red."""
    r = match(usb(mbr_signature=1), {"d1": hi(model="Else", bytes=1)})
    assert r.level == "none"
    assert list(r.device_ids) == []


def test_B9_no_candidates_none():
    """B9 none with empty store."""
    assert match(hi(), {}).level == "none"


# ---------------- B10 Windows join
def _disk(capture, number, text=None):
    from rslib.enum_windows import parse

    disks = parse(text if text is not None else fx_text(f"{capture}/win-disks.json"),
                  fx_text(f"{capture}/win-pnp-chain.json"))
    return next(d for d in disks if d.number == number)


def test_B10_uniqueid_eui_joins_smartctl_eui64_case_insensitive():
    """B10. Mutation: compare UniqueId case-sensitively (upper vs lower hex) -> not joined -> red."""
    from rslib.identity import windows_join
    from rslib.smart import normalise

    from conftest import fx_bytes

    d0 = _disk(BASELINE, 0)
    assert windows_join(d0, normalise(fx_bytes(f"{BASELINE}/smartctl-x-pd0.json"))) == "joined"
    d1 = _disk(BASELINE, 1)
    assert windows_join(d1, normalise(fx_bytes(f"{BASELINE}/smartctl-x-pd1.json"))) == "joined"


def test_B10_same_size_different_eui_is_join_conflict():
    """B10 (in-test mutation of ext_id; also stored as smartctl-x-pd0.eui-mismatch.derived.json). Mutation: join on size alone -> red."""
    from rslib.identity import windows_join
    from rslib.smart import normalise

    doc = fx_json(f"{BASELINE}/smartctl-x-pd0.json")
    doc["nvme_namespaces"][0]["eui64"]["ext_id"] += 1
    assert windows_join(_disk(BASELINE, 0), normalise(json.dumps(doc))) == "join_conflict"


def test_B10_different_size_not_joined():
    """B10: eui equal is not enough, bytes must match too. Mutation: eui-only join -> red."""
    from rslib.identity import windows_join
    from rslib.smart import normalise

    text = json.loads(fx_text(f"{BASELINE}/win-disks.json"))
    for x in text["disks"]:
        if x["Number"] == 0:
            x["Size"] = x["Size"] - 512
    d0 = _disk(BASELINE, 0, json.dumps(text))
    assert windows_join(d0, normalise(fx_text(f"{BASELINE}/smartctl-x-pd0.json"))) != "joined"


def test_B10_usb_uniqueid_not_applicable():
    """B10 counter-case: USBSTOR UniqueId is not an eui. Mutation: report join_conflict for USB -> red."""
    from rslib.identity import windows_join
    from rslib.smart import normalise

    d2 = _disk("windows/usb-stick", 2)
    assert windows_join(d2, normalise(fx_text("windows/usb-stick/smartctl-x-pd2.json"))) == "not_applicable"


def test_B10_cli_observation_records_join_conflict(cli):
    """B10 'observation records join_conflict' (derived pd0 eui mismatch). Mutation: silently pair records -> red."""
    from conftest import make_runner, new_session, obs_for

    sid = new_session(cli)
    res = cli("inventory", "--session", sid,
              runner=make_runner(BASELINE, {"pd0": f"{BASELINE}/smartctl-x-pd0.eui-mismatch.derived.json"}))
    assert res.code in (0, 5), res
    assert obs_for(res, "/dev/pd0")["join"] == "join_conflict"
    assert obs_for(res, "/dev/pd1")["join"] == "joined"
