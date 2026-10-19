"""Phase 05 --check and --out (E1 positive side, E7). Spec: phase-05 Requirements '--check', E7."""
from conftest import assess, ingest_smart, new_session, ok


def finished(cli):
    sid = new_session(cli, "--goal", "diagnosis-only")
    dev = ingest_smart(cli, sid, "smartctl/scrutiny-usbjmicron-hdd-failing.json").data["device_id"]
    assess(cli, sid, dev)
    ok(cli("verdict", "set", sid, dev, "REPAIR_REQUIRED", "--reason", "failing media, lab recovery advised"))
    return sid, dev


def test_check_passes_when_every_section_has_content(cli):
    """--check exit 0 with a verdict (sections 5 and 7 may read 'none'). Mutation: 5/7 'none' counted as empty -> red."""
    sid, _ = finished(cli)
    res = cli("report", sid, "--check")
    assert res.code == 0, res
    assert res.data["check"]["ok"] is True and res.data["check"]["missing_sections"] == []


def test_E7_out_writes_utf8_markdown(cli, tmp_path):
    """E7. Mutation: write with the locale codepage (Vietnamese headings mangled) -> red."""
    sid, _ = finished(cli)
    out = tmp_path / "report.md"
    res = cli("report", sid, "--out", out, json_out=False)
    assert res.code == 0, res
    text = out.read_bytes().decode("utf-8")
    assert "Trạng thái cuối cùng" in text
    assert "REPAIR_REQUIRED" in text


def test_E7_existing_file_not_overwritten_without_force(cli, tmp_path):
    """E7. Mutation: silently overwrite -> red."""
    sid, _ = finished(cli)
    out = tmp_path / "report.md"
    out.write_text("keep me", encoding="utf-8")
    res = cli("report", sid, "--out", out, json_out=False)
    assert res.code == 3, res
    assert out.read_text(encoding="utf-8") == "keep me"
    res2 = cli("report", sid, "--out", out, "--force", json_out=False)
    assert res2.code == 0, res2
    assert "Trạng thái cuối cùng" in out.read_text(encoding="utf-8")
