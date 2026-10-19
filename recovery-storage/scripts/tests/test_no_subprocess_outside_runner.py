"""Phase 01 A18 (+ phase 07 G6 re-check, phase 08 hook, phase 07 installer): process spawning only in runner.py."""
import re

import pytest

from conftest import SCRIPTS

PATTERNS = [
    re.compile(r"^\s*import\s+[^#\n]*\bsubprocess\b", re.M),
    re.compile(r"^\s*from\s+subprocess\s+import\b", re.M),
    re.compile(r"\bos\.system\s*\("),
    re.compile(r"\bos\.popen\s*\("),
    re.compile(r"\bos\.exec[lv]p?e?\s*\("),
    re.compile(r"\bos\.spawn[lv]p?e?\s*\("),
    re.compile(r"\bos\.posix_spawnp?\s*\("),
    re.compile(r"^\s*import\s+[^#\n]*\bpty\b", re.M),
    re.compile(r"^\s*from\s+pty\s+import\b", re.M),
    re.compile(r"__import__\(\s*['\"](subprocess|pty)['\"]"),
    re.compile(r"importlib\.import_module\(\s*['\"](subprocess|pty)['\"]"),
]


def scan(paths):
    hits = []
    for p in paths:
        text = p.read_text(encoding="utf-8")
        for pat in PATTERNS:
            for m in pat.finditer(text):
                line = text.count("\n", 0, m.start()) + 1
                hits.append(f"{p.relative_to(SCRIPTS)}:{line}: {m.group(0).strip()}")
    return hits


def rslib_files():
    root = SCRIPTS / "rslib"
    assert (root / "runner.py").is_file(), "rslib/runner.py missing: nothing to check yet"
    files = [p for p in root.rglob("*.py") if p.name != "runner.py" or p.parent != root]
    assert len(files) >= 6, f"expected the rslib package, found {files}"
    return files


def test_A18_spawn_apis_only_in_runner():
    """A18. Mutation: add `import subprocess` to any other rslib module -> red."""
    assert scan(rslib_files()) == []


def test_A18_runner_is_the_module_that_spawns():
    """A18 positive control: the scanner does see runner.py's import. Mutation: scanner pattern broken -> red."""
    assert scan([SCRIPTS / "rslib" / "runner.py"]), "runner.py should import subprocess"


@pytest.mark.parametrize("name", ["rs.py", "guard_hook.py", "install_junction.py"])
def test_A18_entry_scripts_do_not_spawn(name):
    """A18 extended: phase 08 (guard_hook.py never spawns) and phase 07 (installer: no subprocess). Mutation: shell out -> red."""
    p = SCRIPTS / name
    assert p.is_file(), f"{name} missing"
    assert scan([p]) == []


def test_G6_static_grep_still_holds():
    """G6 'grep over rslib/ confirms A18 still holds' (same scan, named for traceability)."""
    assert scan(rslib_files()) == []
