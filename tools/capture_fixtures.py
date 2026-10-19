"""Dev tool: capture raw R0 outputs from real devices for the fixture corpus.

Runs the frozen PowerShell scripts exactly as the runner does (-EncodedCommand, UTF-16LE base64)
and read-only smartctl per disk. Output is RAW (real serials): it goes to a git-ignored folder.
Redact with tools/redact_fixtures.py before copying into recovery-storage/scripts/tests/fixtures/.

Usage: python -I tools/capture_fixtures.py <label> [--out DIR]
"""
import argparse
import base64
import json
import os
import pathlib
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
PS_DIR = REPO / "recovery-storage" / "scripts" / "rslib" / "ps"
DEFAULT_OUT = REPO / "plans" / "20261019-1726-recovery-storage-skill" / "research" / "samples" / "captures"


def run(argv, env=None, timeout=120):
    p = subprocess.run(argv, capture_output=True, timeout=timeout, env=env)
    return p.returncode, p.stdout.decode("utf-8", "replace"), p.stderr.decode("utf-8", "replace")


def run_ps(script_id, extra_env=None):
    text = (PS_DIR / f"{script_id}.ps1").read_text(encoding="utf-8")
    b64 = base64.b64encode(text.encode("utf-16-le")).decode("ascii")
    env = dict(os.environ, **(extra_env or {}))
    return run(["powershell.exe", "-NoProfile", "-NonInteractive", "-EncodedCommand", b64], env=env)


def save(out, name, code, stdout, stderr):
    (out / name).write_text(stdout, encoding="utf-8")
    meta = {"exit_code": code, "stderr": stderr[:2000]}
    (out / (name + ".meta.json")).write_text(json.dumps(meta, indent=1), encoding="utf-8")
    print(f"{name}: exit={code} bytes={len(stdout)}" + (f" stderr={stderr[:200]!r}" if stderr.strip() else ""))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("label")
    ap.add_argument("--out", type=pathlib.Path, default=DEFAULT_OUT)
    a = ap.parse_args()
    out = a.out / a.label
    out.mkdir(parents=True, exist_ok=True)

    save(out, "win-disks.json", *run_ps("win-disks"))
    save(out, "win-pnp-chain.json", *run_ps("win-pnp-chain"))
    save(out, "win-events.json", *run_ps("win-events", {
        "RS_LOOKBACK_HOURS": "168", "RS_MAX_EVENTS": "50", "RS_MESSAGE_CHARS": "300"}))
    save(out, "smartctl-scan-open.json", *run(["smartctl", "--scan-open", "-j"]))

    disks = json.loads((out / "win-disks.json").read_text(encoding="utf-8"))["disks"]
    for d in disks:
        n = d["Number"]
        code, so, se = run(["smartctl", "-j", "-x", "-n", "standby", f"/dev/pd{n}"])
        save(out, f"smartctl-x-pd{n}.json", code, so, se)
        try:
            has_smart = "smart_status" in json.loads(so)
        except ValueError:
            has_smart = False
        if not has_smart:
            save(out, f"smartctl-x-sat-pd{n}.json",
                 *run(["smartctl", "-j", "-x", "-n", "standby", "-d", "sat", f"/dev/pd{n}"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
