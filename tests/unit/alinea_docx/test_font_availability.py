from pathlib import Path

from alinea_docx import DocumentIndexer, EffectiveStyleResolver, OoxmlPackage
from alinea_docx.font_availability import font_key, normalize_font_families


def fixture() -> Path:
    return (
        Path(__file__).parents[2]
        / "fixtures"
        / "data"
        / "structural_edge"
        / "e01-mixed-theme-unknown.docx"
    )


def themed_effective(available: set[str]):
    package = OoxmlPackage.from_source(fixture())
    resolver = EffectiveStyleResolver(package, available_fonts=available)
    snapshot = DocumentIndexer(package, resolver=resolver).build_snapshot(revision_id="E01")
    return snapshot.paragraphs[2].runs[0].effective


def test_theme_font_availability_changes_resolution_not_xml_name() -> None:
    unavailable = themed_effective(set())
    assert unavailable["font.eastAsia"].status == "UNRESOLVED"
    assert unavailable["font.ascii"].status == "UNRESOLVED"
    assert "RENDER_FONT_MISSING" in (unavailable["font.ascii"].reason or "")

    available = themed_effective({"Alinea Fixture Unknown"})
    assert available["font.eastAsia"].status == "RESOLVED"
    assert available["font.eastAsia"].value == "Alinea Fixture Unknown"
    assert available["font.ascii"].value == "Alinea Fixture Unknown"


def test_font_family_normalization() -> None:
    assert font_key(" Noto  Sans SC ") == "notosanssc"
    assert normalize_font_families(["SimSun", " Sim  Sun ", ""]) == {"simsun"}
