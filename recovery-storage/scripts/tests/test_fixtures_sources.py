"""Phase 01 fixtures (A20, A21) + plan.md "Fixtures: real only"."""
import json
import re
import subprocess
import sys

import pytest

from conftest import FIX, REPO

SOURCES = FIX / "SOURCES.md"
SKIP_NAMES = {"SOURCES.md", "LICENSE-scrutiny"}


def fixture_files():
    return sorted(p for p in FIX.rglob("*") if p.is_file() and p.name not in SKIP_NAMES
                  and not p.name.endswith(".meta.json"))


def table_rows(text):
    return [ln for ln in text.splitlines() if ln.startswith("|") and not set(ln) <= set("|-: ")]


@pytest.mark.slow
def test_A20_redaction_check_passes():
    """A20. Mutation: commit a fixture containing an original identifier -> tool exits 1 -> red."""
    p = subprocess.run([sys.executable, "-I", str(REPO / "tools" / "redact_fixtures.py"), "--check"],
                       capture_output=True, text=True, timeout=300, cwd=REPO)
    assert p.returncode == 0, p.stdout + p.stderr


def test_A21_every_fixture_file_is_named_in_sources():
    """A21. Mutation: add a fixture without a SOURCES.md entry -> red."""
    text = SOURCES.read_text(encoding="utf-8")
    missing = []
    for p in fixture_files():
        rel = p.relative_to(FIX).as_posix()
        capture_dir = rel.split("/")[1] if rel.startswith(("windows/", "linux/")) else None
        if p.name in text or rel in text:
            continue
        if capture_dir and ".derived." not in p.name and f"`{capture_dir}`" in text:
            continue  # raw capture files are documented per capture directory
        missing.append(rel)
    assert missing == []


def test_A21_derived_rows_name_field_and_original_value():
    """A21 'for *.derived.json the single field changed and its original value'. Mutation: row without original -> red."""
    rows = table_rows(SOURCES.read_text(encoding="utf-8"))
    bad = []
    for p in fixture_files():
        if ".derived." not in p.name:
            continue
        mine = [r for r in rows if f"`{p.name}`" in r or f"`{p.relative_to(FIX).as_posix()}`" in r]
        if len(mine) != 1:
            bad.append((p.name, "no single row"))
            continue
        cells = [c.strip() for c in mine[0].strip("|").split("|")]
        if len(cells) < 5 or any(not c for c in cells[:5]):
            bad.append((p.name, cells))
    assert bad == []


def test_A21_verbatim_ingest_fixtures_cite_research_section():
    """plan.md Fixtures + task rule: mapfile/F3 text only from research quotes. Mutation: uncited ingest file -> red."""
    rows = table_rows(SOURCES.read_text(encoding="utf-8"))
    for p in sorted((FIX / "ingest").glob("*")):
        mine = [r for r in rows if f"`{p.name}`" in r]
        assert len(mine) == 1, p.name
        assert re.search(r"researcher-0[34]", mine[0]) and "§" in mine[0], mine[0]


def test_derived_json_fixtures_are_valid_json():
    """Derived fixtures stay parseable smartctl / capture JSON. Mutation: hand-edit breaking JSON -> red."""
    for p in FIX.rglob("*.derived.json"):
        json.loads(p.read_text(encoding="utf-8"))
