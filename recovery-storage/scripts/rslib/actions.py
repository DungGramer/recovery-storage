"""Frozen catalog of actions a gate can cover. rs.py never runs these; the gate records, checks and asks a human.

Risk levels per spec Phase 0: R1 non-destructive but changes device/OS state, R2 writes the source, R3 hardware.
"""
from dataclasses import dataclass

ALL = "all"
SMART_CLASSES = ("hdd", "ssd-sata", "nvme", "external-*")
FLASH_CLASSES = ("usb-flash-or-card", "sd")


@dataclass(frozen=True)
class Action:
    kind: str
    risk: str
    writes_source: object  # True / False / None (n/a)
    classes: object         # ALL or tuple of class names ("external-*" covers every external-<inner>)
    requires: tuple
    stop_criteria: str
    note: str = ""

    def allows(self, cls):
        if self.classes == ALL:
            return True
        if not cls:
            return False
        return any(cls == c or (c.endswith("*") and cls.startswith(c[:-1])) for c in self.classes)


_STOP_READ = ("stop on clicking/beeping, overheating, disconnects, or read rate collapsing; "
              "re-collect SMART and compare before continuing")
_STOP_WRITE = "stop on any write error, disconnect, overheating or capacity mismatch; never repeat writes on a hang"

CATALOG = {a.kind: a for a in (
    Action("smart-selftest-short", "R1", False, SMART_CLASSES, (),
           "abort the self-test (smartctl -X) if the device hangs, disconnects or overheats; stop on mechanical noise"),
    Action("smart-selftest-long", "R1", False, SMART_CLASSES, (),
           "abort the self-test if the device hangs, disconnects or overheats; do not run on a failing disk before "
           "imaging"),
    Action("disk-offline", "R1", False, ALL, (), "stop if the wrong disk number appears; re-check the confirmed path"),
    Action("disk-readonly-attr", "R1", False, ALL, (),
           "stop if the attribute does not stick after replug; prefer a hardware write blocker for forensics"),
    Action("automount-disable", "R1", False, ALL, (), "restore automount after the session; stop if Windows offers "
                                                      "to format (cancel)"),
    Action("wsl-mount-bare", "R1", False, ALL, (), "unmount (wsl --unmount) on any I/O error; verify the disk inside "
                                                   "WSL by model/serial before reading"),
    Action("image-ddrescue", "R1", False, ALL, ("--dest-device",), _STOP_READ + "; always keep the mapfile"),
    Action("badblocks-readonly", "R1", False, ("hdd", "external-hdd"), (), _STOP_READ),
    Action("f3probe", "R2", True, FLASH_CLASSES, (), _STOP_WRITE + "; f3probe saves/restores blocks but a crash "
                                                                    "loses them: secure data first"),
    Action("f3probe-destructive", "R2", True, FLASH_CLASSES, (), _STOP_WRITE),
    Action("f3write-f3read", "R2", True, FLASH_CLASSES, (), _STOP_WRITE + "; f3write fills free space"),
    Action("h2testw", "R2", True, FLASH_CLASSES, (), _STOP_WRITE + "; select the whole free space"),
    Action("format", "R2", True, ALL, (), _STOP_WRITE + "; a successful format proves nothing about capacity"),
    Action("partition-write", "R2", True, ALL, (), _STOP_WRITE + "; write a partition table only after imaging"),
    Action("fs-repair-on-source", "R2", True, ALL, (), _STOP_WRITE + "; repair a copy of the image instead when "
                                                                     "data matters"),
    Action("clear-disk", "R2", True, ALL, (), _STOP_WRITE + "; irreversible: confirm serial and size twice"),
    Action("badblocks-write", "R2", True, ("hdd",), (), _STOP_WRITE + "; destroys all data; HDD only"),
    Action("firmware-update", "R2", True, ALL, ("--controller-id", "--tool-source"),
           "stop if the tool does not identify the exact controller/firmware; never flash firmware from an unverified "
           "source"),
    Action("mptool-reflash", "R2", True, ALL, ("--controller-id", "--tool-source"),
           "stop unless controller, flash id and MPTool version match exactly from two sources; never pick firmware "
           "by brand or capacity"),
    Action("hardware-lab", "R3", None, ALL, (), "hand over to a lab; no further power-on by the operator"),
)}

RISK_ORDER = {"R0": 0, "R1": 1, "R2": 2, "R3": 3}
