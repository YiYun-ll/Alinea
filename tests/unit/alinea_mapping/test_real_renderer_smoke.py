from __future__ import annotations

import os
import time
from pathlib import Path

import pytest
from alinea_mapping.locator import build_pdf_index, locate_issues
from alinea_mapping.renderer import LibreOfficeRenderer
from docx import Document

REAL_SOFFICE = Path("D:/桌面/Alinea/.tools/LibreOffice/program/soffice.com")


@pytest.mark.skipif(
    os.environ.get("ALINEA_RUN_LO_SMOKE") != "1",
    reason="real LibreOffice smoke is enabled with ALINEA_RUN_LO_SMOKE=1",
)
def test_real_libreoffice_render_and_chinese_location_smoke(
    paragraph_factory,
    snapshot_factory,
    issue_factory,
    tmp_path,
    capsys,
):
    assert REAL_SOFFICE.is_file()
    document = Document()
    texts = [
        "Smoke before",
        "中文定位 smoke anchor 全角Ａ",
        "Smoke after",
    ]
    for text in texts:
        document.add_paragraph(text)
    source = tmp_path / "real-smoke.docx"
    document.save(source)

    renderer = LibreOfficeRenderer(
        REAL_SOFFICE,
        timeout_seconds=90,
        max_pages=60,
        workspace_root=REAL_SOFFICE.parents[3],
    )
    started = time.perf_counter()
    artifact = renderer.render(source, tmp_path / "rendered")
    elapsed = time.perf_counter() - started
    assert artifact.page_count >= 1
    assert Path(artifact.pdf_path).is_file()
    assert len(artifact.pdf_sha256) == 64

    pdf_index = build_pdf_index(artifact.pdf_path)
    assert "中文定位" in pdf_index.compact_text
    paragraphs = [paragraph_factory(text, index) for index, text in enumerate(texts)]
    issue = issue_factory(paragraphs[1], "real-smoke-issue")
    located = locate_issues(
        snapshot_factory(paragraphs),
        [issue],
        artifact.pdf_path,
        artifact.pdf_sha256,
        artifact.render_profile_id,
    )[0]
    assert located.location.status == "LOCATED"
    assert located.location.fragments
    with capsys.disabled():
        print(
            f"REAL_LO_SMOKE elapsed_seconds={elapsed:.3f} "
            f"page_count={artifact.page_count} pdf={artifact.pdf_path}"
        )
