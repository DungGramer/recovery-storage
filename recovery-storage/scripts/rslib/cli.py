"""rs.py command tree. Every command: resolve home -> open store (schema check first) -> handler -> one output.

Exit codes: 0 ok, 2 usage, 3 refused (safety/evidence rule), 4 tool/environment failure, 5 needs human decision.
With --json, stdout is exactly one JSON object: {ok, exit_code, reasons, message, ...command keys}.
"""
import argparse
import datetime as dt
import importlib
import json
import sqlite3
import sys

from . import paths, session
from .errors import CommandError, EnvFailure, Refused
from .store import open_store

# subcommand -> "module:function"; handlers are imported lazily so each phase's module stays independent
HANDLERS = {
    ("session", "new"): "session:cmd_new",
    ("session", "show"): "session:cmd_show",
    ("session", "list"): "session:cmd_list",
    ("session", "set"): "session:cmd_set",
    ("session", "note"): "session:cmd_note",
    ("session", "data-state"): "datastate:cmd_data_state",
    ("inventory",): "collect:cmd_inventory",
    ("collect",): "collect:cmd_collect",
    ("device", "link"): "collect:cmd_device_link",
    ("device", "list"): "fleet:cmd_device_list",
    ("device", "show"): "fleet:cmd_device_show",
    ("ingest", "smartctl"): "collect:cmd_ingest_smartctl",
    ("ingest", "ddrescue"): "ingest:cmd_ingest_ddrescue",
    ("ingest", "f3probe"): "ingest:cmd_ingest_f3probe",
    ("ingest", "f3write"): "ingest:cmd_ingest_f3write",
    ("ingest", "f3read"): "ingest:cmd_ingest_f3read",
    ("ingest", "attested"): "ingest:cmd_ingest_attested",
    ("assess",): "assess:cmd_assess",
    ("gate", "open"): "gate:cmd_open",
    ("gate", "confirm"): "gate:cmd_confirm",
    ("gate", "close"): "gate:cmd_close",
    ("gate", "abort"): "gate:cmd_abort",
    ("gate", "list"): "gate:cmd_list",
    ("verdict", "set"): "verdict:cmd_set",
    ("verdict", "show"): "verdict:cmd_show",
    ("report",): "report:cmd_report",
    ("compare",): "fleet:cmd_compare",
    ("rules",): "rules_doc:cmd_rules",
}

VERDICT_STATUSES = ["PASS", "PASS_LIMITED", "FAIL", "REPAIR_REQUIRED", "UNRESOLVED", "RETIRED"]
OUTCOMES = ["success", "failed", "interrupted"]


class Ctx:
    def __init__(self, store, runner, clock, os_family, json_out, who, operator=None, home_flag=None):
        self.store, self.runner, self.clock = store, runner, clock
        self.os_family, self.json, self.who = os_family, json_out, who
        self.operator, self.home_flag = operator, home_flag

    def ask_operator(self, prompt, argv_tail):
        """One line typed by the human at an interactive console (amendment 01)."""
        from .operator import NoConsole, console_command

        try:
            return self.operator.ask(prompt)
        except NoConsole:
            tail = (["--home", f'"{self.home_flag}"'] if self.home_flag else []) + list(argv_tail)
            raise Refused("this step needs the operator at an interactive console (the agent cannot confirm for "
                          "you). Run in your own terminal:\n  " + console_command(tail),
                          ["operator-console-required"], {"command": console_command(tail)})

    def reply(self, data=None, text="", code=0, reasons=()):
        return Reply(code, data or {}, text, list(reasons))


class Reply:
    def __init__(self, code, data, text, reasons):
        self.code, self.data, self.text, self.reasons = code, data, text, reasons


def _session_args(p, required_goal):
    p.add_argument("--goal", action="append", choices=session.GOALS, required=required_goal)
    p.add_argument("--ceiling", choices=session.CEILINGS)
    p.add_argument("--data-value", choices=session.DATA_VALUES)
    p.add_argument("--risk-tolerance", choices=session.RISK_TOLERANCES)


def build_parser():
    p = argparse.ArgumentParser(prog="rs.py", description="recovery-storage: R0 evidence, triage, gated actions, "
                                "evidence-based verdicts and reports for storage devices")
    p.add_argument("--home", help="case store directory (default: $RECOVERY_STORAGE_HOME or ~/.recovery-storage)")
    p.add_argument("--json", action="store_true", help="print exactly one JSON object")
    p.add_argument("--who", choices=session.WHO, default="agent", help="actor recorded in audit events")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("session", help="Phase 0: goals, risk ceiling, data value, symptoms")
    ss = s.add_subparsers(dest="sub", required=True)
    n = ss.add_parser("new")
    _session_args(n, True)
    n.add_argument("--preserve-data", choices=session.PRESERVE)
    n.add_argument("--device-type")
    n.add_argument("--nominal")
    n.add_argument("--symptom", action="append", choices=session.SYMPTOMS)
    n.add_argument("--tried", action="append", choices=session.TRIED)
    n.add_argument("--note")
    n.add_argument("--os")
    ss.add_parser("show").add_argument("session")
    ss.add_parser("list")
    st_ = ss.add_parser("set")
    st_.add_argument("session")
    _session_args(st_, False)
    nt = ss.add_parser("note")
    nt.add_argument("session")
    nt.add_argument("text")
    ds = ss.add_parser("data-state")
    ds.add_argument("session")
    ds.add_argument("device")
    ds.add_argument("state", choices=["secured", "waived", "not-needed"])
    ds.add_argument("--evidence")
    ds.add_argument("--attested", action="store_true")
    ds.add_argument("--reason")

    inv = sub.add_parser("inventory", help="R0: list attached devices with multi-attribute fingerprints")
    inv.add_argument("--session")
    inv.add_argument("--after-replug", action="store_true")

    c = sub.add_parser("collect", help="R0: identity + SMART (smartctl) + OS storage events for one device")
    c.add_argument("device")
    c.add_argument("--session", required=True)
    c.add_argument("--dtype")
    c.add_argument("--allow-spinup", action="store_true")

    d = sub.add_parser("device", help="device link / list / show")
    dd = d.add_subparsers(dest="sub", required=True)
    dl = dd.add_parser("link")
    dl.add_argument("observation")
    dl.add_argument("device", nargs="?")
    dl.add_argument("--new", action="store_true")
    dli = dd.add_parser("list")
    dli.add_argument("--group-by", choices=["triage", "category", "status"])
    dd.add_parser("show").add_argument("device")

    i = sub.add_parser("ingest", help="attach external tool output as evidence")
    ii = i.add_subparsers(dest="sub", required=True)
    ism = ii.add_parser("smartctl")
    ism.add_argument("file")
    ism.add_argument("--session", required=True)
    for kind in ("ddrescue", "f3probe", "f3write", "f3read"):
        k = ii.add_parser(kind)
        k.add_argument("session")
        k.add_argument("device")
        k.add_argument("file")
        k.add_argument("--exit-code", type=int)
    at = ii.add_parser("attested")
    at.add_argument("session")
    at.add_argument("device")
    at.add_argument("--tool", choices=["h2testw", "other"], required=True)
    at.add_argument("--result", choices=["pass", "fail"], required=True)
    at.add_argument("--file")
    at.add_argument("--note")

    a = sub.add_parser("assess", help="health verdict, Phase-1 triage class, hypotheses")
    a.add_argument("session")
    a.add_argument("device")

    g = sub.add_parser("gate", help="identity re-check + human confirmation around a risky action")
    gg = g.add_subparsers(dest="sub", required=True)
    go = gg.add_parser("open")
    go.add_argument("session")
    go.add_argument("device")
    go.add_argument("kind")
    go.add_argument("--dest-device")
    go.add_argument("--controller-id")
    go.add_argument("--tool-source")
    gc = gg.add_parser("confirm")
    gc.add_argument("gate")
    gcl = gg.add_parser("close")
    gcl.add_argument("gate")
    gcl.add_argument("--outcome", choices=OUTCOMES, required=True)
    gcl.add_argument("--note")
    gcl.add_argument("--evidence", action="append")
    ga = gg.add_parser("abort")
    ga.add_argument("gate")
    ga.add_argument("--reason", required=True)
    gg.add_parser("list")

    v = sub.add_parser("verdict", help="final status, refused without the required evidence")
    vv = v.add_subparsers(dest="sub", required=True)
    vs = vv.add_parser("set")
    vs.add_argument("session")
    vs.add_argument("device")
    vs.add_argument("status", choices=VERDICT_STATUSES)
    vs.add_argument("--limitation")
    vs.add_argument("--reason")
    vsh = vv.add_parser("show")
    vsh.add_argument("session")
    vsh.add_argument("device")

    r = sub.add_parser("report", help="spec §7 report per device")
    r.add_argument("session")
    r.add_argument("--device")
    r.add_argument("--redact", action="store_true")
    r.add_argument("--out")
    r.add_argument("--force", action="store_true")
    r.add_argument("--check", action="store_true")

    cmp_ = sub.add_parser("compare", help="delta between two snapshots")
    cmp_.add_argument("snapshots", nargs="*")
    cmp_.add_argument("--device")

    sub.add_parser("rules", help="print health/triage rules, parameters and wear whitelist")
    return p


def _key(a):
    sub = getattr(a, "sub", None)
    return (a.cmd, sub) if sub else (a.cmd,)


def _handler(key):
    mod, fn = HANDLERS[key].split(":")
    return getattr(importlib.import_module(f"rslib.{mod}"), fn)


def _emit(json_out, code, data, text, reasons, message):
    if json_out:
        obj = {"ok": code == 0, "exit_code": code, "reasons": list(reasons), "message": message or ""}
        obj.update(data or {})
        sys.stdout.write(json.dumps(obj, ensure_ascii=False, default=str) + "\n")
        return
    if code == 0:
        if text:
            sys.stdout.write(text + "\n")
        return
    out = sys.stdout if code in (3, 5) else sys.stderr
    lines = [message] if message else []
    if text and text != message:
        lines.append(text)
    if reasons:
        lines.append("reasons: " + ", ".join(reasons))
    out.write("\n".join(lines) + "\n")


def _default_clock():
    return dt.datetime.now(dt.timezone.utc)


def _utf8_streams():
    # Windows consoles default to a legacy code page; Vietnamese text must not crash after a DB commit (H3)
    for s in (sys.stdout, sys.stderr):
        try:
            if (getattr(s, "encoding", "") or "").lower().replace("-", "") != "utf8":
                s.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError, OSError):
            pass


def main(argv, *, runner=None, clock=None, os_family=None, operator=None):
    _utf8_streams()
    a = build_parser().parse_args(argv)
    if operator is None:
        from .operator import ConsoleOperator

        operator = ConsoleOperator()
    clock = clock or _default_clock
    os_family = os_family or ("windows" if sys.platform.startswith("win") else "linux")
    if runner is None:
        from .runner import SubprocessRunner

        runner = SubprocessRunner()
    from .runner import CommandNotAllowed, UnrecordedCommand

    store = None
    try:
        store = open_store(paths.resolve_home(a.home), clock)
        if getattr(runner, "store", None) is None:
            runner.store = store
        ctx = Ctx(store, runner, clock, os_family, a.json, a.who, operator, a.home)
        rep = _handler(_key(a))(ctx, a)
        _emit(a.json, rep.code, rep.data, rep.text, rep.reasons, rep.text if rep.code else "")
        return rep.code
    except CommandError as e:
        _emit(a.json, e.exit_code, e.data, "", e.reasons, e.message)
        return e.exit_code
    except UnrecordedCommand as e:
        _emit(a.json, 4, {}, "", ["unexpected-command"], str(e))
        return 4
    except CommandNotAllowed as e:
        _emit(a.json, 4, {}, "", ["command-not-allowed"], f"refused to run a non-allow-listed command: {e}")
        return 4
    except (sqlite3.Error, OSError) as e:
        _emit(a.json, 4, {}, "", ["environment-error"], f"environment error: {e}")
        return 4
    except Exception as e:  # noqa: BLE001 - never a traceback for the operator; the bug is reported plainly
        _emit(a.json, 4, {}, "", ["internal-error"], f"internal error ({type(e).__name__}): {e}")
        return 4
    finally:
        if store is not None:
            if getattr(runner, "store", None) is store:
                runner.store = None
            store.close()
