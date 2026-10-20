"""Claude Code PreToolUse guard (registered by SKILL.md frontmatter, matcher Bash|PowerShell).

Exit 0 = allow (normal permission flow continues), 2 = deny (stderr shown to Claude), 1 = non-blocking error.
When the frontmatter wrapper sets RS_GUARD_DENY_CODE, a deny exits with that code instead and the wrapper maps it
to 2; every other non-zero exit (python cannot open the file, crash before a decision) becomes 1, so an
installation problem can never block every command.
Non-matching commands never touch the store. A matched destructive command passes only while some gate is `open`
(and not older than OPEN_GATE_MAX_HOURS) in the case store; any failure after a match denies. Never spawns
processes. Leaky by design (see SKILL.md "Guard hook and its limits").
"""
import datetime as dt
import hashlib
import json
import os
import pathlib
import sqlite3
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from rslib import guard_patterns  # noqa: E402
from rslib.paths import resolve_home  # noqa: E402
from rslib.store import SCHEMA_VERSION  # noqa: E402

SEGMENT_CHARS = 200
CONNECT_TIMEOUT_S = 2.0
OPEN_GATE_MAX_HOURS = 12  # a forgotten open gate stops unlocking commands (still closable via rs.py)
NEXT = ("next: rs.py gate open <session> <device> <kind>, then the operator runs "
        "rs.py gate confirm <gate> in their own terminal; use only the OS path printed by gate confirm")


def _deny_code():
    v = os.environ.get("RS_GUARD_DENY_CODE", "")
    return int(v) if v.isdigit() and 2 <= int(v) <= 125 else 2


def _now():
    # single clock: tests pin it (amendment 10; wall clock vs FakeClock era broke 6 tests 2026-10-20 12:00Z)
    return dt.datetime.now(dt.timezone.utc)


def _log(home, rule_id, decision, gate_id, command):
    try:
        digest = hashlib.sha256(command.encode("utf-8", "replace")).hexdigest()
        line = (f"{_now().isoformat()} rule={rule_id} decision={decision} "
                f"gate={gate_id or '-'} sha256={digest}\n")
        with open(pathlib.Path(home) / "guard.log", "a", encoding="utf-8") as f:
            f.write(line)
    except Exception:  # noqa: BLE001 - logging never changes the decision
        pass


def _parse_ts(text):
    try:
        return dt.datetime.fromisoformat(str(text).replace("Z", "+00:00"))
    except ValueError:
        return None


def _gates(home):
    """(open_gate_id, pending_gate_id, stale_open_id) or raises with a reason."""
    db = pathlib.Path(home) / "rs.sqlite"
    if not db.exists():
        return None, None, None
    con = sqlite3.connect(f"{db.resolve().as_uri()}?mode=ro", uri=True, timeout=CONNECT_TIMEOUT_S)
    try:
        v = con.execute("PRAGMA user_version").fetchone()[0]
        if v > SCHEMA_VERSION:
            raise RuntimeError(f"schema {v} is newer than this guard ({SCHEMA_VERSION})")
        now = _now()
        opened, stale = None, None
        for gid, ts in con.execute("SELECT id, COALESCE(confirmed_ts, ts) FROM gates WHERE state = 'open' "
                                   "ORDER BY ts"):
            t = _parse_ts(ts)
            if t is not None and t.tzinfo and (now - t).total_seconds() > OPEN_GATE_MAX_HOURS * 3600:
                stale = stale or gid
                continue
            opened = opened or gid
        pending = con.execute("SELECT id FROM gates WHERE state = 'pending' ORDER BY ts LIMIT 1").fetchone()
        return opened, (pending[0] if pending else None), stale
    finally:
        con.close()


def _decide(command):
    m = guard_patterns.find(command)
    if m is None:
        return 0
    deny = _deny_code()
    home = resolve_home()
    seg = m.segment[:SEGMENT_CHARS]
    try:
        open_id, pending_id, stale_id = _gates(home)
    except Exception as e:  # noqa: BLE001 - unreadable / locked / newer store: fail closed for a matched command
        _log(home, m.rule_id, "deny", None, command)
        sys.stderr.write(f"recovery-storage guard [{m.rule_id}] blocked `{seg}`: cannot read gate store in {home}: "
                         f"{e}\n{NEXT}\n")
        return deny
    if open_id:
        _log(home, m.rule_id, "allow", open_id, command)
        return 0
    _log(home, m.rule_id, "deny", pending_id, command)
    msg = f"recovery-storage guard [{m.rule_id}] blocked `{seg}`: no gate is open in {home}."
    if pending_id:
        msg += f" Gate {pending_id} is pending: the operator runs rs.py gate confirm {pending_id} first."
    if stale_id:
        msg += f" Gate {stale_id} has been open for more than {OPEN_GATE_MAX_HOURS} h: close it and open a new one."
    sys.stderr.write(msg + "\n" + NEXT + "\n")
    return deny


def main():
    try:
        raw = sys.stdin.buffer.read() if hasattr(sys.stdin, "buffer") else sys.stdin.read()
        text = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else raw
        data = json.loads(text)
        tool = data.get("tool_name")
        command = (data.get("tool_input") or {}).get("command")
    except (ValueError, AttributeError, OSError):
        sys.stderr.write("recovery-storage guard: unreadable hook input\n")
        return 1
    if tool not in ("Bash", "PowerShell") or not isinstance(command, str):
        return 0
    try:
        matched = guard_patterns.find(command) is not None
    except Exception as e:  # noqa: BLE001 - a pattern bug must not block every call
        sys.stderr.write(f"recovery-storage guard: internal error, not blocking: {e}\n")
        return 1
    if not matched:
        return 0
    try:
        return _decide(command)
    except Exception as e:  # noqa: BLE001 - after a match, any failure denies
        sys.stderr.write(f"recovery-storage guard: error after a destructive match, blocking: {e}\n{NEXT}\n")
        return _deny_code()


if __name__ == "__main__":
    sys.exit(main())
