from __future__ import annotations

from pathlib import Path

from alinea_repair import apply_approved_patch, run_integrity_gates
from alinea_repair.ooxml import W_NS, locate_snapshot_element
from lxml import etree

from tests.unit.alinea_repair.helpers import Spec, build_case, mutate_xml, read_parts, write_parts


def _patched(tmp_path: Path, *, complex_document: bool = False):
    case = build_case(
        tmp_path / "base.docx",
        [Spec("size", "font.size_pt", 10, 12)],
        complex_document=complex_document,
    )
    plan = case.plan()
    candidate = tmp_path / "candidate.docx"
    result = apply_approved_patch(case.base_path, candidate, case.snapshot, plan)
    assert result.publishable, result.model_dump()
    return case, plan, candidate


def _gates(case, plan, candidate: Path):
    results = run_integrity_gates(case.base_path, candidate, plan, case.snapshot)
    return {result.gate: result for result in results}


def test_g2_and_g4_reject_deliberate_text_change(tmp_path: Path) -> None:
    case, plan, candidate = _patched(tmp_path)

    def change_text(root: etree._Element) -> None:
        target = locate_snapshot_element(root, plan.operations[0].target)
        text = target.find(f".//{{{W_NS}}}t")
        assert text is not None
        text.text = "UNAUTHORIZED"

    mutate_xml(candidate, "word/document.xml", change_text)
    results = _gates(case, plan, candidate)
    assert results["G2"].status == "FAIL"
    assert results["G4"].status == "FAIL"
    assert any(item["code"] == "TEXT_CHANGED" for item in results["G4"].details["differences"])


def test_g4_rejects_tail_change_even_when_g2_text_sequence_matches(tmp_path: Path) -> None:
    case, plan, candidate = _patched(tmp_path)

    def change_tail(root: etree._Element) -> None:
        target = locate_snapshot_element(root, plan.operations[0].target)
        text = target.find(f".//{{{W_NS}}}t")
        assert text is not None
        text.tail = "unexpected-tail"

    mutate_xml(candidate, "word/document.xml", change_tail)
    results = _gates(case, plan, candidate)
    assert results["G2"].status == "PASS"
    assert results["G4"].status == "FAIL"
    assert any(item["code"] == "TAIL_CHANGED" for item in results["G4"].details["differences"])


def test_g3_and_g4_reject_deleted_media(tmp_path: Path) -> None:
    case, plan, candidate = _patched(tmp_path, complex_document=True)
    parts = read_parts(candidate)
    media = [name for name in parts if name.startswith("word/media/")]
    assert media
    for name in media:
        del parts[name]
    write_parts(candidate, parts)
    results = _gates(case, plan, candidate)
    assert results["G3"].status == "FAIL"
    assert results["G3"].details["missing"]
    assert results["G4"].status == "FAIL"


def test_g3_rejects_relationship_change(tmp_path: Path) -> None:
    case, plan, candidate = _patched(tmp_path, complex_document=True)
    parts = read_parts(candidate)
    name = "word/_rels/document.xml.rels"
    parts[name] = parts[name].replace(b"https://example.com/a-b", b"https://example.com/changed")
    write_parts(candidate, parts)
    results = _gates(case, plan, candidate)
    assert results["G3"].status == "FAIL"
    assert name in results["G3"].details["changed"]


def test_g4_rejects_attribute_outside_operation_whitelist(tmp_path: Path) -> None:
    case, plan, candidate = _patched(tmp_path)

    def add_italic(root: etree._Element) -> None:
        target = locate_snapshot_element(root, plan.operations[0].target)
        run = list(target.iter(f"{{{W_NS}}}r"))[0]
        rpr = run.find(f"{{{W_NS}}}rPr")
        assert rpr is not None
        italic = etree.SubElement(rpr, f"{{{W_NS}}}i")
        italic.set(f"{{{W_NS}}}val", "1")

    mutate_xml(candidate, "word/document.xml", add_italic)
    results = _gates(case, plan, candidate)
    assert results["G2"].status == "PASS"
    assert results["G3"].status == "PASS"
    assert results["G4"].status == "FAIL"
    assert results["G4"].details["difference_count"] > 0


def test_g4_rejects_unauthorized_part_byte_change(tmp_path: Path) -> None:
    case, plan, candidate = _patched(tmp_path)
    parts = read_parts(candidate)
    parts["word/styles.xml"] = parts["word/styles.xml"].replace(
        b"</w:styles>", b"<w:latentStyles/></w:styles>"
    )
    write_parts(candidate, parts)
    results = _gates(case, plan, candidate)
    assert results["G4"].status == "FAIL"
    assert any(
        item.get("code") == "UNAUTHORIZED_PART_BYTES_CHANGED"
        for item in results["G4"].details["differences"]
    )


def test_g1_failure_marks_candidate_not_publishable(tmp_path: Path) -> None:
    case = build_case(tmp_path / "base.docx", [Spec("size", "font.size_pt", 10, 12)])
    candidate = tmp_path / "broken.docx"
    candidate.write_bytes(b"not a zip")
    results = _gates(case, case.plan(), candidate)
    assert results["G1"].status == "FAIL"
    assert any(result.status == "FAIL" for result in results.values())
