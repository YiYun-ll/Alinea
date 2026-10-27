from __future__ import annotations

import os
from pathlib import Path

import pytest
from alinea_mapping.locator import (
    LOCATION_METHOD,
    build_page_index,
    build_pdf_index,
    build_text_index,
    locate_issues,
    locate_paragraph,
    normalize,
    normalize_with_mapping,
)
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas


def synthetic_index(page_texts: list[str], chars_per_line: int = 1000):
    pages = []
    for page_index, text in enumerate(page_texts):
        chars = []
        for index, char in enumerate(text):
            line = index // chars_per_line
            column = index % chars_per_line
            x0 = 10 + column * 10
            top = 10 + line * 20
            chars.append(
                {
                    "text": char,
                    "x0": x0,
                    "top": top,
                    "x1": x0 + 8,
                    "bottom": top + 10,
                    "line_index": line,
                }
            )
        line_count = max(1, (len(text) + chars_per_line - 1) // chars_per_line)
        pages.append(
            build_page_index(
                page_index,
                chars_per_line * 10 + 20,
                line_count * 20 + 20,
                chars,
            )
        )
    return build_text_index(pages)


def make_pdf(path: Path, pages: list[list[str]]) -> None:
    document = canvas.Canvas(str(path), pagesize=(612, 792))
    for lines in pages:
        document.setFont("Helvetica", 11)
        for index, line in enumerate(lines):
            document.drawString(72, 730 - index * 24, line)
        document.showPage()
    document.save()


def test_normalize_nfkc_collapses_whitespace_and_preserves_source_mapping():
    normalized = normalize_with_mapping("  Ａ\u00a0 B\n")
    assert normalized.text == "A B"
    assert normalized.source_indices == (2, 3, 5)
    assert normalize("中文　全角Ａ") == "中文 全角A"
    assert normalize_with_mapping("ﬁx").source_indices == (0, 0, 1)
    composed = normalize_with_mapping("e\u0301")
    assert composed.text == "é"
    assert composed.source_indices == (0,)


def test_unique_paragraph_is_located_with_normalized_line_rects(paragraph_factory):
    paragraph = paragraph_factory("alpha unique omega")
    location = locate_paragraph(
        paragraph,
        synthetic_index([paragraph.text]),
        issue_id="issue-unique",
        preview_sha256="preview-sha",
        renderer_profile_id="profile-1",
    )
    assert location.status == "LOCATED"
    assert location.page_index == 0
    assert location.candidate_count == 1
    assert location.score == 1.0
    assert location.method == LOCATION_METHOD
    assert location.preview_pdf_sha256 == "preview-sha"
    assert location.renderer_profile_id == "profile-1"
    assert len(location.fragments) == 1
    assert location.fragments[0].page_size_pt == {"width": 10020.0, "height": 40.0}
    assert len(location.fragments[0].rects_normalized) == 1


def test_repeated_paragraph_without_context_is_ambiguous_without_rects(paragraph_factory):
    paragraph = paragraph_factory("repeated")
    location = locate_paragraph(
        paragraph,
        synthetic_index(["repeated then repeated"]),
    )
    assert location.status == "AMBIGUOUS"
    assert location.candidate_count == 2
    assert location.score == 1.0
    assert location.page_index is None
    assert location.fragments == []


def test_repeated_paragraph_uses_both_contexts_for_disambiguation(paragraph_factory):
    paragraph = paragraph_factory("repeated")
    pdf_index = synthetic_index(
        ["before one repeated after one before two repeated after two"]
    )
    first = locate_paragraph(
        paragraph,
        pdf_index,
        context_before="before one",
        context_after="after one",
    )
    second = locate_paragraph(
        paragraph,
        pdf_index,
        context_before="before two",
        context_after="after two",
    )
    assert first.status == "LOCATED"
    assert second.status == "LOCATED"
    assert second.candidate_count == 2
    assert second.score == 1.0
    first_rect = first.fragments[0].rects_normalized[0]
    second_rect = second.fragments[0].rects_normalized[0]
    assert second_rect[0] > first_rect[0]


def test_low_context_score_is_unlocated_without_rects(paragraph_factory):
    paragraph = paragraph_factory("target")
    location = locate_paragraph(
        paragraph,
        synthetic_index(["wrong target"]),
        context_before="expected",
    )
    assert location.status == "UNLOCATED"
    assert location.reason == "LOW_LOCATION_SCORE"
    assert location.score == pytest.approx(0.8)
    assert location.candidate_count == 1
    assert location.fragments == []


def test_missing_and_empty_text_are_unlocated(paragraph_factory):
    missing = locate_paragraph(paragraph_factory("missing"), synthetic_index(["present"]))
    empty = locate_paragraph(paragraph_factory(" \n"), synthetic_index(["present"]))
    assert missing.status == "UNLOCATED"
    assert missing.reason == "TEXT_NOT_FOUND"
    assert empty.status == "UNLOCATED"
    assert empty.reason == "EMPTY_PARAGRAPH_TEXT"


def test_cross_page_paragraph_returns_zero_based_fragments(paragraph_factory):
    text = "This paragraph continues across a page boundary"
    split = 25
    location = locate_paragraph(
        paragraph_factory(text),
        synthetic_index([text[:split], text[split:]], chars_per_line=18),
    )
    assert location.status == "LOCATED"
    assert location.page_index == 0
    assert [fragment.page_index for fragment in location.fragments] == [0, 1]
    assert all(fragment.rects_normalized for fragment in location.fragments)


def test_multiline_match_returns_one_rect_per_line(paragraph_factory):
    text = "abcdefghijklmnopqrstuvwxyz1234567890"
    location = locate_paragraph(
        paragraph_factory(text),
        synthetic_index([text], chars_per_line=10),
    )
    assert location.status == "LOCATED"
    rects = location.fragments[0].rects_normalized
    assert len(rects) == 4
    assert [rect[1] for rect in rects] == sorted(rect[1] for rect in rects)


def test_cjk_and_fullwidth_match_uses_synthetic_geometry_without_font(paragraph_factory):
    paragraph = paragraph_factory("中文 全角A")
    location = locate_paragraph(paragraph, synthetic_index(["中文　全角Ａ"]))
    assert location.status == "LOCATED"
    assert location.fragments[0].rects_normalized


def test_reportlab_ascii_pdf_builds_char_and_word_index(paragraph_factory, tmp_path):
    path = tmp_path / "ascii.pdf"
    text = "A unique PDF anchor for ascii extraction"
    make_pdf(path, [[text]])
    pdf_index = build_pdf_index(path)
    assert pdf_index.pages[0].chars
    assert any("unique" in word.text for word in pdf_index.pages[0].words)
    location = locate_paragraph(paragraph_factory(text), pdf_index)
    assert location.status == "LOCATED"
    assert location.page_index == 0


def test_locate_issues_binds_preview_and_does_not_mutate_input(
    paragraph_factory,
    snapshot_factory,
    issue_factory,
    tmp_path,
):
    path = tmp_path / "issues.pdf"
    texts = ["before one", "repeated", "after one", "before two", "repeated", "after two"]
    make_pdf(path, [texts])
    paragraphs = [paragraph_factory(text, index) for index, text in enumerate(texts)]
    snapshot = snapshot_factory(paragraphs)
    issue = issue_factory(paragraphs[4], "issue-second")
    result = locate_issues(snapshot, [issue], path, "preview-sha", "profile-1")
    assert result[0].location.status == "LOCATED"
    assert result[0].location.issue_id == "issue-second"
    assert result[0].location.candidate_count == 2
    assert result[0].location.preview_pdf_sha256 == "preview-sha"
    assert result[0].location.renderer_profile_id == "profile-1"
    assert issue.location.status == "PENDING"


def test_locate_issues_without_pdf_returns_not_rendered(
    paragraph_factory,
    snapshot_factory,
    issue_factory,
):
    paragraph = paragraph_factory("text")
    issue = issue_factory(paragraph)
    result = locate_issues(snapshot_factory([paragraph]), [issue], None, None, "profile-1")
    assert result[0].location.status == "NOT_RENDERED"
    assert result[0].location.fragments == []
    assert result[0].location.page_index is None


def _available_cjk_font() -> Path | None:
    windows = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
    candidates = [
        windows / "simhei.ttf",
        windows / "msyh.ttc",
        windows / "simsun.ttc",
        Path("/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc"),
    ]
    return next((path for path in candidates if path.is_file()), None)


CJK_FONT = _available_cjk_font()


@pytest.mark.skipif(CJK_FONT is None, reason="no reportlab-compatible CJK system font found")
def test_reportlab_cjk_pdf_when_system_font_is_available(paragraph_factory, tmp_path):
    assert CJK_FONT is not None
    font_name = "AlineaTestCJK"
    if CJK_FONT.suffix.lower() == ".ttc":
        pdfmetrics.registerFont(TTFont(font_name, str(CJK_FONT), subfontIndex=0))
    else:
        pdfmetrics.registerFont(TTFont(font_name, str(CJK_FONT)))
    path = tmp_path / "cjk.pdf"
    document = canvas.Canvas(str(path), pagesize=(612, 792))
    document.setFont(font_name, 12)
    text = "中文定位与全角Ａ测试"
    document.drawString(72, 730, text)
    document.save()
    location = locate_paragraph(paragraph_factory("中文定位与全角A测试"), build_pdf_index(path))
    assert location.status == "LOCATED"
