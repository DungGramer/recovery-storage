"""Destructive-command patterns for the guard hook (phase 08, amendment 02). Pure: no I/O, no processes.

A deny-list over shell text is LEAKY by construction (variables, eval, script files, GUI tools); it is a second
barrier behind the gate protocol, never the primary control. Commands are tokenised over the whole text with quote
awareness, so a keyword inside a quoted string or a heredoc body (git commit -m "mkfs ...") is data, not an
executable. Control syntax (`then`, `do`, `{`, `(`, `$( )`, backticks, `$x =` assignments), wrappers (sudo,
timeout, ionice, xargs, busybox, Start-Process ...) and nested shells (bash -c, cmd /c, powershell -Command /
-EncodedCommand, wsl) are unwrapped.
"""
import base64
import binascii
import re
import shlex
from dataclasses import dataclass

MAX_DEPTH = 5  # nested shell unwrap depth
SEPARATORS = {";", "&&", "||", "|", "&", "|&", ";;", "(", ")", "{", "}", "((", "))", "$", "\n"}
KEYWORDS = {"then", "do", "else", "elif", "if", "while", "until", "!", "time"}
# wrapper -> flags that take a value (case-sensitive: sudo -E / -n / -S take none)
WRAPPER_VALUE_FLAGS = {
    "sudo": {"-u", "-g", "-h", "-p", "-C", "-D", "-R", "-T", "-r", "-t", "--user", "--group", "--host", "--prompt",
             "--chdir", "--chroot", "--close-from", "--other-user", "--role", "--type", "--command-timeout"},
    "doas": {"-u", "-C"},
    "env": {"-u", "-C", "-S", "--unset", "--chdir", "--split-string"},
    "nice": {"-n", "--adjustment"},
    "ionice": {"-c", "-n", "-p", "-P", "-u", "--class", "--classdata", "--pid", "--pgid", "--uid"},
    "timeout": {"-s", "-k", "--signal", "--kill-after"},
    "xargs": {"-a", "-d", "-E", "-e", "-I", "-i", "-L", "-l", "-n", "-P", "-s", "--arg-file", "--delimiter",
              "--max-args", "--max-procs", "--max-chars", "--replace", "--max-lines", "--eof"},
    "stdbuf": {"-i", "-o", "-e", "--input", "--output", "--error"},
    "chroot": {"--userspec", "--groups"},
    "nsenter": {"-t", "--target", "-S", "-G", "--setuid", "--setgid"},
    "nohup": set(), "exec": {"-a"}, "busybox": set(), "pkexec": {"--user"}, "call": set(),
    "start-process": {"-verb", "-workingdirectory", "-windowstyle", "-credential", "-redirectstandardinput",
                      "-redirectstandardoutput", "-redirectstandarderror"},
    "saps": {"-verb", "-workingdirectory", "-windowstyle", "-credential"},
    "start": set(),
}
WRAPPERS = set(WRAPPER_VALUE_FLAGS)
CASE_FOLD_WRAPPERS = {"start-process", "saps", "start"}  # PowerShell parameters are case-insensitive
SHELLS = {"bash", "sh", "zsh", "dash", "ksh"}
PS = {"powershell", "pwsh"}
DEVICE_TARGET = re.compile(
    r"(?i)^(/dev/(sd[a-z]+\d*|nvme\d+n\d+(p\d+)?|mmcblk\d+(p\d+)?|hd[a-z]+\d*|vd[a-z]+\d*|xvd[a-z]+\d*|"
    r"disk\d+(s\d+)?|rdisk\d+|disk/by-[a-z-]+/.+|mapper/.+|md\d+(p\d+)?|md/.+|dm-\d+|loop\d+(p\d+)?|nbd\d+)|"
    r".*physicaldrive\d+|[/\\]{2}[.?][/\\].*)$")
NOT_DEVICE = {"/dev/null", "/dev/stdout", "/dev/stderr", "/dev/zero", "/dev/tty", "/dev/urandom", "/dev/random"}



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
    # read-only: print [free|all|list], optionally after `unit <u>`
    read_words = {"print", "free", "all", "list", "unit", "b", "kb", "mb", "gb", "tb", "kib", "mib", "gib", "tib",
                  "s", "%", "cyl", "chs", "compact"}
    return not (words and "print" in words and all(w.lower() in read_words for w in words))


def _dd(args):
    for a in args:
        if a.startswith("of="):
            target = a[3:]
            if target in NOT_DEVICE:
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
    if "-n" in args or "-N" in args or "--no-action" in args or "--dry-run" in args:
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


def _cp_tee(args, exe=None):
    """Only the WRITE target matters: cp SRC.. DST (last), tee FILE.. (all), pv writes to stdout only."""
    targets = [a for a in args if not a.startswith("-")]
    return bool(targets) and is_device_target(targets[-1])


def _pv(args):
    """pv writes to stdout unless -o/--output names a file (pv 1.8+)."""
    for i, a in enumerate(args):
        if a in ("-o", "--output") and i + 1 < len(args) and is_device_target(args[i + 1]):
            return True
        if a.startswith("--output=") and is_device_target(a.split("=", 1)[1]):
            return True
    return False


def _tee(args):
    return any(is_device_target(a) for a in args if not a.startswith("-"))


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
    Rule("copy-to-device", _rx(r"^(cp|install)$"), _cp_tee),
    Rule("tee-to-device", _rx(r"^tee$"), _tee),
    Rule("pv-to-device", _rx(r"^pv$"), _pv),
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



# executables that run a heredoc body as commands (`bash <<EOF`, `cat <<EOF | sh`, `ssh host <<EOF` ...)
STDIN_RUNNERS = SHELLS | PS | {"ssh", "wsl", "cmd", "python", "python3", "perl", "ruby", "node", "iex",
                                "invoke-expression", "source", "."}


def _line_tokens(line):
    """Tokens of one line, quote-aware; an unbalanced quote falls back to a plain split of THIS line only."""
    try:
        lex = shlex.shlex(line, posix=True, punctuation_chars=";&|(){}<>$")
        lex.whitespace_split = True
        lex.commenters = ""
        return _split_punct(list(lex))
    except ValueError:
        return re.sub(r"([;&|(){}<>])", r" \1 ", line).split()


def _drop_heredoc_bodies(text):
    """Line scan, O(n log n): a heredoc body is data unless the line that opens it runs it (shell, ssh, ...).
    `<<` inside quotes is not an operator (quote-aware tokens)."""
    import bisect

    lines = text.split("\n")
    positions = {}
    for i, ln in enumerate(lines):
        positions.setdefault(ln.strip(), []).append(i)
    out, i = [], 0
    while i < len(lines):
        toks = _line_tokens(lines[i])
        delim = None
        for k, t in enumerate(toks):
            if t in ("<<", "<<-") and k + 1 < len(toks) and re.fullmatch(r"[A-Za-z_][\w-]*", toks[k + 1]):
                delim = toks[k + 1]
                break
        if delim is None:
            out.append(lines[i])
            i += 1
            continue
        ends = positions.get(delim, [])
        j = bisect.bisect_right(ends, i)
        if j == len(ends):
            out.append(lines[i])
            i += 1
            continue
        end = ends[j]
        runs = any(exe_name(t) in STDIN_RUNNERS for t in toks)
        out.append(lines[i])
        if runs:
            out.extend(lines[i + 1:end])  # executed: judge the body as commands
        i = end + 1
    return "\n".join(out)


PUNCT_OPS = re.compile(r"&&|\|\||;;|&>>|>>|<<<|<<-|<<|&>|>&|<&|>\||\|&|[;&|(){}<>$\n]")


def _split_punct(tokens):
    """shlex glues adjacent punctuation (`)>`, `;(`): split it into shell operators."""
    out = []
    for t in tokens:
        if t and set(t) <= set(";&|(){}<>$\n"):
            out.extend(PUNCT_OPS.findall(t))
        else:
            out.append(t)
    return out


def _normalise(text):
    # line continuations (backslash-newline) join lines before anything else
    text = re.sub(r"\\\r?\n", " ", text)
    # keep Windows path separators: posix shlex would eat the backslash in C:\Windows\diskpart.exe
    text = re.sub(r"\\(?=[A-Za-z0-9_.$-])", "/", text)
    text = _drop_heredoc_bodies(text)
    return text.replace("`", " ; ")


def _tokens(text):
    """Whole-text tokenizer: quotes may span lines; newlines outside quotes are separators. If the whole text does
    not tokenize (an unbalanced quote such as `# don't`), fall back to line by line so later lines are still seen."""
    try:
        lex = shlex.shlex(text, posix=True, punctuation_chars=";&|(){}<>$\n")
        lex.whitespace_split = True
        lex.whitespace = " \t\r"
        lex.commenters = ""
        out = []
        for t in lex:
            if "\n" in t and t.strip("\n") == "":
                out.append("\n")
            elif t and set(t) <= set(";&|(){}$\n") and "\n" in t:
                out.extend(t.replace("\n", " \n ").split(" "))
            else:
                out.append(t)
        return _split_punct([t for t in out if t != ""])
    except ValueError:
        out = []
        for ln in text.split("\n"):
            out.extend(_line_tokens(ln))
            out.append("\n")
        return out


def _segments(text):
    out, seg = [], []
    for t in _tokens(_normalise(text)):
        if t in SEPARATORS or (t and set(t) <= set(";&|(){}$\n")):
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


REDIRECT_OPS = {">", ">>", ">|", "<", "<<", "<<<", "&>", ">&", "&>>", "<&"}


def _without_redirects(args):
    """Drop redirections (operator, its target, a leading fd number) so rules see only real arguments."""
    out, i = [], 0
    while i < len(args):
        a = args[i]
        if a.isdigit() and i + 1 < len(args) and args[i + 1] in REDIRECT_OPS:
            i += 1
            continue
        if a in REDIRECT_OPS:
            i += 2
            continue
        out.append(a)
        i += 1
    return out


def _strip_assignment(seg):
    # PowerShell `$x = <cmd>` / `x = <cmd>` (the `$` itself is a separator token)
    while len(seg) >= 2 and re.fullmatch(r"[A-Za-z_][\w:]*", seg[0]) and seg[1] in ("=", "+=", "-="):
        seg = seg[2:]
    # `$x=Clear-Disk ...` without spaces: the value is a cmdlet (Verb-Noun), not an environment assignment
    if seg:
        m = re.fullmatch(r"[A-Za-z_][\w:]*=([A-Za-z]+-[A-Za-z]+)", seg[0])
        if m:
            seg = [m.group(1)] + seg[1:]
    return seg


def _strip_wrappers(seg):
    i = 0
    start_process = False
    while i < len(seg):
        seg = seg[:i] + _strip_assignment(seg[i:])
        if i >= len(seg):
            break
        e = exe_name(seg[i])
        if e in KEYWORDS:
            i += 1
            continue
        if e == "command" and i + 1 < len(seg) and seg[i + 1] in ("-v", "-V"):
            return []  # `command -v x` only looks a name up
        if e in WRAPPERS or e == "command":
            fold = e in CASE_FOLD_WRAPPERS
            start_process = start_process or fold
            vflags = WRAPPER_VALUE_FLAGS.get(e, set())
            i += 1
            while i < len(seg):
                tok = seg[i]
                key = tok.lower() if fold else tok
                if fold and key == "-filepath":
                    i += 1  # the value is the executable
                    break
                if fold and key == "-argumentlist":
                    seg = seg[:i] + seg[i + 1:]
                    continue
                if tok.startswith("-"):
                    i += 2 if (key in vflags and "=" not in tok and i + 1 < len(seg)) else 1
                    continue
                if re.fullmatch(r"\w+=.*", tok) or (e == "timeout" and re.fullmatch(r"\d+(\.\d+)?[smhd]?", tok)):
                    i += 1
                    continue
                break
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
    return low == "-ec" or (len(low) >= 2 and "-encodedcommand".startswith(low))


def _nested(seg):
    """Inner command text for shell wrappers -> (text|None, undecodable: bool)."""
    e = exe_name(seg[0])
    args = seg[1:]
    if e in ("invoke-expression", "iex"):
        # PowerShell eval of a literal string: judge the string (a variable argument stays a documented leak)
        vals = [a for a in args if a.lower() not in ("-command", "-c")]
        return " ".join(vals), False
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


def is_device_target(t):
    return t not in NOT_DEVICE and bool(DEVICE_TARGET.match(t))


def _redirect_target(seg):
    for i, t in enumerate(seg):
        if t in (">", ">>", ">|", "&>", ">&", "&>>") and i + 1 < len(seg):
            if is_device_target(seg[i + 1]):
                return seg[i + 1]
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
        args = _without_redirects(seg[1:])
        for r in RULES:
            if r.exe.pattern != "^$" and r.exe.match(e) and r.blocks(args):
                return Match(r.id, " ".join(seg))
    return None


def find(command):
    if not isinstance(command, str) or not command.strip():
        return None
    return _find(command, 0)
