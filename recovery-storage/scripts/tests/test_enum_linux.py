"""Phase 02 Linux enumeration (B14) + sysfs constraints. Spec: phase-02 Requirements "Linux enumeration",
Implementation step 4 ('missing chain -> usb null' / 'no mmc dir -> sd_native false'), Security 'sysfs reads constrained'."""
import json

from conftest import fx_json, fx_text

LSBLK = "linux/wsl-ubuntu2204/lsblk-JOb.json"


def parse(text):
    from rslib.enum_linux import parse_lsblk

    return {d.os_path: d for d in parse_lsblk(text)}


def test_B14_lsblk_capture_mapped():
    """B14. Mutation: map `rm` to read_only (swap) or drop `ro` -> red."""
    d = parse(fx_text(LSBLK))
    assert set(d) == {"/dev/sda", "/dev/sdb", "/dev/sdc"}
    sda = d["/dev/sda"]
    assert sda.bytes == 407298048
    assert sda.read_only is True
    assert sda.removable is False
    assert sda.hotplug is False
    assert sda.tran is None
    assert sda.ptuuid is None
    assert sda.model.strip() == "Virtual Disk"
    assert d["/dev/sdb"].read_only is False
    assert d["/dev/sdc"].bytes == 1099511627776


def test_B14_sizes_given_as_strings_become_integers():
    """B14 (in-test mutation: size as string, as older util-linux emits). Mutation: keep the string -> red."""
    doc = fx_json(LSBLK)
    for bd in doc["blockdevices"]:
        bd["size"] = str(bd["size"])
    d = parse(json.dumps(doc))
    assert d["/dev/sda"].bytes == 407298048 and isinstance(d["/dev/sda"].bytes, int)


def test_B14_ptuuid_and_tran_mapped_when_present():
    """B14 'tran ... ptuuid mapped' (in-test mutation of two fields on one disk). Mutation: ptuuid dropped -> red."""
    doc = fx_json(LSBLK)
    doc["blockdevices"][0]["ptuuid"] = "0a1b2c3d"
    doc["blockdevices"][0]["tran"] = "usb"
    sda = parse(json.dumps(doc))["/dev/sda"]
    assert sda.ptuuid == "0a1b2c3d"
    assert sda.tran == "usb"


def test_B14_missing_sysfs_usb_chain_is_null(tmp_path):
    """B14 'missing sysfs USB chain -> usb = null'. Mutation: return {} or guess from tran -> red."""
    from rslib.enum_linux import sysfs_usb

    (tmp_path / "block" / "sda" / "device").mkdir(parents=True)
    assert sysfs_usb("sda", sys_root=tmp_path) is None
    assert sysfs_usb("sdz", sys_root=tmp_path) is None


def test_B14_no_mmc_dir_means_not_native_sd(tmp_path):
    """Step 4 'no mmc dir -> sd_native false'. Mutation: return an empty dict (truthy shape) -> red."""
    from rslib.enum_linux import sysfs_mmc

    (tmp_path / "block").mkdir()
    assert sysfs_mmc("mmcblk0", sys_root=tmp_path) is None


def test_sysfs_paths_cannot_escape_root(tmp_path):
    """Security: device names cannot traverse out of the sysfs root. Mutation: join name unchecked -> reads outside -> red."""
    from rslib.enum_linux import sysfs_usb

    root = tmp_path / "sys"
    (root / "block").mkdir(parents=True)
    outside = tmp_path / "evil" / "device"  # = <root>/block/../../evil/device
    outside.mkdir(parents=True)
    (outside / "idVendor").write_text("abcd\n", encoding="ascii")
    (outside / "idProduct").write_text("1234\n", encoding="ascii")
    try:
        r = sysfs_usb("../../evil", sys_root=root)
    except ValueError:
        r = None
    assert r is None
