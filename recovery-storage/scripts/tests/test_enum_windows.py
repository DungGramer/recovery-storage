"""Phase 02 Windows enumeration parsers (B11, B12, B12b, B12c, B13) + win-events parser (B21).
Spec: phase-02 Key Insights (verified Windows facts), Requirements, B11-B13, B21. Inputs: real captures."""
import json

import pytest

from conftest import BASELINE, USB_SD, USB_STICK, fx_json, fx_text


def disks(capture, win_disks_text=None):
    from rslib.enum_windows import parse

    return {d.number: d for d in parse(win_disks_text or fx_text(f"{capture}/win-disks.json"),
                                       fx_text(f"{capture}/win-pnp-chain.json"))}


def test_B11_bytes_from_get_disk_not_win32_diskdrive():
    """B11: Get-Disk.Size 1000204886016 vs Win32_DiskDrive.Size 1000202273280 in the same capture.
    Mutation: take wmi Size -> red."""
    wmi = {w["Index"]: w["Size"] for w in fx_json(f"{BASELINE}/win-disks.json")["wmi"]}
    d = disks(BASELINE)
    assert wmi[0] != 1000204886016  # the fixture really differs
    assert d[0].bytes == 1000204886016
    assert d[1].bytes == 2000398934016


def test_B11_fingerprint_bytes_from_get_disk():
    """B11 'never used for identity'. Mutation: fingerprint pulls wmi size -> red."""
    from rslib.identity import fingerprint

    assert fingerprint(os_disk=disks(BASELINE)[0]).bytes == 1000204886016


def test_B12_baseline_two_nvme_disks_boot_system_flags():
    """B12. Mutation: read IsBoot from the partition table only, or bus 'NVMe' kept as-is -> red."""
    d = disks(BASELINE)
    assert sorted(d) == [0, 1]
    assert d[0].model == "Samsung SSD 990 PRO 1TB" and d[0].partition_style == "GPT"
    assert d[0].is_boot is True and d[0].is_system is True
    assert d[1].model == "Samsung SSD 980 PRO 2TB" and d[1].partition_style == "MBR"
    assert d[1].is_boot is False and d[1].is_system is False
    assert d[0].bus == "nvme" and d[1].bus == "nvme"
    assert d[0].health_status == "Healthy"
    assert d[0].os_path == "/dev/pd0" and d[1].os_path == "/dev/pd1"


@pytest.mark.parametrize("bus_value,expected", [(17, "nvme"), (7, "usb"), ("NVMe", "nvme"), ("USB", "usb")])
def test_B12_bus_type_numeric_and_string(bus_value, expected):
    """B12 unit case (in-test single-field mutation of BusType). Mutation: accept only strings -> red."""
    doc = fx_json(f"{BASELINE}/win-disks.json")
    for x in doc["disks"]:
        if x["Number"] == 1:
            x["BusType"] = bus_value
    assert disks(BASELINE, json.dumps(doc))[1].bus == expected


def test_B12b_usb_stick_disk2():
    """B12b. Mutation: use Get-Disk "\\t" as serial, or treat USBSTOR UniqueId as identity -> red."""
    from rslib.identity import fingerprint

    d2 = disks(USB_STICK)[2]
    assert d2.model == "General UDisk"
    assert d2.bus == "usb"
    assert d2.bytes == 8054112256
    assert d2.mbr_signature == 1859593249
    assert d2.fs_unrecognised is True
    fp = fingerprint(os_disk=d2)
    assert fp.serial_trust == "absent"
    assert fp.serial_norm is None
    assert fp.mbr_signature == 1859593249
    uid = fx_json(f"{USB_STICK}/win-disks.json")["disks"][2]["UniqueId"]
    assert fp.os_ids.get("unique_id") == uid
    strong = [fp.serial_norm, fp.eui64, fp.wwn, fp.ptuuid]
    assert uid not in strong


def test_B12c_usb_sd_disk3():
    """B12c. Mutation: count signature 0 as an id, or flag FAT32 as unrecognised -> red."""
    from rslib.identity import fingerprint

    d3 = disks(USB_SD)[3]
    assert d3.model == "Generic STORAGE DEVICE"
    assert d3.bytes == 4026531840
    assert d3.fs_unrecognised is False
    fp = fingerprint(os_disk=d3)
    assert fp.serial_trust == "absent"
    assert fp.mbr_signature is None


def test_B12_nvme_disks_have_recognised_fs():
    """Requirements 'partition with no volume -> fs_unrecognised' counter-case. Mutation: always True -> red."""
    d = disks(USB_STICK)
    assert d[0].fs_unrecognised is False
    assert d[1].fs_unrecognised is False


def test_B12_nvme_os_serial_is_eui_not_serial():
    """Key insight: Windows NVMe SerialNumber is the EUI-64. Mutation: fingerprint serial from Get-Disk -> red."""
    from rslib.identity import fingerprint

    fp = fingerprint(os_disk=disks(BASELINE)[0])
    assert fp.serial_norm is None
    assert (fp.eui64 or "").lower() == "0025380e45914fa6"


def test_B13_pnp_chain_usb_stick():
    """B13. Mutation: take instance segment `5&cc3f949&0&8` as usb_serial -> red."""
    u = disks(USB_STICK)[2].usb
    assert u["vid"].upper() == "ABCD" and u["pid"].upper() == "1234"
    assert u["usb_serial"] is None


def test_B13_pnp_chain_sd_reader():
    """B13. Mutation: stop at the USBSTOR node (no VID) -> red."""
    u = disks(USB_SD)[3].usb
    assert u["vid"].upper() == "05E3" and u["pid"].upper() == "0751"
    assert u["usb_serial"] is None


def test_B13_nvme_chain_has_no_usb_node():
    """B13. Mutation: guess usb from PCI VEN/DEV -> red."""
    d = disks(USB_SD)
    assert d[0].usb is None and d[1].usb is None


def _events(doc):
    from rslib.events import parse_windows

    return parse_windows(json.dumps(doc))


def test_B21_ntfs55_tagged_fs_corruption():
    """B21 (derived capture win-events.ntfs55). Mutation: no tag, or tag by id only -> red."""
    r = _events(fx_json(f"{BASELINE}/win-events.ntfs55.derived.json"))
    assert r.status == "ok"
    ntfs = [e for e in r.items if e["provider"] == "Ntfs" and e["id"] == 55]
    assert len(ntfs) == 1 and ntfs[0]["tag"] == "fs_corruption"


def test_B21_same_id_other_provider_untagged():
    """B21 'only Ntfs 55 gets a semantic tag' (in-test provider mutation). Mutation: tag any id 55 -> red."""
    doc = fx_json(f"{BASELINE}/win-events.ntfs55.derived.json")
    doc["events"][0]["provider"] = "disk"
    r = _events(doc)
    assert r.items and r.items[0]["tag"] in (None, "")


def test_B21_real_capture_empty_is_ok_without_warning():
    """B21: unregistered providers absent from `errors` cause no warning. Mutation: empty -> 'partial' -> red."""
    for cap in (BASELINE, USB_STICK, USB_SD):
        r = _events(fx_json(f"{cap}/win-events.json"))
        assert r.status == "ok"
        assert r.items == []


def test_B21_errors_entry_is_partial_with_provider_and_id():
    """B21 (in-test mutation: one errors entry; error id text synthetic). Mutation: ignore errors -> 'ok' -> red."""
    doc = fx_json(f"{BASELINE}/win-events.json")
    doc["errors"] = [{"provider": "disk", "error": "SYNTHETIC-ERROR-ID"}]
    r = _events(doc)
    assert r.status.startswith("partial")
    assert "disk: SYNTHETIC-ERROR-ID" in r.status
