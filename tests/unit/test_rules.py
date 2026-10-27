from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from alinea_docx.rules import compute_ruleset_digest, find_conflicts, validate_rule
from pydantic import ValidationError


def make_rule(**changes: Any) -> dict[str, Any]:
    rule: dict[str, Any] = {
        "rule_id": "body_size",
        "selector": "body",
        "property": "font.size_pt",
        "operator": "eq",
        "expected": 12,
        "source": {
            "source_type": "user_text",
            "reference": "user requirement 1",
            "quote": "正文使用 12 pt 字号",
        },
    }
    rule.update(changes)
    return rule


@pytest.mark.parametrize(
    ("alias", "canonical"),
    [("font.east_asia", "font.eastAsia"), ("font.latin", "font.ascii")],
)
def test_legacy_property_aliases_normalize_at_input(alias: str, canonical: str) -> None:
    legacy = make_rule(property=alias, expected="宋体")
    canonical_rule = make_rule(property=canonical, expected="宋体")

    assert validate_rule(legacy).property == canonical
    assert compute_ruleset_digest([legacy]) == compute_ruleset_digest([canonical_rule])


@pytest.mark.parametrize(
    "rule",
    [
        make_rule(expected="12"),
        make_rule(expected=True),
        make_rule(expected={"value": 12, "unit": "mm"}),
        make_rule(property="font.eastAsia", expected=12),
        make_rule(property="font.bold", expected="true"),
        make_rule(property="paragraph.alignment", expected="middle"),
        make_rule(
            property="paragraph.line_spacing",
            expected=1.5,
        ),
        make_rule(operator="between", expected=[10]),
        make_rule(operator="between", expected=[14, 10]),
        make_rule(operator="in", expected=[]),
        make_rule(operator="in", expected=[10, "12"]),
        make_rule(property="font.eastAsia", expected="宋体", tolerance=0.1),
        make_rule(property="font.eastAsia", expected=["宋体", "黑体"], operator="between"),
        make_rule(
            property="paragraph.line_spacing",
            expected={"type": "MULTIPLE", "value": 18, "unit": "pt"},
        ),
        make_rule(
            property="paragraph.line_spacing",
            operator="between",
            expected=[
                {"type": "MULTIPLE", "value": 1},
                {"type": "EXACT", "value": 18},
            ],
        ),
        make_rule(selector="section"),
        make_rule(selector="body", property="section.margin_top_mm", expected=25),
    ],
)
def test_property_type_unit_and_selector_validation(rule: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        validate_rule(rule)


def test_numeric_units_normalize_to_the_property_canonical_unit() -> None:
    rule = validate_rule(
        make_rule(
            selector="section",
            property="section.margin_top_mm",
            expected={"type": "number", "value": 72, "unit": "pt"},
            tolerance=0,
        )
    )

    assert rule.expected == pytest.approx(25.4)
    assert rule.tolerance == 0


def test_top_level_legacy_unit_is_consumed_at_the_boundary() -> None:
    rule = validate_rule(
        make_rule(
            selector="section",
            property="section.margin_top_mm",
            expected=72,
            unit="pt",
        )
    )

    assert rule.expected == pytest.approx(25.4)
    assert "unit" not in rule.model_dump()


@pytest.mark.parametrize(
    ("raw", "canonical_type"),
    [
        ({"kind": "multiple", "value": 1.5}, "MULTIPLE"),
        ({"kind": "exact_pt", "value": 18, "unit": "pt"}, "EXACT"),
        ({"type": "AT_LEAST", "value": 18}, "AT_LEAST"),
    ],
)
def test_line_spacing_types_are_typed_and_normalized(
    raw: dict[str, Any], canonical_type: str
) -> None:
    rule = validate_rule(make_rule(property="paragraph.line_spacing", expected=raw))

    assert rule.expected == {"type": canonical_type, "value": raw["value"]}


@pytest.mark.parametrize("source_type", ["manual", "preset", "pdf", "user_text"])
@pytest.mark.parametrize("field", ["reference", "quote"])
def test_every_rule_requires_source_reference_and_quote(source_type: str, field: str) -> None:
    source = {"source_type": source_type, "reference": "requirement 1", "quote": "原文要求"}
    source[field] = "  "

    with pytest.raises(ValidationError, match="reference and quote"):
        validate_rule(make_rule(source=source))


def test_digest_is_order_independent_and_content_sensitive() -> None:
    first = make_rule(rule_id="first")
    second = make_rule(rule_id="second", property="font.bold", expected=True)

    assert compute_ruleset_digest([first, second]) == compute_ruleset_digest([second, first])
    assert compute_ruleset_digest([first]) != compute_ruleset_digest(
        [make_rule(rule_id="first", expected=14)]
    )


@pytest.mark.parametrize(
    ("left", "right", "conflicting"),
    [
        ({}, {"rule_id": "right", "expected": 14}, True),
        ({}, {"rule_id": "right", "expected": 12}, False),
        ({}, {"rule_id": "right", "operator": "in", "expected": [10, 12]}, False),
        ({}, {"rule_id": "right", "operator": "in", "expected": [10, 11]}, True),
        (
            {"operator": "between", "expected": [10, 11]},
            {"rule_id": "right", "operator": "between", "expected": [12, 14]},
            True,
        ),
        (
            {"operator": "between", "expected": [10, 12]},
            {"rule_id": "right", "expected": 12},
            False,
        ),
        ({}, {"rule_id": "right", "selector": "heading_1", "expected": 14}, False),
        ({}, {"rule_id": "right", "expected": 14, "enabled": False}, False),
    ],
)
def test_conflicts_use_expectation_intersection(
    left: dict[str, Any], right: dict[str, Any], conflicting: bool
) -> None:
    conflicts = find_conflicts([make_rule(**left), make_rule(**right)])

    assert bool(conflicts) is conflicting
    if conflicting:
        assert conflicts[0].rule_ids == ["body_size", "right"]
        assert conflicts[0].resolved is False


def test_line_spacing_conflicts_include_type_semantics() -> None:
    multiple = make_rule(
        rule_id="multiple",
        property="paragraph.line_spacing",
        expected={"type": "MULTIPLE", "value": 1.5},
    )
    exact = make_rule(
        rule_id="exact",
        property="paragraph.line_spacing",
        expected={"type": "EXACT", "value": 18},
    )

    assert len(find_conflicts([multiple, exact])) == 1


@pytest.mark.parametrize("preset_name", ["thesis_demo", "general_report"])
def test_presets_are_approved_traceable_and_internally_consistent(preset_name: str) -> None:
    path = Path(__file__).parents[2] / "packages" / "format-rules" / f"{preset_name}.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    rules = [validate_rule(rule) for rule in data["rules"]]

    assert data["status"] == "APPROVED"
    assert "非官方" in data["name"]
    assert data["digest"] == compute_ruleset_digest(rules)
    assert find_conflicts(rules) == []
    assert all(rule.source.reference and rule.source.quote for rule in rules)
    properties = {rule.property for rule in rules}
    assert len(properties) >= 8
    assert {
        "section.margin_top_mm",
        "section.margin_bottom_mm",
        "section.margin_left_mm",
        "section.margin_right_mm",
    } <= properties
