"""Parse the frozen PowerShell captures (rslib/ps/win-disks.ps1, win-pnp-chain.ps1) into OsDisk records.

Verified on real captures (fixtures/SOURCES.md): bytes come from Get-Disk.Size (Win32_DiskDrive.Size is
geometry-truncated); USB SerialNumber may be 1-char junk; USB UniqueId embeds the hostname; a USB instance-id
segment containing '&' is Windows-generated, not the device serial; MBR Signature 0 is no identity.
"""
import json
import re
from dataclasses import dataclass, field

# MSFT_Disk BusType enum (learn.microsoft.com MSFT_Disk); PS 5.1 Select-Object usually gives the name string
BUS_TYPES = {0: "unknown", 1: "scsi", 2: "atapi", 3: "ata", 4: "1394", 5: "ssa", 6: "fibre", 7: "usb", 8: "raid",
             9: "iscsi", 10: "sas", 11: "sata", 12: "sd", 13: "mmc", 14: "virtual", 15: "filebackedvirtual",
             16: "spaces", 17: "nvme", 18: "scm", 19: "ufs"}
DATA_PARTITION_TYPES = {"basic", "ifs", "fat32", "fat16", "fat12", "huge", "logical", "unknown"}
USB_NODE = re.compile(r"^USB\\VID_([0-9A-Fa-f]{4})&PID_([0-9A-Fa-f]{4})\\(.+)$")


@dataclass
class OsDisk:
    number: object = None
    os_path: object = None
    model: object = None
    bytes: object = None
    bus: object = None
    serial_raw: object = None
    unique_id: object = None
    mbr_signature: object = None
    ptuuid: object = None
    is_boot: object = None
    is_system: object = None
    is_readonly: object = None
    is_offline: object = None
    health_status: object = None
    operational_status: object = None
    partition_style: object = None
    fs_unrecognised: bool = False
    no_media: bool = False
    usb: object = None
    tran: object = None
    removable: object = None
    read_only: object = None
    hotplug: object = None
    partitions: list = field(default_factory=list)
    extra: dict = field(default_factory=dict)

    def to_dict(self):
        from dataclasses import asdict

        return asdict(self)


def bus_name(v):
    if isinstance(v, bool):
        return None
    if isinstance(v, int):
        return BUS_TYPES.get(v, "unknown")
    if isinstance(v, str) and v.strip():
        s = v.strip()
        return BUS_TYPES.get(int(s), "unknown") if s.isdigit() else s.lower()
    return None


def _as_list(v):
    if v is None:
        return []
    return v if isinstance(v, list) else [v]


def _str(v):
    return v.strip() if isinstance(v, str) and v.strip() else None


def parse_usb_chain(chain):
    for node in _as_list(chain):
        m = USB_NODE.match((node or {}).get("InstanceId") or "")
        if m:
            seg = m.group(3)
            return {"vid": m.group(1).upper(), "pid": m.group(2).upper(),
                    "usb_serial": None if "&" in seg else seg}
    return None


def _fs_unrecognised(parts, vols):
    have = {(v.get("DiskNumber"), v.get("PartitionNumber")): v for v in vols}
    for p in parts:
        if str(p.get("Type") or "").lower() not in DATA_PARTITION_TYPES:
            continue
        v = have.get((p.get("DiskNumber"), p.get("PartitionNumber")))
        if v is None or not _str(v.get("FileSystem")) or str(v.get("FileSystem")).upper() == "RAW":
            return True
    return False


def parse(win_disks_text, pnp_chain_text=None):
    doc = json.loads(win_disks_text)
    chains = {}
    if pnp_chain_text:
        for d in _as_list(json.loads(pnp_chain_text).get("disks")):
            chains[d.get("Index")] = d.get("Chain")
    parts = _as_list(doc.get("partitions"))
    vols = _as_list(doc.get("volumes"))
    out = []
    for d in _as_list(doc.get("disks")):
        n = d.get("Number")
        my_parts = [p for p in parts if p.get("DiskNumber") == n]
        style = _str(d.get("PartitionStyle"))
        sig = d.get("Signature")
        out.append(OsDisk(
            number=n, os_path=f"/dev/pd{n}" if isinstance(n, int) else None,
            model=_str(d.get("FriendlyName")), bytes=d.get("Size") if isinstance(d.get("Size"), int) else None,
            bus=bus_name(d.get("BusType")), serial_raw=d.get("SerialNumber"), unique_id=_str(d.get("UniqueId")),
            mbr_signature=sig if isinstance(sig, int) and sig != 0 and (style or "").upper() == "MBR" else None,
            ptuuid=_str(d.get("Guid")) if (style or "").upper() == "GPT" else None,
            is_boot=d.get("IsBoot"), is_system=d.get("IsSystem"), is_readonly=d.get("IsReadOnly"),
            read_only=d.get("IsReadOnly"), is_offline=d.get("IsOffline"),
            health_status=_str(d.get("HealthStatus")), operational_status=_str(d.get("OperationalStatus")),
            partition_style=style, fs_unrecognised=_fs_unrecognised(my_parts, vols),
            no_media="no media" in str(d.get("OperationalStatus") or "").lower(),
            usb=parse_usb_chain(chains.get(n)) if n in chains else None,
            partitions=[{"number": p.get("PartitionNumber"), "type": p.get("Type"), "mbr_type": p.get("MbrType"),
                         "size": p.get("Size"), "drive_letter": _str(p.get("DriveLetter"))} for p in my_parts],
            extra={"location": d.get("Location")}))
    return out
