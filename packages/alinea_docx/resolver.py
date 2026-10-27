from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Literal

from alinea_contracts.models import ResolvedProperty, StyleNode
from lxml import etree
from pydantic import JsonValue

from .font_availability import font_key, installed_font_families, normalize_font_families
from .ooxml import (
    A_NS,
    OoxmlPackage,
    local_name,
    w_attr,
    w_children,
    w_descendants,
    w_first,
    xml_path,
)

RUN_PROPERTIES = ("font.eastAsia", "font.ascii", "font.size_pt", "font.bold")
PARAGRAPH_PROPERTIES = (
    "paragraph.alignment",
    "paragraph.first_line_indent_chars",
    "paragraph.first_line_indent_mm",
    "paragraph.left_indent_mm",
    "paragraph.right_indent_mm",
    "paragraph.line_spacing",
    "paragraph.space_before_pt",
    "paragraph.space_after_pt",
)
SECTION_PROPERTIES = (
    "section.margin_top_mm",
    "section.margin_bottom_mm",
    "section.margin_left_mm",
    "section.margin_right_mm",
    "section.page_width_mm",
    "section.page_height_mm",
)

type Origin = Literal[
    "DIRECT",
    "CHARACTER_STYLE",
    "PARAGRAPH_STYLE",
    "BASED_ON",
    "DOC_DEFAULT",
    "THEME",
    "NUMBERING",
    "UNKNOWN",
]


@dataclass(frozen=True, slots=True)
class _RawValue:
    value: JsonValue
    raw: str
    error: str | None = None
    origin: Origin | None = None
    origin_ref: str | None = None


@dataclass(frozen=True, slots=True)
class _Layer:
    properties: etree._Element
    origin: Origin
    origin_ref: str


@dataclass(slots=True)
class _Layers:
    items: list[_Layer] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class _Candidate:
    value: JsonValue
    raw: str
    origin: Origin
    origin_ref: str
    layer_origin: Origin
    error: str | None = None

    def evidence(self) -> dict[str, JsonValue]:
        return {
            "layer": self.layer_origin,
            "origin_ref": self.origin_ref,
            "value": self.value,
            "raw_ooxml_value": self.raw,
            **({"reason": self.error} if self.error else {}),
        }


@dataclass(frozen=True, slots=True)
class _StyleDefinition:
    node: StyleNode
    element: etree._Element
    p_pr: etree._Element | None
    r_pr: etree._Element | None


class EffectiveStyleResolver:
    def __init__(
        self, package: OoxmlPackage, *, available_fonts: Iterable[str] | None = None
    ) -> None:
        self.package = package
        self._available_fonts = (
            normalize_font_families(available_fonts)
            if available_fonts is not None
            else installed_font_families()
        )
        self.styles_part_uri: str | None = None
        self._styles: dict[str, _StyleDefinition] = {}
        self._doc_default_p_pr: etree._Element | None = None
        self._doc_default_r_pr: etree._Element | None = None
        self._default_paragraph_style: str | None = None
        self._default_character_style: str | None = None
        self._default_table_style: str | None = None
        self._chain_cache: dict[str, tuple[list[str], str | None]] = {}
        self._load_styles()
        self._load_theme()

    @property
    def styles(self) -> dict[str, StyleNode]:
        return {style_id: definition.node for style_id, definition in self._styles.items()}

    def paragraph_style_id(self, paragraph: etree._Element) -> str | None:
        return self.explicit_paragraph_style_id(paragraph) or self._default_paragraph_style

    def explicit_paragraph_style_id(self, paragraph: etree._Element) -> str | None:
        p_pr = w_first(paragraph, "pPr")
        p_style = w_first(p_pr, "pStyle") if p_pr is not None else None
        return w_attr(p_style, "val") if p_style is not None else None

    def character_style_id(self, run: etree._Element) -> str | None:
        r_pr = w_first(run, "rPr")
        r_style = w_first(r_pr, "rStyle") if r_pr is not None else None
        return w_attr(r_style, "val") if r_style is not None else None

    def get_style_chain(self, style_id: str) -> list[str]:
        return list(self._style_chain(style_id)[0])

    def paragraph_outline_level(self, paragraph: etree._Element) -> int | None:
        p_pr = w_first(paragraph, "pPr")
        outline = w_first(p_pr, "outlineLvl") if p_pr is not None else None
        if outline is not None:
            return _parse_nonnegative_int(w_attr(outline, "val"))
        style_id = self.paragraph_style_id(paragraph)
        if not style_id:
            return None
        chain, _ = self._style_chain(style_id)
        for inherited_id in reversed(chain):
            definition = self._styles[inherited_id]
            outline = (
                w_first(definition.p_pr, "outlineLvl")
                if definition.p_pr is not None
                else None
            )
            if outline is not None:
                return _parse_nonnegative_int(w_attr(outline, "val"))
        return None

    def resolve_paragraph(
        self, paragraph: etree._Element, *, inside_table: bool = False
    ) -> dict[str, ResolvedProperty]:
        result = {
            property_name: self._resolve_paragraph_property(
                property_name, paragraph, inside_table=inside_table
            )
            for property_name in PARAGRAPH_PROPERTIES
        }
        for property_name in RUN_PROPERTIES:
            result[property_name] = self._resolve_run_property(
                property_name,
                None,
                paragraph,
                inside_table=inside_table,
            )
        return result

    def resolve_run(
        self,
        run: etree._Element,
        paragraph: etree._Element,
        *,
        inside_table: bool = False,
    ) -> dict[str, ResolvedProperty]:
        return {
            property_name: self._resolve_run_property(
                property_name, run, paragraph, inside_table=inside_table
            )
            for property_name in RUN_PROPERTIES
        }

    def resolve_section(self, section: etree._Element) -> dict[str, ResolvedProperty]:
        return {
            property_name: self._resolve_section_property(property_name, section)
            for property_name in SECTION_PROPERTIES
        }

    def resolve_property(
        self,
        property_name: str,
        element: etree._Element,
        *,
        paragraph: etree._Element | None = None,
        inside_table: bool = False,
    ) -> ResolvedProperty:
        if property_name in SECTION_PROPERTIES:
            return self._resolve_section_property(property_name, element)
        if property_name in PARAGRAPH_PROPERTIES:
            return self._resolve_paragraph_property(
                property_name, element, inside_table=inside_table
            )
        if property_name in RUN_PROPERTIES:
            owner = paragraph
            if owner is None:
                from .ooxml import nearest_paragraph

                owner = nearest_paragraph(element)
            if owner is None:
                raise ValueError("paragraph is required when resolving a run outside a paragraph")
            return self._resolve_run_property(
                property_name, element, owner, inside_table=inside_table
            )
        raise ValueError(f"Unsupported format property: {property_name}")

    def _resolve_run_property(
        self,
        property_name: str,
        run: etree._Element | None,
        paragraph: etree._Element,
        *,
        inside_table: bool,
    ) -> ResolvedProperty:
        layers = self._run_layers(run, paragraph)
        complex_cascade = self._has_unsupported_lower_cascade(
            paragraph, property_name, inside_table=inside_table
        )
        return self._resolve_layers(
            property_name,
            layers,
            self._extract_run_value,
            complex_cascade=complex_cascade,
            toggle_property=property_name == "font.bold",
        )

    def _resolve_paragraph_property(
        self, property_name: str, paragraph: etree._Element, *, inside_table: bool
    ) -> ResolvedProperty:
        layers = self._paragraph_layers(paragraph)
        complex_cascade = self._has_unsupported_lower_cascade(
            paragraph, property_name, inside_table=inside_table
        )
        return self._resolve_layers(
            property_name,
            layers,
            self._extract_paragraph_value,
            complex_cascade=complex_cascade,
        )

    def _resolve_layers(
        self,
        property_name: str,
        layers: _Layers,
        extractor: object,
        *,
        complex_cascade: bool,
        toggle_property: bool = False,
    ) -> ResolvedProperty:
        candidates: list[_Candidate] = []
        for layer in layers.items:
            raw = extractor(layer.properties, property_name)
            if raw is None:
                continue
            candidates.append(
                _Candidate(
                    value=raw.value,
                    raw=raw.raw,
                    origin=raw.origin or layer.origin,
                    origin_ref=raw.origin_ref or layer.origin_ref,
                    layer_origin=layer.origin,
                    error=raw.error,
                )
            )
        provenance = [candidate.evidence() for candidate in candidates]
        if not candidates:
            reason = (
                "; ".join(dict.fromkeys(layers.problems))
                if layers.problems
                else "property is not set in any supported cascade layer"
            )
            if complex_cascade:
                reason = "table or numbering formatting may affect this property; " + reason
            return _unresolved(property_name, reason, provenance)

        winner = candidates[-1]
        if winner.error:
            return _unresolved(
                property_name,
                winner.error,
                provenance,
                origin=winner.origin,
                origin_ref=winner.origin_ref,
                raw=winner.raw,
            )
        if complex_cascade and winner.layer_origin in {"DOC_DEFAULT", "UNKNOWN"}:
            return _unresolved(
                property_name,
                "table or numbering formatting may override the document default",
                provenance,
                origin=winner.origin,
                origin_ref=winner.origin_ref,
                raw=winner.raw,
            )
        if layers.problems and winner.layer_origin == "DOC_DEFAULT":
            return _unresolved(
                property_name,
                "; ".join(dict.fromkeys(layers.problems)),
                provenance,
                origin=winner.origin,
                origin_ref=winner.origin_ref,
                raw=winner.raw,
            )
        has_style_cycle = any("cycle" in problem for problem in layers.problems)
        if has_style_cycle and winner.layer_origin != "DIRECT":
            return _unresolved(
                property_name,
                "style basedOn cycle makes the inherited value indeterminate",
                provenance,
                origin=winner.origin,
                origin_ref=winner.origin_ref,
                raw=winner.raw,
            )
        if toggle_property and winner.layer_origin != "DIRECT":
            style_toggles = [
                candidate
                for candidate in candidates
                if candidate.layer_origin not in {"DOC_DEFAULT", "DIRECT"}
                and candidate.value is True
            ]
            if len(style_toggles) > 1:
                return _unresolved(
                    property_name,
                    "multiple bold toggle layers cannot be resolved by simple property override",
                    provenance,
                    origin=winner.origin,
                    origin_ref=winner.origin_ref,
                    raw=winner.raw,
                )
        return ResolvedProperty(
            property=property_name,
            value=winner.value,
            status="RESOLVED",
            origin=winner.origin,
            origin_ref=winner.origin_ref,
            raw_ooxml_value=winner.raw,
            provenance=provenance,
        )

    def _paragraph_layers(self, paragraph: etree._Element) -> _Layers:
        layers = _Layers()
        if self._doc_default_p_pr is not None:
            layers.items.append(
                _Layer(self._doc_default_p_pr, "DOC_DEFAULT", self._doc_default_ref("pPrDefault"))
            )
        style_id = self.paragraph_style_id(paragraph)
        if style_id:
            self._append_style_layers(layers, style_id, "pPr", "PARAGRAPH_STYLE")
        p_pr = w_first(paragraph, "pPr")
        if p_pr is not None:
            layers.items.append(_Layer(p_pr, "DIRECT", xml_path(p_pr)))
        return layers

    def _run_layers(
        self, run: etree._Element | None, paragraph: etree._Element
    ) -> _Layers:
        layers = _Layers()
        if self._doc_default_r_pr is not None:
            layers.items.append(
                _Layer(self._doc_default_r_pr, "DOC_DEFAULT", self._doc_default_ref("rPrDefault"))
            )
        paragraph_style = self.paragraph_style_id(paragraph)
        if paragraph_style:
            self._append_style_layers(layers, paragraph_style, "rPr", "PARAGRAPH_STYLE")
        if run is not None:
            character_style = self.character_style_id(run)
            if character_style:
                self._append_style_layers(layers, character_style, "rPr", "CHARACTER_STYLE")
            r_pr = w_first(run, "rPr")
            if r_pr is not None:
                layers.items.append(_Layer(r_pr, "DIRECT", xml_path(r_pr)))
        return layers

    def _append_style_layers(
        self,
        layers: _Layers,
        style_id: str,
        property_container: str,
        leaf_origin: Origin,
    ) -> None:
        chain, problem = self._style_chain(style_id)
        if problem:
            layers.problems.append(problem)
        for index, inherited_id in enumerate(chain):
            definition = self._styles[inherited_id]
            properties = definition.p_pr if property_container == "pPr" else definition.r_pr
            if properties is None:
                continue
            origin = leaf_origin if index == len(chain) - 1 else "BASED_ON"
            origin_ref = f"{self.styles_part_uri}#{inherited_id}"
            layers.items.append(_Layer(properties, origin, origin_ref))

    def _style_chain(self, style_id: str) -> tuple[list[str], str | None]:
        if style_id in self._chain_cache:
            return self._chain_cache[style_id]
        if style_id not in self._styles:
            result = ([], f"style {style_id!r} is referenced but not defined")
            self._chain_cache[style_id] = result
            return result

        leaf_to_root: list[str] = []
        seen: set[str] = set()
        current: str | None = style_id
        problem: str | None = None
        while current:
            if current in seen:
                problem = f"style basedOn cycle detected at {current!r}"
                break
            seen.add(current)
            definition = self._styles.get(current)
            if definition is None:
                problem = f"basedOn style {current!r} is not defined"
                break
            leaf_to_root.append(current)
            current = definition.node.based_on
        result = (list(reversed(leaf_to_root)), problem)
        self._chain_cache[style_id] = result
        return result

    def _extract_run_value(
        self, properties: etree._Element, property_name: str
    ) -> _RawValue | None:
        if property_name in {"font.eastAsia", "font.ascii"}:
            fonts = w_first(properties, "rFonts")
            if fonts is None:
                return None
            script = "eastAsia" if property_name == "font.eastAsia" else "ascii"
            theme = w_attr(fonts, f"{script}Theme")
            if theme is not None:
                return self._resolve_theme_font(theme)
            value = w_attr(fonts, script)
            if value is None:
                return None
            if not value.strip():
                return _RawValue(None, value, error=f"{script} font name is empty")
            return _RawValue(value, value)
        if property_name == "font.size_pt":
            size = w_first(properties, "sz")
            if size is None:
                return None
            raw = w_attr(size, "val")
            number = _parse_finite_number(raw)
            if number is None or number <= 0:
                return _RawValue(None, raw or "", error="w:sz must be a positive half-point value")
            return _RawValue(half_points_to_pt(number), raw or "")
        if property_name == "font.bold":
            bold = w_first(properties, "b")
            if bold is None:
                return None
            raw = w_attr(bold, "val")
            value = True if raw is None else _parse_on_off(raw)
            if value is None:
                return _RawValue(None, raw or "", error="w:b has an unknown on/off value")
            return _RawValue(value, raw if raw is not None else "on")
        return None

    def _extract_paragraph_value(
        self, properties: etree._Element, property_name: str
    ) -> _RawValue | None:
        if property_name == "paragraph.alignment":
            alignment = w_first(properties, "jc")
            if alignment is None:
                return None
            raw = w_attr(alignment, "val") or ""
            values = {
                "left": "left",
                "center": "center",
                "right": "right",
                "both": "justify",
                "distribute": "distribute",
            }
            if raw in values:
                return _RawValue(values[raw], raw)
            if raw in {"start", "end"}:
                return _RawValue(None, raw, error="start/end alignment depends on bidi context")
            return _RawValue(None, raw, error=f"unsupported paragraph alignment: {raw}")

        if property_name in {
            "paragraph.first_line_indent_chars",
            "paragraph.first_line_indent_mm",
            "paragraph.left_indent_mm",
            "paragraph.right_indent_mm",
        }:
            indentation = w_first(properties, "ind")
            if indentation is None:
                return None
            return self._extract_indentation(indentation, property_name)

        if property_name in {
            "paragraph.line_spacing",
            "paragraph.space_before_pt",
            "paragraph.space_after_pt",
        }:
            spacing = w_first(properties, "spacing")
            if spacing is None:
                return None
            return self._extract_spacing(spacing, property_name)
        return None

    def _extract_indentation(
        self, indentation: etree._Element, property_name: str
    ) -> _RawValue | None:
        if property_name == "paragraph.first_line_indent_chars":
            first = w_attr(indentation, "firstLineChars")
            hanging = w_attr(indentation, "hangingChars")
            raw = first if first is not None else hanging
            if raw is None:
                return None
            number = _parse_finite_number(raw)
            if number is None or number < 0:
                return _RawValue(None, raw, error="character indentation must be nonnegative")
            value = hundredths_to_chars(number)
            return _RawValue(-value if first is None else value, raw)
        if property_name == "paragraph.first_line_indent_mm":
            first = w_attr(indentation, "firstLine")
            hanging = w_attr(indentation, "hanging")
            raw = first if first is not None else hanging
            if raw is None:
                if w_attr(indentation, "firstLineChars") is not None:
                    return _RawValue(
                        None,
                        w_attr(indentation, "firstLineChars") or "",
                        error="character-based indentation cannot be converted to millimetres",
                    )
                return None
            number = _parse_finite_number(raw)
            if number is None or number < 0:
                return _RawValue(None, raw, error="twip indentation must be nonnegative")
            value = twips_to_mm(number)
            return _RawValue(-value if first is None else value, raw)
        if property_name in {"paragraph.left_indent_mm", "paragraph.right_indent_mm"}:
            side = "left" if property_name == "paragraph.left_indent_mm" else "right"
            raw = w_attr(indentation, side)
            if raw is None:
                char_raw = w_attr(indentation, f"{side}Chars")
                if char_raw is not None:
                    return _RawValue(
                        None,
                        char_raw,
                        error="character-based side indentation cannot be converted to millimetres",
                    )
                start = w_attr(indentation, "start")
                end = w_attr(indentation, "end")
                if start is not None or end is not None:
                    return _RawValue(
                        None,
                        start or end or "",
                        error="start/end indentation depends on paragraph bidi context",
                    )
                return None
            number = _parse_finite_number(raw)
            if number is None:
                return _RawValue(None, raw, error=f"{side} indentation is not numeric")
            return _RawValue(twips_to_mm(number), raw)
        return None

    def _extract_spacing(
        self, spacing: etree._Element, property_name: str
    ) -> _RawValue | None:
        if property_name == "paragraph.line_spacing":
            raw_line = w_attr(spacing, "line")
            raw_rule = w_attr(spacing, "lineRule")
            if raw_line is None:
                if raw_rule is not None:
                    return _RawValue(None, raw_rule, error="lineRule is set without w:line")
                return None
            line = _parse_finite_number(raw_line)
            if line is None or line <= 0:
                return _RawValue(None, raw_line, error="w:line must be a positive number")
            rule = raw_rule or "auto"
            raw = f"line={raw_line};lineRule={rule}"
            if rule == "auto":
                return _RawValue({"kind": "MULTIPLE", "value": line / 240.0}, raw)
            if rule == "exact":
                return _RawValue(
                    {"kind": "EXACT", "value": twips_to_pt(line), "unit": "pt"}, raw
                )
            if rule == "atLeast":
                return _RawValue(
                    {"kind": "AT_LEAST", "value": twips_to_pt(line), "unit": "pt"}, raw
                )
            return _RawValue(None, raw, error=f"unsupported lineRule: {rule}")

        side = "before" if property_name == "paragraph.space_before_pt" else "after"
        auto = _parse_on_off(w_attr(spacing, f"{side}Autospacing"))
        if auto:
            raw = w_attr(spacing, f"{side}Autospacing") or "on"
            return _RawValue(None, raw, error=f"automatic {side} spacing has no fixed point value")
        lines = w_attr(spacing, f"{side}Lines")
        if lines is not None:
            return _RawValue(
                None,
                lines,
                error=f"{side}Lines cannot be converted to points without line metrics",
            )
        raw = w_attr(spacing, side)
        if raw is None:
            return None
        value = _parse_finite_number(raw)
        if value is None:
            return _RawValue(None, raw, error=f"{side} spacing is not numeric")
        return _RawValue(twips_to_pt(value), raw)

    def _resolve_section_property(
        self, property_name: str, section: etree._Element
    ) -> ResolvedProperty:
        is_margin = property_name.startswith("section.margin_")
        container_name = "pgMar" if is_margin else "pgSz"
        container = w_first(section, container_name)
        attribute_by_property = {
            "section.margin_top_mm": "top",
            "section.margin_bottom_mm": "bottom",
            "section.margin_left_mm": "left",
            "section.margin_right_mm": "right",
            "section.page_width_mm": "w",
            "section.page_height_mm": "h",
        }
        attribute = attribute_by_property[property_name]
        if container is None:
            return _unresolved(property_name, f"w:{container_name} is not set")
        raw = w_attr(container, attribute)
        if raw is None:
            return _unresolved(
                property_name,
                f"w:{container_name}/@w:{attribute} is not set",
                origin_ref=xml_path(container),
            )
        value = _parse_finite_number(raw)
        if value is None or (not is_margin and value <= 0):
            return _unresolved(
                property_name,
                "section page dimension or margin is not a valid twip value",
                origin="DIRECT",
                origin_ref=xml_path(container),
                raw=raw,
            )
        resolved = twips_to_mm(value)
        origin_ref = f"{xml_path(container)}/@w:{attribute}"
        return ResolvedProperty(
            property=property_name,
            value=resolved,
            status="RESOLVED",
            origin="DIRECT",
            origin_ref=origin_ref,
            raw_ooxml_value=raw,
            provenance=[
                {
                    "layer": "DIRECT",
                    "origin_ref": origin_ref,
                    "value": resolved,
                    "raw_ooxml_value": raw,
                }
            ],
        )

    def _resolve_theme_font(self, theme_name: str) -> _RawValue:
        theme_root = getattr(self, "_theme_root", None)
        if theme_root is None:
            return _RawValue(
                None,
                theme_name,
                error=f"theme font {theme_name!r} cannot be resolved without a readable theme part",
                origin="THEME",
            )
        normalized = theme_name.casefold()
        group = "majorFont" if normalized.startswith("major") else "minorFont"
        if normalized.endswith(("eastasia",)):
            font_kind = "ea"
        elif normalized.endswith(("cs", "bidi")):
            font_kind = "cs"
        elif normalized.endswith(("ascii", "hansi")):
            font_kind = "latin"
        else:
            return _RawValue(
                None,
                theme_name,
                error=f"unknown theme font token: {theme_name}",
                origin="THEME",
            )
        if not normalized.startswith(("major", "minor")):
            return _RawValue(
                None,
                theme_name,
                error=f"unknown theme font token: {theme_name}",
                origin="THEME",
            )
        font_scheme = next(
            (
                element
                for element in theme_root.iter()
                if isinstance(element.tag, str)
                and etree.QName(element).namespace == A_NS
                and local_name(element) == "fontScheme"
            ),
            None,
        )
        group_element = None
        if font_scheme is not None:
            group_element = next(
                (
                    child
                    for child in font_scheme
                    if isinstance(child.tag, str)
                    and etree.QName(child).namespace == A_NS
                    and local_name(child) == group
                ),
                None,
            )
        font_element = None
        if group_element is not None:
            font_element = next(
                (
                    child
                    for child in group_element
                    if isinstance(child.tag, str)
                    and etree.QName(child).namespace == A_NS
                    and local_name(child) == font_kind
                ),
                None,
            )
        typeface = font_element.get("typeface", "") if font_element is not None else ""
        origin_ref = f"{self._theme_part_uri}#fontScheme/{group}/{font_kind}"
        if not typeface.strip():
            return _RawValue(
                None,
                theme_name,
                error=(
                    f"theme font {theme_name!r} has no explicit {font_kind} typeface; "
                    "script-dependent fallback is unresolved"
                ),
                origin="THEME",
                origin_ref=origin_ref,
            )
        if font_key(typeface) not in self._available_fonts:
            return _RawValue(
                None,
                theme_name,
                error=f"RENDER_FONT_MISSING: theme typeface {typeface!r} is unavailable",
                origin="THEME",
                origin_ref=origin_ref,
            )
        return _RawValue(
            typeface,
            theme_name,
            origin="THEME",
            origin_ref=origin_ref,
        )

    def _has_unsupported_lower_cascade(
        self, paragraph: etree._Element, property_name: str, *, inside_table: bool
    ) -> bool:
        p_pr = w_first(paragraph, "pPr")
        if p_pr is not None and w_first(p_pr, "numPr") is not None:
            return True
        style_id = self.paragraph_style_id(paragraph)
        if style_id:
            chain, _ = self._style_chain(style_id)
            for inherited_id in chain:
                definition = self._styles[inherited_id]
                if definition.p_pr is not None and w_first(definition.p_pr, "numPr") is not None:
                    return True
        if not inside_table:
            return False

        table_style_id: str | None = None
        current = paragraph.getparent()
        while current is not None:
            if local_name(current) == "tbl":
                tbl_pr = w_first(current, "tblPr")
                tbl_style = w_first(tbl_pr, "tblStyle") if tbl_pr is not None else None
                table_style_id = w_attr(tbl_style, "val") if tbl_style is not None else None
                break
            current = current.getparent()
        table_style_id = table_style_id or self._default_table_style
        if not table_style_id or table_style_id not in self._styles:
            return False
        definition = self._styles[table_style_id]
        containers = (
            w_descendants(definition.element, "rPr")
            if property_name.startswith("font.")
            else w_descendants(definition.element, "pPr")
        )
        extractor = (
            self._extract_run_value
            if property_name.startswith("font.")
            else self._extract_paragraph_value
        )
        return any(extractor(container, property_name) is not None for container in containers)

    def _load_styles(self) -> None:
        related = self.package.related_xml(self.package.main_part_uri, "styles")
        if related is None and self.package.has_part("/word/styles.xml"):
            related = (
                "/word/styles.xml",
                self.package.get_xml("/word/styles.xml", required=True),
            )
        if related is None:
            return
        self.styles_part_uri, root = related
        assert root is not None
        defaults = w_first(root, "docDefaults")
        if defaults is not None:
            r_default = w_first(defaults, "rPrDefault")
            p_default = w_first(defaults, "pPrDefault")
            self._doc_default_r_pr = w_first(r_default, "rPr") if r_default is not None else None
            self._doc_default_p_pr = w_first(p_default, "pPr") if p_default is not None else None

        for element in w_children(root, "style"):
            style_id = w_attr(element, "styleId")
            if not style_id:
                continue
            style_type = w_attr(element, "type") or "unknown"
            if style_type not in {"paragraph", "character", "table", "numbering"}:
                style_type = "unknown"
            name = w_first(element, "name")
            based_on = w_first(element, "basedOn")
            node = StyleNode(
                style_id=style_id,
                style_type=style_type,
                name=w_attr(name, "val") if name is not None else None,
                based_on=w_attr(based_on, "val") if based_on is not None else None,
                default=_parse_on_off(w_attr(element, "default")) or False,
            )
            definition = _StyleDefinition(
                node=node,
                element=element,
                p_pr=w_first(element, "pPr"),
                r_pr=w_first(element, "rPr"),
            )
            self._styles[style_id] = definition
            if node.default:
                if style_type == "paragraph":
                    self._default_paragraph_style = style_id
                elif style_type == "character":
                    self._default_character_style = style_id
                elif style_type == "table":
                    self._default_table_style = style_id

    def _load_theme(self) -> None:
        self._theme_part_uri: str | None = None
        self._theme_root: etree._Element | None = None
        related = self.package.related_xml(self.package.main_part_uri, "theme")
        if related is None:
            return
        self._theme_part_uri, self._theme_root = related

    def _doc_default_ref(self, kind: str) -> str:
        return f"{self.styles_part_uri or '/word/styles.xml'}#docDefaults/{kind}"


def half_points_to_pt(value: float) -> float:
    return value / 2.0


def twips_to_pt(value: float) -> float:
    return value / 20.0


def twips_to_mm(value: float) -> float:
    return value * 25.4 / 1440.0


def hundredths_to_chars(value: float) -> float:
    return value / 100.0


def _parse_finite_number(raw: str | None) -> float | None:
    if raw is None:
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def _parse_nonnegative_int(raw: str | None) -> int | None:
    if raw is None:
        return None
    try:
        value = int(raw)
    except ValueError:
        return None
    return value if value >= 0 else None


def _parse_on_off(raw: str | None) -> bool | None:
    if raw is None:
        return None
    normalized = raw.strip().casefold()
    if normalized in {"1", "true", "on"}:
        return True
    if normalized in {"0", "false", "off"}:
        return False
    return None


def _unresolved(
    property_name: str,
    reason: str,
    provenance: list[dict[str, JsonValue]] | None = None,
    *,
    origin: Origin = "UNKNOWN",
    origin_ref: str | None = None,
    raw: str | None = None,
) -> ResolvedProperty:
    return ResolvedProperty(
        property=property_name,
        value=None,
        status="UNRESOLVED",
        origin=origin,
        origin_ref=origin_ref,
        raw_ooxml_value=raw,
        provenance=provenance or [],
        reason=reason,
    )
