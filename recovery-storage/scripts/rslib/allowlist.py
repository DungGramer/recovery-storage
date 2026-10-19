"""Argv allow-list: the only external commands rslib may run (all R0 read-only).

Allow-list, never deny-list (researcher-01 §4): every token must be recognised; anything else -> CommandNotAllowed.
PowerShell is allowed only as one of the frozen scripts in rslib/ps/, matched by exact content (sha256).
"""
import base64
import binascii
import hashlib
import pathlib
import re

PS_DIR = pathlib.Path(__file__).resolve().parent / "ps"


class CommandNotAllowed(Exception):
    pass


def _sha_file(p):  # used by tests and tools to recompute the pinned table
    return hashlib.sha256(p.read_bytes()).hexdigest()


# sha256 of the shipped script files; a script whose bytes drift from this table is refused (A13b)
# Pinned values: editing a .ps1 without updating this table makes the runner refuse that script (and A13b red).
PS_SCRIPT_SHA256 = {
    "win-disks": "8c0cc4f11a9d14a0f259dfe504600a78d881323832c61c109cc42a1ee55a28e3",
    "win-pnp-chain": "3d64af0dd5d025f29023a99473b4ba8c3904b5529db3a301690d9936a746b999",
    "win-events": "81f24bfeb6f266fba26a0fd9a79b5bf6419146bb6c6b2f6e8fc1932b35c9efda",
}

# inclusive bounds for the win-events parameters (passed as env, validated here)
PS_ENV_BOUNDS = {
    "RS_LOOKBACK_HOURS": (1, 24 * 365),  # up to one year back
    "RS_MAX_EVENTS": (1, 1000),          # per provider
    "RS_MESSAGE_CHARS": (1, 2000),       # message truncation
}
PS_SCRIPT_ENV = {"win-disks": (), "win-pnp-chain": (), "win-events": tuple(PS_ENV_BOUNDS)}

PS_PREFIX = ["-NoProfile", "-NonInteractive", "-EncodedCommand"]

SMART_DEVICE = re.compile(r"^/dev/(sd[a-z]{1,2}|pd\d{1,3}|nvme\d+(n\d+)?|mmcblk\d+)$")
LINUX_DEVICE = re.compile(r"^/dev/[a-z][a-z0-9]{1,15}$")
ISO_TS = re.compile(r"^\d{4}-\d{2}-\d{2}([T ]\d{2}:\d{2}(:\d{2})?(\.\d+)?)?(Z|[+-]\d{2}:?\d{2})?$")

SMART_SIMPLE = {"-j", "-i", "-H", "-A", "-c", "-a", "-x"}
SMART_LOGS = {"error", "xerror", "selftest", "selective", "directory", "devstat", "sataphy", "scttemp"}
SMART_DTYPES = {"auto", "sat", "sat,12", "sat,16", "nvme", "sntjmicron", "sntasmedia", "sntrealtek", "usbjmicron"}
SMART_NODEVICE = {"--scan", "--scan-open", "-V"}


def _deny(msg):
    raise CommandNotAllowed(msg)


def _check_smartctl(args):
    devices, i, nodevice = [], 0, False
    while i < len(args):
        a = args[i]
        if a in SMART_SIMPLE:
            i += 1
        elif a in SMART_NODEVICE:
            nodevice = True
            i += 1
        elif a == "-l" and i + 1 < len(args) and args[i + 1] in SMART_LOGS:
            i += 2
        elif a == "-n" and i + 1 < len(args) and args[i + 1] == "standby":
            i += 2
        elif a == "-d" and i + 1 < len(args) and args[i + 1] in SMART_DTYPES:
            i += 2
        elif a.startswith("/dev/"):
            if not SMART_DEVICE.match(a):
                _deny(f"smartctl device path not allowed: {a!r}")
            devices.append(a)
            i += 1
        else:
            _deny(f"smartctl argument not allowed: {a!r}")
    if nodevice:
        if devices:
            _deny("smartctl scan/version takes no device")
    elif len(devices) != 1:
        _deny(f"smartctl needs exactly one device, got {len(devices)}")


def decode_ps(b64):
    try:
        raw = base64.b64decode(b64, validate=True)
        return raw.decode("utf-16-le")
    except (binascii.Error, ValueError, UnicodeDecodeError):
        return None


def ps_script_id(text):
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    for k, v in PS_SCRIPT_SHA256.items():
        if v == digest:
            return k
    return None


def _check_powershell(args, env):
    if len(args) != 4 or args[:3] != PS_PREFIX:
        _deny("powershell must be -NoProfile -NonInteractive -EncodedCommand <frozen script>")
    text = decode_ps(args[3])
    sid = ps_script_id(text) if text is not None else None
    if sid is None:
        _deny("powershell script is not one of the frozen scripts")
    env = dict(env or {})
    allowed = PS_SCRIPT_ENV[sid]
    if set(env) != set(allowed):
        _deny(f"powershell {sid} env must be exactly {sorted(allowed)}, got {sorted(env)}")
    for k, v in env.items():
        lo, hi = PS_ENV_BOUNDS[k]
        if not (isinstance(v, str) and v.isdigit() and lo <= int(v) <= hi):
            _deny(f"{k}={v!r} outside [{lo}, {hi}]")
    return sid


def _exact(args, *forms):
    return any(len(args) == len(f) and all(p(a) if callable(p) else p == a for p, a in zip(f, args)) for f in forms)


def _dev(a):
    return bool(LINUX_DEVICE.match(a))


def check(tool_id, args, env=None):
    args = list(args)
    if tool_id != "powershell" and env:
        _deny(f"{tool_id} takes no environment parameters")
    if tool_id == "smartctl":
        _check_smartctl(args)
    elif tool_id == "powershell":
        _check_powershell(args, env)
    elif tool_id == "lsblk":
        if not _exact(args, ("-J", "-O", "-b"), ("-J", "-O", "-b", _dev)):
            _deny(f"lsblk form not allowed: {args}")
    elif tool_id == "udevadm":
        if not (len(args) == 3 and args[:2] == ["info", "--query=property"] and args[2].startswith("--name=")
                and _dev(args[2][len("--name="):])):
            _deny(f"udevadm form not allowed: {args}")
    elif tool_id == "blockdev":
        if not _exact(args, ("--getro", _dev), ("--getsize64", _dev)):
            _deny(f"blockdev form not allowed: {args}")
    elif tool_id == "lsusb":
        if args:
            _deny("lsusb takes no arguments")
    elif tool_id == "journalctl":
        if not _exact(args, ("-k", "-o", "json", "--since", lambda a: bool(ISO_TS.match(a)), "--no-pager")):
            _deny(f"journalctl form not allowed: {args}")
    elif tool_id == "dmesg":
        if args != ["--time-format", "iso"]:
            _deny(f"dmesg form not allowed: {args}")
    else:
        _deny(f"tool not in allow-list: {tool_id!r}")


def ps_script_args(script_id):
    """argv (without executable) for a frozen script: base64(UTF-16LE(file text))."""
    text = (PS_DIR / f"{script_id}.ps1").read_text(encoding="utf-8")
    return PS_PREFIX + [base64.b64encode(text.encode("utf-16-le")).decode("ascii")]
