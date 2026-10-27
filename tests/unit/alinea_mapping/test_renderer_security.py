from pathlib import Path

import pytest
from alinea_contracts import AlineaError
from alinea_mapping import LibreOfficeRenderer


def test_external_image_is_rejected_before_renderer_startup(tmp_path: Path) -> None:
    source = (
        Path(__file__).parents[2]
        / "fixtures"
        / "data"
        / "high_risk"
        / "h03-external-image.docx"
    )
    renderer = LibreOfficeRenderer(soffice_path=tmp_path / "missing-soffice")
    with pytest.raises(AlineaError) as caught:
        renderer.render(source, tmp_path / "output")
    assert caught.value.code == "DOCX_UNSAFE_EXTERNAL_RESOURCE"
    assert caught.value.status_code == 422
    assert not (tmp_path / "output").exists()
