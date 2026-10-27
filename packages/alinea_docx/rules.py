from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from itertools import combinations
from typing import Any, Literal, Self

from alinea_contracts.models import FormatRule, RuleConflict, RuleSet
from pydantic import model_validator

_PROPERTY_ALIASES = {
    "font.east_asia": "font.eastAsia",
    "font.latin": "font.ascii",
}
_LINE_TYPE_ALIASES = {
    "MULTIPLE": "MULTIPLE",
    "EXACT": "EXACT",
    "EXACT_PT": "EXACT",
    "AT_LEAST": "AT_LEAST",
    "AT_LEAST_PT": "AT_LEAST",
}
_UNIT_ALIASES = {
    "point": "pt",
    "points": "pt",
    "millimeter": "mm",
    "millimeters": "mm",
    "char": "chars",
    "character": "chars",
    "characters": "chars",
    "x": "multiple",
    "ratio": "multiple",
}
_MM_PER_PT = 25.4 / 72


@dataclass(frozen=True)
class _PropertySpec:
    kind: Literal["number", "string", "boolean", "alignment", "line_spacing"]
    unit: str | None = None
    units: Mapping[str, float] | None = None
    default_tolerance: float = 0
    positive: bool = False
    nonnegative: bool = False


_PROPERTY_SPECS: dict[str, _PropertySpec] = {
    "font.eastAsia": _PropertySpec("string"),
    "font.ascii": _PropertySpec("string"),
    "font.size_pt": _PropertySpec("number", "pt", {"pt": 1}, default_tolerance=0.1, positive=True),
    "font.bold": _PropertySpec("boolean"),
    "paragraph.alignment": _PropertySpec("alignment"),
    "paragraph.first_line_indent_chars": _PropertySpec(
        "number", "chars", {"chars": 1}, nonnegative=True
    ),
    "paragraph.first_line_indent_mm": _PropertySpec(
        "number", "mm", {"mm": 1, "pt": _MM_PER_PT}, default_tolerance=0.2
    ),
    "paragraph.left_indent_mm": _PropertySpec(
        "number", "mm", {"mm": 1, "pt": _MM_PER_PT}, default_tolerance=0.2
    ),
    "paragraph.right_indent_mm": _PropertySpec(
        "number", "mm", {"mm": 1, "pt": _MM_PER_PT}, default_tolerance=0.2
    ),
    "paragraph.line_spacing": _PropertySpec("line_spacing"),
    "paragraph.space_before_pt": _PropertySpec(
        "number", "pt", {"pt": 1}, default_tolerance=0.25, nonnegative=True
    ),
    "paragraph.space_after_pt": _PropertySpec(
        "number", "pt", {"pt": 1}, default_tolerance=0.25, nonnegative=True
    ),
    "section.margin_top_mm": _PropertySpec(
        "number", "mm", {"mm": 1, "pt": _MM_PER_PT}, default_tolerance=0.5, nonnegative=True
    ),
    "section.margin_bottom_mm": _PropertySpec(
        "number", "mm", {"mm": 1, "pt": _MM_PER_PT}, default_tolerance=0.5, nonnegative=True
    ),
    "section.margin_left_mm": _PropertySpec(
        "number", "mm", {"mm": 1, "pt": _MM_PER_PT}, default_tolerance=0.5, nonnegative=True
    ),
    "section.margin_right_mm": _PropertySpec(
        "number", "mm", {"mm": 1, "pt": _MM_PER_PT}, default_tolerance=0.5, nonnegative=True
    ),
    "section.page_width_mm": _PropertySpec(
        "number", "mm", {"mm": 1, "pt": _MM_PER_PT}, default_tolerance=0.5, positive=True
    ),
    "section.page_height_mm": _PropertySpec(
        "number", "mm", {"mm": 1, "pt": _MM_PER_PT}, default_tolerance=0.5, positive=True
    ),
}


def _clean_number(value: Any) -> int | float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("expected a number, not a boolean or non-numeric value")
    if not math.isfinite(value):
        raise ValueError("numeric values must be finite")
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


def _normalize_unit(unit: Any) -> str | None:
    if unit is None:
        return None
    if not isinstance(unit, str) or not unit.strip():
        raise ValueError("unit must be a non-empty string")
    normalized = unit.strip().lower()
    return _UNIT_ALIASES.get(normalized, normalized)


def _normalize_number(value: Any, spec: _PropertySpec, unit_override: Any = None) -> int | float:
    unit = _normalize_unit(unit_override)
    raw_value = value
    if isinstance(value, Mapping):
        if set(value) - {"type", "value", "unit"}:
            raise ValueError("a numeric value object only allows type, value, and unit")
        if "type" in value and value["type"] != "number":
            raise ValueError("a numeric value object must have type='number'")
        if "value" not in value:
            raise ValueError("a numeric value object requires value")
        own_unit = _normalize_unit(value.get("unit"))
        if unit is not None and own_unit is not None and unit != own_unit:
            raise ValueError("conflicting units in rule input")
        unit = own_unit if own_unit is not None else unit
        raw_value = value["value"]
    number = _clean_number(raw_value)
    if unit is None:
        return number
    if spec.units is None or unit not in spec.units:
        raise ValueError(f"unit {unit!r} is not valid for this property")
    converted = float(number) * spec.units[unit]
    return _clean_number(converted)


def _canonical_line_type(value: Any) -> str:
    if not isinstance(value, str):
        raise ValueError("line spacing requires a string type")
    normalized = value.strip().upper()
    if normalized not in _LINE_TYPE_ALIASES:
        raise ValueError("line spacing type must be MULTIPLE, EXACT, or AT_LEAST")
    return _LINE_TYPE_ALIASES[normalized]


def _normalize_line_spacing(value: Any, unit_override: Any = None) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError("line spacing must be a typed object")
    if set(value) - {"type", "kind", "value", "unit"}:
        raise ValueError("line spacing only allows type/kind, value, and unit")
    raw_type = value.get("type", value.get("kind"))
    line_type = _canonical_line_type(raw_type)
    if "type" in value and "kind" in value:
        if _canonical_line_type(value["type"]) != _canonical_line_type(value["kind"]):
            raise ValueError("conflicting line spacing type and kind")
    if "value" not in value:
        raise ValueError("line spacing requires value")
    unit = _normalize_unit(unit_override)
    own_unit = _normalize_unit(value.get("unit"))
    if unit is not None and own_unit is not None and unit != own_unit:
        raise ValueError("conflicting line spacing units")
    unit = own_unit if own_unit is not None else unit
    allowed_units = {"multiple", None} if line_type == "MULTIPLE" else {"pt", None}
    if unit not in allowed_units:
        raise ValueError(f"unit {unit!r} is not valid for {line_type} line spacing")
    number = _clean_number(value["value"])
    if number <= 0:
        raise ValueError("line spacing value must be greater than zero")
    return {"type": line_type, "value": number}


def _normalize_string(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("font names must be non-empty strings")
    return value.strip()


def _normalize_alignment(value: Any) -> str:
    if not isinstance(value, str):
        raise ValueError("alignment must be a string")
    normalized = value.strip().lower()
    if normalized == "both":
        normalized = "justify"
    if normalized not in {"left", "center", "right", "justify"}:
        raise ValueError("alignment must be left, center, right, or justify")
    return normalized


def _normalize_expected(
    property_name: str, operator: str, expected: Any, unit_override: Any = None
) -> Any:
    if operator not in {"eq", "in", "between"}:
        raise ValueError("operator must be eq, in, or between")
    spec = _PROPERTY_SPECS[property_name]
    if operator == "between" and isinstance(expected, Mapping) and spec.kind == "number":
        if set(expected) - {"min", "max", "unit"} or not {"min", "max"} <= set(expected):
            raise ValueError("a range object requires min and max and only allows unit")
        range_unit = expected.get("unit", unit_override)
        expected = [expected["min"], expected["max"]]
        unit_override = range_unit
    if operator in {"in", "between"}:
        if not isinstance(expected, (list, tuple)):
            raise ValueError(f"operator={operator} requires an array")
        values = list(expected)
    else:
        values = [expected]

    def normalize(value: Any) -> Any:
        if spec.kind == "number":
            return _normalize_number(value, spec, unit_override)
        if spec.kind == "line_spacing":
            return _normalize_line_spacing(value, unit_override)
        if spec.kind == "string":
            return _normalize_string(value)
        if spec.kind == "alignment":
            return _normalize_alignment(value)
        if not isinstance(value, bool):
            raise ValueError("font.bold expects a boolean")
        return value

    normalized = [normalize(value) for value in values]
    return normalized if operator in {"in", "between"} else normalized[0]


def _default_tolerance(property_name: str, operator: str, expected: Any) -> float:
    spec = _PROPERTY_SPECS[property_name]
    if spec.kind != "line_spacing":
        return spec.default_tolerance
    sample = expected[0] if operator in {"in", "between"} else expected
    return 0.01 if sample["type"] == "MULTIPLE" else 0.25


def _normalize_rule_mapping(data: Mapping[Any, Any]) -> dict[str, Any]:
    normalized = dict(data)
    if "rule_id" not in normalized and "id" in normalized:
        normalized["rule_id"] = normalized.pop("id")
    property_name = normalized.get("property")
    if isinstance(property_name, str):
        normalized["property"] = _PROPERTY_ALIASES.get(property_name, property_name)
        property_name = normalized["property"]
    if property_name in _PROPERTY_SPECS and "expected" in normalized:
        unit = normalized.pop("unit", None)
        operator = normalized.get("operator", "eq")
        normalized["expected"] = _normalize_expected(
            property_name, operator, normalized["expected"], unit
        )
        if "tolerance" not in normalized:
            normalized["tolerance"] = _default_tolerance(
                property_name, operator, normalized["expected"]
            )
    tolerance = normalized.get("tolerance")
    if isinstance(tolerance, Mapping):
        if set(tolerance) != {"absolute"}:
            raise ValueError("a tolerance object must contain only absolute")
        normalized["tolerance"] = tolerance["absolute"]
    return normalized


def _validate_scalar(property_name: str, value: Any) -> None:
    spec = _PROPERTY_SPECS[property_name]
    if spec.kind == "number":
        number = _clean_number(value)
        if spec.positive and number <= 0:
            raise ValueError(f"{property_name} expects a value greater than zero")
        if spec.nonnegative and number < 0:
            raise ValueError(f"{property_name} expects a non-negative value")
    elif spec.kind == "string":
        _normalize_string(value)
    elif spec.kind == "alignment":
        _normalize_alignment(value)
    elif spec.kind == "line_spacing":
        _normalize_line_spacing(value)
    elif not isinstance(value, bool):
        raise ValueError("font.bold expects a boolean")


class ValidatedFormatRule(FormatRule):
    @model_validator(mode="before")
    @classmethod
    def normalize_input(cls, data: Any) -> Any:
        if isinstance(data, FormatRule):
            data = data.model_dump(mode="python")
        if isinstance(data, Mapping):
            return _normalize_rule_mapping(data)
        return data

    @model_validator(mode="after")
    def validate_property_contract(self) -> Self:
        if not self.source.reference.strip() or not self.source.quote.strip():
            raise ValueError("rule source requires non-empty reference and quote")
        is_section_property = self.property.startswith("section.")
        if (self.selector == "section") != is_section_property:
            raise ValueError("section properties require selector='section' and vice versa")
        if not math.isfinite(self.tolerance):
            raise ValueError("tolerance must be finite")
        spec = _PROPERTY_SPECS[self.property]
        if spec.kind not in {"number", "line_spacing"} and self.tolerance != 0:
            raise ValueError("tolerance is only valid for numeric and line spacing rules")
        if self.operator == "between" and spec.kind not in {"number", "line_spacing"}:
            raise ValueError("operator=between is only valid for numeric and line spacing rules")
        if self.operator in {"in", "between"}:
            if not isinstance(self.expected, list) or not self.expected:
                raise ValueError(f"operator={self.operator} requires a non-empty array")
            values = self.expected
        else:
            values = [self.expected]
        if self.operator == "between" and len(values) != 2:
            raise ValueError("operator=between requires exactly two values")
        for value in values:
            _validate_scalar(self.property, value)
        if self.operator == "between":
            lower, upper = values
            if spec.kind == "line_spacing":
                if lower["type"] != upper["type"]:
                    raise ValueError("a line spacing range must use one type")
                lower, upper = lower["value"], upper["value"]
            if lower > upper:
                raise ValueError("a between range must be ordered from lower to upper")
        return self


def validate_rule(rule: FormatRule | Mapping[str, Any]) -> FormatRule:
    data = rule.model_dump(mode="python") if isinstance(rule, FormatRule) else rule
    return ValidatedFormatRule.model_validate(data)


def _rule_list(
    rules: RuleSet | Iterable[FormatRule | Mapping[str, Any]],
) -> list[FormatRule]:
    source = rules.rules if isinstance(rules, RuleSet) else rules
    return [validate_rule(rule) for rule in source]


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def compute_ruleset_digest(
    rules: RuleSet | Iterable[FormatRule | Mapping[str, Any]],
) -> str:
    canonical_rules = sorted(
        _canonical_json(rule.model_dump(mode="json", exclude_none=True))
        for rule in _rule_list(rules)
    )
    return hashlib.sha256(_canonical_json(canonical_rules).encode("utf-8")).hexdigest()


def _numeric_intervals(rule: FormatRule, values: list[Any]) -> list[tuple[float, float]]:
    tolerance = float(rule.tolerance)
    if rule.operator == "eq":
        return [(float(values[0]) - tolerance, float(values[0]) + tolerance)]
    if rule.operator == "in":
        return [(float(value) - tolerance, float(value) + tolerance) for value in values]
    return [(float(values[0]) - tolerance, float(values[1]) + tolerance)]


def _constraints_overlap(left: FormatRule, right: FormatRule) -> bool:
    spec = _PROPERTY_SPECS[left.property]
    left_values = left.expected if left.operator in {"in", "between"} else [left.expected]
    right_values = right.expected if right.operator in {"in", "between"} else [right.expected]
    if spec.kind == "number":
        left_intervals = _numeric_intervals(left, left_values)
        right_intervals = _numeric_intervals(right, right_values)
        return any(
            max(left_low, right_low) <= min(left_high, right_high)
            for left_low, left_high in left_intervals
            for right_low, right_high in right_intervals
        )
    if spec.kind == "line_spacing":
        for line_type in ("MULTIPLE", "EXACT", "AT_LEAST"):
            left_typed = [value["value"] for value in left_values if value["type"] == line_type]
            right_typed = [value["value"] for value in right_values if value["type"] == line_type]
            if not left_typed or not right_typed:
                continue
            left_intervals = _numeric_intervals(left, left_typed)
            right_intervals = _numeric_intervals(right, right_typed)
            if any(
                max(left_low, right_low) <= min(left_high, right_high)
                for left_low, left_high in left_intervals
                for right_low, right_high in right_intervals
            ):
                return True
        return False
    left_allowed = {_canonical_json(value) for value in left_values}
    right_allowed = {_canonical_json(value) for value in right_values}
    return not left_allowed.isdisjoint(right_allowed)


def find_conflicts(
    rules: RuleSet | Iterable[FormatRule | Mapping[str, Any]],
) -> list[RuleConflict]:
    validated = [rule for rule in _rule_list(rules) if rule.enabled]
    conflicts: list[RuleConflict] = []
    for left, right in combinations(validated, 2):
        if left.selector != right.selector or left.property != right.property:
            continue
        if _constraints_overlap(left, right):
            continue
        rule_ids = sorted([left.rule_id, right.rule_id])
        identity = _canonical_json(
            {"rule_ids": rule_ids, "selector": left.selector, "property": left.property}
        )
        conflict_id = "conflict_" + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24]
        conflicts.append(
            RuleConflict(
                conflict_id=conflict_id,
                rule_ids=rule_ids,
                property=left.property,
                reason=(
                    f"selector {left.selector!r} and property {left.property!r} "
                    "have mutually exclusive expectations"
                ),
            )
        )
    return sorted(conflicts, key=lambda conflict: conflict.conflict_id)


def _coerce_actual_value(rule: FormatRule, value: Any) -> Any:
    spec = _PROPERTY_SPECS[rule.property]
    if spec.kind == "number":
        return _normalize_number(value, spec)
    if spec.kind == "line_spacing":
        return _normalize_line_spacing(value)
    if spec.kind == "string":
        return _normalize_string(value)
    if spec.kind == "alignment":
        return _normalize_alignment(value)
    if not isinstance(value, bool):
        raise ValueError("resolved font.bold value must be a boolean")
    return value


_FONT_IDENTITIES = {
    "simsun": "simsun",
    "宋体": "simsun",
    "simhei": "simhei",
    "黑体": "simhei",
    "kaiti": "kaiti",
    "楷体": "kaiti",
    "fangsong": "fangsong",
    "仿宋": "fangsong",
    "microsoftyahei": "microsoftyahei",
    "微软雅黑": "microsoftyahei",
}


def _font_identity(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    normalized = "".join(value.split()).casefold()
    return _FONT_IDENTITIES.get(normalized, normalized)


def _matches(rule: FormatRule, actual: Any) -> bool:
    spec = _PROPERTY_SPECS[rule.property]
    expected_values = rule.expected if rule.operator in {"in", "between"} else [rule.expected]
    if spec.kind == "string":
        actual = _font_identity(actual)
        expected_values = [_font_identity(value) for value in expected_values]
    if spec.kind == "line_spacing":
        matching_types = [value for value in expected_values if value["type"] == actual["type"]]
        if not matching_types:
            return False
        actual_value = actual["value"]
        expected_values = [value["value"] for value in matching_types]
    else:
        actual_value = actual
    if spec.kind in {"number", "line_spacing"}:
        tolerance = float(rule.tolerance)
        if rule.operator == "eq":
            return abs(float(actual_value) - float(expected_values[0])) <= tolerance
        if rule.operator == "in":
            return any(
                abs(float(actual_value) - float(value)) <= tolerance for value in expected_values
            )
        return (
            float(expected_values[0]) - tolerance
            <= float(actual_value)
            <= float(expected_values[1]) + tolerance
        )
    if rule.operator == "eq":
        return actual_value == expected_values[0]
    return actual_value in expected_values


def _line_unit(value: Any) -> str | None:
    if isinstance(value, Mapping):
        raw_type = value.get("type", value.get("kind"))
        try:
            line_type = _canonical_line_type(raw_type)
        except ValueError:
            return None
        return "multiple" if line_type == "MULTIPLE" else "pt"
    return None


def _evidence_unit(property_name: str, value: Any = None) -> str | None:
    spec = _PROPERTY_SPECS[property_name]
    if spec.kind == "line_spacing":
        return _line_unit(value)
    if isinstance(value, Mapping) and isinstance(value.get("unit"), str):
        return _normalize_unit(value["unit"])
    return spec.unit


__all__ = [
    "ValidatedFormatRule",
    "compute_ruleset_digest",
    "find_conflicts",
    "validate_rule",
]
