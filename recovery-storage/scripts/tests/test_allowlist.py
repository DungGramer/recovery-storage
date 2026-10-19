"""Phase 01 - allow-list validator (A12, A13, A13b). Spec: phase-01 Architecture "Allow-list v1" + A12/A13/A13b."""
import hashlib

import pytest

from conftest import PS_DIR, ps_args

ACCEPTED = [  # A12 verbatim, then the rest of allow-list v1
    ("smartctl", ["-j", "-x", "/dev/pd1"]),
    ("smartctl", ["-j", "-i", "-n", "standby", "/dev/sda"]),
    ("smartctl", ["--scan-open", "-j"]),
    ("smartctl", ["-j", "-x", "-d", "sat", "/dev/sdb"]),
    ("smartctl", ["-j", "-x", "/dev/nvme0n1"]),
    ("lsblk", ["-J", "-O", "-b"]),
]
ACCEPTED_V1 = [
    ("smartctl", ["-j", "-x", "-n", "standby", "-d", "sat", "/dev/pd2"]),
    ("smartctl", ["-j", "-a", "-d", "usbjmicron", "/dev/sdc"]),
    ("smartctl", ["-j", "-H", "-A", "-c", "-l", "selftest", "/dev/mmcblk0"]),
    ("smartctl", ["-V"]),
    ("lsblk", ["-J", "-O", "-b", "/dev/sda"]),
    ("udevadm", ["info", "--query=property", "--name=/dev/sda"]),
    ("blockdev", ["--getro", "/dev/sda"]),
    ("blockdev", ["--getsize64", "/dev/sda"]),
    ("lsusb", []),
    ("journalctl", ["-k", "-o", "json", "--since", "2026-10-19T00:00:00Z", "--no-pager"]),
    ("dmesg", ["--time-format", "iso"]),
]


@pytest.mark.parametrize("tool,args", ACCEPTED, ids=lambda x: " ".join(x) if isinstance(x, list) else x)
def test_A12_accepted_argv(tool, args):
    """A12. Mutation: validator too strict (e.g. rejects -n standby or --scan-open) -> red."""
    from rslib.allowlist import check

    check(tool, list(args))


@pytest.mark.parametrize("tool,args", ACCEPTED_V1, ids=lambda x: " ".join(x) if isinstance(x, list) else x)
def test_allowlist_v1_other_read_only_forms_accepted(tool, args):
    """Allow-list v1 table (phase 01 Architecture). Mutation: drop a listed read-only tool form -> red."""
    from rslib.allowlist import check

    check(tool, list(args))


def _bounds():
    from rslib.allowlist import PS_ENV_BOUNDS

    return PS_ENV_BOUNDS


def _good_events_env():
    return {k: str(lo) for k, (lo, hi) in _bounds().items()}


def test_allowlist_powershell_shipped_scripts_accepted():
    """Allow-list v1 PowerShell rule: shipped scripts, win-events with in-bound env. Mutation: reject valid b64 -> red."""
    from rslib.allowlist import check

    check("powershell", ps_args("win-disks"))
    check("powershell", ps_args("win-pnp-chain"))
    check("powershell", ps_args("win-events"), env=_good_events_env())
    hi_env = {k: str(hi) for k, (lo, hi) in _bounds().items()}
    check("powershell", ps_args("win-events"), env=hi_env)


def test_A13_ps_env_bounds_cover_the_three_parameters():
    """A13 'parameters in allowlist.py'. Mutation: missing one bound -> red."""
    b = _bounds()
    assert set(b) == {"RS_LOOKBACK_HOURS", "RS_MAX_EVENTS", "RS_MESSAGE_CHARS"}
    for lo, hi in b.values():
        assert 1 <= lo <= hi


def _one_byte_changed_script():
    text = (PS_DIR / "win-disks.ps1").read_text(encoding="utf-8")
    i = text.index("R0")
    return text[:i] + "S" + text[i + 1:]


def forbidden_cases():
    """(id, tool, args, env) for A13. Built lazily (bounds come from rslib)."""
    def ev(**over):
        env = _good_events_env()
        env.update(over)
        return env

    lo_hi = _bounds()
    cases = [
        ("smartctl -t short", "smartctl", ["-t", "short", "/dev/sda"], None),
        ("smartctl -s on", "smartctl", ["-s", "on", "/dev/sda"], None),
        ("smartctl -o on", "smartctl", ["-o", "on", "/dev/sda"], None),
        ("smartctl -S on", "smartctl", ["-S", "on", "/dev/sda"], None),
        ("smartctl -C", "smartctl", ["-j", "-C", "-x", "/dev/sda"], None),
        ("smartctl -X", "smartctl", ["-X", "/dev/sda"], None),
        ("smartctl -d sat,x", "smartctl", ["-j", "-x", "-d", "sat,x", "/dev/sda"], None),
        ("smartctl -T permissive", "smartctl", ["-j", "-x", "-T", "permissive", "/dev/sda"], None),
        ("smartctl -g all", "smartctl", ["-j", "-g", "all", "/dev/sda"], None),
        ("smartctl -r ataioctl", "smartctl", ["-j", "-r", "ataioctl", "-x", "/dev/sda"], None),
        ("smartctl two devices", "smartctl", ["-j", "-x", "/dev/sda", "/dev/sdb"], None),
        ("smartctl git-bash rewritten path", "smartctl", ["-j", "-x", "C:/Program Files/Git/dev/sda"], None),
        ("smartctl device with ;rm", "smartctl", ["-j", "-x", "/dev/sda;rm"], None),
        ("smartctl no device", "smartctl", ["-j", "-x"], None),
        ("tool not in table", "diskpart", ["/s", "script.txt"], None),
        ("powershell one byte changed", "powershell", ps_args("win-disks", _one_byte_changed_script()), None),
        ("powershell arbitrary command", "powershell", ["-NoProfile", "-NonInteractive", "-Command", "Get-Disk"], None),
        ("win-events lookback abc", "powershell", ps_args("win-events"), ev(RS_LOOKBACK_HOURS="abc")),
        ("win-events lookback -1", "powershell", ps_args("win-events"), ev(RS_LOOKBACK_HOURS="-1")),
        ("win-events lookback 0", "powershell", ps_args("win-events"), ev(RS_LOOKBACK_HOURS="0")),
        ("win-events lookback above bound", "powershell", ps_args("win-events"),
         ev(RS_LOOKBACK_HOURS=str(lo_hi["RS_LOOKBACK_HOURS"][1] + 1))),
        ("win-events max events above bound", "powershell", ps_args("win-events"),
         ev(RS_MAX_EVENTS=str(lo_hi["RS_MAX_EVENTS"][1] + 1))),
        ("win-events message chars above bound", "powershell", ps_args("win-events"),
         ev(RS_MESSAGE_CHARS=str(lo_hi["RS_MESSAGE_CHARS"][1] + 1))),
        ("win-events extra env var", "powershell", ps_args("win-events"), ev(RS_EXTRA="1")),
        ("win-disks with env var", "powershell", ps_args("win-disks"), {"RS_LOOKBACK_HOURS": "1"}),
    ]
    return cases


FORBIDDEN_IDS = [
    "smartctl -t short", "smartctl -s on", "smartctl -o on", "smartctl -S on", "smartctl -C", "smartctl -X",
    "smartctl -d sat,x", "smartctl -T permissive", "smartctl -g all", "smartctl -r ataioctl",
    "smartctl two devices", "smartctl git-bash rewritten path", "smartctl device with ;rm", "smartctl no device",
    "tool not in table", "powershell one byte changed", "powershell arbitrary command", "win-events lookback abc",
    "win-events lookback -1", "win-events lookback 0", "win-events lookback above bound",
    "win-events max events above bound", "win-events message chars above bound", "win-events extra env var",
    "win-disks with env var",
]


def get_case(case_id):
    for c in forbidden_cases():
        if c[0] == case_id:
            return c
    raise KeyError(case_id)


@pytest.mark.parametrize("case_id", FORBIDDEN_IDS)
def test_A13_validator_rejects(case_id):
    """A13 (validator level). Mutation per case: remove that flag/bound check -> that case red."""
    from rslib.allowlist import CommandNotAllowed, check

    _, tool, args, env = get_case(case_id)
    with pytest.raises(CommandNotAllowed):
        check(tool, args, env=env)


def test_A13_command_not_allowed_is_one_class():
    """Contract: rslib.allowlist.CommandNotAllowed is rslib.runner.CommandNotAllowed. Mutation: two classes -> red."""
    from rslib import allowlist, runner

    assert allowlist.CommandNotAllowed is runner.CommandNotAllowed


def test_A13b_sha256_table_equals_shipped_scripts():
    """A13b. Mutation: edit a .ps1 without updating the table (or table missing an id) -> red."""
    from rslib.allowlist import PS_SCRIPT_SHA256

    files = {p.stem: hashlib.sha256(p.read_bytes()).hexdigest() for p in PS_DIR.glob("*.ps1")}
    assert set(files) == {"win-disks", "win-pnp-chain", "win-events"}
    assert {k: v.lower() for k, v in PS_SCRIPT_SHA256.items()} == files
