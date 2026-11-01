from __future__ import annotations

from pathlib import Path

from docx import Document
from docx.enum.section import WD_ORIENT, WD_SECTION
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.opc.constants import RELATIONSHIP_TYPE as RT
from docx.shared import Mm, Pt
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / "tests" / "fixtures" / "data" / "alinea-agent-complex.docx"
ASSET = ROOT / ".data" / "agent-fixtures" / "agent-complex-figure.png"


def set_run(run, east_asia="宋体", ascii_font="Times New Roman", size=12, bold=False):
    run.font.name = ascii_font
    run.font.size = Pt(size)
    run.font.bold = bold
    run._element.get_or_add_rPr().get_or_add_rFonts().set(qn("w:eastAsia"), east_asia)


def add_paragraph(document, text, style=None, size=12, bold=False):
    paragraph = document.add_paragraph(style=style)
    paragraph.paragraph_format.line_spacing = 1.5
    paragraph.paragraph_format.space_after = Pt(0)
    set_run(paragraph.add_run(text), size=size, bold=bold)
    return paragraph


def add_hyperlink(paragraph, text, url):
    relationship = paragraph.part.relate_to(url, RT.HYPERLINK, is_external=True)
    hyperlink = OxmlElement("w:hyperlink")
    hyperlink.set(qn("r:id"), relationship)
    run = paragraph.add_run(text)
    set_run(run)
    hyperlink.append(run._r)
    paragraph._p.append(hyperlink)


def add_page_field(paragraph):
    run = paragraph.add_run()
    begin = OxmlElement("w:fldChar")
    begin.set(qn("w:fldCharType"), "begin")
    instruction = OxmlElement("w:instrText")
    instruction.set(qn("xml:space"), "preserve")
    instruction.text = " PAGE "
    end = OxmlElement("w:fldChar")
    end.set(qn("w:fldCharType"), "end")
    run._r.extend([begin, instruction, end])


def add_equation(paragraph):
    math = OxmlElement("m:oMath")
    text = OxmlElement("m:t")
    text.text = "E=mc²"
    math.append(text)
    paragraph._p.append(math)


def build(output=OUTPUT):
    ASSET.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGB", (640, 260), "#f7f8fa")
    draw = ImageDraw.Draw(image)
    draw.rectangle((40, 40, 600, 220), outline="#4b6588", width=4)
    draw.line((80, 180, 230, 80, 370, 160, 560, 60), fill="#4b6588", width=5)
    image.save(ASSET)
    document = Document()
    normal = document.styles["Normal"]
    normal.font.name = "Times New Roman"
    normal.font.size = Pt(12)
    normal._element.get_or_add_rPr().get_or_add_rFonts().set(qn("w:eastAsia"), "宋体")
    section = document.sections[0]
    section.top_margin = Mm(25)
    section.bottom_margin = Mm(25)
    section.left_margin = Mm(30)
    section.right_margin = Mm(25)
    add_page_field(section.footer.paragraphs[0])
    cover = add_paragraph(document, "复杂论文格式智能体验证样例", size=22, bold=True)
    cover.alignment = WD_ALIGN_PARAGRAPH.CENTER
    add_paragraph(document, "基于真实高校模板结构的合成测试文档", size=14).alignment = WD_ALIGN_PARAGRAPH.CENTER
    add_paragraph(document, "学院：计算机学院\n专业：软件工程\n作者：脱敏样例", size=14)
    document.add_page_break()
    add_paragraph(document, "摘  要", style="Heading 1", size=16, bold=True)
    add_paragraph(document, "本文构造包含多种 WordprocessingML 对象的论文样例，用于验证智能体只通过受限工具分析文档。")
    add_paragraph(document, "关键词：格式检查；智能体；复杂文档")
    add_paragraph(document, "Abstract", style="Heading 1", size=16, bold=True)
    add_paragraph(document, "This synthetic thesis exercises headings, tables, fields, links and mixed formatting.")
    document.add_page_break()
    add_paragraph(document, "第1章 绪论", style="Heading 1", size=16, bold=True)
    add_paragraph(document, "1.1 研究背景", style="Heading 2", size=14, bold=True)
    body = add_paragraph(document, "论文正文通常同时包含中文与 English text，并继承文档默认样式和段落样式。")
    set_run(body.add_run(" 此处为故意设置的 10.5 pt 混排。"), size=10.5)
    add_paragraph(document, "1.1.1 研究问题", style="Heading 3", size=12, bold=True)
    add_paragraph(document, "智能体可以建议操作，但格式事实、修复资格和最终质量结论必须由确定性工具给出。")
    add_paragraph(document, "第2章 复杂对象", style="Heading 1", size=16, bold=True)
    add_paragraph(document, "2.1 图、表与公式", style="Heading 2", size=14, bold=True)
    document.add_picture(str(ASSET), width=Mm(130))
    add_paragraph(document, "图2-1 复杂格式处理流程", size=10.5).alignment = WD_ALIGN_PARAGRAPH.CENTER
    add_paragraph(document, "表2-1 检测结果对照", size=10.5).alignment = WD_ALIGN_PARAGRAPH.CENTER
    table = document.add_table(rows=4, cols=3)
    table.style = "Table Grid"
    values = [
        ["对象", "检查", "修复"],
        ["普通正文", "支持", "审批后支持"],
        ["合并单元格", "保留结构", "人工复核"],
        ["公式与域", "只读诊断", "不自动修复"],
    ]
    for row, row_values in zip(table.rows, values):
        for cell, value in zip(row.cells, row_values):
            set_run(cell.paragraphs[0].add_run(value), size=10.5)
    table.cell(2, 1).merge(table.cell(2, 2))
    equation = add_paragraph(document, "公式示例：")
    add_equation(equation)
    hyperlink = add_paragraph(document, "公开参考链接：")
    add_hyperlink(hyperlink, "Example", "https://example.com/alinea-agent-complex")
    landscape = document.add_section(WD_SECTION.NEW_PAGE)
    landscape.orientation = WD_ORIENT.LANDSCAPE
    landscape.page_width, landscape.page_height = landscape.page_height, landscape.page_width
    add_paragraph(document, "第3章 跨节版式", style="Heading 1", size=16, bold=True)
    add_paragraph(document, "本节使用横向页面，验证 Agent 返回结构摘要时保留分节信息。")
    portrait = document.add_section(WD_SECTION.NEW_PAGE)
    portrait.orientation = WD_ORIENT.PORTRAIT
    portrait.page_width, portrait.page_height = portrait.page_height, portrait.page_width
    add_paragraph(document, "参考文献", style="Heading 1", size=16, bold=True)
    for index in range(1, 6):
        add_paragraph(document, f"[{index}] 作者. 文档格式验证研究[J]. 软件学报, 2025, 36({index}): 100-110.", size=10.5)
    add_paragraph(document, "附  录", style="Heading 1", size=16, bold=True)
    add_paragraph(document, "附录正文保留一段低置信文本，供角色建议工具进行有限分析。")
    output.parent.mkdir(parents=True, exist_ok=True)
    document.save(output)
    return output


if __name__ == "__main__":
    print(build())
