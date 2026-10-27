from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import zipfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from docx import Document
from docx.enum.section import WD_SECTION
from docx.enum.style import WD_STYLE_TYPE
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.opc.constants import RELATIONSHIP_TYPE as RT
from docx.shared import Mm, Pt
from lxml import etree
from PIL import Image, ImageDraw
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

FIXTURE_ROOT = Path(__file__).resolve().parent
ROOT = FIXTURE_ROOT.parents[1]
DATA_ROOT = FIXTURE_ROOT / "data"
ASSET_ROOT = FIXTURE_ROOT / "assets"
GOLDEN_ROOT = FIXTURE_ROOT / "golden"
EXAMPLES_ROOT = ROOT / "examples"
MANIFEST_PATH = GOLDEN_ROOT / "manifest.json"
DEMO_GOLDEN_PATH = EXAMPLES_ROOT / "alinea-demo.golden.json"
FIXED_ZIP_DATETIME = (2024, 1, 1, 0, 0, 0)
FIXED_DATETIME = datetime(2024, 1, 1, tzinfo=timezone.utc)
CATEGORY_COUNTS = {
    "normal": 5,
    "single_property_error": 8,
    "multi_property_error": 5,
    "structural_edge": 6,
    "high_risk": 6,
}
CATEGORY_ZH = {
    "normal": "正常",
    "single_property_error": "单属性错误",
    "multi_property_error": "多属性错误",
    "structural_edge": "结构边缘",
    "high_risk": "高风险",
}
FORMAT_PROPERTIES = {
    "font.eastAsia",
    "font.ascii",
    "font.size_pt",
    "font.bold",
    "paragraph.alignment",
    "paragraph.first_line_indent_chars",
    "paragraph.first_line_indent_mm",
    "paragraph.left_indent_mm",
    "paragraph.right_indent_mm",
    "paragraph.line_spacing",
    "paragraph.space_before_pt",
    "paragraph.space_after_pt",
    "section.margin_top_mm",
    "section.margin_bottom_mm",
    "section.margin_left_mm",
    "section.margin_right_mm",
    "section.page_width_mm",
    "section.page_height_mm",
}
SELECTORS = {
    "body",
    "heading_1",
    "heading_2",
    "heading_3",
    "caption",
    "table_text",
    "section",
}
BODY = {
    "font.eastAsia": "SimSun",
    "font.ascii": "Times New Roman",
    "font.size_pt": 12.0,
    "font.bold": False,
    "paragraph.alignment": "both",
    "paragraph.first_line_indent_chars": 2.0,
    "paragraph.line_spacing": 1.5,
    "paragraph.space_before_pt": 0.0,
    "paragraph.space_after_pt": 0.0,
}
HEADING = {
    "font.eastAsia": "SimHei",
    "font.ascii": "Arial",
    "font.size_pt": 16.0,
    "font.bold": True,
    "paragraph.alignment": "left",
    "paragraph.first_line_indent_chars": 0.0,
    "paragraph.line_spacing": 1.5,
    "paragraph.space_before_pt": 12.0,
    "paragraph.space_after_pt": 6.0,
}
CAPTION = {
    "font.eastAsia": "SimSun",
    "font.ascii": "Times New Roman",
    "font.size_pt": 10.5,
    "font.bold": False,
    "paragraph.alignment": "center",
    "paragraph.first_line_indent_chars": 0.0,
    "paragraph.line_spacing": 1.0,
    "paragraph.space_before_pt": 6.0,
    "paragraph.space_after_pt": 6.0,
}
TABLE_TEXT = {
    "font.eastAsia": "SimSun",
    "font.ascii": "Times New Roman",
    "font.size_pt": 10.5,
    "font.bold": False,
    "paragraph.alignment": "left",
    "paragraph.first_line_indent_chars": 0.0,
    "paragraph.line_spacing": 1.0,
    "paragraph.space_before_pt": 0.0,
    "paragraph.space_after_pt": 0.0,
}
SECTION = {
    "section.margin_top_mm": 25.4,
    "section.margin_bottom_mm": 25.4,
    "section.margin_left_mm": 25.4,
    "section.margin_right_mm": 25.4,
    "section.page_width_mm": 210.0,
    "section.page_height_mm": 297.0,
}
ALLOWED_XML = {
    "font.eastAsia": ["w:rPr/w:rFonts/@w:eastAsia"],
    "font.ascii": ["w:rPr/w:rFonts/@w:ascii"],
    "font.size_pt": ["w:rPr/w:sz/@w:val", "w:rPr/w:szCs/@w:val"],
    "font.bold": ["w:rPr/w:b/@w:val", "w:rPr/w:bCs/@w:val"],
    "paragraph.alignment": ["w:pPr/w:jc/@w:val"],
    "paragraph.first_line_indent_chars": ["w:pPr/w:ind/@w:firstLineChars"],
    "paragraph.first_line_indent_mm": ["w:pPr/w:ind/@w:firstLine"],
    "paragraph.left_indent_mm": ["w:pPr/w:ind/@w:left"],
    "paragraph.right_indent_mm": ["w:pPr/w:ind/@w:right"],
    "paragraph.line_spacing": ["w:pPr/w:spacing/@w:line", "w:pPr/w:spacing/@w:lineRule"],
    "paragraph.space_before_pt": ["w:pPr/w:spacing/@w:before"],
    "paragraph.space_after_pt": ["w:pPr/w:spacing/@w:after"],
    "section.margin_top_mm": ["w:sectPr/w:pgMar/@w:top"],
    "section.margin_bottom_mm": ["w:sectPr/w:pgMar/@w:bottom"],
    "section.margin_left_mm": ["w:sectPr/w:pgMar/@w:left"],
    "section.margin_right_mm": ["w:sectPr/w:pgMar/@w:right"],
    "section.page_width_mm": ["w:sectPr/w:pgSz/@w:w"],
    "section.page_height_mm": ["w:sectPr/w:pgSz/@w:h"],
}

SAMPLES: list[dict[str, Any]] = []


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def xml_bytes(element: etree._Element) -> bytes:
    return etree.tostring(
        element,
        xml_declaration=True,
        encoding="UTF-8",
        standalone=True,
    )


def normalize_zip(
    path: Path,
    transform: Callable[[dict[str, bytes]], None] | None = None,
) -> None:
    with zipfile.ZipFile(path) as source:
        entries = {info.filename: source.read(info) for info in source.infolist()}
    if transform is not None:
        transform(entries)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as target:
        for name in sorted(entries):
            info = zipfile.ZipInfo(name, FIXED_ZIP_DATETIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = 0o600 << 16
            target.writestr(info, entries[name], compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
    temporary.replace(path)


def save_document(
    document: Document,
    path: Path,
    transform: Callable[[dict[str, bytes]], None] | None = None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    document.save(path)
    normalize_zip(path, transform)


def replace_child(parent: etree._Element, tag: str) -> etree._Element:
    for child in list(parent):
        if child.tag == tag:
            parent.remove(child)
    child = etree.Element(tag)
    parent.append(child)
    return child


def get_or_add(parent: etree._Element, tag: str) -> etree._Element:
    child = parent.find(tag)
    if child is None:
        child = etree.Element(tag)
        parent.append(child)
    return child


def set_font_attributes(r_pr: etree._Element, east_asia: str, ascii_font: str) -> None:
    r_fonts = get_or_add(r_pr, qn("w:rFonts"))
    for attribute in list(r_fonts.attrib):
        del r_fonts.attrib[attribute]
    r_fonts.set(qn("w:ascii"), ascii_font)
    r_fonts.set(qn("w:hAnsi"), ascii_font)
    r_fonts.set(qn("w:eastAsia"), east_asia)
    r_fonts.set(qn("w:cs"), ascii_font)


def set_run_font(
    run: Any,
    east_asia: str = "SimSun",
    ascii_font: str = "Times New Roman",
    size_pt: float = 12.0,
    bold: bool = False,
) -> None:
    run.font.name = ascii_font
    run.font.size = Pt(size_pt)
    run.font.bold = bold
    r_pr = run._r.get_or_add_rPr()
    set_font_attributes(r_pr, east_asia, ascii_font)
    sz_cs = get_or_add(r_pr, qn("w:szCs"))
    sz_cs.set(qn("w:val"), str(round(size_pt * 2)))
    b_cs = get_or_add(r_pr, qn("w:bCs"))
    b_cs.set(qn("w:val"), "1" if bold else "0")


def set_theme_run_font(run: Any) -> None:
    run.font.size = Pt(12)
    run.font.bold = False
    r_pr = run._r.get_or_add_rPr()
    r_fonts = get_or_add(r_pr, qn("w:rFonts"))
    for attribute in list(r_fonts.attrib):
        del r_fonts.attrib[attribute]
    r_fonts.set(qn("w:asciiTheme"), "majorHAnsi")
    r_fonts.set(qn("w:hAnsiTheme"), "majorHAnsi")
    r_fonts.set(qn("w:eastAsiaTheme"), "majorEastAsia")


def set_indent_chars(paragraph_or_style: Any, chars: float) -> None:
    if hasattr(paragraph_or_style, "_p"):
        p_pr = paragraph_or_style._p.get_or_add_pPr()
    else:
        p_pr = paragraph_or_style.element.get_or_add_pPr()
    ind = get_or_add(p_pr, qn("w:ind"))
    for attribute in ("firstLine", "hanging", "hangingChars"):
        ind.attrib.pop(qn(f"w:{attribute}"), None)
    ind.set(qn("w:firstLineChars"), str(round(chars * 100)))


def set_paragraph_format(
    paragraph_or_style: Any,
    alignment: str,
    first_line_chars: float,
    line_spacing: float,
    before_pt: float,
    after_pt: float,
) -> None:
    alignment_values = {
        "left": WD_ALIGN_PARAGRAPH.LEFT,
        "center": WD_ALIGN_PARAGRAPH.CENTER,
        "right": WD_ALIGN_PARAGRAPH.RIGHT,
        "both": WD_ALIGN_PARAGRAPH.JUSTIFY,
    }
    fmt = paragraph_or_style.paragraph_format
    fmt.alignment = alignment_values[alignment]
    fmt.line_spacing = line_spacing
    fmt.space_before = Pt(before_pt)
    fmt.space_after = Pt(after_pt)
    set_indent_chars(paragraph_or_style, first_line_chars)


def format_paragraph(paragraph: Any, values: dict[str, Any]) -> None:
    set_paragraph_format(
        paragraph,
        values["paragraph.alignment"],
        values["paragraph.first_line_indent_chars"],
        values["paragraph.line_spacing"],
        values["paragraph.space_before_pt"],
        values["paragraph.space_after_pt"],
    )


def format_run(run: Any, values: dict[str, Any], **overrides: Any) -> None:
    actual = dict(values)
    actual.update(overrides)
    set_run_font(
        run,
        actual["font.eastAsia"],
        actual["font.ascii"],
        actual["font.size_pt"],
        actual["font.bold"],
    )


def configure_doc_defaults(document: Document) -> None:
    styles = document.styles.element
    doc_defaults = styles.find(qn("w:docDefaults"))
    if doc_defaults is None:
        doc_defaults = OxmlElement("w:docDefaults")
        styles.insert(0, doc_defaults)
    r_pr_default = get_or_add(doc_defaults, qn("w:rPrDefault"))
    r_pr = replace_child(r_pr_default, qn("w:rPr"))
    set_font_attributes(r_pr, BODY["font.eastAsia"], BODY["font.ascii"])
    for tag in ("w:sz", "w:szCs"):
        node = OxmlElement(tag)
        node.set(qn("w:val"), "24")
        r_pr.append(node)
    for tag in ("w:b", "w:bCs"):
        node = OxmlElement(tag)
        node.set(qn("w:val"), "0")
        r_pr.append(node)
    p_pr_default = get_or_add(doc_defaults, qn("w:pPrDefault"))
    p_pr = replace_child(p_pr_default, qn("w:pPr"))
    spacing = OxmlElement("w:spacing")
    spacing.set(qn("w:before"), "0")
    spacing.set(qn("w:after"), "0")
    spacing.set(qn("w:line"), "360")
    spacing.set(qn("w:lineRule"), "auto")
    p_pr.append(spacing)
    justification = OxmlElement("w:jc")
    justification.set(qn("w:val"), "both")
    p_pr.append(justification)
    indent = OxmlElement("w:ind")
    indent.set(qn("w:firstLineChars"), "200")
    p_pr.append(indent)


def configure_style(style: Any, values: dict[str, Any]) -> None:
    style.font.name = values["font.ascii"]
    style.font.size = Pt(values["font.size_pt"])
    style.font.bold = values["font.bold"]
    set_font_attributes(
        style.element.get_or_add_rPr(),
        values["font.eastAsia"],
        values["font.ascii"],
    )
    set_paragraph_format(
        style,
        values["paragraph.alignment"],
        values["paragraph.first_line_indent_chars"],
        values["paragraph.line_spacing"],
        values["paragraph.space_before_pt"],
        values["paragraph.space_after_pt"],
    )


def configure_section(section: Any, **margin_overrides: float) -> None:
    section.page_width = Mm(210)
    section.page_height = Mm(297)
    values = {
        "top": margin_overrides.get("top", 25.4),
        "bottom": margin_overrides.get("bottom", 25.4),
        "left": margin_overrides.get("left", 25.4),
        "right": margin_overrides.get("right", 25.4),
    }
    section.top_margin = Mm(values["top"])
    section.bottom_margin = Mm(values["bottom"])
    section.left_margin = Mm(values["left"])
    section.right_margin = Mm(values["right"])
    section.header_distance = Mm(12.7)
    section.footer_distance = Mm(12.7)


def new_document(**margin_overrides: float) -> Document:
    document = Document()
    configure_doc_defaults(document)
    configure_style(document.styles["Heading 1"], HEADING)
    configure_style(document.styles["Caption"], CAPTION)
    configure_section(document.sections[0], **margin_overrides)
    properties = document.core_properties
    properties.title = "Alinea synthetic formatting fixture"
    properties.subject = "Non-sensitive generated test data"
    properties.author = "Alinea Fixture Generator"
    properties.last_modified_by = "Alinea Fixture Generator"
    properties.comments = "Imaginary content; no manual Microsoft Word verification."
    properties.created = FIXED_DATETIME
    properties.modified = FIXED_DATETIME
    properties.revision = 1
    settings = document.settings.element
    update_fields = settings.find(qn("w:updateFields"))
    if update_fields is None:
        update_fields = OxmlElement("w:updateFields")
        settings.append(update_fields)
    update_fields.set(qn("w:val"), "false")
    return document


def make_style_chain(document: Document) -> Any:
    styles = document.styles
    base = styles.add_style("Alinea Base", WD_STYLE_TYPE.PARAGRAPH)
    base.base_style = styles["Normal"]
    base.font.size = Pt(12)
    body = styles.add_style("Alinea Body", WD_STYLE_TYPE.PARAGRAPH)
    body.base_style = base
    derived = styles.add_style("Alinea Derived", WD_STYLE_TYPE.PARAGRAPH)
    derived.base_style = body
    derived.paragraph_format.line_spacing = 1.5
    return derived


def add_paragraph(
    document: Document,
    text: str,
    values: dict[str, Any] = BODY,
    style: Any | None = None,
    direct: bool = True,
    **overrides: Any,
) -> tuple[Any, Any]:
    paragraph = document.add_paragraph(style=style)
    run = paragraph.add_run(text)
    if direct:
        actual = dict(values)
        actual.update(overrides)
        format_run(run, values, **overrides)
        format_paragraph(paragraph, actual)
    return paragraph, run


def add_heading(document: Document, text: str, direct: bool = True, **overrides: Any) -> tuple[Any, Any]:
    return add_paragraph(document, text, HEADING, "Heading 1", direct, **overrides)


def add_caption(document: Document, text: str, **overrides: Any) -> tuple[Any, Any]:
    return add_paragraph(document, text, CAPTION, "Caption", direct=True, **overrides)


def add_hyperlink(paragraph: Any, text: str, url: str, values: dict[str, Any] = BODY) -> Any:
    relationship_id = paragraph.part.relate_to(url, RT.HYPERLINK, is_external=True)
    hyperlink = OxmlElement("w:hyperlink")
    hyperlink.set(qn("r:id"), relationship_id)
    run = paragraph.add_run(text)
    format_run(run, values)
    paragraph._p.remove(run._r)
    hyperlink.append(run._r)
    paragraph._p.append(hyperlink)
    return run


def add_table(document: Document, rows: list[list[str]]) -> Any:
    table = document.add_table(rows=len(rows), cols=len(rows[0]))
    table.style = "Table Grid"
    for row_index, row in enumerate(rows):
        for column_index, text in enumerate(row):
            cell = table.cell(row_index, column_index)
            paragraph = cell.paragraphs[0]
            run = paragraph.add_run(text)
            format_run(run, TABLE_TEXT)
            format_paragraph(paragraph, TABLE_TEXT)
    return table


def add_image(document: Document, asset: Path, width_mm: float = 80) -> Any:
    paragraph = document.add_paragraph(style="Caption")
    format_paragraph(paragraph, CAPTION)
    run = paragraph.add_run()
    run.add_picture(str(asset), width=Mm(width_mm))
    return paragraph


def add_header_footer(section: Any, heading: str, footer: str) -> None:
    section.header.is_linked_to_previous = False
    header_paragraph = section.header.paragraphs[0]
    header_run = header_paragraph.add_run(heading)
    set_run_font(header_run, size_pt=9)
    header_paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
    section.footer.is_linked_to_previous = False
    footer_paragraph = section.footer.paragraphs[0]
    footer_run = footer_paragraph.add_run(footer)
    set_run_font(footer_run, size_pt=9)
    footer_paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER


def anchor(text: str, selector: str = "body", unique: bool = True, match: str = "substring") -> dict[str, Any]:
    return {
        "paragraph_text_anchor": text,
        "selector": selector,
        "unique": unique,
        "match": match,
    }


def expectation(
    target_id: str,
    selector: str,
    property_name: str,
    text_anchor: str,
    actual: Any,
    expected: Any,
    status: str = "VIOLATION",
    run_index: int | None = 0,
    fixable: bool | None = None,
    locatable: bool = True,
    skip_reason: str | None = None,
    expected_origin: str | None = None,
) -> dict[str, Any]:
    if fixable is None:
        fixable = status == "VIOLATION"
    return {
        "target_id": target_id,
        "selector": selector,
        "property": property_name,
        "paragraph_text_anchor": text_anchor,
        "run_index": run_index,
        "actual": actual,
        "expected": expected,
        "status": status,
        "fixable": fixable,
        "locatable": locatable,
        "expected_skip_reason": skip_reason,
        "expected_origin": expected_origin,
        "allowed_xml_changes": ALLOWED_XML.get(property_name, []) if fixable else [],
        "repair_disposition": "AUTO_WITH_APPROVAL" if fixable else (
            "NOT_REQUIRED" if status == "COMPLIANT" else "MANUAL_REVIEW"
        ),
    }


def rendering_pending(note: str = "Render separately; no page count or rectangle is asserted.") -> dict[str, Any]:
    return {
        "status": "NOT_RENDERED",
        "page_count": None,
        "locations": [],
        "note": note,
    }


def register_sample(
    sample_id: str,
    category: str,
    filename: str,
    description: str,
    anchors: list[dict[str, Any]],
    expectations: list[dict[str, Any]],
    document: Document | None = None,
    transform: Callable[[dict[str, bytes]], None] | None = None,
    raw_bytes: bytes | None = None,
    expected_errors: list[dict[str, Any]] | None = None,
    expected_degradations: list[dict[str, Any]] | None = None,
    reopen_expectation: str = "REOPEN_OK",
    structural_facts: dict[str, Any] | None = None,
    rendering: dict[str, Any] | None = None,
) -> dict[str, Any]:
    path = DATA_ROOT / category / filename
    if document is not None:
        save_document(document, path, transform)
    elif raw_bytes is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw_bytes)
    else:
        raise ValueError("document or raw_bytes is required")
    statuses = Counter(item["status"] for item in expectations)
    record = {
        "sample_id": sample_id,
        "category": category,
        "category_zh": CATEGORY_ZH[category],
        "file": path.relative_to(FIXTURE_ROOT).as_posix(),
        "description": description,
        "paragraph_anchors": anchors,
        "expected_supported_properties": sorted({item["property"] for item in expectations}),
        "expectations": expectations,
        "expected_issue_count": statuses["VIOLATION"],
        "expected_unverifiable_count": statuses["UNVERIFIABLE"],
        "expected_skipped_count": statuses["SKIPPED"],
        "expected_skip_reasons": sorted(
            {item["expected_skip_reason"] for item in expectations if item["expected_skip_reason"]}
            | {item["reason_code"] for item in (expected_errors or [])}
            | {item["code"] for item in (expected_degradations or [])}
        ),
        "expected_errors": expected_errors or [],
        "expected_degradations": expected_degradations or [],
        "reopen_expectation": reopen_expectation,
        "rendering": rendering or rendering_pending(),
        "structural_facts": structural_facts or {},
        "file_size_bytes": path.stat().st_size,
        "file_sha256": sha256_file(path),
        "truth_source": "KNOWN_GENERATOR_INPUT",
    }
    SAMPLES.append(record)
    return record


def build_asset() -> Path:
    ASSET_ROOT.mkdir(parents=True, exist_ok=True)
    path = ASSET_ROOT / "alinea-grid.png"
    image = Image.new("RGB", (320, 120), (255, 255, 255))
    draw = ImageDraw.Draw(image)
    draw.rectangle((2, 2, 317, 117), outline=(31, 78, 121), width=3)
    for x in range(40, 320, 40):
        draw.line((x, 4, x, 116), fill=(174, 196, 216), width=1)
    for y in range(30, 120, 30):
        draw.line((4, y, 316, y), fill=(174, 196, 216), width=1)
    draw.ellipse((126, 30, 194, 90), fill=(237, 125, 49), outline=(99, 62, 20), width=2)
    image.save(path, format="PNG", optimize=False)
    return path


def build_normal(asset: Path) -> None:
    text = "N01 正常中文正文：公开假想数据用于核对宋体、字号与行距。"
    document = new_document()
    add_heading(document, "N01 正常中文文档")
    add_paragraph(document, text)
    expectations = [
        expectation("N01-C1", "body", "font.eastAsia", text, "SimSun", "SimSun", "COMPLIANT"),
        expectation("N01-C2", "body", "font.size_pt", text, 12.0, 12.0, "COMPLIANT"),
        expectation("N01-C3", "body", "paragraph.line_spacing", text, 1.5, 1.5, "COMPLIANT", None),
    ]
    register_sample("N01", "normal", "n01-zh-body.docx", "中文正文与标题，全部满足假想规范。", [anchor(text)], expectations, document)

    text = "N02 English body: synthetic public notes use deterministic Latin formatting."
    document = new_document()
    add_heading(document, "N02 English Research Notes")
    add_paragraph(document, text)
    expectations = [
        expectation("N02-C1", "body", "font.ascii", text, "Times New Roman", "Times New Roman", "COMPLIANT"),
        expectation("N02-C2", "body", "font.bold", text, False, False, "COMPLIANT"),
        expectation("N02-C3", "body", "paragraph.first_line_indent_chars", text, 2.0, 2.0, "COMPLIANT", None),
    ]
    register_sample("N02", "normal", "n02-en-body.docx", "英文正文，覆盖 Latin 字体与首行缩进。", [anchor(text)], expectations, document)

    text = "N03 样式继承锚点：docDefaults、三级 basedOn 与有效字号均符合规范。"
    document = new_document()
    derived = make_style_chain(document)
    add_heading(document, "N03 多级样式继承")
    add_paragraph(document, text, style=derived, direct=False)
    expectations = [
        expectation("N03-C1", "body", "font.eastAsia", text, "SimSun", "SimSun", "COMPLIANT", expected_origin="DOC_DEFAULT"),
        expectation("N03-C2", "body", "font.size_pt", text, 12.0, 12.0, "COMPLIANT", expected_origin="BASED_ON"),
        expectation("N03-C3", "body", "paragraph.line_spacing", text, 1.5, 1.5, "COMPLIANT", None, expected_origin="BASED_ON"),
    ]
    register_sample(
        "N03",
        "normal",
        "n03-docdefaults-basedon.docx",
        "Normal <- Alinea Base <- Alinea Body <- Alinea Derived 的多级继承。",
        [anchor(text)],
        expectations,
        document,
        structural_facts={"doc_defaults": True, "based_on_chain": ["Normal", "AlineaBase", "AlineaBody", "AlineaDerived"]},
    )

    body_text = "N04 媒体保真正文锚点：图片、简单表格和超链接均不改变正文规则。"
    cell_text = "N04 表格唯一单元格"
    document = new_document()
    add_heading(document, "N04 图片表格与链接")
    paragraph, _ = add_paragraph(document, body_text)
    add_hyperlink(paragraph, " 公开示例链接", "https://example.com/alinea-fixture")
    add_table(document, [[cell_text, "公开值"], ["甲", "乙"]])
    add_image(document, asset)
    add_caption(document, "N04 图题：确定性网格图片")
    expectations = [
        expectation("N04-C1", "body", "font.size_pt", body_text, 12.0, 12.0, "COMPLIANT"),
        expectation("N04-C2", "table_text", "font.size_pt", cell_text, 10.5, 10.5, "COMPLIANT"),
    ]
    register_sample(
        "N04",
        "normal",
        "n04-table-image-link.docx",
        "简单表格、内嵌 PNG 与外部超链接的合规媒体保真样本。",
        [anchor(body_text), anchor(cell_text, "table_text")],
        expectations,
        document,
        structural_facts={"tables": 1, "embedded_images": 1, "hyperlinks": 1},
    )

    text = "N05 第二节正文锚点：多节页眉页脚与统一页边距。"
    document = new_document()
    add_heading(document, "N05 第一节")
    add_paragraph(document, "N05 第一节正文，内容为公开假想文本。")
    add_header_footer(document.sections[0], "N05 第一节页眉", "N05 第一节页脚")
    second = document.add_section(WD_SECTION.NEW_PAGE)
    configure_section(second)
    add_heading(document, "N05 第二节")
    add_paragraph(document, text)
    add_header_footer(second, "N05 第二节页眉", "N05 第二节页脚")
    expectations = [
        expectation("N05-C1", "section", "section.margin_top_mm", text, 25.4, 25.4, "COMPLIANT", None),
        expectation("N05-C2", "body", "paragraph.space_after_pt", text, 0.0, 0.0, "COMPLIANT", None),
    ]
    register_sample(
        "N05",
        "normal",
        "n05-sections-headers.docx",
        "两节、独立页眉页脚，节属性满足规范。",
        [anchor(text)],
        expectations,
        document,
        structural_facts={"sections": 2, "headers": 2, "footers": 2},
    )


def build_single_property_errors() -> None:
    cases = [
        ("S01", "font.size_pt", 10.5, 12.0, "直接 run 覆盖继承字号。", "size"),
        ("S02", "font.eastAsia", "SimHei", "SimSun", "仅中文字体错误，Latin 字体保持不变。", "eastAsia"),
        ("S03", "font.bold", True, False, "仅粗体错误。", "bold"),
        ("S04", "paragraph.alignment", "center", "both", "仅对齐方式错误。", "alignment"),
        ("S05", "paragraph.line_spacing", 1.0, 1.5, "仅行距错误。", "line"),
        ("S06", "paragraph.first_line_indent_chars", 0.0, 2.0, "仅首行缩进字符数错误。", "indent"),
        ("S07", "paragraph.space_before_pt", 12.0, 0.0, "仅段前距错误。", "before"),
        ("S08", "section.margin_top_mm", 20.0, 25.4, "仅节上边距错误。", "top"),
    ]
    for sample_id, property_name, actual, expected, description, kind in cases:
        text = f"{sample_id} 唯一正文锚点：{description}"
        margins = {"top": 20.0} if kind == "top" else {}
        document = new_document(**margins)
        add_heading(document, f"{sample_id} 单属性错误")
        if kind == "size":
            derived = make_style_chain(document)
            add_paragraph(document, text, style=derived, direct=False)
            paragraph = document.paragraphs[-1]
            run = paragraph.add_run("DIRECT_SIZE_OVERRIDE")
            set_run_font(run, size_pt=10.5)
            target_anchor = "DIRECT_SIZE_OVERRIDE"
            run_index = 1
            anchors = [anchor(text), anchor(target_anchor)]
        else:
            target_anchor = text
            run_index = 0 if selector_is_run(property_name) else None
            anchors = [anchor(text, "section" if kind == "top" else "body")]
            overrides: dict[str, Any] = {}
            if kind == "eastAsia":
                overrides["font.eastAsia"] = actual
            elif kind == "bold":
                overrides["font.bold"] = actual
            elif kind == "alignment":
                overrides["paragraph.alignment"] = actual
            elif kind == "line":
                overrides["paragraph.line_spacing"] = actual
            elif kind == "indent":
                overrides["paragraph.first_line_indent_chars"] = actual
            elif kind == "before":
                overrides["paragraph.space_before_pt"] = actual
            if kind != "top":
                add_paragraph(document, text, **overrides)
            else:
                add_paragraph(document, text)
        selector = "section" if kind == "top" else "body"
        exp = expectation(
            f"{sample_id}-T1",
            selector,
            property_name,
            target_anchor,
            actual,
            expected,
            run_index=run_index,
            expected_origin="DIRECT",
        )
        facts = {"direct_run_override": True, "inherited_size_pt": 12.0} if kind == "size" else {}
        register_sample(
            sample_id,
            "single_property_error",
            f"{sample_id.lower()}-{kind}.docx",
            description,
            anchors,
            [exp],
            document,
            structural_facts=facts,
        )


def selector_is_run(property_name: str) -> bool:
    return property_name.startswith("font.")


def build_multi_property_errors() -> None:
    text = "M01 同段落不同 run："
    chinese = "中文字体错误"
    english = "Latin font and size errors"
    document = new_document()
    add_heading(document, "M01 不同 Run 多属性")
    paragraph, run0 = add_paragraph(document, text)
    run1 = paragraph.add_run(chinese)
    format_run(run1, BODY, **{"font.eastAsia": "SimHei"})
    run2 = paragraph.add_run(english)
    format_run(run2, BODY, **{"font.ascii": "Arial", "font.size_pt": 10.5})
    expectations = [
        expectation("M01-T1", "body", "font.eastAsia", text, "SimHei", "SimSun", run_index=1),
        expectation("M01-T2", "body", "font.ascii", text, "Arial", "Times New Roman", run_index=2),
        expectation("M01-T3", "body", "font.size_pt", text, 10.5, 12.0, run_index=2),
    ]
    register_sample("M01", "multi_property_error", "m01-different-runs.docx", "同段落不同 run 的三项错误，可分批审批修复。", [anchor(text)], expectations, document, structural_facts={"target_run_indices": [1, 2]})

    text = "M02 直接覆盖锚点：字号、粗体与对齐同时偏离规范。"
    document = new_document()
    derived = make_style_chain(document)
    add_heading(document, "M02 样式与直接格式")
    paragraph = document.add_paragraph(style=derived)
    run = paragraph.add_run(text)
    format_run(run, BODY, **{"font.size_pt": 14.0, "font.bold": True})
    format_paragraph(paragraph, {**BODY, "paragraph.alignment": "right"})
    expectations = [
        expectation("M02-T1", "body", "font.size_pt", text, 14.0, 12.0),
        expectation("M02-T2", "body", "font.bold", text, True, False),
        expectation("M02-T3", "body", "paragraph.alignment", text, "right", "both", run_index=None),
    ]
    register_sample("M02", "multi_property_error", "m02-style-direct-multi.docx", "多级样式之上的直接 run 与段落覆盖。", [anchor(text)], expectations, document)

    text = "M03 段落属性锚点：行距、首行缩进、段前与段后四项错误。"
    document = new_document()
    add_heading(document, "M03 段落间距组合")
    add_paragraph(
        document,
        text,
        **{
            "paragraph.line_spacing": 2.0,
            "paragraph.first_line_indent_chars": 1.0,
            "paragraph.space_before_pt": 18.0,
            "paragraph.space_after_pt": 9.0,
        },
    )
    expectations = [
        expectation("M03-T1", "body", "paragraph.line_spacing", text, 2.0, 1.5, run_index=None),
        expectation("M03-T2", "body", "paragraph.first_line_indent_chars", text, 1.0, 2.0, run_index=None),
        expectation("M03-T3", "body", "paragraph.space_before_pt", text, 18.0, 0.0, run_index=None),
        expectation("M03-T4", "body", "paragraph.space_after_pt", text, 9.0, 0.0, run_index=None),
    ]
    register_sample("M03", "multi_property_error", "m03-paragraph-spacing.docx", "行距、缩进和段前段后组合修复。", [anchor(text)], expectations, document)

    text = "M04 节边距锚点：上、下、左、右四项边距错误。"
    document = new_document(top=18.0, bottom=19.0, left=20.0, right=21.0)
    add_heading(document, "M04 节页边距组合")
    add_paragraph(document, text)
    expectations = [
        expectation("M04-T1", "section", "section.margin_top_mm", text, 18.0, 25.4, run_index=None),
        expectation("M04-T2", "section", "section.margin_bottom_mm", text, 19.0, 25.4, run_index=None),
        expectation("M04-T3", "section", "section.margin_left_mm", text, 20.0, 25.4, run_index=None),
        expectation("M04-T4", "section", "section.margin_right_mm", text, 21.0, 25.4, run_index=None),
    ]
    register_sample("M04", "multi_property_error", "m04-section-margins.docx", "同一节的四项页边距错误。", [anchor(text, "section")], expectations, document)

    caption_text = "M05 图题：字号与对齐错误"
    cell_text = "M05 表格文字：字体与粗体错误"
    document = new_document()
    add_heading(document, "M05 图题和表格批量修复")
    add_paragraph(document, "M05 普通正文保持合规。")
    add_caption(document, caption_text, **{"font.size_pt": 12.0, "paragraph.alignment": "right"})
    table = add_table(document, [[cell_text, "合规单元格"]])
    target_paragraph = table.cell(0, 0).paragraphs[0]
    target_run = target_paragraph.runs[0]
    format_run(target_run, TABLE_TEXT, **{"font.eastAsia": "SimHei", "font.bold": True})
    expectations = [
        expectation("M05-T1", "caption", "font.size_pt", caption_text, 12.0, 10.5),
        expectation("M05-T2", "caption", "paragraph.alignment", caption_text, "right", "center", run_index=None),
        expectation("M05-T3", "table_text", "font.eastAsia", cell_text, "SimHei", "SimSun"),
        expectation("M05-T4", "table_text", "font.bold", cell_text, True, False),
    ]
    register_sample("M05", "multi_property_error", "m05-caption-table.docx", "图题与表格内文字的多目标批量修复。", [anchor(caption_text, "caption"), anchor(cell_text, "table_text")], expectations, document)


def build_structural_edges(asset: Path) -> None:
    normal_text = "E01 中英混排 ordinary Latin text：普通 run 可有效解析。"
    theme_text = "E01 THEME_UNKNOWN_ANCHOR 主题字体未知"
    document = new_document()
    add_heading(document, "E01 混排与未知主题字体")
    add_paragraph(document, normal_text)
    paragraph = document.add_paragraph()
    run = paragraph.add_run(theme_text)
    set_theme_run_font(run)
    format_paragraph(paragraph, BODY)

    def set_unknown_theme(entries: dict[str, bytes]) -> None:
        theme = etree.fromstring(entries["word/theme/theme1.xml"])
        ns = {"a": "http://schemas.openxmlformats.org/drawingml/2006/main"}
        for xpath in (".//a:majorFont/a:latin", ".//a:majorFont/a:ea", ".//a:minorFont/a:latin", ".//a:minorFont/a:ea"):
            for node in theme.xpath(xpath, namespaces=ns):
                node.set("typeface", "Alinea Fixture Unknown")
        entries["word/theme/theme1.xml"] = xml_bytes(theme)

    expectations = [
        expectation("E01-U1", "body", "font.eastAsia", theme_text, {"theme": "majorEastAsia", "typeface": "Alinea Fixture Unknown"}, "SimSun", "UNVERIFIABLE", fixable=False, skip_reason="THEME_FONT_UNRESOLVED"),
        expectation("E01-U2", "body", "font.ascii", theme_text, {"theme": "majorHAnsi", "typeface": "Alinea Fixture Unknown"}, "Times New Roman", "UNVERIFIABLE", fixable=False, skip_reason="THEME_FONT_UNRESOLVED"),
    ]
    register_sample(
        "E01",
        "structural_edge",
        "e01-mixed-theme-unknown.docx",
        "CJK/Latin 混排，主题引用存在但字体不在受支持字体清单。",
        [anchor(normal_text), anchor(theme_text)],
        expectations,
        document,
        transform=set_unknown_theme,
        expected_degradations=[{"code": "THEME_FONT_UNRESOLVED", "stage": "STYLE_RESOLUTION", "action": "MARK_UNVERIFIABLE_NO_AUTO_FIX"}],
        structural_facts={"theme_typeface": "Alinea Fixture Unknown", "font_availability_requires_renderer": True},
    )

    repeated = "第一章"
    document = new_document()
    add_heading(document, "E02 重复短句定位")
    for _ in range(3):
        add_heading(document, repeated)
    add_paragraph(document, "E02 上下文前导段落，仅用于提供邻接信息。")
    add_paragraph(document, "继续")
    add_paragraph(document, "E02 中间上下文段落。")
    add_paragraph(document, "继续")
    expectations = [
        {
            **expectation("E02-C1", "heading_1", "font.size_pt", repeated, 16.0, 16.0, "COMPLIANT", locatable=False, skip_reason="AMBIGUOUS_REPEATED_TEXT"),
            "unique": False,
        },
    ]
    register_sample(
        "E02",
        "structural_edge",
        "e02-repeated-short-text.docx",
        "三个“第一章”和两个“继续”必须降级为定位歧义。",
        [anchor(repeated, "heading_1", unique=False), anchor("继续", unique=False)],
        expectations,
        document,
        expected_degradations=[{"code": "LOCATION_AMBIGUOUS", "stage": "LOCATION_MAPPING", "action": "DO_NOT_DRAW_UNIQUE_RECT"}],
        structural_facts={"anchor_occurrences": {"第一章": 3, "继续": 2}},
    )

    long_prefix = "E03 LONG_CROSS_PAGE_ANCHOR "
    long_text = long_prefix + "".join(
        f"第{index:03d}段公开假想长文本用于验证跨页段落的多片段定位与失败降级；"
        "Alinea synthetic long-form content keeps every character deterministic."
        for index in range(150)
    )
    document = new_document()
    add_heading(document, "E03 长跨页文本")
    add_paragraph(document, long_text)
    expectations = [
        expectation("E03-C1", "body", "paragraph.line_spacing", long_prefix, 1.5, 1.5, "COMPLIANT", None, locatable=True),
    ]
    register_sample(
        "E03",
        "structural_edge",
        "e03-long-cross-page.docx",
        "单个长段落自然跨页；页数与多矩形必须渲染后测量。",
        [anchor(long_prefix, match="prefix")],
        expectations,
        document,
        rendering=rendering_pending("Long paragraph may span pages; derive page count and fragments from a renderer."),
        structural_facts={"paragraph_character_count": len(long_text), "explicit_page_breaks": 0},
    )

    body_text = "E04 结构媒体锚点：表格、图片、图题和超链接共同出现。"
    cell_text = "E04 表格定位文本"
    document = new_document()
    add_heading(document, "E04 复合媒体结构")
    paragraph, _ = add_paragraph(document, body_text)
    add_hyperlink(paragraph, " Example Public Link", "https://example.com/alinea-structural-edge")
    add_table(document, [[cell_text, "English cell"], ["第二行甲", "Second row"]])
    add_image(document, asset, width_mm=65)
    add_caption(document, "E04 图题：网格仅由几何图形组成")
    expectations = [
        expectation("E04-C1", "table_text", "paragraph.alignment", cell_text, "left", "left", "COMPLIANT", None),
        expectation("E04-C2", "caption", "font.size_pt", "E04 图题：网格仅由几何图形组成", 10.5, 10.5, "COMPLIANT"),
    ]
    register_sample(
        "E04",
        "structural_edge",
        "e04-table-image-hyperlink.docx",
        "媒体对象与文本锚点组合，供内容/媒体哈希 Gate 使用。",
        [anchor(body_text), anchor(cell_text, "table_text")],
        expectations,
        document,
        structural_facts={"tables": 1, "embedded_images": 1, "hyperlinks": 1},
    )

    section_texts = [
        "E05 第一节唯一正文锚点。",
        "E05 第二节唯一正文锚点。",
        "E05 第三节唯一正文锚点。",
    ]
    document = new_document()
    for index, text in enumerate(section_texts):
        if index:
            section = document.add_section(WD_SECTION.NEW_PAGE)
            configure_section(section)
        add_heading(document, f"E05 第{index + 1}节标题")
        add_paragraph(document, text)
        add_header_footer(document.sections[index], f"E05 页眉 {index + 1}", f"E05 页脚 {index + 1}")
    expectations = [
        expectation("E05-C1", "section", "section.margin_left_mm", section_texts[-1], 25.4, 25.4, "COMPLIANT", None),
    ]
    register_sample(
        "E05",
        "structural_edge",
        "e05-three-sections.docx",
        "三节及独立页眉页脚，验证节范围而非虚构页码。",
        [anchor(text) for text in section_texts],
        expectations,
        document,
        structural_facts={"sections": 3, "headers": 3, "footers": 3},
    )

    text = "E06 未知部件锚点：检查器忽略未知 part，修复时必须保留。"
    document = new_document()
    add_heading(document, "E06 未知 OPC 部件")
    add_paragraph(document, text)

    def add_unknown_part(entries: dict[str, bytes]) -> None:
        content_types = etree.fromstring(entries["[Content_Types].xml"])
        override = etree.SubElement(content_types, "{http://schemas.openxmlformats.org/package/2006/content-types}Override")
        override.set("PartName", "/word/alineaUnknown.xml")
        override.set("ContentType", "application/vnd.alinea.fixture+xml")
        entries["[Content_Types].xml"] = xml_bytes(content_types)
        relationships = etree.fromstring(entries["word/_rels/document.xml.rels"])
        relationship = etree.SubElement(relationships, "{http://schemas.openxmlformats.org/package/2006/relationships}Relationship")
        relationship.set("Id", "rIdAlineaUnknown")
        relationship.set("Type", "https://example.invalid/alinea/unknown-part")
        relationship.set("Target", "alineaUnknown.xml")
        entries["word/_rels/document.xml.rels"] = xml_bytes(relationships)
        entries["word/alineaUnknown.xml"] = b'<?xml version="1.0" encoding="UTF-8"?><alinea:boundary xmlns:alinea="https://example.invalid/alinea"><value>safe</value></alinea:boundary>'

    expectations = [
        expectation("E06-C1", "body", "font.size_pt", text, 12.0, 12.0, "COMPLIANT"),
    ]
    register_sample(
        "E06",
        "structural_edge",
        "e06-unknown-part.docx",
        "含无敏感信息的自定义未知 part，不参与格式解析但必须保真。",
        [anchor(text)],
        expectations,
        document,
        transform=add_unknown_part,
        expected_degradations=[{"code": "UNKNOWN_PART_IGNORED_FOR_INSPECTION", "stage": "PACKAGE_PARSE", "action": "PRESERVE_ON_REPAIR"}],
        structural_facts={"unknown_part_uri": "/word/alineaUnknown.xml"},
    )


def build_high_risk(asset: Path) -> None:
    stable_text = "H01 TRACK_CHANGE_ANCHOR 修订段落"
    document = new_document()
    add_heading(document, "H01 Track Changes")
    paragraph, _ = add_paragraph(document, stable_text)
    insertion = OxmlElement("w:ins")
    insertion.set(qn("w:id"), "101")
    insertion.set(qn("w:author"), "Alinea Fixture")
    insertion.set(qn("w:date"), "2024-01-01T00:00:00Z")
    inserted_run = paragraph.add_run(" 插入文本的字号不受自动修复支持。")
    set_run_font(inserted_run, size_pt=10.5)
    paragraph._p.remove(inserted_run._r)
    insertion.append(inserted_run._r)
    paragraph._p.append(insertion)
    deletion = OxmlElement("w:del")
    deletion.set(qn("w:id"), "102")
    deletion.set(qn("w:author"), "Alinea Fixture")
    deletion.set(qn("w:date"), "2024-01-01T00:00:00Z")
    deleted_run = OxmlElement("w:r")
    deleted_text = OxmlElement("w:delText")
    deleted_text.text = "安全假想删除文本"
    deleted_run.append(deleted_text)
    deletion.append(deleted_run)
    paragraph._p.append(deletion)
    expectations = [
        expectation("H01-S1", "body", "font.size_pt", stable_text, 10.5, 12.0, "SKIPPED", None, fixable=False, locatable=False, skip_reason="TRACK_CHANGES_MANUAL_REVIEW"),
    ]
    register_sample(
        "H01",
        "high_risk",
        "h01-track-changes.docx",
        "含 w:ins/w:del 的修订文档，已知偏差不得危险自动修改。",
        [anchor(stable_text)],
        expectations,
        document,
        expected_degradations=[{"code": "TRACK_CHANGES_MANUAL_REVIEW", "stage": "INSPECTION_REPAIR", "action": "SKIP_REVISION_RUNS_AND_REJECT_AUTO_FIX"}],
        structural_facts={"insertions": 1, "deletions": 1},
    )

    field_text = "H02 COMPLEX_FIELD_ANCHOR "
    document = new_document()
    add_heading(document, "H02 Complex Field and Equation")
    paragraph, _ = add_paragraph(document, field_text)
    begin = paragraph.add_run()
    format_run(begin, BODY)
    begin_char = OxmlElement("w:fldChar")
    begin_char.set(qn("w:fldCharType"), "begin")
    begin_char.set(qn("w:dirty"), "false")
    begin_char.set(qn("w:fldLock"), "true")
    begin._r.append(begin_char)
    instruction = paragraph.add_run()
    format_run(instruction, BODY)
    instruction_text = OxmlElement("w:instrText")
    instruction_text.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
    instruction_text.text = ' TOC \\o "1-3" \\h \\z \\u '
    instruction._r.append(instruction_text)
    separate = paragraph.add_run()
    format_run(separate, BODY)
    separate_char = OxmlElement("w:fldChar")
    separate_char.set(qn("w:fldCharType"), "separate")
    separate._r.append(separate_char)
    placeholder = paragraph.add_run("H02_FIELD_PLACEHOLDER")
    set_run_font(placeholder, size_pt=10.5)
    end = paragraph.add_run()
    format_run(end, BODY)
    end_char = OxmlElement("w:fldChar")
    end_char.set(qn("w:fldCharType"), "end")
    end._r.append(end_char)
    math_paragraph, _ = add_paragraph(document, "H02 EQUATION_ANCHOR ")
    math = etree.fromstring(
        b'<m:oMath xmlns:m="http://schemas.openxmlformats.org/officeDocument/2006/math"><m:r><m:t>x+1=2</m:t></m:r></m:oMath>'
    )
    math_paragraph._p.append(math)
    expectations = [
        expectation("H02-S1", "body", "font.size_pt", field_text, 10.5, 12.0, "SKIPPED", 4, fixable=False, locatable=False, skip_reason="COMPLEX_FIELD_MANUAL_REVIEW"),
        expectation("H02-S2", "body", "font.size_pt", "H02 EQUATION_ANCHOR", "OMML_NOT_SUPPORTED", 12.0, "SKIPPED", None, fixable=False, locatable=False, skip_reason="UNSUPPORTED_EQUATION"),
    ]
    register_sample(
        "H02",
        "high_risk",
        "h02-complex-field-equation.docx",
        "锁定 TOC 复杂域和原生 OMML 公式，禁止自动更新或改写。",
        [anchor(field_text, match="prefix"), anchor("H02 EQUATION_ANCHOR", match="prefix")],
        expectations,
        document,
        expected_degradations=[
            {"code": "COMPLEX_FIELD_MANUAL_REVIEW", "stage": "INSPECTION_REPAIR", "action": "DO_NOT_UPDATE_OR_AUTO_FIX_FIELD"},
            {"code": "UNSUPPORTED_EQUATION", "stage": "INSPECTION_REPAIR", "action": "PRESERVE_OMML_AND_SKIP"},
        ],
        structural_facts={"complex_fields": 1, "equations": 1, "field_locked": True},
    )

    text = "H03 外部图片关系锚点：禁止联网获取 example.invalid 资源。"
    document = new_document()
    add_heading(document, "H03 External Image Relationship")
    add_paragraph(document, text)
    add_image(document, asset, width_mm=55)
    blips = list(document.element.body.iter(qn("a:blip")))
    if len(blips) != 1:
        raise AssertionError("Expected one image blip")
    blip = blips[0]
    blip.attrib.pop(qn("r:embed"), None)
    external_id = document.part.relate_to(
        "https://example.invalid/alinea-safe-external-image.png",
        RT.IMAGE,
        is_external=True,
    )
    blip.set(qn("r:link"), external_id)
    expectations = [
        expectation("H03-S1", "body", "font.size_pt", text, 12.0, 12.0, "COMPLIANT"),
    ]
    register_sample(
        "H03",
        "high_risk",
        "h03-external-image.docx",
        "外部图片关系使用保留无效域名，不含真实远程负载且不得联网。",
        [anchor(text)],
        expectations,
        document,
        expected_degradations=[{"code": "EXTERNAL_IMAGE_RELATIONSHIP", "stage": "PACKAGE_RENDER_REPAIR", "action": "DO_NOT_FETCH_MARK_MANUAL_REVIEW"}],
        structural_facts={"external_image_target": "https://example.invalid/alinea-safe-external-image.png", "embedded_media_retained": 1},
    )

    corrupt = b"PK\x03\x04ALINEA-SAFE-TRUNCATED-ZIP-FIXTURE\x00\x00\x00"
    register_sample(
        "H04",
        "high_risk",
        "h04-corrupt-zip.docx",
        "截断 ZIP 签名，不含可执行或恶意内容。",
        [],
        [],
        raw_bytes=corrupt,
        expected_errors=[{"code": "INVALID_DOCX", "reason_code": "CORRUPT_ZIP", "stage": "PACKAGE_VALIDATION"}],
        expected_degradations=[{"code": "REJECT_BEFORE_PARSE", "stage": "PACKAGE_VALIDATION", "action": "KEEP_ORIGINAL_DOWNLOADABLE"}],
        reopen_expectation="REOPEN_ERROR",
        structural_facts={"safe_boundary_only": True},
    )

    document = new_document()
    add_paragraph(document, "H05 此文本不会形成有效 XML。")

    def break_document_xml(entries: dict[str, bytes]) -> None:
        entries["word/document.xml"] = b'<?xml version="1.0" encoding="UTF-8"?><w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p>'

    register_sample(
        "H05",
        "high_risk",
        "h05-invalid-xml.docx",
        "ZIP 结构完整但 word/document.xml 未闭合。",
        [],
        [],
        document,
        transform=break_document_xml,
        expected_errors=[{"code": "INVALID_DOCX", "reason_code": "INVALID_XML", "stage": "XML_PARSE"}],
        expected_degradations=[{"code": "REJECT_BEFORE_INSPECTION", "stage": "XML_PARSE", "action": "KEEP_ORIGINAL_DOWNLOADABLE"}],
        reopen_expectation="REOPEN_ERROR",
        structural_facts={"malformed_part": "/word/document.xml", "safe_boundary_only": True},
    )

    text = "H06 安全 ZIP 边界元数据样本，不得解压到工作区之外。"
    document = new_document()
    add_paragraph(document, text)

    def add_zip_boundaries(entries: dict[str, bytes]) -> None:
        entries["../alinea-safe-boundary-marker.txt"] = b"SAFE METADATA ONLY; DO NOT EXTRACT\n"
        entries["word/alinea-compression-ratio.txt"] = b"A" * 65536

    record = register_sample(
        "H06",
        "high_risk",
        "h06-zip-boundary-metadata.docx",
        "同一小型 ZIP 含路径穿越名称与高压缩比文本；仅安全边界元数据。",
        [],
        [],
        document,
        transform=add_zip_boundaries,
        expected_errors=[
            {"code": "INVALID_DOCX", "reason_code": "UNSAFE_ZIP_PATH", "stage": "PACKAGE_VALIDATION"},
            {"code": "INVALID_DOCX", "reason_code": "COMPRESSION_RATIO_EXCEEDED", "stage": "PACKAGE_VALIDATION"},
        ],
        expected_degradations=[{"code": "REJECT_BEFORE_EXTRACTION_OR_PARSE", "stage": "PACKAGE_VALIDATION", "action": "DO_NOT_EXTRACT_DO_NOT_RENDER"}],
        reopen_expectation="SECURITY_REJECT_BEFORE_REOPEN",
        structural_facts={"expected_error_match": "ALL_REASON_CODES_UNORDERED", "safe_boundary_only": True},
    )
    path = FIXTURE_ROOT / record["file"]
    with zipfile.ZipFile(path) as archive:
        ratio_info = archive.getinfo("word/alinea-compression-ratio.txt")
        ratio = ratio_info.file_size / ratio_info.compress_size
        traversal = archive.getinfo("../alinea-safe-boundary-marker.txt")
    record["structural_facts"].update(
        {
            "path_traversal_entry": traversal.filename,
            "path_traversal_uncompressed_bytes": traversal.file_size,
            "compression_ratio_entry": ratio_info.filename,
            "compression_ratio_uncompressed_bytes": ratio_info.file_size,
            "compression_ratio_compressed_bytes": ratio_info.compress_size,
            "compression_ratio": round(ratio, 3),
            "expected_minimum_detection_ratio": 100.0,
        }
    )


DEMO_TARGETS = [
    ("D01", "body", "font.eastAsia", "SimHei", "SimSun", 0),
    ("D02", "heading_1", "font.size_pt", 18.0, 16.0, 0),
    ("D03", "body", "font.size_pt", 10.5, 12.0, 0),
    ("D04", "body", "font.bold", True, False, 0),
    ("D05", "body", "paragraph.alignment", "center", "both", None),
    ("D06", "body", "paragraph.line_spacing", 1.0, 1.5, None),
    ("D07", "body", "paragraph.first_line_indent_chars", 0.0, 2.0, None),
    ("D08", "body", "paragraph.space_before_pt", 12.0, 0.0, None),
    ("D09", "body", "paragraph.space_after_pt", 12.0, 0.0, None),
    ("D10", "section", "section.margin_top_mm", 20.0, 25.4, None),
]
DEMO_ANCHORS = {
    "D01": "DEMO_PAGE_01_FONT_EASTASIA 中文字体目标：这是第一页的公开假想正文。",
    "D02": "DEMO_PAGE_02_HEADING_SIZE 标题字号目标",
    "D03": "DEMO_PAGE_03_BODY_SIZE 正文字号目标：用于核对 12 pt 正文规范。",
    "D04": "DEMO_PAGE_04_BOLD 粗体目标：用于核对正文非粗体规则。",
    "D05": "DEMO_PAGE_05_ALIGNMENT 对齐目标：用于核对两端对齐规则。",
    "D06": "DEMO_PAGE_06_LINE_SPACING 行距目标：用于核对 1.5 倍行距规则。",
    "D07": "DEMO_PAGE_07_FIRST_LINE 首行缩进目标：用于核对两字符缩进规则。",
    "D08": "DEMO_PAGE_08_SPACE_BEFORE 段前距目标：用于核对 0 pt 段前距规则。",
    "D09": "DEMO_PAGE_09_SPACE_AFTER 段后距目标：用于核对 0 pt 段后距规则。",
    "D10": "DEMO_PAGE_10_SECTION_MARGIN 节上边距目标：全文唯一节的锚点。",
}


def demo_expectation(compliant: bool, target: tuple[Any, ...]) -> dict[str, Any]:
    target_id, selector, property_name, wrong, expected, run_index = target
    actual = expected if compliant else wrong
    return expectation(
        target_id,
        selector,
        property_name,
        DEMO_ANCHORS[target_id],
        actual,
        expected,
        "COMPLIANT" if compliant else "VIOLATION",
        run_index,
        fixable=False if compliant else True,
        locatable=True,
        expected_origin="DIRECT",
    )


def build_demo(compliant: bool, asset: Path) -> tuple[Document, list[dict[str, Any]]]:
    document = new_document(top=25.4 if compliant else 20.0)
    targets: list[dict[str, Any]] = []
    target_by_page = {index + 1: target for index, target in enumerate(DEMO_TARGETS)}
    for page in range(1, 11):
        target = target_by_page[page]
        target_id = target[0]
        if page != 2:
            add_heading(document, f"演示文档 第 {page:02d} 页：公开假想研究笔记")
        if page == 1:
            add_paragraph(document, DEMO_ANCHORS[target_id], **{"font.eastAsia": "SimHei"} if not compliant else {})
            paragraph, _ = add_paragraph(document, "DEMO_LINK_PARAGRAPH 公开超链接：")
            add_hyperlink(paragraph, "Example Public Website", "https://example.com/alinea-demo")
        elif page == 2:
            add_heading(document, DEMO_ANCHORS[target_id], **{"font.size_pt": 18.0} if not compliant else {})
            add_paragraph(document, "第二页正文保持合规，标题是唯一目标。")
        elif page == 3:
            add_paragraph(document, DEMO_ANCHORS[target_id], **{"font.size_pt": 10.5} if not compliant else {})
        elif page == 4:
            add_paragraph(document, DEMO_ANCHORS[target_id], **{"font.bold": True} if not compliant else {})
        elif page == 5:
            add_paragraph(document, DEMO_ANCHORS[target_id], **{"paragraph.alignment": "center"} if not compliant else {})
        elif page == 6:
            add_paragraph(document, DEMO_ANCHORS[target_id], **{"paragraph.line_spacing": 1.0} if not compliant else {})
        elif page == 7:
            add_paragraph(document, DEMO_ANCHORS[target_id], **{"paragraph.first_line_indent_chars": 0.0} if not compliant else {})
        elif page == 8:
            add_paragraph(document, DEMO_ANCHORS[target_id], **{"paragraph.space_before_pt": 12.0} if not compliant else {})
            add_table(document, [["DEMO_TABLE_ANCHOR", "Synthetic value"], ["中文单元格", "English cell"]])
        elif page == 9:
            add_paragraph(document, DEMO_ANCHORS[target_id], **{"paragraph.space_after_pt": 12.0} if not compliant else {})
            add_image(document, asset, width_mm=55)
            add_caption(document, "DEMO_IMAGE_CAPTION 确定性几何图，不含敏感信息。")
        elif page == 10:
            add_paragraph(document, DEMO_ANCHORS[target_id])
            add_paragraph(document, "DEMO_FINAL_PARAGRAPH 对照文档保留完全相同的正文与媒体内容。")
        targets.append(demo_expectation(compliant, target))
        if page < 10:
            break_paragraph = document.add_paragraph()
            break_run = break_paragraph.add_run()
            break_run.add_break(WD_BREAK.PAGE)
    return document, targets


GUIDELINE_LINES = [
    "ALINEA IMAGINARY FORMAT GUIDELINE - SYNTHETIC E2E DATA ONLY",
    "",
    "This is an imaginary guideline created only for software testing.",
    "It is not a university, publisher, employer, or government requirement.",
    "All expected values originate in tests/fixtures/generate_fixtures.py.",
    "",
    "BODY: East Asian font SimSun; Latin font Times New Roman; 12 pt; not bold.",
    "BODY: justified alignment; first-line indent 2.0 characters; 1.5 line spacing.",
    "BODY: space before 0 pt; space after 0 pt.",
    "HEADING 1: East Asian font SimHei; Latin font Arial; 16 pt; bold.",
    "HEADING 1: left aligned; first-line indent 0; 1.5 line spacing.",
    "HEADING 1: space before 12 pt; space after 6 pt.",
    "CAPTION: SimSun / Times New Roman; 10.5 pt; centered; single spacing.",
    "TABLE TEXT: SimSun / Times New Roman; 10.5 pt; left aligned; single spacing.",
    "SECTION: A4; top, bottom, left, and right margins all 25.4 mm.",
    "",
    "The ten deliberate demo deviations are D01 through D10:",
    "D01 body East Asian font SimHei instead of SimSun.",
    "D02 heading 1 size 18 pt instead of 16 pt.",
    "D03 body size 10.5 pt instead of 12 pt.",
    "D04 body bold true instead of false.",
    "D05 body centered instead of justified.",
    "D06 body single spacing instead of 1.5 spacing.",
    "D07 body first-line indent 0 instead of 2 characters.",
    "D08 body space before 12 pt instead of 0 pt.",
    "D09 body space after 12 pt instead of 0 pt.",
    "D10 section top margin 20 mm instead of 25.4 mm.",
    "",
    "No rendered page index, bounding box, or manual Word verification is implied.",
]


def write_guideline() -> None:
    EXAMPLES_ROOT.mkdir(parents=True, exist_ok=True)
    EXAMPLES_ROOT.joinpath("guideline.txt").write_text("\n".join(GUIDELINE_LINES) + "\n", encoding="utf-8", newline="\n")
    path = EXAMPLES_ROOT / "guideline.pdf"
    pdf = canvas.Canvas(str(path), pagesize=A4, invariant=1, pageCompression=1)
    pdf.setTitle("Alinea Imaginary Format Guideline")
    pdf.setAuthor("Alinea Fixture Generator")
    width, height = A4
    y = height - 54
    for index, line in enumerate(GUIDELINE_LINES):
        if y < 54:
            pdf.showPage()
            y = height - 54
        pdf.setFont("Helvetica-Bold" if index == 0 else "Helvetica", 11 if index == 0 else 9.5)
        pdf.drawString(54, y, line)
        y -= 15
    pdf.save()


def build_examples(asset: Path) -> None:
    demo, demo_targets = build_demo(False, asset)
    save_document(demo, EXAMPLES_ROOT / "alinea-demo.docx")
    compliant, compliant_targets = build_demo(True, asset)
    save_document(compliant, EXAMPLES_ROOT / "alinea-demo-compliant.docx")
    write_guideline()
    golden = {
        "schema_version": "1.0",
        "document": "alinea-demo.docx",
        "compliant_document": "alinea-demo-compliant.docx",
        "guideline": ["guideline.txt", "guideline.pdf"],
        "source_of_truth": "KNOWN_GENERATOR_INPUT_NO_MANUAL_WORD_VERIFICATION",
        "unit_serialization_policy": "actual/expected are generator inputs in property units. Section lengths are stored as twips; compare raw XML or allow 0.01 mm round-trip quantization (20 mm becomes 1134 twips = 20.0025 mm).",
        "target_count": 10,
        "expected_issue_count": 0 if any(t["status"] != "VIOLATION" for t in demo_targets) else 10,
        "explicit_page_breaks": 9,
        "logical_page_blocks": 10,
        "rendering": rendering_pending("Nine explicit page breaks define ten logical blocks; rendered page count is not asserted here."),
        "targets": demo_targets,
        "compliant_expectations": compliant_targets,
        "preservation_expectations": {
            "text_sequence_identical_to_compliant": True,
            "embedded_media_hashes_identical_to_compliant": True,
            "only_approved_xml_properties_may_change": True,
        },
    }
    write_json(DEMO_GOLDEN_PATH, golden)


def build_manifest() -> None:
    manifest = {
        "schema_version": "1.0",
        "generator": "tests/fixtures/generate_fixtures.py",
        "generator_version": "1.0",
        "truth_source": "KNOWN_GENERATOR_INPUT_NO_MANUAL_WORD_VERIFICATION",
        "manual_microsoft_word_verified": False,
        "deterministic_metadata_timestamp": "2024-01-01T00:00:00Z",
        "zip_timestamp_policy": "Fixed to 2024-01-01 00:00:00; entries sorted by part name.",
        "sample_count": 30,
        "expected_category_counts": CATEGORY_COUNTS,
        "category_names_zh": CATEGORY_ZH,
        "rule_set_id": "alinea-imaginary-fixture-rules-v1",
        "rule_baseline": {
            "body": BODY,
            "heading_1": HEADING,
            "caption": CAPTION,
            "table_text": TABLE_TEXT,
            "section": SECTION,
        },
        "expectation_scope": "All listed properties are asserted; unlisted properties are not golden detection targets.",
        "location_policy": "locatable describes text-anchor eligibility only. No page index or rectangle is ground truth until rendering.",
        "unit_serialization_policy": "actual/expected are generator inputs in property units. Section lengths are stored as twips; compare raw XML or allow 0.01 mm round-trip quantization.",
        "security_error_policy": "Top-level API error is INVALID_DOCX; reason_code distinguishes deterministic validation failures. H06 may report reason codes in any order.",
        "samples": SAMPLES,
    }
    write_json(MANIFEST_PATH, manifest)


def all_paragraphs(document: Document) -> list[Any]:
    from docx.text.paragraph import Paragraph

    return [Paragraph(element, document) for element in document.element.body.iter(qn("w:p"))]


def validate_anchor(document: Document, item: dict[str, Any]) -> None:
    paragraphs = all_paragraphs(document)
    text_anchor = item["paragraph_text_anchor"]
    matches = [p for p in paragraphs if text_anchor in p.text]
    if not matches:
        raise AssertionError(f"Anchor not found: {text_anchor!r}")
    if item.get("unique", True) and len(matches) != 1:
        raise AssertionError(f"Anchor is not unique: {text_anchor!r}")


def validate_docx_sample(record: dict[str, Any], path: Path) -> str:
    if record["reopen_expectation"] == "SECURITY_REJECT_BEFORE_REOPEN":
        with zipfile.ZipFile(path) as archive:
            names = set(archive.namelist())
            if "../alinea-safe-boundary-marker.txt" not in names:
                raise AssertionError("H06 traversal metadata is missing")
            info = archive.getinfo("word/alinea-compression-ratio.txt")
            if info.file_size / info.compress_size <= 100:
                raise AssertionError("H06 compression ratio is not beyond the fixture threshold")
        return "SECURITY_REJECT"
    if record["reopen_expectation"] == "REOPEN_ERROR":
        try:
            Document(path)
        except Exception as error:
            return type(error).__name__
        raise AssertionError(f"Expected reopen failure: {path}")
    document = Document(path)
    for item in record["paragraph_anchors"]:
        validate_anchor(document, item)
    for item in record["expectations"]:
        validate_anchor(document, item)
        if item["status"] not in {"SKIPPED", "UNVERIFIABLE"} and item["run_index"] is not None:
            paragraph = next(p for p in all_paragraphs(document) if item["paragraph_text_anchor"] in p.text)
            if item["run_index"] >= len(paragraph.runs):
                raise AssertionError(f"Run index missing for {record['sample_id']}: {item['target_id']}")
    return "REOPEN_OK"


def media_hashes(document: Document) -> dict[str, str]:
    result = {}
    for part in document.part.package.parts:
        if str(part.partname).startswith("/word/media/"):
            result[str(part.partname)] = sha256_bytes(part.blob)
    return result


def validate_outputs() -> dict[str, Any]:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    samples = manifest["samples"]
    if len(samples) != 30:
        raise AssertionError(f"Expected 30 samples, found {len(samples)}")
    counts = Counter(sample["category"] for sample in samples)
    if dict(counts) != CATEGORY_COUNTS:
        raise AssertionError(f"Category mismatch: {dict(counts)}")
    if len({sample["sample_id"] for sample in samples}) != 30:
        raise AssertionError("Duplicate sample IDs")
    if len({sample["file"] for sample in samples}) != 30:
        raise AssertionError("Duplicate sample paths")
    reopen_results = {}
    for sample in samples:
        if sample["category"] == "single_property_error":
            if sample["expected_issue_count"] != 1 or len(sample["expectations"]) != 1:
                raise AssertionError(f"Not a strict single-property case: {sample['sample_id']}")
        if sample["category"] == "multi_property_error" and sample["expected_issue_count"] < 2:
            raise AssertionError(f"Not a multi-property case: {sample['sample_id']}")
        if sample["category"] == "normal" and sample["expected_issue_count"] != 0:
            raise AssertionError(f"Normal case contains a violation: {sample['sample_id']}")
        for item in sample["expectations"]:
            if item["property"] not in FORMAT_PROPERTIES or item["selector"] not in SELECTORS:
                raise AssertionError(f"Contract property/selector mismatch: {item}")
            if item["status"] == "VIOLATION" and item["actual"] == item["expected"]:
                raise AssertionError(f"Violation without a difference: {item['target_id']}")
            if item["status"] == "COMPLIANT" and item["actual"] != item["expected"]:
                raise AssertionError(f"Compliant value mismatch: {item['target_id']}")
            if item["status"] in {"UNVERIFIABLE", "SKIPPED"} and not item["expected_skip_reason"]:
                raise AssertionError(f"Missing skip reason: {item['target_id']}")
        path = FIXTURE_ROOT / sample["file"]
        if not path.is_file():
            raise AssertionError(f"Missing sample: {path}")
        if path.stat().st_size != sample["file_size_bytes"] or sha256_file(path) != sample["file_sha256"]:
            raise AssertionError(f"Manifest hash/size mismatch: {path}")
        reopen_results[sample["sample_id"]] = validate_docx_sample(sample, path)

    demo_golden = json.loads(DEMO_GOLDEN_PATH.read_text(encoding="utf-8"))
    if demo_golden["target_count"] != 10 or len(demo_golden["targets"]) != 10:
        raise AssertionError("Demo must have exactly ten targets")
    if len({item["target_id"] for item in demo_golden["targets"]}) != 10:
        raise AssertionError("Demo target IDs are not unique")
    demo = Document(EXAMPLES_ROOT / "alinea-demo.docx")
    compliant = Document(EXAMPLES_ROOT / "alinea-demo-compliant.docx")
    demo_text = [p.text for p in all_paragraphs(demo)]
    compliant_text = [p.text for p in all_paragraphs(compliant)]
    if demo_text != compliant_text:
        raise AssertionError("Demo and compliant text sequences differ")
    if media_hashes(demo) != media_hashes(compliant) or not media_hashes(demo):
        raise AssertionError("Demo and compliant media hashes differ or are empty")
    demo_breaks = len(list(demo.element.body.iter(qn("w:br"))))
    compliant_breaks = len(list(compliant.element.body.iter(qn("w:br"))))
    if demo_breaks != 9 or compliant_breaks != 9:
        raise AssertionError("Demo documents must contain exactly nine explicit page breaks")
    for target in demo_golden["targets"]:
        validate_anchor(demo, target)
        if target["property"] not in FORMAT_PROPERTIES or target["selector"] not in SELECTORS:
            raise AssertionError(f"Invalid demo target: {target}")
    for target in demo_golden["compliant_expectations"]:
        validate_anchor(compliant, target)
    for name in ("guideline.txt", "guideline.pdf"):
        if not EXAMPLES_ROOT.joinpath(name).is_file():
            raise AssertionError(f"Missing {name}")
    pdf_bytes = EXAMPLES_ROOT.joinpath("guideline.pdf").read_bytes()
    if not pdf_bytes.startswith(b"%PDF-") or b"%%EOF" not in pdf_bytes[-64:]:
        raise AssertionError("Guideline PDF signature/EOF is invalid")
    with Image.open(ASSET_ROOT / "alinea-grid.png") as image:
        image.verify()
    return {
        "samples": len(samples),
        "category_counts": dict(counts),
        "docx_reopened": sum(value == "REOPEN_OK" for value in reopen_results.values()),
        "expected_reopen_failures": sum(value != "REOPEN_OK" and value != "SECURITY_REJECT" for value in reopen_results.values()),
        "expected_security_rejections": sum(value == "SECURITY_REJECT" for value in reopen_results.values()),
        "demo_targets": len(demo_golden["targets"]),
        "demo_explicit_page_breaks": demo_breaks,
        "demo_media_parts": len(media_hashes(demo)),
        "json_files_validated": 2,
    }


def generate() -> dict[str, Any]:
    SAMPLES.clear()
    DATA_ROOT.mkdir(parents=True, exist_ok=True)
    GOLDEN_ROOT.mkdir(parents=True, exist_ok=True)
    EXAMPLES_ROOT.mkdir(parents=True, exist_ok=True)
    asset = build_asset()
    build_normal(asset)
    build_single_property_errors()
    build_multi_property_errors()
    build_structural_edges(asset)
    build_high_risk(asset)
    build_examples(asset)
    build_manifest()
    return validate_outputs()


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate deterministic, non-sensitive Alinea DOCX fixtures.")
    parser.add_argument("--validate-only", action="store_true", help="Validate existing binaries and golden JSON without regenerating.")
    args = parser.parse_args()
    summary = validate_outputs() if args.validate_only else generate()
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
