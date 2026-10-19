"""Phase 02 B1 - smartctl exit-status bitmask and collection status. Spec: phase-02 Key Insights (bits 0-2 / 3-4 / 5-7),
Requirements "Collection status (frozen enum)", B1."""
import pytest

from conftest import smart

FLAG = {8: "smart_failing", 16: "prefail_threshold_now", 32: "attribute_failed_in_past",
        64: "error_log_has_records", 128: "selftest_log_has_errors"}
STATUS_ENUM = {"ok", "standby", "not_exposed", "unsupported_bridge", "needs_elevation", "collection_failed",
               "malformed", "unknown", "tool_missing", "timeout"}


@pytest.mark.parametrize("code,expected", [
    (0, set()),
    (216, {"smart_failing", "prefail_threshold_now", "error_log_has_records", "selftest_log_has_errors"}),
    (32, {"attribute_failed_in_past"}),
    (8, {"smart_failing"}), (16, {"prefail_threshold_now"}), (64, {"error_log_has_records"}),
    (128, {"selftest_log_has_errors"}),
    (7, set()),  # bits 0-2 are collection problems, never health flags
    (255, set(FLAG.values())),
])
def test_B1_exit_flags(code, expected):
    """B1. Mutation: shift bit mapping by one (e.g. 32 -> error_log) or report bits 0-2 as flags -> red."""
    from rslib.smart import exit_flags

    assert set(exit_flags(code)) == expected


@pytest.mark.parametrize("code,messages,status", [
    (0, [], "ok"),
    (216, [], "ok"),
    (32, [], "ok"),
    (4, [], "collection_failed"),
    (1, ["/dev/sdz: Unable to detect device type"], "collection_failed"),
    (2, ["Smartctl open device: /dev/sda failed: \\\\.\\PhysicalDrive0: Open failed, Error=5"], "needs_elevation"),
    (1, ["/dev/pd2: Unknown USB bridge [0xabcd:0x1234]"], "unsupported_bridge"),
    # pattern text only (phase 02 Requirements lists these substrings; no real sample captured)
    (1, ["Unsupported USB bridge"], "unsupported_bridge"),
    (1, ["type is ambiguous"], "unsupported_bridge"),
])
def test_B1_classify_collection(code, messages, status):
    """B1 + Requirements message patterns. Mutation: Error=5 -> collection_failed, or exit 4 -> ok -> red."""
    from rslib.smart import classify_collection

    assert classify_collection(code, messages) == status


@pytest.mark.parametrize("rel,status,flags,msg", [
    ("smartctl/scrutiny-usbjmicron-hdd-failing.json", "ok",
     {"smart_failing", "prefail_threshold_now", "error_log_has_records", "selftest_log_has_errors"}, None),
    ("smartctl/scrutiny-open-failed.json", "needs_elevation", set(), "Open failed, Error=5"),
    ("smartctl/missing-device.json", "collection_failed", set(), "Unable to detect device type"),
    ("windows/usb-stick/smartctl-x-pd2.json", "unsupported_bridge", set(), "Unknown USB bridge [0xabcd:0x1234]"),
    ("windows/usb-stick/smartctl-x-sat-pd2.json", "needs_elevation", set(), "Open failed, Error=5"),
    ("smartctl/nvme-990pro-x.json", "ok", set(), None),
])
def test_B1_fixture_exit_status_to_collection(rel, status, flags, msg):
    """B1 on the named fixtures. Mutation: drop the message text, or call exit 216 a collection failure -> red."""
    rec = smart(rel)
    assert rec.collection_status == status
    assert set(rec.flags) == flags
    if msg:
        assert msg in (rec.message or "")
    assert rec.collection_status in STATUS_ENUM
