from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from alinea_contracts.errors import AlineaError
from alinea_contracts.models import RunRange
from alinea_repair import compute_execution_key, compute_plan_digest, create_repair_plan
from alinea_repair.properties import normalize_property_value

from tests.unit.alinea_repair.helpers import Spec, build_case


def test_digest_binding_and_execution_key_stability(tmp_path: Path) -> None:
    case = build_case(
        tmp_path / "base.docx",
        [
            Spec("one", "font.size_pt", 10, 12),
            Spec("two", "paragraph.alignment", "left", "center", "p0"),
        ],
    )
    first = case.plan(approved=False)
    second = case.plan(approved=False)
    assert compute_plan_digest(first) == first.plan_digest == second.plan_digest
    for update in (
        {"base_revision_id": "other"},
        {"inspection_id": "other"},
        {"rule_set_version": 4},
        {"rule_set_digest": "other"},
        {"selected_issue_ids": list(reversed(first.selected_issue_ids))},
        {
            "operations": [
                first.operations[0].model_copy(update={"desired_after": 14}),
                first.operations[1],
            ]
        },
    ):
        changed = first.model_copy(update=update)
        assert compute_plan_digest(changed) != first.plan_digest

    key = compute_execution_key(first.plan_digest, case.snapshot.sha256, "actor-A")
    assert key == compute_execution_key(first, case.snapshot.sha256, "actor-A")
    assert (
        key
        == hashlib.sha256(
            (first.plan_digest + case.snapshot.sha256 + "actor-A").encode()
        ).hexdigest()
    )
    assert key != compute_execution_key(first.plan_digest, case.snapshot.sha256, "actor-B")
    assert key != compute_execution_key(first.plan_digest, "0" * 64, "actor-A")


def test_plan_filters_or_rejects_unsafe_issues(tmp_path: Path) -> None:
    case = build_case(
        tmp_path / "base.docx",
        [
            Spec("safe", "font.size_pt", 10, 12, "p0:r0"),
            Spec("review", "font.bold", False, True, "p0:r1", eligibility="NEEDS_REVIEW"),
            Spec(
                "unknown",
                "paragraph.alignment",
                "left",
                "center",
                "p0",
                detection_status="POSSIBLE_VIOLATION",
            ),
        ],
    )
    automatic = create_repair_plan(case.snapshot, case.issues, case.rule_set)
    assert automatic.selected_issue_ids == ["safe"]
    for selected in (["review"], ["unknown"]):
        with pytest.raises(AlineaError) as caught:
            create_repair_plan(case.snapshot, case.issues, case.rule_set, selected)
        assert caught.value.code == "UNSAFE_REPAIR_OPERATION"
    operation = automatic.operations[0]
    assert operation.base_revision_sha256 == case.snapshot.sha256
    assert operation.rule_set_digest == case.rule_set.digest
    assert operation.expected_before == 10
    assert operation.desired_after == 12
    assert operation.impact_scope == "EXACT_SELECTED_RUNS"
    assert operation.allowed_xml_changes == ["w:rPr/w:sz/@w:val", "w:rPr/w:szCs/@w:val"]


@pytest.mark.parametrize(
    ("spec", "display_value"),
    [
        (Spec("font", "font.eastAsia", "SimHei", "SimSun"), " simhei "),
        (Spec("align", "paragraph.alignment", "center", "justify", "p0"), "CENTER"),
        (Spec("size", "font.size_pt", 10.5, 12), 10.5000000001),
        (
            Spec(
                "spacing",
                "paragraph.line_spacing",
                {"kind": "MULTIPLE", "value": 1.0},
                {"type": "MULTIPLE", "value": 1.5},
                "p0",
            ),
            {"type": "MULTIPLE", "value": 1},
        ),
    ],
)
def test_plan_binds_old_value_to_snapshot_not_display_evidence(
    tmp_path: Path, spec: Spec, display_value: object
) -> None:
    case = build_case(tmp_path / "base.docx", [spec])
    element_ref = case.issues[0].element_ref
    if not spec.prop.startswith("font."):
        element_ref = element_ref.model_copy(update={"run_range": RunRange(start=0, end=1)})
    issue = case.issues[0].model_copy(
        update={
            "actual": case.issues[0].actual.model_copy(update={"value": display_value}),
            "element_ref": element_ref,
        }
    )

    plan = create_repair_plan(case.snapshot, [issue], case.rule_set)

    assert plan.operations[0].expected_before == normalize_property_value(spec.prop, spec.before)
