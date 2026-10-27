from __future__ import annotations

from typing import Any

import pytest
from alinea_contracts.errors import AlineaError
from alinea_contracts.models import (
    DocumentSnapshot,
    ElementRef,
    ParagraphNode,
    ResolvedProperty,
    RuleSet,
    RunNode,
    SectionNode,
)
from alinea_docx.inspector import inspect_document
from alinea_docx.rules import compute_ruleset_digest


def resolve_values(
    values: dict[str, Any], status: str = "RESOLVED", origin: str = "DIRECT"
) -> dict[str, ResolvedProperty]:
    return {
        property_name: ResolvedProperty(
            property=property_name,
            value=value,
            status=status,
            origin=origin,
            raw_ooxml_value=f"raw:{property_name}",
        )
        for property_name, value in values.items()
    }


def paragraph_ref(ordinal: int = 0) -> ElementRef:
    return ElementRef(
        revision_id="rev_1",
        part_uri="/word/document.xml",
        kind="paragraph",
        xml_path=f"/w:document/w:body/w:p[{ordinal + 1}]",
        paragraph_ordinal=ordinal,
        text_sha256=f"paragraph-{ordinal}",
        text_excerpt=f"段落 {ordinal}",
    )


def section_ref(ordinal: int = 0) -> ElementRef:
    return ElementRef(
        revision_id="rev_1",
        part_uri="/word/document.xml",
        kind="section",
        xml_path=f"/w:document/w:body/w:sectPr[{ordinal + 1}]",
        paragraph_ordinal=ordinal,
        section_ordinal=ordinal,
        text_sha256=f"section-{ordinal}",
    )


def make_run(
    index: int,
    text: str,
    values: dict[str, Any] | None = None,
    *,
    status: str = "RESOLVED",
    origin: str = "DIRECT",
    unsupported_features: list[str] | None = None,
) -> RunNode:
    return RunNode(
        index=index,
        text=text,
        effective=resolve_values(values or {}, status, origin),
        unsupported_features=unsupported_features or [],
    )


def make_paragraph(
    *,
    role: str = "body",
    ordinal: int = 0,
    runs: list[RunNode] | None = None,
    values: dict[str, Any] | None = None,
    status: str = "RESOLVED",
    origin: str = "DIRECT",
    unsupported_features: list[str] | None = None,
) -> ParagraphNode:
    selected_runs = runs or []
    return ParagraphNode(
        element_ref=paragraph_ref(ordinal),
        text="".join(run.text for run in selected_runs) or f"段落 {ordinal}",
        normalized_text=f"paragraph-{ordinal}",
        semantic_role=role,
        role_confidence=1,
        runs=selected_runs,
        effective=resolve_values(values or {}, status, origin),
        unsupported_features=unsupported_features or [],
    )


def make_section(
    ordinal: int = 0,
    values: dict[str, Any] | None = None,
    *,
    status: str = "RESOLVED",
    origin: str = "DIRECT",
) -> SectionNode:
    return SectionNode(
        element_ref=section_ref(ordinal),
        effective=resolve_values(values or {}, status, origin),
    )


def make_snapshot(
    *,
    paragraphs: list[ParagraphNode] | None = None,
    sections: list[SectionNode] | None = None,
    unsupported_features: list[str] | None = None,
) -> DocumentSnapshot:
    return DocumentSnapshot(
        revision_id="rev_1",
        sha256="snapshot-sha256",
        parts=[],
        paragraphs=paragraphs or [],
        sections=sections or [],
        styles={},
        unsupported_features=unsupported_features or [],
        renderer_profile_id="test-renderer",
    )


def make_rule(**changes: Any) -> dict[str, Any]:
    rule: dict[str, Any] = {
        "rule_id": "size_rule",
        "selector": "body",
        "property": "font.size_pt",
        "operator": "eq",
        "expected": 12,
        "tolerance": 0,
        "source": {
            "source_type": "user_text",
            "reference": "user requirement 1",
            "quote": "正文使用 12 pt 字号",
        },
    }
    rule.update(changes)
    return rule


def make_ruleset(rules: list[dict[str, Any]], status: str = "APPROVED") -> RuleSet:
    return RuleSet(
        rule_set_id="rs_test",
        project_id="project_test",
        version=1,
        name="测试规则集",
        status=status,
        digest=compute_ruleset_digest(rules),
        rules=rules,
    )


def inspect_single(
    property_name: str,
    expected: Any,
    actual: Any,
    **rule_changes: Any,
):
    selector = "section" if property_name.startswith("section.") else "body"
    tolerance = rule_changes.pop("tolerance", 0)
    rule = make_rule(
        selector=selector,
        property=property_name,
        expected=expected,
        tolerance=tolerance,
        **rule_changes,
    )
    if selector == "section":
        snapshot = make_snapshot(sections=[make_section(values={property_name: actual})])
    elif property_name.startswith("font."):
        text = "中文" if property_name == "font.eastAsia" else "ABC"
        snapshot = make_snapshot(
            paragraphs=[make_paragraph(runs=[make_run(0, text, {property_name: actual})])]
        )
    else:
        snapshot = make_snapshot(paragraphs=[make_paragraph(values={property_name: actual})])
    return inspect_document(snapshot, make_ruleset([rule]), inspection_id="ins_test")


def test_inspector_rejects_non_approved_rulesets() -> None:
    with pytest.raises(AlineaError) as caught:
        inspect_document(make_snapshot(), make_ruleset([make_rule()], status="DRAFT"))

    assert caught.value.code == "RULESET_NOT_APPROVED"


@pytest.mark.parametrize(
    ("property_name", "expected", "actual", "unit"),
    [
        ("font.eastAsia", "宋体", "仿宋", None),
        ("font.ascii", "Times New Roman", "Arial", None),
        ("font.size_pt", 12, 10, "pt"),
        ("font.bold", True, False, None),
        ("paragraph.alignment", "justify", "left", None),
        ("paragraph.first_line_indent_chars", 2, 1, "chars"),
        ("paragraph.first_line_indent_mm", 8, 10, "mm"),
        ("paragraph.left_indent_mm", 0, 5, "mm"),
        ("paragraph.right_indent_mm", 0, 5, "mm"),
        (
            "paragraph.line_spacing",
            {"type": "MULTIPLE", "value": 1.5},
            {"type": "MULTIPLE", "value": 1},
            "multiple",
        ),
        ("paragraph.space_before_pt", 0, 6, "pt"),
        ("paragraph.space_after_pt", 0, 6, "pt"),
        ("section.margin_top_mm", 25, 20, "mm"),
        ("section.margin_bottom_mm", 25, 20, "mm"),
        ("section.margin_left_mm", 30, 20, "mm"),
        ("section.margin_right_mm", 25, 20, "mm"),
        ("section.page_width_mm", 210, 200, "mm"),
        ("section.page_height_mm", 297, 290, "mm"),
    ],
)
def test_every_supported_property_emits_typed_evidence(
    property_name: str, expected: Any, actual: Any, unit: str | None
) -> None:
    result = inspect_single(property_name, expected, actual)

    assert result.summary.violations == 1
    assert result.summary.unverifiable == 0
    assert result.summary.evaluated_rules == 1
    issue = result.issues[0]
    assert issue.property == property_name
    assert issue.actual.value == actual
    assert issue.actual.unit == unit
    assert issue.actual.origin == "DIRECT"
    assert issue.expected.value == expected
    assert issue.expected.unit == unit
    assert issue.expected.origin == "RULE"
    assert issue.location.status == "PENDING"
    assert issue.location.issue_id == issue.issue_id


def test_role_selection_script_selection_and_empty_runs() -> None:
    body = make_paragraph(
        runs=[
            make_run(0, "中文", {"font.eastAsia": "仿宋", "font.ascii": "Arial"}),
            make_run(1, "English", {"font.eastAsia": "仿宋", "font.ascii": "Arial"}),
            make_run(2, "", {"font.eastAsia": "仿宋", "font.ascii": "Arial"}),
            make_run(3, "   ", {"font.eastAsia": "仿宋", "font.ascii": "Arial"}),
            make_run(4, "中文ABC", {"font.eastAsia": "仿宋", "font.ascii": "Arial"}),
        ]
    )
    heading = make_paragraph(
        role="heading_1",
        ordinal=1,
        runs=[make_run(0, "中文Heading", {"font.eastAsia": "仿宋", "font.ascii": "Arial"})],
    )
    rules = [
        make_rule(rule_id="east_asia", property="font.eastAsia", expected="宋体"),
        make_rule(rule_id="ascii", property="font.ascii", expected="Times New Roman"),
    ]

    result = inspect_document(make_snapshot(paragraphs=[body, heading]), make_ruleset(rules))
    targets = {
        (
            issue.element_ref.paragraph_ordinal,
            issue.element_ref.run_range.start,
            issue.property,
        )
        for issue in result.issues
    }

    assert targets == {
        (0, 0, "font.eastAsia"),
        (0, 1, "font.ascii"),
        (0, 4, "font.eastAsia"),
        (0, 4, "font.ascii"),
    }
    assert result.summary.evaluated_rules == 2
    assert result.summary.skipped_rules == 0
    assert result.summary.violations == 4
    assert result.summary.fixable == 4


def test_inherited_origin_comes_from_input_resolved_property() -> None:
    paragraph = make_paragraph(
        runs=[
            make_run(
                0,
                "ABC",
                {"font.size_pt": 10},
                origin="BASED_ON",
            )
        ]
    )

    result = inspect_document(make_snapshot(paragraphs=[paragraph]), make_ruleset([make_rule()]))

    assert result.issues[0].actual.origin == "BASED_ON"
    assert result.issues[0].actual.raw_ooxml_value == "raw:font.size_pt"


def test_unknown_values_are_not_confirmed_violations() -> None:
    runs = [
        make_run(0, "a", {"font.size_pt": None}, status="UNRESOLVED", origin="UNKNOWN"),
        make_run(1, "b", {"font.size_pt": 10}, status="UNSUPPORTED", origin="UNKNOWN"),
        make_run(2, "c", {"font.size_pt": 10}, status="CONFLICTED", origin="UNKNOWN"),
        make_run(3, "d", {"font.size_pt": 10}),
        make_run(4, "e", {"font.size_pt": "12"}),
    ]

    result = inspect_document(
        make_snapshot(paragraphs=[make_paragraph(runs=runs)]),
        make_ruleset([make_rule()]),
    )

    unknown = [issue for issue in result.issues if issue.detection_status == "UNKNOWN"]
    assert len(result.issues) == 5
    assert len(unknown) == 4
    assert result.summary.violations == 1
    assert result.summary.unverifiable == 4
    assert result.summary.fixable == 1
    assert all(issue.repair.eligibility == "UNSUPPORTED" for issue in unknown)
    assert all(issue.location.status == "PENDING" for issue in unknown)


def test_duplicate_findings_deduplicate_and_ids_are_stable() -> None:
    snapshot = make_snapshot(
        paragraphs=[make_paragraph(runs=[make_run(0, "ABC", {"font.size_pt": 10})])]
    )
    ruleset = make_ruleset([make_rule(), make_rule()])

    first = inspect_document(snapshot, ruleset, inspection_id="ins_stable")
    second = inspect_document(snapshot, ruleset, inspection_id="ins_stable")
    other = inspect_document(snapshot, ruleset, inspection_id="ins_other")

    assert len(first.issues) == 1
    assert first.summary.evaluated_rules == 2
    assert first.summary.violations == 1
    assert first.issues[0].issue_id == second.issues[0].issue_id
    assert first.issues[0].fingerprint == second.issues[0].fingerprint
    assert first.issues[0].fingerprint == other.issues[0].fingerprint
    assert first.issues[0].issue_id != other.issues[0].issue_id


def test_default_inspection_id_is_deterministic() -> None:
    snapshot = make_snapshot(
        paragraphs=[make_paragraph(runs=[make_run(0, "ABC", {"font.size_pt": 10})])]
    )
    ruleset = make_ruleset([make_rule()])

    first = inspect_document(snapshot, ruleset)
    second = inspect_document(snapshot, ruleset)

    assert first.inspection_id == second.inspection_id
    assert first.issues[0].issue_id == second.issues[0].issue_id


@pytest.mark.parametrize(
    ("operator", "expected", "tolerance", "actual", "violating"),
    [
        ("eq", 12, 0.2, 12.2, False),
        ("eq", 12, 0.1, 12.2, True),
        ("in", [10, 12], 0, 10, False),
        ("in", [10, 12], 0, 11, True),
        ("between", [10, 12], 0, 11.5, False),
        ("between", [10, 12], 0.1, 12.05, False),
        ("between", [10, 12], 0.1, 12.2, True),
    ],
)
def test_numeric_operators_and_tolerance(
    operator: str, expected: Any, tolerance: float, actual: float, violating: bool
) -> None:
    result = inspect_single(
        "font.size_pt", expected, actual, operator=operator, tolerance=tolerance
    )

    assert bool(result.issues) is violating


def test_actual_units_are_converted_before_comparison() -> None:
    result = inspect_single("section.margin_top_mm", 24, {"value": 72, "unit": "pt"})

    assert result.issues[0].actual.value == pytest.approx(25.4)
    assert result.issues[0].actual.unit == "mm"
    assert result.issues[0].expected.unit == "mm"


def test_line_spacing_type_mismatch_is_a_violation_not_unknown() -> None:
    result = inspect_single(
        "paragraph.line_spacing",
        {"type": "MULTIPLE", "value": 1.5},
        {"type": "EXACT", "value": 18},
    )

    issue = result.issues[0]
    assert issue.detection_status == "CONFIRMED_VIOLATION"
    assert issue.actual.unit == "pt"
    assert issue.expected.unit == "multiple"


@pytest.mark.parametrize(
    ("scope", "feature"),
    [
        ("document", "tracked_changes"),
        ("paragraph", "OLE"),
        ("run", "formula"),
        ("run", "field"),
    ],
)
def test_document_and_object_risks_block_automatic_repair(scope: str, feature: str) -> None:
    paragraph = make_paragraph(
        runs=[
            make_run(
                0,
                "ABC",
                {"font.size_pt": 10},
                unsupported_features=[feature] if scope == "run" else None,
            )
        ],
        unsupported_features=[feature] if scope == "paragraph" else None,
    )
    snapshot = make_snapshot(
        paragraphs=[paragraph],
        unsupported_features=[feature] if scope == "document" else None,
    )

    result = inspect_document(snapshot, make_ruleset([make_rule()]))

    assert result.issues[0].repair.eligibility == "NEEDS_REVIEW"
    assert result.issues[0].repair.requires_approval is True
    assert feature in (result.issues[0].repair.reason or "")
    assert result.summary.fixable == 0


def test_safe_manual_and_unsupported_repair_eligibility() -> None:
    safe = inspect_single("font.size_pt", 12, 10)
    manual = inspect_single("font.size_pt", 12, 10, fix_policy="MANUAL_ONLY")
    unsupported = inspect_single("font.size_pt", 12, 10, fix_policy="UNSUPPORTED")

    assert safe.issues[0].repair.eligibility == "SAFE_SINGLE_TARGET"
    assert safe.issues[0].repair.requires_approval is True
    assert safe.summary.fixable == 1
    assert manual.issues[0].repair.eligibility == "NEEDS_REVIEW"
    assert manual.summary.fixable == 0
    assert unsupported.issues[0].repair.eligibility == "UNSUPPORTED"
    assert unsupported.summary.fixable == 0


@pytest.mark.parametrize(
    ("property_name", "expected", "actual"),
    [
        ("paragraph.first_line_indent_chars", 2, 1),
        ("section.page_width_mm", 210, 200),
        ("section.page_height_mm", 297, 290),
    ],
)
def test_layout_sensitive_repairs_require_review(
    property_name: str, expected: Any, actual: Any
) -> None:
    result = inspect_single(property_name, expected, actual)

    assert result.issues[0].repair.eligibility == "NEEDS_REVIEW"
    assert result.summary.fixable == 0


def test_each_section_is_an_independent_target() -> None:
    sections = [
        make_section(0, {"section.margin_top_mm": 20}),
        make_section(1, {"section.margin_top_mm": 30}),
    ]
    rule = make_rule(
        rule_id="margin",
        selector="section",
        property="section.margin_top_mm",
        expected=25,
        tolerance=0,
    )

    result = inspect_document(make_snapshot(sections=sections), make_ruleset([rule]))

    assert len(result.issues) == 2
    assert {issue.element_ref.section_ordinal for issue in result.issues} == {0, 1}
    assert result.summary.violations == 2


def test_summary_counts_disabled_and_targetless_rules_as_skipped() -> None:
    snapshot = make_snapshot(
        paragraphs=[make_paragraph(runs=[make_run(0, "ABC", {"font.size_pt": 10})])]
    )
    rules = [
        make_rule(),
        make_rule(rule_id="disabled", expected=14, enabled=False),
        make_rule(rule_id="caption", selector="caption", expected=10),
    ]

    result = inspect_document(snapshot, make_ruleset(rules))

    assert result.summary.evaluated_rules == 1
    assert result.summary.skipped_rules == 2
    assert result.summary.violations == 1


def test_mapping_ruleset_normalizes_legacy_aliases_before_contract_validation() -> None:
    rule = make_rule(rule_id="legacy", property="font.eastAsia", expected="宋体")
    raw_ruleset = make_ruleset([rule]).model_dump(mode="python")
    raw_ruleset["rules"][0]["property"] = "font.east_asia"
    snapshot = make_snapshot(
        paragraphs=[make_paragraph(runs=[make_run(0, "中文", {"font.eastAsia": "仿宋"})])]
    )

    result = inspect_document(snapshot, raw_ruleset)

    assert result.issues[0].property == "font.eastAsia"
    assert result.summary.violations == 1
