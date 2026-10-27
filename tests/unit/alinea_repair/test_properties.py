from __future__ import annotations

from pathlib import Path

import pytest
from alinea_repair import apply_approved_patch
from alinea_repair.ooxml import W_NS, locate_snapshot_element, parse_xml
from lxml import etree

from tests.unit.alinea_repair.helpers import Spec, build_case, mutate_xml, read_parts


def _child(parent: etree._Element, path: str) -> etree._Element:
    current = parent
    for local in path.split("/"):
        current = current.find(f"{{{W_NS}}}{local}")
        assert current is not None, path
    return current


def _first_line_conflicts(path: Path) -> None:
    def mutate(root: etree._Element) -> None:
        paragraph = root.find(f".//{{{W_NS}}}p")
        assert paragraph is not None
        ppr = etree.Element(f"{{{W_NS}}}pPr")
        indent = etree.SubElement(ppr, f"{{{W_NS}}}ind")
        for name, value in (
            ("firstLine", "111"),
            ("firstLineChars", "100"),
            ("hanging", "22"),
            ("hangingChars", "33"),
            ("left", "99"),
        ):
            indent.set(f"{{{W_NS}}}{name}", value)
        paragraph.insert(0, ppr)

    mutate_xml(path, "word/document.xml", mutate)


def _font_conflicts(path: Path) -> None:
    def mutate(root: etree._Element) -> None:
        run = root.find(f".//{{{W_NS}}}p/{{{W_NS}}}r")
        assert run is not None
        rpr = etree.Element(f"{{{W_NS}}}rPr")
        fonts = etree.SubElement(rpr, f"{{{W_NS}}}rFonts")
        fonts.set(f"{{{W_NS}}}ascii", "Keep-Ascii")
        fonts.set(f"{{{W_NS}}}hAnsi", "Keep-HAnsi")
        fonts.set(f"{{{W_NS}}}eastAsia", "Keep-EastAsia")
        run.insert(0, rpr)

    mutate_xml(path, "word/document.xml", mutate)


@pytest.mark.parametrize(
    ("spec", "relative_path", "attribute", "expected", "mutator"),
    [
        (
            Spec("font", "font.eastAsia", "宋体", "SimSun"),
            "w:rPr/w:rFonts",
            "eastAsia",
            "SimSun",
            _font_conflicts,
        ),
        (
            Spec("font", "font.ascii", "Times New Roman", "Arial"),
            "w:rPr/w:rFonts",
            "ascii",
            "Arial",
            _font_conflicts,
        ),
        (Spec("size", "font.size_pt", 10, 12.5), "w:rPr/w:sz", "val", "25", None),
        (Spec("bold", "font.bold", True, False), "w:rPr/w:b", "val", "0", None),
        (
            Spec("align", "paragraph.alignment", "left", "JUSTIFY", "p0"),
            "w:pPr/w:jc",
            "val",
            "both",
            None,
        ),
        (
            Spec(
                "line",
                "paragraph.line_spacing",
                {"type": "MULTIPLE", "value": 1},
                {"type": "MULTIPLE", "value": 1.5},
                "p0",
            ),
            "w:pPr/w:spacing",
            "line",
            "360",
            None,
        ),
        (
            Spec(
                "line",
                "paragraph.line_spacing",
                {"type": "EXACT", "value": 12},
                {"type": "EXACT", "value": 18},
                "p0",
            ),
            "w:pPr/w:spacing",
            "line",
            "360",
            None,
        ),
        (
            Spec(
                "line",
                "paragraph.line_spacing",
                {"type": "AT_LEAST", "value": 12},
                {"type": "AT-LEAST", "value": 16},
                "p0",
            ),
            "w:pPr/w:spacing",
            "lineRule",
            "atLeast",
            None,
        ),
        (
            Spec("indent", "paragraph.first_line_indent_chars", 1, 2, "p0"),
            "w:pPr/w:ind",
            "firstLineChars",
            "200",
            _first_line_conflicts,
        ),
        (
            Spec("indent", "paragraph.first_line_indent_mm", 5, 12.7, "p0"),
            "w:pPr/w:ind",
            "firstLine",
            "720",
            _first_line_conflicts,
        ),
        (
            Spec("left", "paragraph.left_indent_mm", 0, 25.4, "p0"),
            "w:pPr/w:ind",
            "left",
            "1440",
            None,
        ),
        (
            Spec("right", "paragraph.right_indent_mm", 0, 12.7, "p0"),
            "w:pPr/w:ind",
            "right",
            "720",
            None,
        ),
        (
            Spec("before", "paragraph.space_before_pt", 0, 12, "p0"),
            "w:pPr/w:spacing",
            "before",
            "240",
            None,
        ),
        (
            Spec("after", "paragraph.space_after_pt", 0, 6, "p0"),
            "w:pPr/w:spacing",
            "after",
            "120",
            None,
        ),
        (Spec("top", "section.margin_top_mm", 20, 25.4, "section"), "w:pgMar", "top", "1440", None),
        (
            Spec("bottom", "section.margin_bottom_mm", 20, 12.7, "section"),
            "w:pgMar",
            "bottom",
            "720",
            None,
        ),
        (
            Spec("left", "section.margin_left_mm", 20, 20, "section"),
            "w:pgMar",
            "left",
            "1134",
            None,
        ),
        (
            Spec("right", "section.margin_right_mm", 20, 20, "section"),
            "w:pgMar",
            "right",
            "1134",
            None,
        ),
        (Spec("width", "section.page_width_mm", 200, 210, "section"), "w:pgSz", "w", "11906", None),
        (
            Spec("height", "section.page_height_mm", 280, 297, "section"),
            "w:pgSz",
            "h",
            "16838",
            None,
        ),
    ],
)
def test_property_registry_end_to_end(
    tmp_path: Path,
    spec: Spec,
    relative_path: str,
    attribute: str,
    expected: str,
    mutator,
) -> None:
    case = build_case(tmp_path / "base.docx", [spec], mutator=mutator)
    candidate = tmp_path / "candidate.docx"
    result = apply_approved_patch(case.base_path, candidate, case.snapshot, case.plan())
    assert result.publishable, (spec, result.model_dump())
    root = parse_xml(read_parts(candidate)["word/document.xml"]).getroot()
    target = locate_snapshot_element(root, case.issues[0].element_ref)
    if spec.target == "section":
        base = target
    elif ":r" in spec.target:
        base = list(target.iter(f"{{{W_NS}}}r"))[0]
    else:
        base = target
    relative = relative_path.replace("w:", "")
    element = _child(base, relative)
    assert element.get(f"{{{W_NS}}}{attribute}") == expected
    if spec.prop == "font.size_pt":
        assert _child(base, "rPr/szCs").get(f"{{{W_NS}}}val") == expected
    if spec.prop == "font.bold":
        assert _child(base, "rPr/bCs").get(f"{{{W_NS}}}val") == expected
    if spec.prop == "font.ascii":
        fonts = _child(base, "rPr/rFonts")
        assert fonts.get(f"{{{W_NS}}}hAnsi") == "Arial"
        assert fonts.get(f"{{{W_NS}}}eastAsia") == "Keep-EastAsia"
    if spec.prop == "font.eastAsia":
        fonts = _child(base, "rPr/rFonts")
        assert fonts.get(f"{{{W_NS}}}ascii") == "Keep-Ascii"
        assert fonts.get(f"{{{W_NS}}}hAnsi") == "Keep-HAnsi"
    if spec.prop == "paragraph.line_spacing":
        spacing = _child(base, "pPr/spacing")
        if spec.after["type"] == "MULTIPLE":
            assert spacing.get(f"{{{W_NS}}}lineRule") == "auto"
        elif spec.after["type"] == "EXACT":
            assert spacing.get(f"{{{W_NS}}}lineRule") == "exact"
    if spec.prop == "paragraph.first_line_indent_chars":
        indent = _child(base, "pPr/ind")
        for name in ("firstLine", "hanging", "hangingChars"):
            assert f"{{{W_NS}}}{name}" not in indent.attrib
        assert indent.get(f"{{{W_NS}}}left") == "99"
    if spec.prop == "paragraph.first_line_indent_mm":
        indent = _child(base, "pPr/ind")
        for name in ("firstLineChars", "hanging", "hangingChars"):
            assert f"{{{W_NS}}}{name}" not in indent.attrib
        assert indent.get(f"{{{W_NS}}}left") == "99"
