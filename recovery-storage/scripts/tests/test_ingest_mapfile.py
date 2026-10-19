"""Phase 03 ddrescue mapfile parser (C20, C21). Spec: phase-03 Requirements 'ddrescue mapfile' + C20/C21.
Input: verbatim GNU ddrescue 1.30 manual example quoted in researcher-04 §1; C21 cases are single-token in-test
mutations of that text (listed in fixtures/SOURCES.md)."""
import pytest

from conftest import BYTES_980, BYTES_990, MAP_980, MAP_990, MAP_HDD500, fx_text

MAP = "ingest/ddrescue-manual-1.30.map"
BAD_LINE = 10  # `0x00117000  0x00000200  -` (1-based)


def parse(text):
    from rslib.ingest import parse_mapfile

    return parse_mapfile(text)


def mutate(old, new):
    text = fx_text(MAP)
    lines = text.splitlines(keepends=True)
    assert old in lines[BAD_LINE - 1]
    lines[BAD_LINE - 1] = lines[BAD_LINE - 1].replace(old, new, 1)
    return "".join(lines)


def test_C20_verbatim_manual_example():
    """C20. Mutation: count the status line as a block, or skip `/`/`*` -> totals differ -> red."""
    r = parse(fx_text(MAP))
    assert r.total == 1474560
    assert r.rescued == 1142784
    assert r.bad == 512
    assert r.non_scraped == 4096
    assert r.non_trimmed == 32256
    assert r.non_tried == 294912
    assert r.rescued_pct == 77.5
    assert r.finished is False


def test_C20_finished_derived_mapfile():
    """C20 'finished (status line char +)' on the derived all-`+` copy. Mutation: finished from blocks only -> red."""
    r = parse(fx_text("ingest/ddrescue-manual-1.30.finished.derived.map"))
    assert r.finished is True
    assert r.bad == 0 and r.non_tried == 0 and r.non_trimmed == 0 and r.non_scraped == 0
    assert r.rescued == r.total == 1474560
    assert r.rescued_pct == 100.0


def test_C20_comment_after_whitespace_is_comment():
    """Requirements '# at line start or after whitespace'. Mutation: only column-0 comments -> malformed -> red."""
    text = fx_text(MAP).replace("0x00000000  0x00117000  +", "0x00000000  0x00117000  +  # first block", 1)
    assert parse(text).rescued == 1142784


@pytest.mark.parametrize("token,bad", [("0x200", 512), ("512", 512), ("010", 8)])
def test_C21_cpp_integer_syntax(token, bad):
    """C21. Mutation: int(s, 0) (raises on `010`) or decimal-only parsing (`010` -> 10) -> red."""
    r = parse(mutate("0x00000200", token))
    assert r.bad == bad
    assert r.total == 1474560 - 512 + bad


@pytest.mark.parametrize("token", ["0o10", "-0x200", "-512", "abc", "12z"])
def test_C21_malformed_number_reports_line(token):
    """C21. Mutation: accept Python `0o` syntax or negative sizes -> red; line number required."""
    from rslib.ingest import MalformedInput

    with pytest.raises(MalformedInput) as ei:
        parse(mutate("0x00000200", token))
    assert ei.value.line == BAD_LINE


@pytest.mark.parametrize("text", ["", "\n\n", "# only comments\n# Mapfile.\n"])
def test_C21_empty_file_malformed(text):
    """C21 'empty file -> malformed'. Mutation: return zero totals -> red."""
    from rslib.ingest import MalformedInput

    with pytest.raises(MalformedInput):
        parse(text)


def test_C21_unknown_status_char_malformed():
    """Requirements block chars are ?*/-+ only (in-test: `-` -> `X`). Mutation: ignore unknown chars -> red."""
    from rslib.ingest import MalformedInput

    text = fx_text(MAP).splitlines(keepends=True)
    text[BAD_LINE - 1] = text[BAD_LINE - 1].rstrip("\n")[:-1] + "X\n"
    with pytest.raises(MalformedInput) as ei:
        parse("".join(text))
    assert ei.value.line == BAD_LINE


# ---------------- amendment 01 B: start / end / contiguous
def test_C20b_verbatim_map_start_end_contiguous():
    """Amendment 01 B 'parse_mapfile adds start (pos of first block), end (pos + size of last block), contiguous'.
    Verbatim floppy map: 0 .. 0x168000, contiguous. Mutation: end = pos of last block (0x120000) or = total of a
    different status -> red; contiguous False on a gapless map -> red."""
    r = parse(fx_text(MAP))
    assert r.start == 0
    assert r.end == 1474560
    assert r.contiguous is True
    assert r.total == 1474560 and r.finished is False  # existing fields unchanged


@pytest.mark.parametrize("rel,end", [(MAP_980, BYTES_980), (MAP_990, BYTES_990), (MAP_HDD500, 500107862016)])
def test_C20b_derived_full_coverage_maps_end_at_device_bytes(rel, end):
    """Amendment 01 B fixtures: derived maps end exactly at the device byte count (SOURCES.md).
    Mutation: 32-bit / 8-hex-digit size parsing (truncates 0x1D1C0FF6000) -> red."""
    r = parse(fx_text(rel))
    assert (r.start, r.end, r.contiguous, r.finished) == (0, end, True, True)
    assert r.rescued == r.total == end
    assert r.bad == r.non_tried == r.non_trimmed == r.non_scraped == 0


def test_C20b_gap_is_not_contiguous():
    """Amendment 01 B 'blocks are contiguous (each pos == previous pos + size)'; third block removed in-test.
    Mutation: contiguous derived from end - start == total only when sizes happen to match, or always True -> red."""
    lines = fx_text(MAP_980).splitlines(keepends=True)
    lines = [ln for ln in lines if ln.strip() != "0x00117200  0x00001000  +"]
    r = parse("".join(lines))
    assert r.contiguous is False
    assert r.start == 0 and r.end == BYTES_980
    assert r.total == BYTES_980 - 0x1000


def test_C20b_shifted_start():
    """Amendment 01 B 'start (pos of first block)'. Mutation: start hard-coded 0 -> red."""
    t = fx_text(MAP_980).replace("0x00000000  0x00117000  +", "0x00000200  0x00116E00  +", 1)
    r = parse(t)
    assert r.start == 512 and r.end == BYTES_980 and r.contiguous is True
