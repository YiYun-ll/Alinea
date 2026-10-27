from alinea_contracts import FormatRule
from alinea_docx.rules import _font_identity, _matches


def test_simsun_and_chinese_name_are_equivalent() -> None:
    assert _font_identity("SimSun") == _font_identity("宋体")
    rule = FormatRule(
        rule_id="body_font",
        selector="body",
        property="font.eastAsia",
        expected="宋体",
        source={"source_type": "preset", "reference": "test", "quote": "宋体"},
    )
    assert _matches(rule, "SimSun")
    assert _matches(rule, "宋体")
    assert not _matches(rule, "SimHei")
