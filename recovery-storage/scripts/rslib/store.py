"""SQLite case store + content-addressed evidence files under <home>.

Schema version lives in PRAGMA user_version and is checked BEFORE any write: a newer DB is never touched (A4).
Missing values stay NULL / JSON null, never 0 (later rules must be able to say "unknown").
"""
import datetime as dt
import hashlib
import json
import os
import pathlib
import sqlite3
import uuid

from . import paths
from .errors import EnvFailure

SCHEMA_VERSION = 1

SCHEMA = """
CREATE TABLE sessions (
    id TEXT PRIMARY KEY, created_ts TEXT NOT NULL, data TEXT NOT NULL
);
CREATE TABLE session_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT NOT NULL, ts TEXT NOT NULL, who TEXT NOT NULL,
    field TEXT NOT NULL, old TEXT, new TEXT, note TEXT
);
CREATE TABLE devices (
    id TEXT PRIMARY KEY, created_ts TEXT NOT NULL, fingerprint TEXT NOT NULL, detected_class TEXT, data TEXT
);
CREATE TABLE observations (
    id TEXT PRIMARY KEY, ts TEXT NOT NULL, session_id TEXT, device_id TEXT, match TEXT, os_path TEXT,
    after_replug INTEGER NOT NULL DEFAULT 0, fingerprint TEXT NOT NULL, data TEXT NOT NULL
);
CREATE TABLE inventory_runs (
    id TEXT PRIMARY KEY, ts TEXT NOT NULL, session_id TEXT, after_replug INTEGER NOT NULL DEFAULT 0,
    device_ids TEXT NOT NULL
);
CREATE TABLE snapshots (
    id TEXT PRIMARY KEY, ts TEXT NOT NULL, session_id TEXT, device_id TEXT, source TEXT NOT NULL,
    collection_status TEXT NOT NULL, tool_version TEXT, sha256 TEXT, path TEXT, data TEXT NOT NULL
);
CREATE TABLE assessments (
    id TEXT PRIMARY KEY, ts TEXT NOT NULL, session_id TEXT NOT NULL, device_id TEXT NOT NULL,
    rules_version TEXT NOT NULL, inputs_key TEXT NOT NULL, data TEXT NOT NULL
);
CREATE TABLE evidence (
    id TEXT PRIMARY KEY, ts TEXT NOT NULL, session_id TEXT, device_id TEXT, kind TEXT NOT NULL,
    level TEXT NOT NULL, sha256 TEXT NOT NULL, path TEXT, data TEXT NOT NULL, who TEXT
);
CREATE UNIQUE INDEX evidence_dedup ON evidence(session_id, device_id, kind, sha256);
CREATE TABLE data_states (
    id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, session_id TEXT NOT NULL, device_id TEXT NOT NULL,
    state TEXT NOT NULL, evidence_id TEXT, attested INTEGER NOT NULL DEFAULT 0, reason TEXT, who TEXT
);
CREATE TABLE gates (
    id TEXT PRIMARY KEY, ts TEXT NOT NULL, session_id TEXT NOT NULL, device_id TEXT NOT NULL, kind TEXT NOT NULL,
    risk TEXT NOT NULL, state TEXT NOT NULL, lock_slot TEXT, phrase_hash TEXT, data TEXT NOT NULL,
    before_json TEXT, after_json TEXT, identity_drift INTEGER NOT NULL DEFAULT 0, outcome TEXT,
    abort_reason TEXT, opened_ts TEXT, confirmed_ts TEXT, closed_ts TEXT, confirmed_by TEXT
);
-- global R2 lock and one live gate per device, enforced by the DB (phase 04 D18)
CREATE UNIQUE INDEX gates_global ON gates(lock_slot) WHERE state IN ('pending', 'open');
CREATE UNIQUE INDEX gates_device ON gates(device_id) WHERE state IN ('pending', 'open');
CREATE TABLE verdicts (
    id TEXT PRIMARY KEY, ts TEXT NOT NULL, session_id TEXT NOT NULL, device_id TEXT NOT NULL, status TEXT NOT NULL,
    reason TEXT, limitation TEXT
);
CREATE TABLE tool_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, tool TEXT NOT NULL, tool_version TEXT, argv TEXT NOT NULL,
    exit_code INTEGER, timed_out INTEGER NOT NULL DEFAULT 0, tool_missing INTEGER NOT NULL DEFAULT 0,
    refused INTEGER NOT NULL DEFAULT 0, duration_s REAL, stderr TEXT, stdout_sha256 TEXT, stdout_path TEXT
);
"""


def new_id(prefix):
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def sha256_hex(data):
    return hashlib.sha256(data).hexdigest()


def _utcnow():
    return dt.datetime.now(dt.timezone.utc)


def iso(t):
    # fixed width (microseconds always present) so string order == time order
    return t.astimezone(dt.timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


class Store:
    def __init__(self, home, con, clock=None):
        self.home = pathlib.Path(home)
        self.con = con
        self.clock = clock or _utcnow

    # ------------------------------------------------------------ basics
    def now(self):
        return iso(self.clock())

    def close(self):
        self.con.close()

    def execute(self, sql, params=()):
        cur = self.con.execute(sql, params)
        self.con.commit()
        return cur

    def query(self, sql, params=()):
        return [dict(r) for r in self.con.execute(sql, params)]

    def one(self, sql, params=()):
        r = self.con.execute(sql, params).fetchone()
        return dict(r) if r else None

    # ------------------------------------------------------------ files
    def write_blob(self, data, subdir, suffix=".bin"):
        """Content-addressed atomic write under <home>/<subdir>; returns (sha256, path relative to home)."""
        if isinstance(data, str):
            data = data.encode("utf-8")
        digest = sha256_hex(data)
        rel = pathlib.Path(subdir) / f"{digest}{suffix}"
        target = self.home / rel
        if not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            tmp = target.with_name(target.name + f".tmp{os.getpid()}")
            tmp.write_bytes(data)
            os.replace(tmp, target)
        return digest, rel.as_posix()

    def read_blob(self, rel):
        return (self.home / rel).read_bytes()

    def evidence_subdir(self, session_id):
        if not session_id:
            return "sessions/_unscoped/evidence"
        return f"sessions/{session_id}/evidence"

    # ------------------------------------------------------------ tool runs
    def record_run(self, result, refused=False):
        digest = path = None
        if result.stdout is not None and not refused and not result.tool_missing:
            data = result.stdout if isinstance(result.stdout, bytes) else str(result.stdout).encode("utf-8")
            digest, path = self.write_blob(data, "runs", ".out")
        self.execute(
            "INSERT INTO tool_runs (ts, tool, tool_version, argv, exit_code, timed_out, tool_missing, refused,"
            " duration_s, stderr, stdout_sha256, stdout_path) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (self.now(), result.tool, result.tool_version, json.dumps(list(result.argv)), result.exit_code,
             int(bool(result.timed_out)), int(bool(result.tool_missing)), int(bool(refused)), result.duration_s,
             result.stderr, digest, path))


def _check_version(con, db_path):
    v = con.execute("PRAGMA user_version").fetchone()[0]
    if v > SCHEMA_VERSION:
        con.close()
        raise EnvFailure(f"database schema newer than this tool: {db_path} has schema {v}, "
                         f"this tool supports {SCHEMA_VERSION}", ["schema-newer"])
    return v


def open_store(home, clock=None):
    home = pathlib.Path(home)
    db = home / "rs.sqlite"
    try:
        if db.exists():
            # read-only probe first: a newer schema must leave the file byte-identical
            probe = sqlite3.connect(f"{db.resolve().as_uri()}?mode=ro", uri=True)
            try:
                _check_version(probe, db)
            finally:
                try:
                    probe.close()
                except sqlite3.Error:
                    pass
        home.mkdir(parents=True, exist_ok=True)
        paths.sessions_dir(home).mkdir(exist_ok=True)
        if os.name == "posix":
            os.chmod(home, 0o700)
        con = sqlite3.connect(db, timeout=10)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA foreign_keys = ON")
        v = _check_version(con, db)
        if v == 0:
            con.executescript(SCHEMA)
            con.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
            con.commit()
    except EnvFailure:
        raise
    except (OSError, sqlite3.Error) as e:
        raise EnvFailure(f"cannot use home {home}: {e}", ["home-not-writable"]) from None
    return Store(home, con, clock)


def dumps(obj):
    return json.dumps(obj, ensure_ascii=False, sort_keys=True)


def loads(text):
    return json.loads(text) if text else None
