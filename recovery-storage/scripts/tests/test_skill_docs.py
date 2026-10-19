"""Phase 06 docs lint (F1-F7, F9 live, F10) + phase 08 frontmatter/limits (H15, H18).
Spec: phase-06 Requirements (SKILL.md, references/, method block shape) + F1-F10; phase-08 H15, H18."""
import argparse
import re
import unicodedata

import pytest

from conftest import SKILL_DIR

SKILL = SKILL_DIR / "SKILL.md"
REFS = SKILL_DIR / "references"
REF_NAMES = ["safety-and-gates", "phase1-hardware-triage", "device-hdd", "device-ssd-nvme", "device-usb-flash-sd",
             "device-external-bridge", "imaging-ddrescue", "file-partition-recovery", "authenticity-f3-h2testw",
             "controller-mptool", "health-signals", "tools-windows", "tools-linux"]
TRIGGERS = ["USB không nhận", "thẻ nhớ lỗi", "thẻ SD lỗi", "cứu dữ liệu ổ cứng", "khôi phục dữ liệu",
            "kiểm tra USB fake dung lượng", "USB giả dung lượng", "SMART", "sức khỏe ổ SSD", "ổ NVMe",
            "ổ cứng kêu lạch cạch", "ổ cứng ngoài không nhận", "recover data from failing drive", "check SSD health",
            "fake capacity USB", "SD card not detected", "ddrescue", "TestDisk", "PhotoRec", "F3", "H2testw"]
FIELDS = ["Preconditions", "Risk", "Tool", "Expected result", "Stop criteria"]


def N(s):
    return unicodedata.normalize("NFC", s)


def read(p):
    assert p.is_file(), f"missing {p}"
    return N(p.read_text(encoding="utf-8"))


def docs():
    return [SKILL] + [REFS / f"{n}.md" for n in REF_NAMES]


# ---------------- minimal YAML-subset parser for frontmatter (no PyYAML at runtime or in tests)
def _ind(line):
    return len(line) - len(line.lstrip(" "))


def _scalar(v):
    v = v.strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in "'\"":
        inner = v[1:-1]
        return inner.replace("''", "'") if v[0] == "'" else inner.replace('\\"', '"').replace("\\\\", "\\")
    return v


def _block(lines, i, indent):
    if lines[i].lstrip().startswith("- ") or lines[i].strip() == "-":
        out = []
        while i < len(lines) and _ind(lines[i]) == indent and lines[i].lstrip().startswith("-"):
            rest = lines[i].lstrip()[1:].lstrip()
            if re.match(r"^[\w.-]+\s*:(\s|$)", rest):
                lines[i] = " " * (indent + 2) + rest
                obj, i = _block(lines, i, indent + 2)
            else:
                obj, i = _scalar(rest), i + 1
            out.append(obj)
        return out, i
    out = {}
    while i < len(lines) and _ind(lines[i]) == indent:
        m = re.match(r"^\s*([\w.-]+)\s*:(.*)$", lines[i])
        assert m, f"unparseable frontmatter line: {lines[i]!r}"
        key, val = m.group(1), m.group(2).strip()
        i += 1
        if val[:1] in ("|", ">") and set(val) <= set("|>+-"):
            buf = []
            while i < len(lines) and _ind(lines[i]) > indent:
                buf.append(lines[i].strip())
                i += 1
            out[key] = ("\n" if val[0] == "|" else " ").join(buf)
        elif val == "":
            if i < len(lines) and (_ind(lines[i]) > indent or lines[i].lstrip().startswith("- ")):
                out[key], i = _block(lines, i, _ind(lines[i]))
            else:
                out[key] = None
        else:
            buf = [val]
            while i < len(lines) and _ind(lines[i]) > indent and not lines[i].lstrip().startswith("- "):
                buf.append(lines[i].strip())
                i += 1
            out[key] = _scalar(" ".join(buf))
    return out, i


def frontmatter():
    text = read(SKILL)
    m = re.match(r"^---\r?\n(.*?)\r?\n---\r?\n", text, re.S)
    assert m, "SKILL.md must start with a --- frontmatter block"
    lines = [ln.rstrip() for ln in m.group(1).splitlines() if ln.strip() and not ln.lstrip().startswith("#")]
    fm, i = _block(lines, 0, 0)
    assert i == len(lines)
    return fm, text[m.end():]


# ---------------- F1
def test_F1_frontmatter_name_and_description_triggers():
    """F1. Mutation: drop a Vietnamese trigger from the description -> red."""
    fm, _ = frontmatter()
    assert set(fm) <= {"name", "description", "hooks"}, set(fm)
    assert fm["name"] == "recovery-storage"
    desc = N(fm["description"]).casefold()
    missing = [t for t in TRIGGERS if N(t).casefold() not in desc]
    assert missing == []


def test_references_files_exist():
    """Phase 06 Related Code Files: one reference per purpose. Mutation: merge/rename a playbook -> red."""
    for n in REF_NAMES:
        assert (REFS / f"{n}.md").is_file(), n


# ---------------- F2
LINK = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")


def test_F2_relative_links_resolve():
    """F2. Mutation: link to a reference file that does not exist -> red."""
    broken = []
    for p in docs():
        for target in LINK.findall(read(p)):
            if re.match(r"^[a-z]+://", target) or target.startswith(("#", "mailto:")):
                continue
            path = target.split("#", 1)[0]
            if path and not (p.parent / path).exists():
                broken.append(f"{p.name}: {target}")
    assert broken == []


# ---------------- F3
def subcommands(parser):
    for a in parser._actions:
        if isinstance(a, argparse._SubParsersAction):
            return dict(a.choices)
    return {}


def tree():
    from rslib.cli import build_parser

    top = subcommands(build_parser())
    assert top, "rslib.cli.build_parser() has no subcommands"
    return {k: set(subcommands(v)) for k, v in top.items()}


MENTION = re.compile(r"rs\.py((?:[ \t]+[^\s`|)\]]+(?:\|[^\s`|)\]]+)*)+)")


def mentions(text):
    out = []
    for m in MENTION.finditer(text):
        toks = m.group(1).split()
        clean = []
        skip = False
        for t in toks:
            if skip:
                skip = False
                continue
            if t == "--home":
                skip = True
                continue
            if t.startswith("-"):
                continue
            clean.append(t)
        if clean and not clean[0].startswith(("<", "[", "{", "$")):
            out.append(clean)
    return out


def test_F3_every_documented_subcommand_exists():
    """F3. Mutation: docs mention `rs.py gate run` (rejected design) -> red."""
    t = tree()
    bad = []
    for p in docs():
        for toks in mentions(read(p)):
            if toks[0] not in t:
                bad.append(f"{p.name}: rs.py {' '.join(toks)}")
            elif t[toks[0]] and len(toks) > 1 and not toks[1].startswith(("<", "[")):
                for sub in toks[1].split("|"):
                    if sub not in t[toks[0]]:
                        bad.append(f"{p.name}: rs.py {toks[0]} {sub}")
    assert bad == []


def test_F3_every_argparse_subcommand_mentioned_in_skill_md():
    """F3 (strict: nested subcommands too). Mutation: add a subcommand without documenting it -> red."""
    t = tree()
    seen = {}
    for toks in mentions(read(SKILL)):
        seen.setdefault(toks[0], set())
        if len(toks) > 1:
            seen[toks[0]].update(toks[1].split("|"))
    missing = [c for c in t if c not in seen]
    missing += [f"{c} {s}" for c, subs in t.items() if c in seen for s in subs if s not in seen[c]]
    assert missing == []


# ---------------- F4 / F5
def method_blocks():
    out = []
    for p in docs():
        text = read(p)
        for m in re.finditer(r"^### Method: *(.+)$", text, re.M):
            body = text[m.end():]
            nxt = re.search(r"^#{1,6} ", body, re.M)
            out.append((p.name, m.group(1).strip(), body[: nxt.start()] if nxt else body))
    return out


def fields(body):
    got = {}
    for f in FIELDS:
        m = re.search(rf"^- {re.escape(f)}: *(.*)$", body, re.M)
        got[f] = m.group(1).strip() if m else None
    return got


def test_F4_method_blocks_have_five_fields_and_valid_risk():
    """F4. Mutation: a method without stop criteria, or Risk naming a kind not in the catalog -> red."""
    from rslib.actions import CATALOG

    blocks = method_blocks()
    assert blocks, "no `### Method:` blocks found"
    bad = []
    for fname, name, body in blocks:
        f = fields(body)
        if any(not v for v in f.values()):
            bad.append((fname, name, "empty field", f))
            continue
        m = re.match(r"^R([0-3])\b.*\(gate kind: *([\w-]+)\)", f["Risk"])
        if not m:
            bad.append((fname, name, "risk shape", f["Risk"]))
        elif m.group(2) != "none" and m.group(2) not in CATALOG:
            bad.append((fname, name, "unknown kind", m.group(2)))
    assert bad == []


def test_F5_every_catalog_kind_documented_with_same_risk():
    """F5. Mutation: document image-ddrescue as R2 (catalog R1), or leave a kind undocumented -> red."""
    from rslib.actions import CATALOG

    seen = {}
    for _, _, body in method_blocks():
        risk = fields(body)["Risk"] or ""
        m = re.match(r"^R([0-3])\b.*\(gate kind: *([\w-]+)\)", risk)
        if m and m.group(2) != "none":
            seen.setdefault(m.group(2), set()).add("R" + m.group(1))
    assert sorted(set(CATALOG) - set(seen)) == []
    wrong = {k: v for k, v in seen.items() if k in CATALOG and v != {CATALOG[k].risk}}
    assert wrong == {}


# ---------------- F6
THRESH = re.compile(r"(?i)(percentage[_ ]used|endurance|available[_ ]spare|\b(?:attr(?:ibute)?|id)\s*#?\s*"
                    r"(?:5|187|197|198|199)\b)[^\n]{0,60}?(>=|<=|≥|≤|>|<|=|at least|above|below|exceeds?)\s*\d")


def outside_rules_blocks(text):
    keep, in_fence, rules_fence, prev = [], False, False, ""
    for ln in text.splitlines():
        if ln.strip().startswith("```"):
            if not in_fence:
                in_fence, rules_fence = True, "rs.py rules" in prev or "rs.py rules" in ln
            else:
                in_fence = False
            continue
        if not (in_fence and rules_fence):
            keep.append(ln)
        if ln.strip():
            prev = ln
    return keep


def test_F6_no_thresholds_restated_in_references():
    """F6. Mutation: write 'percentage_used >= 80 means watch' in a playbook -> red."""
    bad = []
    for p in docs():
        for ln in outside_rules_blocks(read(p)):
            if THRESH.search(ln):
                bad.append(f"{p.name}: {ln.strip()}")
    assert bad == []


# ---------------- F7 (automatable part)
F7_ITEMS = [
    (re.compile(r"\bABCD\b"), None),                                   # no-name VID hint
    (re.compile(r"(?i)usbipd.*mass[- ]storage|mass[- ]storage.*usbipd"), None),
    (re.compile(r"(?i)PhysicalDrive"), "file-partition-recovery.md"),  # TestDisk/PhotoRec device arg
    (re.compile(r"(?i)seagate.*(packed|raw)"), None),
    (re.compile(r"(?i)temperature band|°C.*(watch|critical)"), "health-signals.md"),
]


def test_F7_unverified_items_labelled():
    """F7 automatable subset: lines carrying [M]/[K]/[UNVERIFIED] research items carry `[UNVERIFIED]`.
    Mutation: state the VID ABCD hint as fact -> red. Full F7 stays a reviewer item (see live test)."""
    bad = []
    for p in docs():
        for ln in read(p).splitlines():
            for pat, only in F7_ITEMS:
                if (only is None or p.name == only) and pat.search(ln) and "[UNVERIFIED]" not in ln:
                    bad.append(f"{p.name}: {ln.strip()}")
    assert bad == []


@pytest.mark.live
def test_F7_reviewer_check_all_unverified_items():
    """F7 full check is a reviewer task (phase review): compare every reference line against research items marked
    [M]/[K]/[UNVERIFIED]. Fails until the review is recorded."""
    pytest.fail("MANUAL: record the F7 reviewer pass (date, reviewer, findings) in the phase-06 review.")


@pytest.mark.live
def test_F9_trigger_eval_with_skill_creator():
    """F9: positive VI/EN prompts select the skill, negatives do not (skill-creator eval in a live Claude session)."""
    pytest.fail("MANUAL: run the skill-creator trigger eval; record date, method and per-prompt result in the "
                "phase-06 review. Positives: 'USB không nhận trên Windows', 'kiểm tra thẻ nhớ có phải hàng fake dung "
                "lượng không', 'check my NVMe health'. Negatives: 'khôi phục file đã xóa trên Google Drive', "
                "'recover a deleted git branch', 'tối ưu database SQLite'.")


# ---------------- F10
def test_F10_skill_md_states_hard_rules():
    """F10. Mutation: remove the gate-limit or redaction statement -> red."""
    _, body = frontmatter()
    b = body.casefold()
    assert re.search(r"(cannot|can't|can not|does not|doesn't)\s+(block|stop|prevent)", b), "gate limit"
    assert re.search(r"never\s+type[^.\n]{0,40}device path", b) and "gate confirm" in b, "device path rule"
    assert re.search(r"format[^.\n]{0,60}(not|never)[^.\n]{0,30}evidence|(not|never)[^.\n]{0,40}format[^.\n]{0,30}evidence", b), \
        "format success is not evidence"
    assert "stop_unsafe" in b and "hardware_diagnosis_required" in b and "escalate" in b
    assert "--redact" in b and "shar" in b


# ---------------- H15 / H18 (phase 08)
def test_H15_frontmatter_hooks_registration():
    """H15. Mutation: matcher 'Bash' only (PowerShell unguarded) or two hooks -> red."""
    fm, _ = frontmatter()
    pre = fm["hooks"]["PreToolUse"]
    assert pre[0]["matcher"] == "Bash|PowerShell"
    hooks = pre[0]["hooks"]
    assert len(hooks) == 1 and hooks[0]["type"] == "command" and hooks[0]["command"]


def test_H18_guard_limits_section_lists_every_leak():
    """H18. Mutation: drop 'any open gate unlocks every device' from the leak list -> red."""
    _, body = frontmatter()
    m = re.search(r"^#+ *Guard hook and its limits *$(.*?)(?=^#{1,2} |\Z)", body, re.M | re.S)
    assert m, "section 'Guard hook and its limits' missing"
    s = m.group(1).casefold()
    checks = {
        "obfuscation": r"obfuscat|eval|alias",
        "script files": r"script file|\.py|\.sh|\.ps1",
        "gui tools": r"gui|h2testw|mptool",
        "mcp / non-bash tools": r"mcp|non-bash",
        "outside claude": r"outside claude|user runs",
        "any open gate unlocks all": r"any open gate|one open gate|any `?open`? gate",
        "never invoked": r"never invoked|not invoked|without the skill",
        "rest of session": r"rest of the session",
    }
    missing = [k for k, pat in checks.items() if not re.search(pat, s)]
    assert missing == []
