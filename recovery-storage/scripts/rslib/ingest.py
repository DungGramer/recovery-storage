"""Parsers for external tool output (untrusted input: size-limited, line-oriented, no eval) + ingest commands.

ddrescue mapfile format: GNU ddrescue manual "Mapfile structure" (researcher-04 §1); integers use C++ syntax
(0x hex, leading-0 octal, decimal). F3 exit codes from f3probe.c: 0 good, 101 damaged, 102 limbo,
103 wraparound, 104 chain; anything else is a tool/usage error (researcher-03 §1).
"""
import pathlib
import re
from dataclasses import asdict, dataclass

from . import session as sess
from . import store as st
from .collect import device_row
from .errors import UsageError

MAX_INPUT_BYTES = 16 * 1024 * 1024
BLOCK_CHARS = "?*/-+"
STATUS_CHARS = "?*/-FG+"
F3_CODES = {0: ("good", None), 101: ("damaged", None), 102: ("fake", "limbo"), 103: ("fake", "wraparound"),
            104: ("fake", "chain")}
NUM = re.compile(r"^(0[xX][0-9A-Fa-f]+|0[0-7]*|[1-9][0-9]*)$")


class MalformedInput(Exception):
    def __init__(self, message, line=None):
        super().__init__(message if line is None else f"line {line}: {message}")
        self.line = line


def _num(tok, line):
    if not NUM.match(tok):
        raise MalformedInput(f"not a C++ integer: {tok!r}", line)
    if tok[:2] in ("0x", "0X"):
        return int(tok, 16)
    if len(tok) > 1 and tok[0] == "0":
        return int(tok, 8)
    return int(tok, 10)


@dataclass
class MapSummary:
    total: int
    rescued: int
    bad: int
    non_tried: int
    non_trimmed: int
    non_scraped: int
    rescued_pct: float
    finished: bool
    current_status: str
    start: int = 0
    end: int = 0
    contiguous: bool = True

    def to_dict(self):
        return asdict(self)


def _strip_comment(s):
    m = re.search(r"(^|\s)#", s)
    return s[:m.start()] if m else s


def parse_mapfile(text):
    if len(text.encode("utf-8", "replace")) > MAX_INPUT_BYTES:
        raise MalformedInput("mapfile too large")
    status_line = None
    sums = {c: 0 for c in BLOCK_CHARS}
    blocks = 0
    start = end = None
    contiguous = True
    for i, raw in enumerate(text.splitlines(), 1):
        s = _strip_comment(raw).strip()
        if not s:
            continue
        toks = s.split()
        if status_line is None:
            if len(toks) not in (2, 3) or toks[1] not in STATUS_CHARS or len(toks[1]) != 1:
                raise MalformedInput("bad status line (expected: current_pos current_status [current_pass])", i)
            _num(toks[0], i)
            if len(toks) == 3 and not toks[2].isdigit():
                raise MalformedInput("current_pass must be decimal", i)
            status_line = toks[1]
            continue
        if len(toks) != 3:
            raise MalformedInput("block line needs: pos size status", i)
        pos = _num(toks[0], i)
        size = _num(toks[1], i)
        if toks[2] not in BLOCK_CHARS or len(toks[2]) != 1:
            raise MalformedInput(f"unknown block status {toks[2]!r}", i)
        if start is None:
            start = pos
        elif pos != end:
            contiguous = False
        end = pos + size
        sums[toks[2]] += size
        blocks += 1
    if status_line is None or blocks == 0:
        raise MalformedInput("empty mapfile (no status line or no blocks)")
    total = sum(sums.values())
    return MapSummary(total=total, rescued=sums["+"], bad=sums["-"], non_tried=sums["?"], non_trimmed=sums["*"],
                      non_scraped=sums["/"], rescued_pct=round(100.0 * sums["+"] / total, 1) if total else 0.0,
                      finished=status_line == "+", current_status=status_line, start=start, end=end,
                      contiguous=contiguous)


def _size_line(text, label):
    m = re.search(rf"{re.escape(label)}\s*:?\s*([^\n]+)", text)
    return m.group(1).strip() if m else None


def parse_f3probe(text, exit_code):
    good_text = "Good news" in text
    bad = re.search(r"Bad news:.*?(counterfeit of type (\w+)|is damaged)", text)
    out = {"result": "inconclusive", "fake_type": None, "reason": "", "exit_code": exit_code,
           "usable_size": _size_line(text, "Usable size"), "announced_size": _size_line(text, "Announced size")}
    if exit_code not in F3_CODES:
        out["reason"] = f"exit code {exit_code} is a tool/usage error, not a probe result"
        return out
    result, ftype = F3_CODES[exit_code]
    if result == "good":
        agree = good_text and not bad
    elif result == "damaged":
        agree = bool(bad) and bad.group(1) == "is damaged"
    else:
        agree = bool(bad) and bad.group(2) == ftype
    if not agree and (good_text or bad):
        out["reason"] = f"exit code {exit_code} and output text disagree"
        return out
    out.update(result=result, fake_type=ftype, reason=f"exit code {exit_code}" + ("" if agree else
                                                                                   " (no summary text to cross-check)"))
    return out


def parse_f3write(text, exit_code):
    if "No space!" in text:
        return {"result": "inconclusive", "reason": "nothing written (No space!): free space is needed for f3write",
                "exit_code": exit_code}
    failed = [m.start() for m in re.finditer(r"Write failure|Can't create file", text)]
    if failed:
        tail = re.findall(r"Free space:\s*([^\n]+)", text[failed[0]:])
        if tail and tail[-1].strip().startswith("0.00 Byte"):
            # WSL drvfs reports the full volume as EIO (real run 2026-10-19, amendment 06 F2)
            return {"result": "inconclusive", "reason": "write error when the volume became full (a filesystem-full "
                    "error reported as I/O error, e.g. WSL drvfs); verify with f3read", "exit_code": exit_code}
        return {"result": "fail", "reason": "write failure reported", "exit_code": exit_code}
    if exit_code == 0:
        return {"result": "pass", "reason": "files written", "exit_code": exit_code,
                "free_space": _size_line(text, "Free space")}
    return {"result": "inconclusive", "reason": f"exit code {exit_code}", "exit_code": exit_code}


def _f3read_bytes(text, label):
    m = re.search(rf"{re.escape(label)}:\s*[^\n(]*\((\d+) sectors\)", text)
    return int(m.group(1)) * 512 if m else None


def parse_f3read(text, exit_code):
    """The summary decides; f3read 8.0 exits 0 even with lost data (real card 2026-10-20, amendment 06 F1)."""
    out = {"data_ok_bytes": _f3read_bytes(text, "Data OK"), "data_lost_bytes": _f3read_bytes(text, "Data LOST"),
           "corrupted_bytes": _f3read_bytes(text, "Corrupted"), "changed_bytes": _f3read_bytes(text, "Slightly changed"),
           "overwritten_bytes": _f3read_bytes(text, "Overwritten"), "exit_code": exit_code}
    lost, ok = out["data_lost_bytes"], out["data_ok_bytes"]
    if isinstance(lost, int) and lost > 0:
        out.update(result="fail", reason=f"{lost} bytes lost (corrupted {out['corrupted_bytes']}, changed "
                                         f"{out['changed_bytes']}, overwritten {out['overwritten_bytes']})")
    elif lost == 0 and ok:
        out.update(result="pass", reason="all sectors read back intact")
    else:
        out.update(result="inconclusive", reason=f"exit code {exit_code}, no f3read summary parsed")
    return out


# ------------------------------------------------------------------ commands
def _read(path):
    p = pathlib.Path(path)
    try:
        if p.stat().st_size > MAX_INPUT_BYTES:
            raise UsageError(f"{p} is larger than {MAX_INPUT_BYTES} bytes (pass the mapfile/log, not an image)")
        data = p.read_bytes()
    except OSError as e:
        raise UsageError(f"cannot read {p}: {e}")
    if len(data) > MAX_INPUT_BYTES:
        raise UsageError(f"{p} is larger than {MAX_INPUT_BYTES} bytes")
    return p, data


def save_evidence(ctx, session_id, device_id, kind, level, data, parsed, extra=None, who=None):
    digest = st.sha256_hex(data)
    row = ctx.store.one("SELECT * FROM evidence WHERE session_id = ? AND device_id = ? AND kind = ? AND sha256 = ?",
                        (session_id, device_id, kind, digest))
    if row is not None:
        return {"id": row["id"], "kind": kind, "sha256": digest, "level": row["level"],
                "parsed": current_parsed(ctx.store, row), "existing": True}
    _, path = ctx.store.write_blob(data, ctx.store.evidence_subdir(session_id), f".{kind}")
    eid = st.new_id("E")
    body = {"parsed": parsed}
    body.update(extra or {})
    ctx.store.execute("INSERT INTO evidence (id, ts, session_id, device_id, kind, level, sha256, path, data, who) "
                      "VALUES (?,?,?,?,?,?,?,?,?,?)",
                      (eid, ctx.store.now(), session_id, device_id, kind, level, digest, path, st.dumps(body),
                       who or ctx.who))
    return {"id": eid, "kind": kind, "sha256": digest, "level": level, "parsed": parsed, "existing": False}


def current_parsed(store, row):
    """Parsed result of an evidence row by the CURRENT parser, from the stored blob and exit code; the stored parsed
    copy is only a fallback (amendment 06 F5: rows written by an older parser must not decide a verdict)."""
    d = row["data"] if isinstance(row["data"], dict) else (st.loads(row["data"]) or {})
    old = d.get("parsed") or {}
    parser = REPARSE.get(row["kind"])
    if parser is None or not row.get("path"):
        return old
    try:
        text = store.read_blob(row["path"]).decode("utf-8", "replace")
    except OSError:
        return old
    if row["kind"] == "ddrescue":
        try:
            return parse_mapfile(text).to_dict()
        except MalformedInput:
            return old
    return parser(text, old.get("exit_code"))


def evidence_rows(store, session_id, device_id):
    rows = store.query("SELECT * FROM evidence WHERE session_id = ? AND device_id = ? ORDER BY ts, rowid",
                       (session_id, device_id))
    for r in rows:
        r["data"] = st.loads(r["data"]) or {}
        r["data"]["parsed"] = current_parsed(store, r)
    return rows


def _prepare(ctx, a):
    sess.load(ctx.store, a.session)
    device_row(ctx.store, a.device)
    return _read(a.file)


def _reply(ctx, ev, kind, text):
    data = {"evidence": {k: ev[k] for k in ("id", "kind", "sha256", "level", "parsed")}}
    return ctx.reply(data, f"{kind}: {text} (evidence {ev['id']}{', already ingested' if ev['existing'] else ''})")


def cmd_ingest_ddrescue(ctx, a):
    p, data = _prepare(ctx, a)
    try:
        m = parse_mapfile(data.decode("utf-8", "replace"))
    except MalformedInput as e:
        raise UsageError(f"malformed mapfile {p.name}: {e}", ["malformed"])
    ev = save_evidence(ctx, a.session, a.device, "ddrescue", "parsed", data, m.to_dict(), {"file": p.name})
    return _reply(ctx, ev, "ddrescue", f"rescued {m.rescued}/{m.total} bytes ({m.rescued_pct}%), bad {m.bad}, "
                                       f"finished {m.finished}")


def _f3(ctx, a, kind, parser):
    p, data = _prepare(ctx, a)
    if a.exit_code is None:
        raise UsageError(f"ingest {kind} needs --exit-code (the tool's exit status is the primary signal)")
    parsed = parser(data.decode("utf-8", "replace"), a.exit_code)
    ev = save_evidence(ctx, a.session, a.device, kind, "parsed", data, parsed, {"file": p.name})
    return _reply(ctx, ev, kind, f"{parsed['result']} ({parsed['reason']})")


def cmd_ingest_f3probe(ctx, a):
    return _f3(ctx, a, "f3probe", parse_f3probe)


def cmd_ingest_f3write(ctx, a):
    return _f3(ctx, a, "f3write", parse_f3write)


def cmd_ingest_f3read(ctx, a):
    return _f3(ctx, a, "f3read", parse_f3read)


def cmd_ingest_attested(ctx, a):
    if not a.file:
        raise UsageError("ingest attested needs --file (log or screenshot of the tool result)")
    from .operator import require_echo_safe

    require_echo_safe(file=a.file, note=a.note, home=ctx.home_flag)
    sess.load(ctx.store, a.session)
    fp = device_row(ctx.store, a.device)["fingerprint"]
    p, data = _read(a.file)
    from .datastate import operator_yes

    operator_yes(ctx, f"attest {a.tool} {a.result} for {a.device} ({fp.get('model')}, {fp.get('bytes')} bytes), "
                      f"attachment {p.name}",
                 ["ingest", "attested", a.session, a.device, "--tool", a.tool, "--result", a.result, "--file",
                  f'"{p.resolve()}"'])
    parsed = {"tool": a.tool, "result": a.result, "note": a.note, "file": p.name, "attested_by": "operator"}
    ev = save_evidence(ctx, a.session, a.device, "attested", "attested", data, parsed, {"file": p.name},
                       who="operator")
    return _reply(ctx, ev, "attested", f"{a.tool} {a.result} (operator attestation, sha256 {ev['sha256']})")


REPARSE = {"f3probe": parse_f3probe, "f3write": parse_f3write, "f3read": parse_f3read, "ddrescue": parse_mapfile}
