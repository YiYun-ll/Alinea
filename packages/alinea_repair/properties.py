from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

from alinea_contracts.errors import AlineaError
from alinea_contracts.models import FormatProperty
from pydantic import JsonValue

from alinea_repair._util import normalized_name


@dataclass(frozen=True)
class AttributeChange:
    element_path: str
    attribute: str
    value: str | None
    primary: bool

    @property
    def whitelist_path(self) -> str:
        return f"{self.element_path}/@{self.attribute}"


@dataclass(frozen=True)
class PropertyPatch:
    strategy: Literal[
        "DIRECT_RUN_PROPERTY",
        "DIRECT_PARAGRAPH_PROPERTY",
        "DIRECT_SECTION_PROPERTY",
    ]
    changes: tuple[AttributeChange, ...]

    @property
    def allowed_xml_changes(self) -> list[str]:
        return [change.whitelist_path for change in self.changes]


def _invalid(prop: str, message: str) -> AlineaError:
    return AlineaError(
        "INVALID_REPAIR_VALUE",
        f"Invalid value for {prop}: {message}",
        status_code=422,
        details={"property": prop},
    )


def _number(prop: str, value: JsonValue, *, minimum: float | None = 0) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise _invalid(prop, "expected a number")
    result = float(value)
    if not math.isfinite(result):
        raise _invalid(prop, "number must be finite")
    if minimum is not None and result < minimum:
        raise _invalid(prop, f"number must be at least {minimum}")
    return result


def _integer_ooxml(prop: str, value: float, scale: float) -> str:
    converted = value * scale
    if not math.isfinite(converted) or abs(converted) > 2_147_483_647:
        raise _invalid(prop, "value is outside the supported OOXML range")
    return str(round(converted))


def _xml_text(prop: str, value: JsonValue) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _invalid(prop, "expected a non-empty string")
    for character in value:
        codepoint = ord(character)
        if not (
            codepoint in (0x9, 0xA, 0xD)
            or 0x20 <= codepoint <= 0xD7FF
            or 0xE000 <= codepoint <= 0xFFFD
            or 0x10000 <= codepoint <= 0x10FFFF
        ):
            raise _invalid(prop, "string contains a character forbidden by XML 1.0")
    return value


def normalize_line_spacing(prop: str, value: JsonValue) -> dict[str, JsonValue]:
    if not isinstance(value, dict):
        raise _invalid(prop, "expected {'type': 'MULTIPLE|EXACT|AT_LEAST', 'value': ...}")
    if (
        set(value) - {"type", "kind", "value", "unit"}
        or ("type" in value) == ("kind" in value)
        or "value" not in value
    ):
        raise _invalid(prop, "only type (or kind), value and optional unit are accepted")
    spacing_type = value.get("type", value.get("kind"))
    if not isinstance(spacing_type, str):
        raise _invalid(prop, "line-spacing type must be a string")
    normalized_type = normalized_name(spacing_type).upper()
    if normalized_type not in {"MULTIPLE", "EXACT", "AT_LEAST"}:
        raise _invalid(prop, "line-spacing type must be MULTIPLE, EXACT or AT_LEAST")
    unit = value.get("unit")
    if normalized_type == "MULTIPLE":
        if unit is not None and normalized_name(str(unit)) not in {"line", "lines", "multiple"}:
            raise _invalid(prop, "MULTIPLE accepts only a line/multiple unit")
    elif unit is not None and normalized_name(str(unit)) != "pt":
        raise _invalid(prop, "EXACT and AT_LEAST accept only pt")
    number = _number(prop, value["value"], minimum=0)
    if number <= 0:
        raise _invalid(prop, "line-spacing value must be greater than zero")
    return {"type": normalized_type, "value": number}


def normalize_property_value(prop: FormatProperty, value: JsonValue) -> JsonValue:
    if value is None:
        return None
    if prop in {"font.eastAsia", "font.ascii"}:
        return _xml_text(prop, value)
    if prop == "font.bold":
        if not isinstance(value, bool):
            raise _invalid(prop, "expected a boolean")
        return value
    if prop == "paragraph.alignment":
        if not isinstance(value, str):
            raise _invalid(prop, "expected an alignment string")
        alignment = normalized_name(value).replace("_", "")
        aliases = {
            "left": "left",
            "center": "center",
            "centre": "center",
            "right": "right",
            "justify": "both",
            "both": "both",
        }
        if alignment not in aliases:
            raise _invalid(prop, "expected left, center, right or justify")
        return aliases[alignment]
    if prop == "paragraph.line_spacing":
        return normalize_line_spacing(prop, value)
    if prop in {
        "font.size_pt",
        "paragraph.first_line_indent_chars",
        "paragraph.first_line_indent_mm",
        "paragraph.space_before_pt",
        "paragraph.space_after_pt",
        "section.margin_top_mm",
        "section.margin_bottom_mm",
        "section.margin_left_mm",
        "section.margin_right_mm",
        "section.page_width_mm",
        "section.page_height_mm",
    }:
        number = _number(prop, value)
        if (
            prop in {"font.size_pt", "section.page_width_mm", "section.page_height_mm"}
            and number <= 0
        ):
            raise _invalid(prop, "value must be greater than zero")
        return number
    if prop in {"paragraph.left_indent_mm", "paragraph.right_indent_mm"}:
        return _number(prop, value, minimum=None)
    raise _invalid(prop, "property is not supported by the repair whitelist")


def values_equal(prop: FormatProperty, left: JsonValue, right: JsonValue) -> bool:
    if left is None or right is None:
        return left is None and right is None
    try:
        normalized_left = normalize_property_value(prop, left)
        normalized_right = normalize_property_value(prop, right)
    except AlineaError:
        return False
    if prop in {"font.eastAsia", "font.ascii"}:
        return str(normalized_left).casefold() == str(normalized_right).casefold()
    if isinstance(normalized_left, float) and isinstance(normalized_right, float):
        return math.isclose(normalized_left, normalized_right, rel_tol=1e-9, abs_tol=1e-9)
    if prop == "paragraph.line_spacing":
        assert isinstance(normalized_left, dict) and isinstance(normalized_right, dict)
        return normalized_left["type"] == normalized_right["type"] and math.isclose(
            float(normalized_left["value"]),
            float(normalized_right["value"]),
            rel_tol=1e-9,
            abs_tol=1e-9,
        )
    return normalized_left == normalized_right


def encode_property(prop: FormatProperty, desired_after: JsonValue) -> PropertyPatch:
    value = normalize_property_value(prop, desired_after)
    run_strategy = "DIRECT_RUN_PROPERTY"
    paragraph_strategy = "DIRECT_PARAGRAPH_PROPERTY"
    section_strategy = "DIRECT_SECTION_PROPERTY"

    def change(
        path: str, attribute: str, encoded: str | None, primary: bool = True
    ) -> AttributeChange:
        return AttributeChange(path, attribute, encoded, primary)

    if prop == "font.eastAsia":
        return PropertyPatch(
            run_strategy, (change("w:rPr/w:rFonts", "w:eastAsia", _xml_text(prop, value)),)
        )
    if prop == "font.ascii":
        font_name = _xml_text(prop, value)
        return PropertyPatch(
            run_strategy,
            (
                change("w:rPr/w:rFonts", "w:ascii", font_name),
                change("w:rPr/w:rFonts", "w:hAnsi", font_name),
            ),
        )
    if prop == "font.size_pt":
        points = float(value)
        half_points = points * 2
        if not math.isclose(half_points, round(half_points), rel_tol=0, abs_tol=1e-9):
            raise _invalid(prop, "font size must be representable in half points")
        encoded = str(round(half_points))
        return PropertyPatch(
            run_strategy,
            (
                change("w:rPr/w:sz", "w:val", encoded),
                change("w:rPr/w:szCs", "w:val", encoded),
            ),
        )
    if prop == "font.bold":
        encoded = "1" if value else "0"
        return PropertyPatch(
            run_strategy,
            (
                change("w:rPr/w:b", "w:val", encoded),
                change("w:rPr/w:bCs", "w:val", encoded),
            ),
        )
    if prop == "paragraph.alignment":
        return PropertyPatch(paragraph_strategy, (change("w:pPr/w:jc", "w:val", str(value)),))
    if prop == "paragraph.line_spacing":
        assert isinstance(value, dict)
        spacing_type = value["type"]
        number = float(value["value"])
        if spacing_type == "MULTIPLE":
            line = _integer_ooxml(prop, number, 240)
            rule = "auto"
        else:
            line = _integer_ooxml(prop, number, 20)
            rule = "exact" if spacing_type == "EXACT" else "atLeast"
        return PropertyPatch(
            paragraph_strategy,
            (
                change("w:pPr/w:spacing", "w:line", line),
                change("w:pPr/w:spacing", "w:lineRule", rule),
            ),
        )
    if prop in {"paragraph.first_line_indent_chars", "paragraph.first_line_indent_mm"}:
        if prop == "paragraph.first_line_indent_chars":
            primary_attribute = "w:firstLineChars"
            encoded = _integer_ooxml(prop, float(value), 100)
            removed = ("w:firstLine", "w:hanging", "w:hangingChars")
        else:
            primary_attribute = "w:firstLine"
            encoded = _integer_ooxml(prop, float(value), 1440 / 25.4)
            removed = ("w:firstLineChars", "w:hanging", "w:hangingChars")
        changes = [change("w:pPr/w:ind", primary_attribute, encoded)]
        changes.extend(change("w:pPr/w:ind", attribute, None, False) for attribute in removed)
        return PropertyPatch(paragraph_strategy, tuple(changes))
    if prop in {"paragraph.left_indent_mm", "paragraph.right_indent_mm"}:
        attribute = "w:left" if prop == "paragraph.left_indent_mm" else "w:right"
        return PropertyPatch(
            paragraph_strategy,
            (change("w:pPr/w:ind", attribute, _integer_ooxml(prop, float(value), 1440 / 25.4)),),
        )
    if prop in {"paragraph.space_before_pt", "paragraph.space_after_pt"}:
        attribute = "w:before" if prop == "paragraph.space_before_pt" else "w:after"
        return PropertyPatch(
            paragraph_strategy,
            (change("w:pPr/w:spacing", attribute, _integer_ooxml(prop, float(value), 20)),),
        )

    section_attributes = {
        "section.margin_top_mm": ("w:pgMar", "w:top"),
        "section.margin_bottom_mm": ("w:pgMar", "w:bottom"),
        "section.margin_left_mm": ("w:pgMar", "w:left"),
        "section.margin_right_mm": ("w:pgMar", "w:right"),
        "section.page_width_mm": ("w:pgSz", "w:w"),
        "section.page_height_mm": ("w:pgSz", "w:h"),
    }
    if prop in section_attributes:
        path, attribute = section_attributes[prop]
        return PropertyPatch(
            section_strategy,
            (change(path, attribute, _integer_ooxml(prop, float(value), 1440 / 25.4)),),
        )
    raise _invalid(prop, "property is not supported by the repair whitelist")
