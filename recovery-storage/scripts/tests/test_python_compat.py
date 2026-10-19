"""Phase 01 non-functional 'Python >= 3.10 stdlib only (no 3.11+ APIs)' + plan Decision Q6 (static half of G10)."""
import re
import sys

import pytest

from conftest import SCRIPTS

BANNED = [r"\bimport\s+tomllib\b", r"\bfrom\s+tomllib\b", r"\bdatetime\.UTC\b", r"from\s+datetime\s+import[^\n]*\bUTC\b",
          r"\bStrEnum\b", r"\bExceptionGroup\b", r"\bexcept\s*\*", r"\btyping\.Self\b", r"from\s+typing\s+import[^\n]*\bSelf\b"]
THIRD_PARTY_HINTS = [r"^\s*(import|from)\s+(yaml|requests|pydantic|click|rich|attr|attrs)\b"]


def runtime_files():
    files = sorted((SCRIPTS / "rslib").rglob("*.py")) + [SCRIPTS / n for n in ("rs.py", "guard_hook.py", "install_junction.py")]
    assert (SCRIPTS / "rslib" / "cli.py").is_file()
    return [f for f in files if f.is_file()]


def test_no_python_311_plus_apis():
    """G10 static / phase 01 NFR. Mutation: `import tomllib` or `datetime.UTC` in rslib -> red."""
    bad = []
    for f in runtime_files():
        t = f.read_text(encoding="utf-8")
        for pat in BANNED:
            if re.search(pat, t):
                bad.append(f"{f.relative_to(SCRIPTS)}: {pat}")
    assert bad == []


def test_stdlib_only_at_runtime():
    """Decision 'stdlib only at runtime'. Mutation: import yaml/requests -> red."""
    bad = []
    for f in runtime_files():
        for ln in f.read_text(encoding="utf-8").splitlines():
            if any(re.match(p, ln) for p in THIRD_PARTY_HINTS):
                bad.append(f"{f.name}: {ln.strip()}")
    assert bad == []


def test_runtime_modules_compile_for_310_grammar():
    """Every runtime file parses with feature_version=(3, 10). Mutation: `match`-free is fine, but 3.12 f-string nesting
    or `type X = ...` aliases -> red."""
    import ast

    for f in runtime_files():
        ast.parse(f.read_text(encoding="utf-8"), filename=str(f), feature_version=(3, 10))
