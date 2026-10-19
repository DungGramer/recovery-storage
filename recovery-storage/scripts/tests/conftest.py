"""Shared helpers for the frozen spec-first suite (contract: tests/CONTRACT.md).

rslib is imported only inside helpers/tests, so collection succeeds before implementation and every
test fails on its own until the module it needs exists (a missing module FAILS, never skips).
No helper here spawns smartctl/PowerShell: CLI tests get a RecordedRunner answered from real captures.
"""
import base64
import contextlib
import datetime as dt
import io
import hashlib
import json
import pathlib
import re
import unicodedata

import pytest

SCRIPTS = pathlib.Path(__file__).resolve().parents[1]
SKILL_DIR = SCRIPTS.parent
REPO = SKILL_DIR.parent
TESTS = SCRIPTS / "tests"
FIX = TESTS / "fixtures"
PS_DIR = SCRIPTS / "rslib" / "ps"
PLAN_DIR = REPO / "plans" / "20261019-1726-recovery-storage-skill"
UTC = dt.timezone.utc

BASELINE = "windows/baseline-nvme-only"
USB_STICK = "windows/usb-stick"
USB_SD = "windows/usb-sd"

GOALS = ["data-recovery", "device-recovery", "diagnosis-only", "authenticity-check",
         "health-assessment", "forensic-preservation"]
SYMPTOMS = ["mechanical-noise", "burning-smell", "physical-damage", "liquid-damage", "overheating",
            "not-detected", "disconnects-repeatedly", "slow-io", "read-only", "wrong-capacity",
            "raw-or-unreadable-fs", "missing-partition", "deleted-files", "io-errors", "encrypted-locked",
            "not-spinning"]
TRIAGE_CLASSES = ["SOFTWARE_RECOVERY_CANDIDATE", "CONTROLLER_RECOVERY_CANDIDATE",
                  "HARDWARE_DIAGNOSIS_REQUIRED", "STOP_UNSAFE", "UNDETERMINED"]
CATEGORIES = ["connection-cable-power-bridge", "partition-or-filesystem", "bad-sectors-io",
              "controller-or-firmware", "nand-degradation", "fake-capacity-or-counterfeit", "write-locked",
              "encryption-or-protection", "physical-hardware"]
REPORT_HEADINGS = ["Mục tiêu xử lý", "Thông tin nhận dạng", "Triệu chứng và bằng chứng",
                   "Chẩn đoán và mức độ tin cậy", "Phương án đã thử", "Công cụ, phiên bản, kết quả",
                   "Thay đổi đã thực hiện", "Kiểm định sau phục hồi", "Trạng thái cuối cùng",
                   "Hạn chế còn tồn tại", "Khuyến nghị sử dụng"]

# Real (non-derived) smartctl fixtures, SOURCES.md "smartctl/" table.
REAL_SMART = sorted(p.name for p in (FIX / "smartctl").glob("*.json") if ".derived." not in p.name)


# ---------------------------------------------------------------- fixture files
def fx(rel):
    return FIX / rel


def fx_bytes(rel):
    return fx(rel).read_bytes()


def fx_text(rel):
    return fx(rel).read_text(encoding="utf-8")


def fx_json(rel):
    return json.loads(fx_text(rel))


def sha256_hex(data):
    return hashlib.sha256(data).hexdigest()


def norm(s):
    """Case-insensitive, Unicode-NFC comparison form."""
    return unicodedata.normalize("NFC", str(s)).casefold()


def ps_args(script_id, text=None):
    """Exact PowerShell argv (without executable) per phase 01 allow-list."""
    if text is None:
        text = (PS_DIR / f"{script_id}.ps1").read_text(encoding="utf-8")
    b64 = base64.b64encode(text.encode("utf-16-le")).decode("ascii")
    return ["-NoProfile", "-NonInteractive", "-EncodedCommand", b64]


def eui64_of(smart_doc):
    """`002538` + 10 hex of ext_id (phase 02 key insight), from a smartctl document."""
    e = smart_doc["nvme_namespaces"][0]["eui64"]
    return f"{e['oui']:06x}{e['ext_id']:010x}"


# ---------------------------------------------------------------- clock
class FakeClock:
    """Deterministic UTC clock: every call advances one second (ordering = call order)."""

    def __init__(self, start=dt.datetime(2026, 10, 20, 0, 0, 0, tzinfo=UTC)):
        self.now = start

    def __call__(self):
        self.now = self.now + dt.timedelta(seconds=1)
        return self.now

    def advance(self, **kw):
        self.now = self.now + dt.timedelta(**kw)


# ---------------------------------------------------------------- recordings
_RUNNERS = []


def _exit_and_version(rel, data):
    meta = fx(rel + ".meta.json")
    exit_code = None
    if meta.exists():
        exit_code = json.loads(meta.read_text(encoding="utf-8"))["exit_code"]
    version = None
    try:
        doc = json.loads(data)
    except ValueError:
        doc = None
    if isinstance(doc, dict) and isinstance(doc.get("smartctl"), dict):
        sm = doc["smartctl"]
        if exit_code is None:
            exit_code = sm.get("exit_status")
        if sm.get("version"):
            version = ".".join(str(x) for x in sm["version"])
    return (0 if exit_code is None else exit_code), version


def recording(tool_id, args, rel=None, **kw):
    """Recording answering (tool_id, args) with fixture `rel` (exit code from .meta.json or smartctl block)."""
    from rslib.runner import Recording

    if rel is not None:
        data = fx_bytes(rel)
        exit_code, version = _exit_and_version(rel, data)
        kw.setdefault("stdout", data)
        kw.setdefault("exit_code", exit_code)
        if tool_id == "smartctl":
            kw.setdefault("tool_version", version)
    return Recording(tool_id, list(args), **kw)


def _smart_args(dev):
    return [["-j", "-i", "-n", "standby", dev], ["-j", "-x", "-n", "standby", dev],
            ["-j", "-x", dev], ["-j", "-i", dev]]


def _sat_args(dev):
    return [["-j", "-x", "-n", "standby", "-d", "sat", dev], ["-j", "-i", "-n", "standby", "-d", "sat", dev],
            ["-j", "-x", "-d", "sat", dev]]


def capture_files(capture):
    base = FIX / capture
    files = {}
    for key, name in (("win-disks", "win-disks.json"), ("win-pnp-chain", "win-pnp-chain.json"),
                      ("win-events", "win-events.json"), ("scan-open", "smartctl-scan-open.json")):
        if (base / name).exists():
            files[key] = f"{capture}/{name}"
    for p in sorted(base.glob("smartctl-x-*pd*.json")):
        if ".derived." in p.name:
            continue
        m = re.fullmatch(r"smartctl-x-(sat-)?pd(\d+)\.json", p.name)
        if m:
            files[("sat-pd" if m.group(1) else "pd") + m.group(2)] = f"{capture}/{p.name}"
    return files


def capture_recordings(capture, override=None, extra=()):
    """Recordings for every R0 command the contract allows against a Windows capture.

    override: {key: fixture rel path | dict of Recording kwargs | None (drop)}; keys:
    win-disks, win-pnp-chain, win-events, scan-open, pd<N>, sat-pd<N>.
    Identity probe `-j -i ...` is answered with the `-x` capture of the same disk (superset;
    documented in fixtures/SOURCES.md "Recording substitutions").
    """
    files = capture_files(capture)
    for k, v in (override or {}).items():
        if v is None:
            files.pop(k, None)
        else:
            files[k] = v
    recs = []

    def add(tool, args, src):
        if isinstance(src, dict):
            recs.append(recording(tool, args, **src))
        else:
            recs.append(recording(tool, args, src))

    for key, src in files.items():
        if key in ("win-disks", "win-pnp-chain", "win-events"):
            add("powershell", ps_args(key), src)
        elif key == "scan-open":
            add("smartctl", ["--scan-open", "-j"], src)
        elif key.startswith("sat-pd"):
            for a in _sat_args("/dev/pd" + key[6:]):
                add("smartctl", a, src)
        elif key.startswith("pd"):
            for a in _smart_args("/dev/pd" + key[2:]):
                add("smartctl", a, src)
    recs.extend(extra)
    return recs


def make_runner(capture=None, override=None, extra=(), replace=None):
    """replace: {(tool_id, tuple(args)): rel | Recording kwargs} swaps single recordings (exact argv)."""
    from rslib.runner import RecordedRunner

    recs = capture_recordings(capture, override, extra) if capture else list(extra)
    for (tool, args), src in (replace or {}).items():
        recs = [r for r in recs if not (r.tool_id == tool and tuple(r.args) == tuple(args))]
        recs.append(recording(tool, list(args), **src) if isinstance(src, dict) else recording(tool, list(args), src))
    r = RecordedRunner(recs)
    _RUNNERS.append(r)
    return r


@pytest.fixture(autouse=True)
def _no_unrecorded_commands():
    """A19: tests never silently pass on an unexpected command, even if the CLI swallowed the raise."""
    _RUNNERS.clear()
    yield
    bad = [(i, r.unrecorded) for i, r in enumerate(_RUNNERS) if getattr(r, "unrecorded", None)]
    _RUNNERS.clear()
    assert not bad, f"RecordedRunner got unrecorded commands: {bad}"


# ---------------------------------------------------------------- CLI driver
class Result:
    def __init__(self, code, out, err, data, prompts=None, answers=None):
        self.code, self.out, self.err, self.data = code, out, err, data
        self.prompts = list(prompts or [])   # every operator.ask() prompt, in order (amendment 01 A)
        self.answers = list(answers or [])   # scripted answers given to the operator

    @property
    def text(self):
        return self.out + "\n" + self.err

    @property
    def reasons(self):
        return set((self.data or {}).get("reasons") or [])

    @property
    def message(self):
        return str((self.data or {}).get("message") or "")

    def __repr__(self):
        return f"Result(code={self.code}, out={self.out[:1500]!r}, err={self.err[:800]!r})"


_SCRIPTED = object()


class RecordingOperator:
    """Amendment 01 A: wraps rslib.operator.ScriptedOperator (answers in order, exhausted -> NoConsole) and
    records each prompt so tests can assert what the human was asked."""

    def __init__(self, answers):
        from rslib.operator import ScriptedOperator

        self.answers = list(answers)
        self.inner = ScriptedOperator(list(answers))
        self.prompts = []

    def ask(self, prompt):
        self.prompts.append(prompt)
        return self.inner.ask(prompt)


class Cli:
    """In-process `rs.py` driver: rslib.cli.main(argv, runner=..., clock=..., os_family=..., operator=...).

    Operator (amendment 01 A): `answers=[...]` -> a ScriptedOperator answering in order. With neither `answers`
    nor `operator`, an EMPTY ScriptedOperator is passed, so a command that asks the human gets NoConsole
    (exit 3 operator-console-required) and a test never blocks on a real console. `operator=None` passes None
    explicitly (production default: ConsoleOperator); `operator=obj` passes obj.
    """

    def __init__(self, home, runners=None):
        self.home = home
        self.clock = FakeClock()
        self.runners = runners  # optional private registry (module-scoped corpora)

    def runner(self, *a, **k):
        r = make_runner(*a, **k)
        if self.runners is not None:
            self.runners.append(r)
        return r

    def __call__(self, *args, runner=None, json_out=True, os_family="windows", home="default", answers=None,
                 operator=_SCRIPTED):
        from rslib import cli as rcli

        if runner is None:
            runner = self.runner()  # empty: any spawn attempt is an unrecorded command
        if operator is _SCRIPTED:
            operator = RecordingOperator(answers or [])
        else:
            assert answers is None, "pass answers= or operator=, not both"
        argv = []
        h = self.home if home == "default" else home
        if h is not None:
            argv += ["--home", str(h)]
        if json_out:
            argv.append("--json")
        argv += [str(a) for a in args]
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                code = rcli.main(argv, runner=runner, clock=self.clock, os_family=os_family, operator=operator)
            except SystemExit as e:  # argparse usage errors
                code = e.code if isinstance(e.code, int) else (0 if e.code is None else 2)
        o, e = out.getvalue(), err.getvalue()
        data = None
        if json_out and o.strip():
            try:
                data = json.loads(o)
            except ValueError:
                data = None
        assert "Traceback (most recent call last)" not in e, e
        rec = operator if isinstance(operator, RecordingOperator) else None
        return Result(code, o, e, data, rec.prompts if rec else None, rec.answers if rec else None)


@pytest.fixture
def home(tmp_path):
    return tmp_path / "rshome"


@pytest.fixture
def cli(home):
    return Cli(home)


# ---------------------------------------------------------------- flow helpers
def ok(res, code=0):
    assert res.code == code, res
    return res.data


def new_session(cli, *flags):
    res = cli("session", "new", *(flags or ("--goal", "diagnosis-only")))
    return ok(res)["session"]["id"]


def inventory(cli, runner, sid=None, after_replug=False, expect=0):
    args = ["inventory"]
    if sid:
        args += ["--session", sid]
    if after_replug:
        args.append("--after-replug")
    res = cli(*args, runner=runner)
    assert res.code == expect, res
    return res


def obs_for(res, os_path):
    for o in res.data["observations"]:
        if o["os_path"] == os_path:
            return o
    raise AssertionError(f"no observation for {os_path}: {res}")


def device_at(cli, capture, sid, os_path, override=None):
    """Inventory a capture and return the device id observed at os_path."""
    res = inventory(cli, cli.runner(capture, override), sid)
    dev = obs_for(res, os_path)["device_id"]
    assert dev, res
    return dev


def collect(cli, capture, sid, dev, *extra, override=None, expect=0):
    res = cli("collect", dev, "--session", sid, *extra, runner=cli.runner(capture, override))
    assert res.code == expect, res
    return res


def assess(cli, sid, dev, expect=0):
    res = cli("assess", sid, dev)
    assert res.code == expect, res
    return res.data["assessment"] if res.data else None


def prepared(cli, capture, os_path, *session_flags, override=None):
    """session new -> inventory -> collect -> assess for the disk at os_path. Returns (sid, dev, assessment)."""
    sid = new_session(cli, *session_flags)
    dev = device_at(cli, capture, sid, os_path, override)
    collect(cli, capture, sid, dev, override=override)
    a = assess(cli, sid, dev)
    return sid, dev, a


def ingest_smart(cli, sid, rel, expect=0):
    res = cli("ingest", "smartctl", fx(rel), "--session", sid)
    assert res.code == expect, res
    return res


def ingested_assessment(cli, rel, *session_flags):
    """session new -> ingest smartctl fixture -> assess. Returns (sid, dev, assessment)."""
    sid = new_session(cli, *session_flags)
    dev = ingest_smart(cli, sid, rel).data["device_id"]
    return sid, dev, assess(cli, sid, dev)


def open_gate(cli, capture, sid, dev, kind, *extra, override=None):
    return cli("gate", "open", sid, dev, kind, *extra, runner=cli.runner(capture, override))


def ev_text(items):
    return json.dumps(items, ensure_ascii=False)


def ev_paths(items):
    return [str(e.get("path")) for e in items]


def smart(rel):
    from rslib import smart as rsmart

    return rsmart.normalise(fx_bytes(rel))


# ---------------------------------------------------------------- gate helpers (phase 04)
MAP_PARTIAL = "ingest/ddrescue-manual-1.30.map"
MAP_FINISHED = "ingest/ddrescue-manual-1.30.finished.derived.map"   # finished, but a 1474560 B floppy image
# Amendment 01 B: finished AND covering the whole device (ends exactly at the device byte count).
MAP_980 = "ingest/ddrescue-finished.980pro.derived.map"            # BASELINE /dev/pd1, 2000398934016 B
MAP_990 = "ingest/ddrescue-finished.990pro.derived.map"            # BASELINE /dev/pd0, 1000204886016 B
MAP_HDD500 = "ingest/ddrescue-finished.hitachi500.derived.map"      # scrutiny-usbjmicron-hdd-failing, 500107862016 B
BYTES_980 = 2000398934016
BYTES_990 = 1000204886016
FLOPPY_BYTES = 1474560
OPERATOR_REASONS = {"operator-console-required", "operator-declined"}


def serial_980():
    return fx_json(f"{BASELINE}/smartctl-x-pd1.json")["serial_number"]


def phrase_980():
    """Serial trust high -> last 4 chars of the normalised serial (phase 04 'expected phrase')."""
    return serial_980().strip().upper().rstrip(".")[-4:]


def nvme1(cli, *flags, capture=BASELINE):
    sid, dev, _ = prepared(cli, capture, "/dev/pd1", *flags)
    return sid, dev


def stick(cli, *flags):
    sid, dev, _ = prepared(cli, USB_STICK, "/dev/pd2", *flags)
    return sid, dev


def other_device(cli, capture, sid, dev, dest_path=None):
    """Device id of another attached disk of `capture` (dest of an image gate): `dest_path`, else the first
    observed disk that is not `dev`."""
    res = inventory(cli, cli.runner(capture), sid)
    if dest_path is not None:
        return obs_for(res, dest_path)["device_id"]
    return next(o["device_id"] for o in res.data["observations"] if o["device_id"] and o["device_id"] != dev)


def image_gate(cli, capture, sid, dev, outcome="success", dest_path=None):
    """Amendment 02 C: open + operator-confirm (+ close with `outcome`, unless outcome is None) an `image-ddrescue`
    gate on `dev`, dest = another attached device of the same capture. The session ceiling must allow R1.
    Returns the gate id."""
    dest = other_device(cli, capture, sid, dev, dest_path)
    g, opened = gate_ok(cli, capture, sid, dev, "image-ddrescue", "--dest-device", dest)
    res = confirm(cli, capture, g, opened.data["confirmation"]["phrase"])
    assert res.code == 0 and res.data["gate"]["state"] == "open", res
    if outcome is not None:
        res = close(cli, capture, g, outcome)
        assert res.code == 0 and res.data["gate"]["state"] == "closed", res
    return g


def secure(cli, sid, dev, mapfile=MAP_980, capture=BASELINE):
    """Amendment 02 C: image-ddrescue gate (open, confirm, close success) -> ingest ddrescue -> data-state secured
    --evidence (no operator: --evidence is tool evidence). Default map covers the 980 PRO (nvme1 / BASELINE /dev/pd1)
    exactly; other devices pass their own map. The session ceiling must allow R1 (the image gate)."""
    image_gate(cli, capture, sid, dev)
    ev = ok(cli("ingest", "ddrescue", sid, dev, fx(mapfile)))["evidence"]["id"]
    res = cli("session", "data-state", sid, dev, "secured", "--evidence", ev)
    return ev, res


def gate_ok(cli, capture, sid, dev, kind, *extra, override=None):
    res = open_gate(cli, capture, sid, dev, kind, *extra, override=override)
    assert res.code == 0, res
    assert res.data["gate"]["state"] == "pending"
    return res.data["gate"]["id"], res


def confirm(cli, capture, gate, phrase, override=None, json_out=True):
    """Amendment 01 A: no --phrase; the human types `phrase` at the operator prompt."""
    return cli("gate", "confirm", gate, runner=cli.runner(capture, override), answers=[phrase], json_out=json_out)


def close(cli, capture, gate, outcome="success", *extra, override=None):
    return cli("gate", "close", gate, "--outcome", outcome, *extra, runner=cli.runner(capture, override))


def gate_open_state(cli, capture, sid, dev, kind, phrase, *extra, override=None):
    """open + confirm -> state open. Returns gate id."""
    g, _ = gate_ok(cli, capture, sid, dev, kind, *extra, override=override)
    res = confirm(cli, capture, g, phrase, override)
    assert res.code == 0, res
    assert res.data["gate"]["state"] == "open"
    return g


# ---------------------------------------------------------------- store reads (amendment 01 A audit columns)
def db_rows(home, table):
    """All rows of `table` as dicts (table names fixed in CONTRACT.md sec. 5 / amendment 01)."""
    import sqlite3

    con = sqlite3.connect(pathlib.Path(home) / "rs.sqlite")
    con.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in con.execute(f"SELECT * FROM {table}")]
    finally:
        con.close()


def make_parsed_stale(home, evidence_id, old):
    """Amendment 06 F5: simulate a row written by an older parser. Every JSON text column of the evidence row that
    holds a parser result (top level or under `parsed`) gets `old` (dict) instead, keeping its `exit_code`; the blob
    file and `sha256` are not touched. Column-agnostic on purpose: the contract fixes behaviour, not the column."""
    import sqlite3

    con = sqlite3.connect(pathlib.Path(home) / "rs.sqlite")
    try:
        cols = [r[1] for r in con.execute("PRAGMA table_info(evidence)")]
        row = con.execute("SELECT * FROM evidence WHERE id = ?", (evidence_id,)).fetchone()
        assert row is not None, evidence_id
        for col, val in zip(cols, row):
            if not isinstance(val, str):
                continue
            try:
                doc = json.loads(val)
            except ValueError:
                continue
            if not isinstance(doc, dict):
                continue
            target = doc.get("parsed") if isinstance(doc.get("parsed"), dict) else doc
            if "result" not in target:
                continue
            code = target.get("exit_code")
            target.clear()
            target.update(old)
            if code is not None:
                target["exit_code"] = code
            con.execute(f"UPDATE evidence SET {col} = ? WHERE id = ?", (json.dumps(doc), evidence_id))
        con.commit()
    finally:
        con.close()


# Pre-amendment-06 f3read parse of a summary-bearing exit-0 output (live store row E-0fa5fe3226ed shape).
F3READ_OLD_INCONCLUSIVE = {"result": "inconclusive", "reason": "exit code 0 / summary not parsed",
                           "data_ok_bytes": None, "data_lost_bytes": None, "overwritten_bytes": None}


def operator_state(home):
    """Rows an operator command may change (amendment 01 A 'nothing is changed in the store')."""
    return {t: sorted(map(repr, db_rows(home, t))) for t in ("gates", "data_states", "evidence")}


# ---------------------------------------------------------------- amendment 02 helpers
# Look-alike stick: the same capture with only Disk 2's MBR Signature changed (fixtures/SOURCES.md).
OTHERSIG = {"win-disks": f"{USB_STICK}/win-disks.othersig.derived.json"}
STICK_BYTES = 8054112256
STICK_PHRASE = "8054112256"   # junk serial -> phrase = byte count (D11)


def link(cli, obs, target, answers=("YES",), **kw):
    """Amendment 02 A: `device link <observation> <device|--new>` asks the operator; tests answer YES by default."""
    return cli("device", "link", obs, target, answers=list(answers) if answers is not None else None, **kw)


def printed_link_command(res, dev):
    """Amendment 02 A: the close output prints `device link <observation> <device>`. Returns the observation token
    (None when no such command is printed)."""
    m = re.search(r"device link\s+\"?([A-Za-z0-9_.:-]+)\"?\s+\"?" + re.escape(str(dev)), res.out + "\n" + res.err)
    return m.group(1) if m else None


def assert_console_required(res, *command_words):
    """Amendment 01 A: exit 3 operator-console-required; message carries `python <abs>/rs.py <command words>`
    (separators normalised, case-folded; an optional global `--home <path>` before the subcommand tolerated)."""
    assert res.code == 3, res
    assert "operator-console-required" in res.reasons, res
    msg = (res.message + "\n" + res.text).replace("\\", "/").casefold()
    rs = re.escape((SCRIPTS / "rs.py").as_posix().casefold())
    words = r"\s+".join(re.escape(str(w).casefold()) for w in command_words)
    pat = rf"python(?:3)?(?:\.exe)?\"?\s+\"?{rs}\"?\s+(?:--home\s+\S+\s+)?{words}"
    assert re.search(pat, msg), (pat, res)
