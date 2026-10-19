"""Human operator channel (amendment 01): confirmations that the agent must not be able to give itself.

Production reads one line from an interactive console (stdin must be a TTY). An agent's tool calls run without a
TTY, so `gate confirm`, data-state waivers and attestations require the operator to run the command in their own
terminal. Tests inject ScriptedOperator through rslib.cli.main(operator=...); rs.py never does.
Known leak: a script importing rslib with an injected operator, or a pseudo-terminal wrapper (documented).
Name is fixed by amendment 01 (`rslib.operator`); it shadows the stdlib `operator` only if Python runs with rslib/
itself on sys.path, so never place an entry script inside rslib/.
"""
import sys


class NoConsole(Exception):
    pass


def _is_console(stream):
    if stream is None or not hasattr(stream, "isatty") or not stream.isatty():
        return False
    if sys.platform.startswith("win"):
        # isatty() is also True for the NUL device; a real console handle accepts GetConsoleMode
        try:
            import ctypes
            import msvcrt

            handle = msvcrt.get_osfhandle(stream.fileno())
            mode = ctypes.c_uint32()
            return bool(ctypes.windll.kernel32.GetConsoleMode(handle, ctypes.byref(mode)))
        except (OSError, ValueError, AttributeError):
            return False
    return True


class ConsoleOperator:
    def ask(self, prompt):
        stdin = sys.stdin
        if not _is_console(stdin):
            raise NoConsole("no interactive console")
        sys.stderr.write(prompt)
        sys.stderr.flush()
        line = stdin.readline()
        if not line:
            raise NoConsole("console closed")
        return line.strip()


class ScriptedOperator:
    def __init__(self, answers):
        self.answers = list(answers)
        self.prompts = []

    def ask(self, prompt):
        self.prompts.append(prompt)
        if not self.answers:
            raise NoConsole("no scripted answer left")
        return str(self.answers.pop(0)).strip()


UNSAFE_CHARS = set('"$`;&|<>\n\r')


def require_echo_safe(**values):
    """Values echoed into a command the operator will paste must not carry shell syntax (amendment 02 G)."""
    from .errors import UsageError

    for name, v in values.items():
        if v is not None and set(str(v)) & UNSAFE_CHARS:
            bad = "".join(sorted(set(str(v)) & UNSAFE_CHARS)).replace("\n", "\\n").replace("\r", "\\r")
            raise UsageError(f"--{name.replace('_', '-')} contains characters that are not allowed ({bad}): "
                             "use plain text", ["unsafe-characters"])


def console_command(argv_tail):
    """Exact command line for the operator to run in their own terminal."""
    import pathlib

    rs = pathlib.Path(__file__).resolve().parent.parent / "rs.py"
    return f'python "{rs}" ' + " ".join(argv_tail)
