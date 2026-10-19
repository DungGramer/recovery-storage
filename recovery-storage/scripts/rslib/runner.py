"""The ONLY module allowed to spawn processes (A18). Every call: allow-list check before spawn, timeout,
recorded as a tool_runs row (stdout to a content-addressed file, stderr truncated).

RecordedRunner replays real captured outputs through the same validator (tests); there is no replay switch
in production code paths.
"""
import os
import pathlib
import re
import signal
import subprocess
import time
from dataclasses import dataclass

from .allowlist import CommandNotAllowed, check

STDERR_MAX = 4000
DEFAULT_TIMEOUTS = {"smartctl": 90.0, "powershell": 120.0, "lsblk": 30.0, "udevadm": 30.0, "blockdev": 30.0,
                    "lsusb": 30.0, "journalctl": 60.0, "dmesg": 30.0}
EXECUTABLES = {"powershell": "powershell.exe"}

__all__ = ["CommandNotAllowed", "RunResult", "Recording", "RecordedRunner", "SubprocessRunner",
           "UnrecordedCommand", "STDERR_MAX"]


class UnrecordedCommand(Exception):
    pass


def _which(name):
    """PATH lookup that never uses the current directory and, on Windows, only accepts .exe (a planted
    smartctl.bat in the CWD or on a recovered drive must not run). shutil.which may search the CWD first."""
    base = name[:-4] if name.lower().endswith(".exe") else name
    cwd = os.path.normcase(os.path.abspath(os.getcwd()))
    for d in os.environ.get("PATH", "").split(os.pathsep):
        d = d.strip().strip('"')
        if not d or not os.path.isabs(d) or os.path.normcase(os.path.abspath(d)) == cwd:
            continue
        cand = os.path.join(d, base + (".exe" if os.name == "nt" else ""))
        if os.path.isfile(cand) and (os.name == "nt" or os.access(cand, os.X_OK)):
            return cand
    return None


@dataclass
class RunResult:
    tool: str
    argv: tuple
    exit_code: object = None
    timed_out: bool = False
    tool_missing: bool = False
    duration_s: float = 0.0
    stdout: bytes = b""
    stderr: str = ""
    tool_version: object = None


class _Base:
    def __init__(self, store=None):
        self.store = store

    def _refuse(self, tool_id, args):
        if self.store is not None:
            self.store.record_run(RunResult(tool=tool_id, argv=tuple(args)), refused=True)

    def _validate(self, tool_id, args, env):
        try:
            check(tool_id, args, env)
        except CommandNotAllowed:
            self._refuse(tool_id, args)
            raise

    def _persist(self, res):
        res.stderr = (res.stderr or "")[:STDERR_MAX]
        if self.store is not None:
            self.store.record_run(res)
        return res


class SubprocessRunner(_Base):
    def __init__(self, store=None, timeouts=None):
        super().__init__(store)
        self.timeouts = dict(DEFAULT_TIMEOUTS)
        self.timeouts.update(timeouts or {})
        self._versions = {}

    def resolve(self, tool_id):
        override = os.environ.get(f"RS_{tool_id.upper()}")
        if override:
            p = pathlib.Path(override)
            # absolute existing file only: a relative override could resolve against the CWD
            return str(p) if p.is_absolute() and p.is_file() else None
        if os.name == "nt" and tool_id == "powershell":
            fixed = pathlib.Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "WindowsPowerShell" / \
                "v1.0" / "powershell.exe"
            if fixed.is_file():
                return str(fixed)
        return _which(EXECUTABLES.get(tool_id, tool_id))

    def _version(self, tool_id, exe):
        if tool_id != "smartctl":
            return None
        if exe not in self._versions:
            out = self._spawn([exe, "-V"], None, 30.0)[1]
            m = re.search(rb"smartctl (\d+\.\d+)", out or b"")
            self._versions[exe] = m.group(1).decode() if m else None
        return self._versions[exe]

    @staticmethod
    def _kill(proc):
        if os.name == "nt":
            # kill the whole tree: a .bat or shell wrapper leaves children holding the pipes
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True)
        else:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except OSError:
                proc.kill()

    def _spawn(self, argv, env_extra, timeout):
        env = dict(os.environ)
        env.update(env_extra or {})
        kw = {"start_new_session": True} if os.name != "nt" else {}
        proc = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                env=env, **kw)
        try:
            out, err = proc.communicate(timeout=timeout)
            return proc.returncode, out, err, False
        except subprocess.TimeoutExpired:
            self._kill(proc)
            try:
                out, err = proc.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                out, err = b"", b""
            return None, out, err, True

    def run(self, tool_id, args, env=None):
        args = list(args)
        self._validate(tool_id, args, env)
        exe = self.resolve(tool_id)
        res = RunResult(tool=tool_id, argv=tuple(args))
        if exe is None:
            res.tool_missing = True
            res.stdout = None
            return self._persist(res)
        res.tool_version = self._version(tool_id, exe)
        start = time.monotonic()
        try:
            code, out, err, timed_out = self._spawn([exe] + args, env, self.timeouts.get(tool_id, 60.0))
        except OSError:
            res.tool_missing = True
            res.stdout = None
            return self._persist(res)
        res.duration_s = time.monotonic() - start
        res.exit_code, res.timed_out = code, timed_out
        res.stdout = out or b""
        res.stderr = (err or b"").decode("utf-8", "replace")
        return self._persist(res)


@dataclass
class Recording:
    tool_id: str
    args: list
    stdout: object = b""
    exit_code: object = 0
    stderr: str = ""
    tool_version: object = None
    tool_missing: bool = False
    timed_out: bool = False


class RecordedRunner(_Base):
    def __init__(self, recordings, store=None):
        super().__init__(store)
        self.recordings = {(r.tool_id, tuple(r.args)): r for r in recordings}
        self.calls = []
        self.unrecorded = []

    def run(self, tool_id, args, env=None):
        args = list(args)
        self._validate(tool_id, args, env)
        key = (tool_id, tuple(args))
        rec = self.recordings.get(key)
        if rec is None:
            self.unrecorded.append(key)
            raise UnrecordedCommand(f"no recording for {tool_id} {args}")
        self.calls.append(key)
        stdout = rec.stdout.encode("utf-8") if isinstance(rec.stdout, str) else rec.stdout
        res = RunResult(tool=tool_id, argv=tuple(args), exit_code=rec.exit_code, timed_out=rec.timed_out,
                        tool_missing=rec.tool_missing, stdout=None if rec.tool_missing else stdout,
                        stderr=rec.stderr, tool_version=rec.tool_version)
        return self._persist(res)
