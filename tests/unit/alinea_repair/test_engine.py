from __future__ import annotations

import hashlib
import zipfile
from pathlib import Path

import pytest
from alinea_contracts.errors import AlineaError
from alinea_contracts.models import RunRange
from alinea_repair import apply_approved_patch, compute_plan_digest
from alinea_repair.ooxml import M_NS, W_NS, locate_snapshot_element, parse_xml
from lxml import etree

from tests.unit.alinea_repair.helpers import (
    Spec,
    build_case,
    gate,
    mutate_xml,
    read_parts,
    sha256_file,
)


def _resign(plan):
    unsigned = plan.model_copy(update={"plan_digest": ""})
    return unsigned.model_copy(update={"plan_digest": compute_plan_digest(unsigned)})


def test_complex_package_single_run_patch_is_lossless(tmp_path: Path) -> None:
    case = build_case(
        tmp_path / "base.docx",
        [Spec("size", "font.size_pt", 10, 12, "p0:r0")],
        complex_document=True,
    )
    original_hash = sha256_file(case.base_path)
    original_parts = read_parts(case.base_path)
    candidate = tmp_path / "candidate.docx"

    result = apply_approved_patch(case.base_path, candidate, case.snapshot, case.plan())

    assert result.status == "PATCHED"
    assert result.publishable is True
    assert result.changed_parts == ["word/document.xml"]
    assert gate(result, "G0").status == "WARN"
    assert [gate(result, name).status for name in ("G1", "G2", "G3", "G4")] == ["PASS"] * 4
    assert sha256_file(case.base_path) == original_hash
    assert result.candidate_sha256 == sha256_file(candidate)
    candidate_parts = read_parts(candidate)
    assert set(candidate_parts) == set(original_parts)
    for name, data in original_parts.items():
        if name != "word/document.xml":
            assert candidate_parts[name] == data, name
    for name, data in original_parts.items():
        if name.startswith(("word/media/", "word/embeddings/")) or name.endswith(".rels"):
            assert candidate_parts[name] == data

    operation = case.plan().operations[0]
    before_root = parse_xml(original_parts["word/document.xml"]).getroot()
    after_root = parse_xml(candidate_parts["word/document.xml"]).getroot()
    before_paragraph = locate_snapshot_element(before_root, operation.target)
    after_paragraph = locate_snapshot_element(after_root, operation.target)
    before_runs = list(before_paragraph.iter(f"{{{W_NS}}}r"))
    after_runs = list(after_paragraph.iter(f"{{{W_NS}}}r"))
    assert etree.tostring(before_runs[1]) == etree.tostring(after_runs[1])
    rpr = after_runs[0].find(f"{{{W_NS}}}rPr")
    assert rpr is not None
    assert after_runs[0][0] is rpr
    assert rpr.find(f"{{{W_NS}}}sz").get(f"{{{W_NS}}}val") == "24"
    assert rpr.find(f"{{{W_NS}}}szCs").get(f"{{{W_NS}}}val") == "24"
    assert after_runs[0].find(f"{{{W_NS}}}t").text == "Hello-0 "


def test_missing_rpr_ppr_insertion_and_schema_order(tmp_path: Path) -> None:
    case = build_case(
        tmp_path / "base.docx",
        [
            Spec("bold", "font.bold", False, True, "p0:r0"),
            Spec(
                "spacing",
                "paragraph.line_spacing",
                {"type": "MULTIPLE", "value": 1},
                {"type": "MULTIPLE", "value": 1.5},
                "p0",
            ),
            Spec("alignment", "paragraph.alignment", "left", "center", "p0"),
        ],
    )
    result = apply_approved_patch(
        case.base_path, tmp_path / "candidate.docx", case.snapshot, case.plan()
    )
    assert result.publishable, result.model_dump()
    root = parse_xml(read_parts(tmp_path / "candidate.docx")["word/document.xml"]).getroot()
    paragraph = locate_snapshot_element(root, case.issues[1].element_ref)
    ppr = paragraph.find(f"{{{W_NS}}}pPr")
    assert ppr is not None and paragraph[0] is ppr
    assert [etree.QName(child).localname for child in ppr] == ["spacing", "jc"]
    run = list(paragraph.iter(f"{{{W_NS}}}r"))[0]
    rpr = run.find(f"{{{W_NS}}}rPr")
    assert rpr is not None and run[0] is rpr
    assert [etree.QName(child).localname for child in rpr] == ["b", "bCs"]
    assert rpr.find(f"{{{W_NS}}}b").get(f"{{{W_NS}}}val") == "1"
    assert rpr.find(f"{{{W_NS}}}bCs").get(f"{{{W_NS}}}val") == "1"


def test_unapproved_or_missing_approval_time_is_rejected(tmp_path: Path) -> None:
    case = build_case(tmp_path / "base.docx", [Spec("size", "font.size_pt", 10, 12)])
    for plan in (case.plan(approved=False), case.plan().model_copy(update={"approved_at": None})):
        with pytest.raises(AlineaError) as caught:
            apply_approved_patch(case.base_path, tmp_path / "candidate.docx", case.snapshot, plan)
        assert caught.value.code == "REPAIR_NOT_APPROVED"
        assert caught.value.status_code == 409
        assert not (tmp_path / "candidate.docx").exists()


def test_stale_base_and_digest_tampering_never_write_candidate(tmp_path: Path) -> None:
    case = build_case(tmp_path / "base.docx", [Spec("size", "font.size_pt", 10, 12)])
    with case.base_path.open("ab") as stream:
        stream.write(b"stale-suffix")
    stale_hash = sha256_file(case.base_path)
    with pytest.raises(AlineaError) as caught:
        apply_approved_patch(case.base_path, tmp_path / "stale.docx", case.snapshot, case.plan())
    assert caught.value.code == "STALE_REPAIR_PLAN"
    assert caught.value.status_code == 409
    assert sha256_file(case.base_path) == stale_hash
    assert not (tmp_path / "stale.docx").exists()

    fresh_case = build_case(tmp_path / "fresh.docx", [Spec("size", "font.size_pt", 10, 12)])
    plan = fresh_case.plan()
    operation = plan.operations[0].model_copy(update={"desired_after": 14})
    tampered = plan.model_copy(update={"operations": [operation]})
    with pytest.raises(AlineaError) as caught:
        apply_approved_patch(
            fresh_case.base_path, tmp_path / "tampered.docx", fresh_case.snapshot, tampered
        )
    assert caught.value.code == "STALE_REPAIR_PLAN"
    assert not (tmp_path / "tampered.docx").exists()


@pytest.mark.parametrize("precondition", ["before", "base_sha", "ruleset", "para_id", "run_range"])
def test_individual_stale_preconditions_are_rejected(tmp_path: Path, precondition: str) -> None:
    case = build_case(tmp_path / "base.docx", [Spec("size", "font.size_pt", 10, 12)])
    plan = case.plan()
    operation = plan.operations[0]
    if precondition == "before":
        operation = operation.model_copy(update={"expected_before": 99})
    elif precondition == "base_sha":
        operation = operation.model_copy(update={"base_revision_sha256": "0" * 64})
    elif precondition == "ruleset":
        operation = operation.model_copy(update={"rule_set_digest": "changed"})
    elif precondition == "para_id":
        target = operation.target.model_copy(update={"para_id": "FFFFFFFF"})
        operation = operation.model_copy(update={"target": target})
    else:
        target = operation.target.model_copy(update={"run_range": RunRange(start=0, end=99)})
        operation = operation.model_copy(update={"target": target})
    plan = _resign(plan.model_copy(update={"operations": [operation]}))
    with pytest.raises(AlineaError) as caught:
        apply_approved_patch(case.base_path, tmp_path / "candidate.docx", case.snapshot, plan)
    assert caught.value.code == "STALE_REPAIR_PLAN", (precondition, caught.value.details)
    assert not (tmp_path / "candidate.docx").exists()


@pytest.mark.parametrize("feature", ["formula", "field", "textbox"])
def test_complex_exact_target_is_rejected(tmp_path: Path, feature: str) -> None:
    def add_feature(path: Path) -> None:
        def mutate(root: etree._Element) -> None:
            paragraph = root.find(f".//{{{W_NS}}}p")
            assert paragraph is not None
            if feature == "formula":
                etree.SubElement(paragraph, f"{{{M_NS}}}oMath")
            elif feature == "field":
                etree.SubElement(paragraph, f"{{{W_NS}}}fldSimple")
            else:
                etree.SubElement(paragraph, f"{{{W_NS}}}txbxContent")

        mutate_xml(path, "word/document.xml", mutate)

    case = build_case(
        tmp_path / "base.docx",
        [Spec("size", "font.size_pt", 10, 12)],
        mutator=add_feature,
    )
    with pytest.raises(AlineaError) as caught:
        apply_approved_patch(
            case.base_path, tmp_path / "candidate.docx", case.snapshot, case.plan()
        )
    assert caught.value.code == "UNSUPPORTED_FOR_AUTO_REPAIR"
    assert not (tmp_path / "candidate.docx").exists()


def test_global_track_changes_is_rejected(tmp_path: Path) -> None:
    def add_tracking(path: Path) -> None:
        mutate_xml(
            path,
            "word/document.xml",
            lambda root: etree.SubElement(root.find(f"{{{W_NS}}}body"), f"{{{W_NS}}}ins"),
        )

    case = build_case(
        tmp_path / "base.docx",
        [Spec("size", "font.size_pt", 10, 12)],
        mutator=add_tracking,
    )
    with pytest.raises(AlineaError) as caught:
        apply_approved_patch(
            case.base_path, tmp_path / "candidate.docx", case.snapshot, case.plan()
        )
    assert caught.value.code == "UNSUPPORTED_FOR_AUTO_REPAIR"
    assert not (tmp_path / "candidate.docx").exists()


def test_execution_key_actor_is_verified(tmp_path: Path) -> None:
    case = build_case(tmp_path / "base.docx", [Spec("size", "font.size_pt", 10, 12)])
    plan = case.plan(actor="user-1")
    with pytest.raises(AlineaError) as caught:
        apply_approved_patch(case.base_path, tmp_path / "missing.docx", case.snapshot, plan)
    assert caught.value.code == "APPROVED_ACTOR_REQUIRED"
    result = apply_approved_patch(
        case.base_path,
        tmp_path / "candidate.docx",
        case.snapshot,
        plan,
        approved_actor="user-1",
    )
    expected = hashlib.sha256(
        (plan.plan_digest + case.snapshot.sha256 + "user-1").encode()
    ).hexdigest()
    assert result.execution_key == expected
    assert result.publishable


def test_base_path_cannot_be_candidate(tmp_path: Path) -> None:
    case = build_case(tmp_path / "base.docx", [Spec("size", "font.size_pt", 10, 12)])
    with pytest.raises(AlineaError) as caught:
        apply_approved_patch(case.base_path, case.base_path, case.snapshot, case.plan())
    assert caught.value.code == "IMMUTABLE_BASE_VIOLATION"
    assert zipfile.is_zipfile(case.base_path)


def test_text_anchor_accepts_ooxml_breaks_and_tabs(tmp_path: Path) -> None:
    def add_controls(path: Path) -> None:
        def mutate(root: etree._Element) -> None:
            run = root.find(f".//{{{W_NS}}}r")
            assert run is not None
            etree.SubElement(run, f"{{{W_NS}}}br")
            etree.SubElement(run, f"{{{W_NS}}}tab")

        mutate_xml(path, "word/document.xml", mutate)

    case = build_case(
        tmp_path / "base.docx",
        [Spec("alignment", "paragraph.alignment", "left", "center", "p0")],
        mutator=add_controls,
    )

    result = apply_approved_patch(
        case.base_path, tmp_path / "candidate.docx", case.snapshot, case.plan()
    )

    assert result.publishable


def test_section_anchor_uses_section_xml_hash(tmp_path: Path) -> None:
    case = build_case(
        tmp_path / "base.docx",
        [Spec("margin", "section.margin_top_mm", 20, 25.4, "section")],
    )

    result = apply_approved_patch(
        case.base_path, tmp_path / "candidate.docx", case.snapshot, case.plan()
    )

    assert result.publishable
