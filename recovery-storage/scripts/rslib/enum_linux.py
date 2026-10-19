"""Linux enumeration: lsblk -J -O -b (via runner) + sysfs file reads constrained to the sysfs root."""
import json
import pathlib
import re

from .enum_windows import OsDisk

DEV_NAME = re.compile(r"^[a-z][a-z0-9]{0,31}$")
SYS_ROOT = pathlib.Path("/sys")


def _int(v):
    if isinstance(v, bool):
        return None
    if isinstance(v, int):
        return v
    if isinstance(v, str) and v.strip().isdigit():
        return int(v.strip())
    return None


def _bool(v):
    if isinstance(v, bool):
        return v
    if isinstance(v, str) and v.strip() in ("0", "1"):
        return v.strip() == "1"
    if isinstance(v, int):
        return bool(v)
    return None


def _str(v):
    return v.strip() if isinstance(v, str) and v.strip() else None


def _fs_unrecognised(children):
    for c in children or []:
        if c.get("type") == "part" and not _str(c.get("fstype")):
            return True
    return False


def parse_lsblk(text):
    doc = json.loads(text)
    out = []
    for b in doc.get("blockdevices") or []:
        if b.get("type") not in ("disk", None):
            continue
        tran = _str(b.get("tran"))
        name = _str(b.get("name")) or ""
        bus = tran or ("mmc" if name.startswith("mmcblk") else ("nvme" if name.startswith("nvme") else None))
        out.append(OsDisk(
            os_path=_str(b.get("path")) or (f"/dev/{name}" if name else None), model=_str(b.get("model")),
            bytes=_int(b.get("size")), bus=bus, serial_raw=b.get("serial"), unique_id=_str(b.get("wwn")),
            ptuuid=_str(b.get("ptuuid")), partition_style=_str(b.get("pttype")), tran=tran,
            removable=_bool(b.get("rm")), read_only=_bool(b.get("ro")), is_readonly=_bool(b.get("ro")),
            hotplug=_bool(b.get("hotplug")), fs_unrecognised=_fs_unrecognised(b.get("children")),
            no_media=bool(_bool(b.get("rm")) and _int(b.get("size")) == 0),
            is_boot=_is_boot(b), is_system=_is_boot(b),
            extra={"vendor": _str(b.get("vendor")), "subsystems": _str(b.get("subsystems"))}))
    return out


def _mounts(b):
    pts = []
    for key in ("mountpoints", "mountpoint"):
        v = b.get(key)
        pts += [x for x in (v if isinstance(v, list) else [v]) if x]
    for c in b.get("children") or []:
        pts += _mounts(c)
    return pts


def _is_boot(b):
    mounts = set(_mounts(b))
    return bool(mounts & {"/", "/boot", "/boot/efi", "[SWAP]"})


def _safe_dir(sys_root, *parts):
    root = pathlib.Path(sys_root).resolve()
    p = root.joinpath(*parts).resolve()
    if p != root and root not in p.parents:
        raise ValueError(f"path escapes sysfs root: {p}")
    return p


def _read(p):
    try:
        return p.read_text(encoding="ascii", errors="replace").strip() or None
    except OSError:
        return None


def sysfs_usb(dev_name, sys_root=SYS_ROOT):
    """Walk /sys/block/<dev>/device upward to the USB device node (idVendor/idProduct)."""
    if not DEV_NAME.match(dev_name or ""):
        return None
    start = _safe_dir(sys_root, "block", dev_name, "device")
    if not start.is_dir():
        return None
    root = pathlib.Path(sys_root).resolve()
    node = start
    for _ in range(12):
        vid, pid = node / "idVendor", node / "idProduct"
        if vid.is_file() and pid.is_file():
            return {"vid": (_read(vid) or "").upper(), "pid": (_read(pid) or "").upper(),
                    "usb_serial": _read(node / "serial")}
        if node == root or root not in node.parents:
            break
        node = node.parent
    return None


def sysfs_mmc(dev_name, sys_root=SYS_ROOT):
    """Native mmc readers only expose CID fields here; USB card readers do not (researcher-02 §4)."""
    if not DEV_NAME.match(dev_name or ""):
        return None
    d = _safe_dir(sys_root, "block", dev_name, "device")
    if not d.is_dir() or not (d / "cid").is_file():
        return None
    return {k: _read(d / k) for k in ("cid", "csd", "manfid", "oemid", "name", "serial", "date")}
