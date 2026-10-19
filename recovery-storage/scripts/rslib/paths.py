"""Home resolution: --home > env RECOVERY_STORAGE_HOME > ~/.recovery-storage."""
import os
import pathlib

ENV_HOME = "RECOVERY_STORAGE_HOME"
DEFAULT_DIRNAME = ".recovery-storage"


def resolve_home(flag=None):
    if flag:
        return pathlib.Path(flag)
    env = os.environ.get(ENV_HOME)
    if env:
        return pathlib.Path(env)
    return pathlib.Path.home() / DEFAULT_DIRNAME


def sessions_dir(home):
    return pathlib.Path(home) / "sessions"


def runs_dir(home):
    return pathlib.Path(home) / "runs"


def evidence_dir(home, session_id):
    return sessions_dir(home) / session_id / "evidence"
