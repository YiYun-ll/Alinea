from __future__ import annotations

import hashlib
import zipfile
from io import BytesIO

import pytest
from alinea_docx import parse_docx, parse_xml, text_sha256
from docx import Document
from docx.enum.style import WD_STYLE_TYPE
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.opc.constants import RELATIONSHIP_TYPE as RT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Mm, Pt
from lxml import etree

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
CT_NS = "http://schemas.openxmlformats.org/package/2006/content-types"
PKG_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
FOOTNOTES_CONTENT_TYPE = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.footnotes+xml"
)


def _document_bytes(document: Document) -> bytes:
    output = BytesIO()
    document.save(output)
    return output.getvalue()


def _set_fonts(style: object, *, ascii_font: str, east_asia: str) -> None:
    r_pr = style.element.get_or_add_rPr()
    fonts = r_pr.find(qn("w:rFonts"))
    if fonts is None:
        fonts = OxmlElement("w:rFonts")
        r_pr.insert(0, fonts)
    fonts.set(qn("w:ascii"), ascii_font)
    fonts.set(qn("w:hAnsi"), ascii_font)
    fonts.set(qn("w:eastAsia"), east_asia)
    for attribute in ("asciiTheme", "hAnsiTheme", "eastAsiaTheme"):
        fonts.attrib.pop(qn(f"w:{attribute}"), None)


def _ppr_child(p_pr: etree._Element, name: str) -> etree._Element:
    child = p_pr.find(qn(f"w:{name}"))
    if child is None:
        child = OxmlElement(f"w:{name}")
        p_pr.append(child)
    return child


def _clear_doc_default_run_properties(document: Document) -> etree._Element:
    defaults = document.styles.element.find(qn("w:docDefaults"))
    assert defaults is not None
    r_pr = defaults.find(f"{qn('w:rPrDefault')}/{qn('w:rPr')}")
    assert r_pr is not None
    for child in list(r_pr):
        r_pr.remove(child)
    normal_r_pr = document.styles["Normal"].element.find(qn("w:rPr"))
    if normal_r_pr is not None:
        document.styles["Normal"].element.remove(normal_r_pr)
    return r_pr


def _add_footnotes(data: bytes) -> bytes:
    replacements: dict[str, bytes] = {}
    with zipfile.ZipFile(BytesIO(data)) as source:
        content_types = parse_xml(source.read("[Content_Types].xml"))
        override = etree.SubElement(content_types, f"{{{CT_NS}}}Override")
        override.set("PartName", "/word/footnotes.xml")
        override.set("ContentType", FOOTNOTES_CONTENT_TYPE)
        replacements["[Content_Types].xml"] = etree.tostring(
            content_types, xml_declaration=True, encoding="UTF-8", standalone=True
        )

        rels = parse_xml(source.read("word/_rels/document.xml.rels"))
        relationship = etree.SubElement(rels, f"{{{PKG_REL_NS}}}Relationship")
        relationship.set("Id", "rIdFootnotesTest")
        relationship.set(
            "Type",
            "http://schemas.openxmlformats.org/officeDocument/2006/relationships/footnotes",
        )
        relationship.set("Target", "footnotes.xml")
        replacements["word/_rels/document.xml.rels"] = etree.tostring(
            rels, xml_declaration=True, encoding="UTF-8", standalone=True
        )

        output = BytesIO()
        with zipfile.ZipFile(output, "w") as target:
            for info in source.infolist():
                target.writestr(info, replacements.get(info.filename, source.read(info.filename)))
            footnotes = parse_xml(
                f"""<w:footnotes xmlns:w="{W_NS}">
                  <w:footnote w:id="1"><w:p><w:r><w:t>Footnote text</w:t></w:r></w:p></w:footnote>
                </w:footnotes>""".encode()
            )
            target.writestr(
                "word/footnotes.xml",
                etree.tostring(footnotes, xml_declaration=True, encoding="UTF-8", standalone=True),
            )
    return output.getvalue()


def test_doc_defaults_and_unset_properties_are_explicit() -> None:
    document = Document()
    r_pr = _clear_doc_default_run_properties(document)
    fonts = OxmlElement("w:rFonts")
    fonts.set(qn("w:ascii"), "Default Latin")
    fonts.set(qn("w:eastAsia"), "Default East Asia")
    size = OxmlElement("w:sz")
    size.set(qn("w:val"), "20")
    r_pr.append(fonts)
    r_pr.append(size)
    plain = document.styles.add_style("Plain", WD_STYLE_TYPE.PARAGRAPH)
    paragraph = document.add_paragraph(style=plain)
    paragraph.add_run("plain text")

    snapshot = parse_docx(_document_bytes(document))
    effective = snapshot.paragraphs[0].runs[0].effective

    assert effective["font.ascii"].value == "Default Latin"
    assert effective["font.eastAsia"].value == "Default East Asia"
    assert effective["font.size_pt"].value == 10
    assert effective["font.size_pt"].origin == "DOC_DEFAULT"
    assert effective["font.bold"].status == "UNRESOLVED"

    for child in list(r_pr):
        r_pr.remove(child)
    unresolved = parse_docx(_document_bytes(document)).paragraphs[0].runs[0].effective
    assert unresolved["font.ascii"].status == "UNRESOLVED"
    assert unresolved["font.eastAsia"].status == "UNRESOLVED"
    assert unresolved["font.size_pt"].status == "UNRESOLVED"
    assert unresolved["font.size_pt"].value is None


def test_based_on_chain_direct_overrides_units_and_provenance() -> None:
    document = Document()
    base = document.styles.add_style("BaseBody", WD_STYLE_TYPE.PARAGRAPH)
    base.base_style = document.styles["Normal"]
    _set_fonts(base, ascii_font="Times New Roman", east_asia="宋体")
    base.font.size = Pt(12)
    base.font.bold = True
    base_p_pr = base.element.get_or_add_pPr()
    _ppr_child(base_p_pr, "jc").set(qn("w:val"), "center")
    indentation = _ppr_child(base_p_pr, "ind")
    for name, value in {
        "firstLineChars": "200",
        "firstLine": "567",
        "left": "1440",
        "right": "720",
    }.items():
        indentation.set(qn(f"w:{name}"), value)
    spacing = _ppr_child(base_p_pr, "spacing")
    for name, value in {
        "line": "360",
        "lineRule": "auto",
        "before": "240",
        "after": "120",
    }.items():
        spacing.set(qn(f"w:{name}"), value)

    derived = document.styles.add_style("DerivedBody", WD_STYLE_TYPE.PARAGRAPH)
    derived.base_style = base
    derived_p_pr = derived.element.get_or_add_pPr()
    _ppr_child(derived_p_pr, "jc").set(qn("w:val"), "right")
    derived_spacing = _ppr_child(derived_p_pr, "spacing")
    derived_spacing.set(qn("w:line"), "280")
    derived_spacing.set(qn("w:lineRule"), "exact")

    character_base = document.styles.add_style("CharBase", WD_STYLE_TYPE.CHARACTER)
    _set_fonts(character_base, ascii_font="Character Latin", east_asia="Character East Asia")
    character_base.font.size = Pt(11)
    character_derived = document.styles.add_style("CharDerived", WD_STYLE_TYPE.CHARACTER)
    character_derived.base_style = character_base
    character_derived.font.size = Pt(12.5)

    paragraph = document.add_paragraph(style=derived)
    paragraph.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.LEFT
    inherited_run = paragraph.add_run("中文 ABC")
    direct_fonts = OxmlElement("w:rFonts")
    direct_fonts.set(qn("w:eastAsia"), "黑体")
    inherited_run._r.get_or_add_rPr().insert(0, direct_fonts)
    override_run = paragraph.add_run("override")
    override_run.font.size = Pt(13)
    override_run.font.bold = False
    override_run.font.name = "Arial"
    character_run = paragraph.add_run("character")
    character_run.style = character_derived

    section = document.sections[0]
    section.top_margin = Mm(25)
    section.bottom_margin = Mm(30)
    section.left_margin = Mm(20)
    section.right_margin = Mm(18)
    section.page_width = Mm(210)
    section.page_height = Mm(297)

    snapshot = parse_docx(_document_bytes(document), revision_id="rev_test")
    indexed = snapshot.paragraphs[0]
    first = indexed.runs[0].effective
    second = indexed.runs[1].effective
    third = indexed.runs[2].effective

    assert first["font.eastAsia"].value == "黑体"
    assert first["font.eastAsia"].origin == "DIRECT"
    assert first["font.ascii"].value == "Times New Roman"
    assert first["font.ascii"].origin == "BASED_ON"
    assert first["font.size_pt"].value == 12
    assert first["font.bold"].value is True
    assert first["font.ascii"].provenance
    assert second["font.size_pt"].value == 13
    assert second["font.size_pt"].origin == "DIRECT"
    assert second["font.bold"].value is False
    assert second["font.ascii"].value == "Arial"
    assert third["font.size_pt"].value == 12.5
    assert third["font.size_pt"].origin == "CHARACTER_STYLE"
    assert third["font.ascii"].value == "Character Latin"
    assert third["font.ascii"].origin == "BASED_ON"
    assert third["font.eastAsia"].value == "Character East Asia"

    paragraph_format = indexed.effective
    assert paragraph_format["paragraph.alignment"].value == "left"
    assert paragraph_format["paragraph.first_line_indent_chars"].value == 2
    assert paragraph_format["paragraph.first_line_indent_mm"].value == pytest.approx(10.00125)
    assert paragraph_format["paragraph.left_indent_mm"].value == pytest.approx(25.4)
    assert paragraph_format["paragraph.right_indent_mm"].value == pytest.approx(12.7)
    assert paragraph_format["paragraph.line_spacing"].value == {
        "kind": "EXACT",
        "value": 14,
        "unit": "pt",
    }
    assert paragraph_format["paragraph.space_before_pt"].value == 12
    assert paragraph_format["paragraph.space_after_pt"].value == 6
    assert len(paragraph_format["paragraph.line_spacing"].provenance) >= 2

    section_format = snapshot.sections[0].effective
    assert section_format["section.margin_top_mm"].value == pytest.approx(25, abs=0.01)
    assert section_format["section.margin_bottom_mm"].value == pytest.approx(30, abs=0.01)
    assert section_format["section.margin_left_mm"].value == pytest.approx(20, abs=0.01)
    assert section_format["section.margin_right_mm"].value == pytest.approx(18, abs=0.01)
    assert section_format["section.page_width_mm"].value == pytest.approx(210, abs=0.01)
    assert section_format["section.page_height_mm"].value == pytest.approx(297, abs=0.01)


def test_line_spacing_multiple_exact_and_at_least() -> None:
    document = Document()
    for line, rule in (("360", "auto"), ("240", "exact"), ("360", "atLeast")):
        paragraph = document.add_paragraph(f"{rule} spacing")
        spacing = _ppr_child(paragraph._p.get_or_add_pPr(), "spacing")
        spacing.set(qn("w:line"), line)
        spacing.set(qn("w:lineRule"), rule)

    paragraphs = parse_docx(_document_bytes(document)).paragraphs

    assert paragraphs[0].effective["paragraph.line_spacing"].value == {
        "kind": "MULTIPLE",
        "value": 1.5,
    }
    assert paragraphs[1].effective["paragraph.line_spacing"].value == {
        "kind": "EXACT",
        "value": 12,
        "unit": "pt",
    }
    assert paragraphs[2].effective["paragraph.line_spacing"].value == {
        "kind": "AT_LEAST",
        "value": 18,
        "unit": "pt",
    }


def test_unknown_theme_fonts_never_fall_back_to_invented_names() -> None:
    document = Document()
    run = document.add_paragraph().add_run("themed")
    fonts = OxmlElement("w:rFonts")
    fonts.set(qn("w:ascii"), "MustNotMaskTheme")
    fonts.set(qn("w:asciiTheme"), "unknownThemeToken")
    fonts.set(qn("w:eastAsiaTheme"), "majorEastAsia")
    run._r.get_or_add_rPr().insert(0, fonts)

    effective = parse_docx(_document_bytes(document)).paragraphs[0].runs[0].effective

    assert effective["font.ascii"].status == "UNRESOLVED"
    assert effective["font.ascii"].value is None
    assert effective["font.ascii"].origin == "THEME"
    assert effective["font.eastAsia"].status == "UNRESOLVED"
    assert effective["font.eastAsia"].value is None


def test_real_block_order_story_parts_hyperlink_runs_roles_and_hashes() -> None:
    document = Document()
    document.add_paragraph("Before")
    table = document.add_table(rows=1, cols=2)
    table.cell(0, 0).text = "Cell A"
    table.cell(0, 1).text = "Cell B"
    document.add_paragraph("1.1 Section heading")
    document.add_paragraph("图 1-1 Caption")
    document.add_paragraph("[1] Reference entry")
    hyperlink_paragraph = document.add_paragraph("Link ")
    relationship_id = document.part.relate_to(
        "https://example.invalid", RT.HYPERLINK, is_external=True
    )
    hyperlink = OxmlElement("w:hyperlink")
    hyperlink.set(qn("r:id"), relationship_id)
    run = OxmlElement("w:r")
    text = OxmlElement("w:t")
    text.text = "Linked"
    run.append(text)
    hyperlink.append(run)
    hyperlink_paragraph._p.append(hyperlink)
    document.sections[0].header.paragraphs[0].text = "Header text"
    document.sections[0].footer.paragraphs[0].text = "Footer text"

    snapshot = parse_docx(_add_footnotes(_document_bytes(document)))

    main = [p for p in snapshot.paragraphs if p.element_ref.part_uri == "/word/document.xml"]
    assert [p.text for p in main] == [
        "Before",
        "Cell A",
        "Cell B",
        "1.1 Section heading",
        "图 1-1 Caption",
        "[1] Reference entry",
        "Link Linked",
    ]
    assert [p.element_ref.paragraph_ordinal for p in snapshot.paragraphs] == list(
        range(len(snapshot.paragraphs))
    )
    assert all(p.element_ref.xml_path.startswith("/") for p in snapshot.paragraphs)
    assert main[1].inside_table
    assert main[1].semantic_role == "table_text"
    assert {"tbl:0", "tr:0", "tc:0"} <= set(main[1].element_ref.container_path)
    assert main[3].semantic_role == "heading_2"
    assert main[4].semantic_role == "caption"
    assert main[5].semantic_role == "reference"
    assert main[0].element_ref.context_after_sha256 == text_sha256("Cell A")
    assert main[0].element_ref.context_before_sha256 is None
    assert main[-1].runs[-1].text == "Linked"
    assert main[-1].runs[-1].effective["font.size_pt"].status == "RESOLVED"

    by_text = {p.text: p for p in snapshot.paragraphs}
    assert by_text["Header text"].element_ref.part_uri.startswith("/word/header")
    assert by_text["Footer text"].element_ref.part_uri.startswith("/word/footer")
    assert by_text["Footnote text"].element_ref.part_uri == "/word/footnotes.xml"
    assert snapshot.package_inventory["external_relationships"]

    run_refs = snapshot.package_inventory["run_element_refs"]
    assert len(run_refs) == sum(len(p.runs) for p in snapshot.paragraphs)
    linked_ref = next(
        item
        for item in run_refs
        if item["paragraph_ordinal"] == main[-1].element_ref.paragraph_ordinal
        and item["run_index"] == len(main[-1].runs) - 1
    )
    assert linked_ref["element_ref"]["run_range"] == {"start": 1, "end": 2}
    assert linked_ref["element_ref"]["text_sha256"] == "sha256:" + hashlib.sha256(
        b"Linked"
    ).hexdigest()
    assert linked_ref["element_ref"]["xml_path"].endswith("/w:r[1]")
    assert snapshot.fingerprints["part_text_raw:/word/footnotes.xml"]
