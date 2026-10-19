"""Dev tool: build the committed fixture corpus from raw (git-ignored) captures, with identifiers redacted.

Every serial / WWN / EUI-64 / UUID / GUID / hostname found in the raw files is replaced by a deterministic
placeholder of the same length and character class (hex stays hex), consistent across all files, so joins
(Windows UniqueId eui.<hex> <-> smartctl nvme eui64 oui+ext_id) still hold after redaction.
NVMe eui64 keeps its OUI (public vendor id) and redacts the 10-hex extension.

Usage: python -I tools/redact_fixtures.py            (writes recovery-storage/scripts/tests/fixtures/)
       python -I tools/redact_fixtures.py --check    (exit 1 if any original identifier is found under recovery-storage/)
"""
import argparse
import hashlib
import json
import os
import pathlib
import re
import shutil
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
SAMPLES = REPO / "plans" / "20261019-1726-recovery-storage-skill" / "research" / "samples"
FIXTURES = REPO / "recovery-storage" / "scripts" / "tests" / "fixtures"
SALT = b"recovery-storage-fixtures"

# raw source -> fixture path (relative to FIXTURES)
SMARTCTL_FILES = {
    "smartctl-x-nvme-sda.json": "smartctl/nvme-990pro-x.json",
    "smartctl-x-nvme-sdb.json": "smartctl/nvme-980pro-x.json",
    "smartctl-i-standby-nvme.json": "smartctl/nvme-990pro-i-standby.json",
    "smartctl-x-missing.json": "smartctl/missing-device.json",
    "scrutiny/smart-ata.json": "smartctl/scrutiny-ata-hdd-healthy.json",
    "scrutiny/smart-ata-full.json": "smartctl/scrutiny-ata-ssd-healthy.json",
    "scrutiny/smart-ata-failed-scrutiny.json": "smartctl/scrutiny-ata-ssd-crc199.json",
    "scrutiny/smart-fail.json": "smartctl/scrutiny-open-failed.json",
    "scrutiny/smart-fail2.json": "smartctl/scrutiny-usbjmicron-hdd-failing.json",
    "scrutiny/smart-nvme-failed.json": "smartctl/scrutiny-nvme-media-errors.json",
    "scrutiny/smart-sat.json": "smartctl/scrutiny-sat-partial.json",
    "scrutiny/smart-scsi.json": "smartctl/scrutiny-scsi-no-smartctl-block.json",
}
CAPTURE_DIRS = {
    "captures/baseline-nvme-only": "windows/baseline-nvme-only",
    "captures/usb-stick": "windows/usb-stick",
    "captures/usb-sd": "windows/usb-sd",
    "captures/sd-reader-empty": "windows/sd-reader-empty",
    "captures/wsl-ubuntu2204": "linux/wsl-ubuntu2204",
}
COPY_AS_IS = {"scrutiny/LICENSE-scrutiny": "LICENSE-scrutiny"}

HEX = "0123456789abcdef"
ALNUM = "ABCDEFGHJKLMNPQRSTUVWXYZ0123456789"
GUID_RE = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")


def _digest(value):
    return hashlib.sha256(SALT + value.encode("utf-8")).digest()


def placeholder(value):
    """Same length, same character class per position, deterministic."""
    d = _digest(value)
    out = []
    for i, ch in enumerate(value):
        b = d[i % len(d)] ^ (i * 31 & 0xFF)
        if ch in "0123456789abcdef" and value.lower() == value and re.fullmatch(r"[0-9a-f_.\-x]+", value):
            out.append(HEX[b % 16])
        elif ch in "0123456789ABCDEF" and re.fullmatch(r"[0-9A-F_.\-x]+", value):
            out.append(HEX[b % 16].upper())
        elif ch.isalnum():
            c = ALNUM[b % len(ALNUM)]
            out.append(c.lower() if ch.islower() else c)
        else:
            out.append(ch)
    return "".join(out)


class Redactor:
    def __init__(self):
        self.map = {}

    def add(self, value, replacement=None):
        if not isinstance(value, str):
            return
        v = value.strip().rstrip(".")
        if len(v) < 4 or set(v) <= set("0 \t_-."):
            return
        if v not in self.map:
            self.map[v] = replacement or placeholder(v)

    def add_eui(self, oui, ext_id):
        old = f"{oui:06x}{ext_id:010x}"
        new_ext = placeholder(f"{ext_id:010x}")
        new = f"{oui:06x}{new_ext}"
        for o, n in ((old, new), (old.upper(), new.upper())):
            self.map[o] = n
            self.map["_".join(o[i:i + 4] for i in range(0, 16, 4))] = "_".join(n[i:i + 4] for i in range(0, 16, 4))
        return int(new_ext, 16)

    def apply(self, text):
        for old in sorted(self.map, key=len, reverse=True):
            text = text.replace(old, self.map[old])
        return text


def collect_smartctl(r, doc):
    r.add(doc.get("serial_number"))
    wwn = doc.get("wwn")
    if isinstance(wwn, dict) and "id" in wwn:
        wwn["id"] = int(placeholder(f"{wwn['id']:09x}"), 16)
    for ns in doc.get("nvme_namespaces", []) or []:
        e = ns.get("eui64")
        if isinstance(e, dict) and "ext_id" in e:
            e["ext_id"] = r.add_eui(e["oui"], e["ext_id"])


def collect_windows(r, doc):
    for d in doc.get("disks", []) + doc.get("physical", []):
        if not isinstance(d, dict):
            continue
        r.add(d.get("SerialNumber"))
        r.add(d.get("Guid"))
        uid = d.get("UniqueId") or ""
        if ":" in uid and not uid.startswith("eui."):
            r.add(uid.rsplit(":", 1)[1])  # USB UniqueId ends with ":<HOSTNAME>"


def collect_linux_lsblk(r, doc):
    def walk(devs):
        for b in devs:
            for k in ("serial", "ptuuid", "uuid", "partuuid", "wwn"):
                r.add(b.get(k))
            walk(b.get("children", []))
    walk(doc.get("blockdevices", []))


def collect():
    r = Redactor()
    host = os.environ.get("COMPUTERNAME")
    if host:
        r.add(host)
    loaded = {}
    for src, dst in SMARTCTL_FILES.items():
        doc = json.loads((SAMPLES / src).read_text(encoding="utf-8"))
        collect_smartctl(r, doc)
        loaded[dst] = doc
    for src, dst in CAPTURE_DIRS.items():
        for f in sorted((SAMPLES / src).iterdir()):
            text = f.read_text(encoding="utf-8")
            if f.suffix == ".json" and not f.name.endswith(".meta.json"):
                doc = json.loads(text)
                if f.name.startswith("smartctl-x"):
                    collect_smartctl(r, doc)
                elif f.name == "win-disks.json":
                    collect_windows(r, doc)
                elif f.name.startswith("lsblk"):
                    collect_linux_lsblk(r, doc)
                loaded[f"{dst}/{f.name}"] = doc
            else:
                loaded[f"{dst}/{f.name}"] = text
    for text_or_doc in list(loaded.values()):
        if isinstance(text_or_doc, str):
            for g in GUID_RE.findall(text_or_doc):
                r.add(g)
            for m in re.findall(r"^ID_(?:SERIAL|SERIAL_SHORT|WWN|WWN_WITH_EXTENSION|WWN_VENDOR_EXTENSION)=(.+)$", text_or_doc, re.M):
                r.add(m)
    return r, loaded


def write(r, loaded):
    # Overwrite only the files generated from raw captures; derived (*.derived.*), ingest/ and scenario
    # fixtures are hand-made from real files and must survive a rebuild.
    for dst, content in loaded.items():
        text = content if isinstance(content, str) else json.dumps(content, indent=1, ensure_ascii=False)
        out = FIXTURES / dst
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(r.apply(text) + ("" if text.endswith("\n") else "\n"), encoding="utf-8", newline="\n")
    for src, dst in COPY_AS_IS.items():
        shutil.copyfile(SAMPLES / src, FIXTURES / dst)


def check(r):
    hits = []
    for f in (REPO / "recovery-storage").rglob("*"):
        if f.is_file() and f.suffix in (".json", ".txt", ".md", ".py", ".ps1"):
            text = f.read_text(encoding="utf-8", errors="replace")
            hits += [(str(f.relative_to(REPO)), old) for old in r.map if old in text]
    for f, old in hits:
        print(f"LEAK {f}: {old[:4]}...")
    return 1 if hits else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    r, loaded = collect()
    if a.check:
        return check(r)
    write(r, loaded)
    print(f"redacted identifiers: {len(r.map)}; fixtures under {FIXTURES.relative_to(REPO)}")
    return check(r)


if __name__ == "__main__":
    sys.exit(main())
