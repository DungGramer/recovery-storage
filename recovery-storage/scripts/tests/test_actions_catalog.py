"""Phase 04 action catalog (frozen data). Spec: phase-04 Requirements 'Action catalog' table + D1."""
import pytest

R1 = ["smart-selftest-short", "smart-selftest-long", "disk-offline", "disk-readonly-attr", "automount-disable",
      "wsl-mount-bare", "image-ddrescue", "badblocks-readonly"]
R2 = ["f3probe", "f3probe-destructive", "f3write-f3read", "h2testw", "format", "partition-write",
      "fs-repair-on-source", "clear-disk", "badblocks-write", "firmware-update", "mptool-reflash"]
R3 = ["hardware-lab"]
ALL_CLASSES = ["hdd", "ssd-sata", "nvme", "external-hdd", "external-ssd", "usb-flash-or-card", "sd"]


def cat():
    from rslib.actions import CATALOG

    return CATALOG


def test_catalog_kinds_exact():
    """Catalog table. Mutation: add/remove a kind (unknown kinds must be refused, so the set is frozen) -> red."""
    assert set(cat()) == set(R1 + R2 + R3)


@pytest.mark.parametrize("kind,risk", [(k, "R1") for k in R1] + [(k, "R2") for k in R2] + [(k, "R3") for k in R3])
def test_catalog_risk_levels(kind, risk):
    """Catalog risk column. Mutation: image-ddrescue as R2 (or f3probe as R1) -> red."""
    assert cat()[kind].risk == risk


@pytest.mark.parametrize("kind", R1)
def test_catalog_r1_do_not_write_source(kind):
    """Catalog 'writes source: no' for R1. Mutation: flag a read action as writing -> data-not-secured on imaging -> red."""
    assert cat()[kind].writes_source is False


@pytest.mark.parametrize("kind", R2)
def test_catalog_r2_write_source(kind):
    """Catalog 'writes source: yes' for R2. Mutation: f3write-f3read marked non-writing -> red."""
    assert cat()[kind].writes_source is True


def test_catalog_hardware_lab_writes_source_na():
    """Catalog hardware-lab 'n/a'. Mutation: True/False instead of n/a -> red."""
    assert cat()["hardware-lab"].writes_source is None


@pytest.mark.parametrize("kind,allowed", [
    ("smart-selftest-short", {"hdd", "ssd-sata", "nvme", "external-hdd", "external-ssd"}),
    ("smart-selftest-long", {"hdd", "ssd-sata", "nvme", "external-hdd", "external-ssd"}),
    ("badblocks-readonly", {"hdd", "external-hdd"}),
    ("badblocks-write", {"hdd"}),
    ("f3probe", {"usb-flash-or-card", "sd"}),
    ("f3probe-destructive", {"usb-flash-or-card", "sd"}),
    ("f3write-f3read", {"usb-flash-or-card", "sd"}),
    ("h2testw", {"usb-flash-or-card", "sd"}),
    ("format", set(ALL_CLASSES)),
    ("image-ddrescue", set(ALL_CLASSES)),
    ("disk-offline", set(ALL_CLASSES)),
    ("mptool-reflash", set(ALL_CLASSES)),
    ("hardware-lab", set(ALL_CLASSES)),
])
def test_catalog_allowed_classes(kind, allowed):
    """Catalog classes column. Mutation: badblocks-write allowed on external-hdd, or f3 on hdd -> red."""
    a = cat()[kind]
    assert {c for c in ALL_CLASSES if a.allows(c)} == allowed


@pytest.mark.parametrize("kind,req", [
    ("image-ddrescue", {"--dest-device"}),
    ("firmware-update", {"--controller-id", "--tool-source"}),
    ("mptool-reflash", {"--controller-id", "--tool-source"}),
    ("format", set()), ("f3probe", set()), ("smart-selftest-short", set()),
])
def test_catalog_requires(kind, req):
    """Catalog requires column. Mutation: drop --tool-source provenance requirement -> red."""
    assert set(cat()[kind].requires) == req


def test_catalog_every_kind_has_stop_criteria():
    """Catalog field stop_criteria (shown in the confirmation block, D11). Mutation: empty text -> red."""
    for k, a in cat().items():
        assert (a.stop_criteria or "").strip(), k
