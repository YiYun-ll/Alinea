import pytest
from app.services.rules import load_preset


@pytest.mark.parametrize("preset_id", ["thesis_demo", "general_report"])
def test_builtin_presets_load_and_validate(preset_id: str) -> None:
    ruleset = load_preset(preset_id)
    assert ruleset.rules
    assert ruleset.digest
    assert all(rule.source.reference and rule.source.quote for rule in ruleset.rules)
