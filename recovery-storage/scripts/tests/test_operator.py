"""Amendment 01 A (2026-10-19): operator console. Spec: plans/20261019-1726-recovery-storage-skill/
amendment-01-operator-console-and-mapfile-coverage.md section A; contract in tests/CONTRACT.md "Amendment 01"."""
import inspect
import io
import sys

import pytest

from conftest import SCRIPTS


def test_AM01A_scripted_operator_answers_in_order_then_no_console():
    """Amendment 01 A 'ScriptedOperator(answers): answers consumed in order; running out raises NoConsole'.
    Mutation: answers popped from the end, or '' returned when exhausted (a silent empty answer) -> red."""
    from rslib.operator import NoConsole, ScriptedOperator

    op = ScriptedOperator(["first", "YES"])
    assert op.ask("q1: ") == "first"
    assert op.ask("q2: ") == "YES"
    with pytest.raises(NoConsole):
        op.ask("q3: ")


def test_AM01A_scripted_operator_empty_raises_immediately():
    """Amendment 01 A. Mutation: empty list treated as 'answer YES' -> red."""
    from rslib.operator import NoConsole, ScriptedOperator

    with pytest.raises(NoConsole):
        ScriptedOperator([]).ask("Type the confirmation phrase: ")


def test_AM01A_console_operator_requires_a_tty(monkeypatch):
    """Amendment 01 A 'ConsoleOperator requires sys.stdin.isatty(); otherwise it raises NoConsole'. The piped stdin
    holds a would-be answer, so reading it instead of refusing returns 'YES'.
    Mutation: read stdin without the isatty check (an agent pipes the answer) -> no raise -> red."""
    from rslib.operator import ConsoleOperator, NoConsole

    monkeypatch.setattr(sys, "stdin", io.StringIO("YES\n"))
    with pytest.raises(NoConsole):
        ConsoleOperator().ask("Type YES to attest h2testw pass for X: ")


def test_AM01A_no_console_is_an_exception_class():
    """Contract: NoConsole is raised (and caught by the CLI). Mutation: NoConsole not an Exception subclass -> red."""
    from rslib.operator import NoConsole

    assert inspect.isclass(NoConsole) and issubclass(NoConsole, Exception)


def test_AM01A_main_accepts_operator_keyword():
    """Amendment 01 A `rslib.cli.main(argv, *, runner=None, clock=None, os_family=None, operator=None)`.
    Mutation: operator positional / missing / default not None -> red."""
    from rslib.cli import main

    p = inspect.signature(main).parameters["operator"]
    assert p.kind is inspect.Parameter.KEYWORD_ONLY
    assert p.default is None


def test_AM01A_rs_py_never_passes_an_operator():
    """Amendment 01 A '`rs.py` never passes an operator (production always uses the console)'.
    Mutation: rs.py builds a ScriptedOperator / passes operator= -> red."""
    src = (SCRIPTS / "rs.py").read_text(encoding="utf-8")
    code = "\n".join(ln.split("#", 1)[0] for ln in src.splitlines())  # comments may mention the operator
    assert "operator=" not in code and "Operator(" not in code and "rslib.operator" not in code, src
