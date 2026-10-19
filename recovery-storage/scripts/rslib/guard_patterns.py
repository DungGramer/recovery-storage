"""Destructive-command patterns for the guard hook (phase 08). Pure: no I/O, no processes.

A deny-list over shell text is LEAKY by construction (variables, eval, script files, GUI tools); it is a second
barrier behind the gate protocol, never the primary control. Commands are tokenised with quote awareness, so a
keyword inside a quoted string (git commit -m "mkfs ...") is an argument, not an executable. Control syntax
(`then`, `do`, `{`, `(`, `$( )`, backticks), wrappers (sudo, timeout, ionice, xargs, busybox, Start-Process ...) and
nested shells (bash -c, cmd /c, powershell -Command / -EncodedCommand, wsl) are unwrapped.
"""
import base64
import binascii
import re
import shlex
from dataclasses import dataclass

MAX_DEPTH = 5  # nested shell unwrap depth
SEPARATORS = {";", "&&", "||", "|", "&", "|&", ";;", "(", ")", "{", "}", "((", "))", "$"}
KEYWORDS = {"then", "do", "else", "elif", "if", "while", "until", "!", "time"}
WRAPPERS = {"sudo", "doas", "nohup", "command", "exec", "env", "stdbuf", "nice", "ionice", "timeout", "xargs",
            "busybox", "pkexec", "chroot", "nsenter", "start-process", "saps", "start", "call"}
WRAPPER_VALUE_FLAGS = {"-u", "-g", "-n", "-c", "-p", "-s", "-k", "-t", "-i", "-o", "-e", "-filepath",
                       "-argumentlist", "-verb", "-workingdirectory", "-windowstyle"}
SHELLS = {"bash", "sh", "zsh", "dash", "ksh"}
PS = {"powershell", "pwsh"}
DEVICE_TARGET = re.compile(r"(?i)^(/dev/(sd[a-z]+\d*|nvme\d+n\d+(p\d+)?|mmcblk\d+(p\d+)?|hd[a-z]+\d*|vd[a-z]+\d*|"
                           r"xvd[a-z]+\d*|disk\d+(s\d+)?|rdisk\d+)|.*physicaldrive\d+|[/\\]{2}[.?][/\\].*)$")


@dataclass(frozen=True)
class Rule:
    id: str
    exe: object       # compiled regex on the normalised executable name
    blocks: object    # predicate(args: list[str]) -> bool


@dataclass(frozen=True)
class Match:
    rule_id: str
    segment: str


def _flags(args):
    return [a for a in args if a.startswith("-")]


def _short_cluster_has(args, ch):
    return any(re.fullmatch(r"-[A-Za-z]+", a) and ch in a[1:] for a in args)


def _only(args, allowed):
    fl = _flags(args)
    return bool(fl) and all(f.split("=", 1)[0] in allowed for f in fl)


def _not_help(args, extra=()):
    return not _only(args, {"--help", "-h", "-V", "--version", *extra})


def _wipefs(args):
    dangerous = any(a in ("-a", "--all", "-o", "--offset") or a.startswith("--offset=") or
                    (re.fullmatch(r"-[A-Za-z]+", a) and ("a" in a[1:] or "o" in a[1:])) for a in args)
    no_act = "--no-act" in args or _short_cluster_has(args, "n")
    return dangerous and not no_act


def _sgdisk(args):
    return not _only(args, {"-p", "--print", "-i", "--info", "-v", "--verify", "--help", "-V", "--version"})


def _parted(args):
    if "-l" in args or "--list" in args:
        return False
    words = [a for a in args if not a.startswith("-") and not a.startswith("/dev/")]
    return not (words and all(w == "print" for w in words))


def _dd(args):
    for a in args:
        if a.startswith("of="):
            target = a[3:]
            if target in ("/dev/null", "/dev/stdout", "/dev/stderr"):
                return False
            if target.startswith("/dev/") or DEVICE_TARGET.match(target):
                return True
    return False


def _chkdsk(args):
    bad = {"/f", "/r", "/x", "/b", "/spotfix", "/offlinescanandfix", "/forceofflinefix"}
    return any(a.lower() in bad for a in args)


def _badblocks(args):
    return any(re.fullmatch(r"-[A-Za-z]+", a) and ("w" in a[1:] or "n" in a[1:]) for a in args)


def _testdisk(args):
    if "/cmd" not in [a.lower() for a in args]:
        return False
    return any("write" in a.lower().split(",") or "noconfirm" in a.lower() for a in args)


def _hdparm(args):
    bad = ("--security-", "--write-sector", "--repair-sector", "--make-bad-sector", "--trim-sector-ranges",
           "--fwdownload", "--dco-restore", "--dco-setmax")
    return any(a.startswith(bad) for a in args)


NVME_WRITE = {"format", "sanitize", "fw-download", "fw-commit", "fw-activate", "ns-delete", "ns-create", "write",
              "write-zeroes", "write-uncor", "dsm", "device-self-test"}


def _nvme(args):
    sub = next((a for a in args if not a.startswith("-")), None)
    return sub in NVME_WRITE


def _smartctl(args):
    for a in args:
        k = a.split("=", 1)[0]
        if k in ("-t", "--test", "-s", "--smart", "-o", "--offlineauto", "-S", "--saveauto", "-X", "--abort",
                 "-C", "--captive"):
            return True
    return False


def _fsck(args):
    if "-n" in args or "--no-action" in args or "--dry-run" in args:
        return False
    if any(re.fullmatch(r"-[A-Za-z]+", a) and "n" in a[1:] and not set(a[1:]) & set("ypa") for a in args):
        return False
    return True


def _format_cmd(args):
    return any(re.fullmatch(r"[A-Za-z]:[/\\]?", a) for a in args)


def _repair_volume(args):
    fl = [a.lower() for a in _flags(args)]
    value_flags = {"-driveletter", "-path", "-objectid", "-filesystemlabel", "-cimsession", "-throttlelimit"}
    return any(f not in value_flags | {"-scan"} for f in fl)


CRYPT_WRITE = {"luksformat", "erase", "lukserase", "reencrypt", "luksaddkey", "luksremovekey", "lukskillslot",
               "lukschangekey", "convert", "repair", "luksheaderrestore", "format"}


def _cryptsetup(args):
    return any(a.lower() in CRYPT_WRITE for a in args)


def _defrag(args):
    return not all(a.lower() in ("/a", "/analyze", "/?", "/h", "/v", "/u") or re.fullmatch(r"[A-Za-z]:", a)
                   for a in args) if args else True


def _optimize_volume(args):
    fl = [a.lower() for a in _flags(args)]
    value_flags = {"-driveletter", "-path", "-objectid", "-filesystemlabel", "-cimsession", "-throttlelimit"}
    return any(f not in value_flags | {"-analyze", "-verbose"} for f in fl) or not fl


def _cipher(args):
    return any(a.lower().startswith("/w") for a in args)


def _mdadm(args):
    return any(a in ("--zero-superblock", "--create", "-C", "--grow", "-G") for a in args)


def _tune2fs(args):
    return not _only(args, {"-l", "--help", "-V"})


def _manage_bde(args):
    return any(a.lower() in ("-on", "-off", "-w", "-wipefreespace") for a in args)


def _cp_tee(args):
    targets = [a for a in args if not a.startswith("-")]
    return bool(targets) and any(DEVICE_TARGET.match(t) for t in targets[-1:] + targets)


def _always(args):
    return True


def _rx(p):
    return re.compile(p, re.I)


RULES = (
    Rule("diskpart", _rx(r"^diskpart$"), _always),
    Rule("ps-disk-cmdlet", _rx(r"^(format-volume|clear-disk|initialize-disk|set-disk|new-partition|remove-partition|"
                               r"resize-partition|set-partition|update-storagefirmware|initialize-volume)$"), _always),
    Rule("ps-repair-volume", _rx(r"^repair-volume$"), _repair_volume),
    Rule("ps-optimize-volume", _rx(r"^optimize-volume$"), _optimize_volume),
    Rule("cmd-format", _rx(r"^format$"), _format_cmd),
    Rule("chkdsk-fix", _rx(r"^chkdsk$"), _chkdsk),
    Rule("defrag", _rx(r"^defrag$"), _defrag),
    Rule("cipher-wipe", _rx(r"^cipher$"), _cipher),
    Rule("manage-bde-change", _rx(r"^manage-bde$"), _manage_bde),
    Rule("mkfs", _rx(r"^(mkfs(\..+)?|mke2fs|mkntfs|mkdosfs|mkexfatfs|mkswap)$"), _not_help),
    Rule("wipefs", _rx(r"^wipefs$"), _wipefs),
    Rule("shred", _rx(r"^shred$"), _not_help),
    Rule("fstrim", _rx(r"^fstrim$"), _not_help),
    Rule("sgdisk", _rx(r"^sgdisk$"), _sgdisk),
    Rule("gdisk", _rx(r"^gdisk$"), lambda a: "-l" not in a),
    Rule("parted", _rx(r"^parted$"), _parted),
    Rule("fdisk", _rx(r"^fdisk$"), lambda a: not ({"-l", "--list"} & set(a))),
    Rule("sfdisk", _rx(r"^sfdisk$"), lambda a: not ({"-l", "-d", "-J", "--dump", "--list", "--json"} & set(a))),
    Rule("cfdisk", _rx(r"^cfdisk$"), _always),
    Rule("dd-to-device", _rx(r"^dd$"), _dd),
    Rule("copy-to-device", _rx(r"^(cp|tee|pv)$"), _cp_tee),
    Rule("ddrescue", _rx(r"^ddrescue$"), _not_help),
    Rule("f3-write", _rx(r"^(f3probe|f3write|f3fix|f3brew)$"), _not_help),
    Rule("badblocks-write", _rx(r"^badblocks$"), _badblocks),
    Rule("testdisk-write", _rx(r"^testdisk(_win)?$"), _testdisk),
    Rule("hdparm-write", _rx(r"^hdparm$"), _hdparm),
    Rule("nvme-write", _rx(r"^nvme$"), _nvme),
    Rule("sg-format", _rx(r"^sg_(format|sanitize|write_same|unmap)$"), _not_help),
    Rule("smartctl-state", _rx(r"^smartctl$"), _smartctl),
    Rule("blkdiscard", _rx(r"^blkdiscard$"), lambda a: not _only(a, {"--help", "-h", "-V", "--version"})),
    Rule("cryptsetup-write", _rx(r"^cryptsetup$"), _cryptsetup),
    Rule("mdadm-write", _rx(r"^mdadm$"), _mdadm),
    Rule("tune2fs", _rx(r"^tune2fs$"), _tune2fs),
    Rule("fsck-repair", _rx(r"^(fsck(\..+)?|e2fsck|ntfsfix|xfs_repair|dosfsck|exfatfsck|fsck_exfat)$"), _fsck),
    Rule("redirect-to-device", _rx(r"^$"), _always),            # emitted for `> /dev/sdX` on any command
    Rule("powershell-encoded-undecodable", _rx(r"^$"), _always),  # emitted by the unwrapper (plan R2)
)
RULE_IDS = {r.id for r in RULES}


def _normalise(text):
    # keep Windows path separators: posix shlex would eat the backslash in C:\Windows\diskpart.exe
    text = re.sub(r"\\(?=[A-Za-z0-9_.$-])", "/", text)
    return text.replace("`", " ; ")


def _tokens(line):
    try:
        lex = shlex.shlex(line, posix=True, punctuation_chars=";&|(){}<>$")
        lex.whitespace_split = True
        lex.whitespace = " \t\r"
        lex.commenters = ""
        return list(lex)
    except ValueError:
        return re.sub(r"([;&|(){}<>])", r" \1 ", line).split()


def _segments(text):
    out = []
    for line in _normalise(text).splitlines() or [text]:
        seg = []
        for t in _tokens(line):
            if t in SEPARATORS or (t and set(t) <= set(";&|(){}$")):
                if seg:
                    out.append(seg)
                seg = []
            else:
                seg.append(t)
        if seg:
            out.append(seg)
    return out


def exe_name(tok):
    base = re.split(r"[\\/]", tok)[-1]
    return re.sub(r"\.(exe|com|cmd|bat)$", "", base, flags=re.I).lower()


def _strip_wrappers(seg):
    i = 0
    start_process = False
    while i < len(seg):
        e = exe_name(seg[i])
        if e in KEYWORDS:
            i += 1
            continue
        if e in WRAPPERS:
            start_process = start_process or e in ("start-process", "saps", "start")
            i += 1
            while i < len(seg) and (seg[i].startswith("-") or re.fullmatch(r"\w+=.*", seg[i]) or
                                    (e == "timeout" and re.fullmatch(r"\d+[smhd]?", seg[i]))):
                if seg[i].lower() in WRAPPER_VALUE_FLAGS and i + 1 < len(seg) and \
                        seg[i].lower() not in ("-filepath", "-argumentlist"):
                    i += 1
                if seg[i].lower() == "-filepath":
                    i += 1  # the value is the executable
                    break
                if seg[i].lower() == "-argumentlist":
                    seg = seg[:i] + seg[i + 1:]
                    continue
                i += 1
            continue
        if re.fullmatch(r"[A-Za-z_]\w*=.*", seg[i]):
            i += 1
            continue
        break
    rest = seg[i:]
    if start_process:
        # Start-Process diskpart -ArgumentList "/s x" -> diskpart /s x
        rest = [p for t in rest for p in t.replace(",", " ").split()]
    return rest


def _decode_ps(b64):
    try:
        return base64.b64decode(b64, validate=True).decode("utf-16-le")
    except (binascii.Error, ValueError, UnicodeDecodeError):
        return None


def _is_encoded_flag(low):
    return low == "-ec" or (len(low) >= 2 and "-encodedcommand".startswith(low) and low not in ("-",))


def _nested(seg):
    """Inner command text for shell wrappers -> (text|None, undecodable: bool)."""
    e = exe_name(seg[0])
    args = seg[1:]
    if e in SHELLS:
        for i, a in enumerate(args):
            if a == "-c" or re.fullmatch(r"-[a-z]*c[a-z]*", a):
                return (" ".join(args[i + 1:i + 2]) if i + 1 < len(args) else ""), False
        return None, False
    if e == "cmd":
        for i, a in enumerate(args):
            if a.lower() in ("/c", "/k"):
                return " ".join(args[i + 1:]), False
        return None, False
    if e == "wsl":
        i = 0
        while i < len(args):
            a = args[i]
            if a in ("-e", "--exec", "--"):
                return " ".join(args[i + 1:]), False
            if a in ("-d", "--distribution", "-u", "--user", "--cd"):
                i += 2
                continue
            if a.startswith("-"):
                i += 1
                continue
            return " ".join(args[i:]), False
        return None, False
    if e in PS:
        i = 0
        while i < len(args):
            a, low = args[i], args[i].lower()
            if _is_encoded_flag(low):
                text = _decode_ps(args[i + 1]) if i + 1 < len(args) else None
                return (text, text is None)
            if low in ("-command", "-c", "-co", "-com", "-comm", "-comma", "-comman"):
                return " ".join(args[i + 1:]), False
            if low in ("-file", "-f"):
                return None, False
            if low in ("-executionpolicy", "-ep", "-ex", "-windowstyle", "-w", "-version", "-v",
                       "-configurationname"):
                i += 2
                continue
            if a.startswith("-"):
                i += 1
                continue
            return " ".join(args[i:]), False
    return None, False


def _redirect_target(seg):
    for i, t in enumerate(seg):
        if t in (">", ">>", ">|") and i + 1 < len(seg):
            target = seg[i + 1]
            if target not in ("/dev/null", "/dev/stdout", "/dev/stderr") and DEVICE_TARGET.match(target):
                return target
    return None


def _find(text, depth):
    for seg in _segments(text):
        seg = _strip_wrappers(seg)
        if not seg:
            continue
        if _redirect_target(seg):
            return Match("redirect-to-device", " ".join(seg))
        inner, undecodable = _nested(seg)
        if undecodable:
            return Match("powershell-encoded-undecodable", " ".join(seg)[:200])
        if inner is not None and depth < MAX_DEPTH:
            m = _find(inner, depth + 1)
            if m:
                return m
            continue
        e = exe_name(seg[0])
        for r in RULES:
            if r.exe.pattern != "^$" and r.exe.match(e) and r.blocks(seg[1:]):
                return Match(r.id, " ".join(seg))
    return None


def find(command):
    if not isinstance(command, str) or not command.strip():
        return None
    return _find(command, 0)
