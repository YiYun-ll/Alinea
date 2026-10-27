from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from datetime import datetime
from typing import Literal
from uuid import uuid4

from alinea_contracts.errors import AlineaError
from alinea_contracts.models import (
    DocumentSnapshot,
    ElementRef,
    Issue,
    ParagraphNode,
    RepairOperation,
    RepairPlan,
    RuleSet,
)

from alinea_repair._util import normalize_sha256
from alinea_repair.properties import encode_property, normalize_property_value
from alinea_repair.refs import find_fresh_ref, find_snapshot_node


def _snapshot_before_value(snapshot: DocumentSnapshot, issue: Issue, fresh: ElementRef) -> object:
    node = find_snapshot_node(snapshot, fresh)
    if not issue.property.startswith("font.") or fresh.run_range is None:
        resolved = node.effective.get(issue.property)
    else:
        if (
            not isinstance(node, ParagraphNode)
            or fresh.run_range.end != fresh.run_range.start + 1
        ):
            raise AlineaError(
                "UNSAFE_REPAIR_OPERATION",
                "A run repair plan requires exactly one resolved run",
                status_code=422,
                details={"issue_id": issue.issue_id},
            )
        run = next((item for item in node.runs if item.index == fresh.run_range.start), None)
        resolved = run.effective.get(issue.property) if run is not None else None
    if resolved is None or resolved.property != issue.property or resolved.status != "RESOLVED":
        raise AlineaError(
            "UNSAFE_REPAIR_OPERATION",
            "The snapshot has no resolved old value for the repair target",
            status_code=422,
            details={"issue_id": issue.issue_id, "property": issue.property},
        )
    return resolved.value


def compute_plan_digest(plan: RepairPlan) -> str:
    payload = {
        "project_id": plan.project_id,
        "base_revision_id": plan.base_revision_id,
        "inspection_id": plan.inspection_id,
        "rule_set_id": plan.rule_set_id,
        "rule_set_version": plan.rule_set_version,
        "rule_set_digest": plan.rule_set_digest,
        "selected_issue_ids": plan.selected_issue_ids,
        "operations": [operation.model_dump(mode="json") for operation in plan.operations],
    }
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def compute_execution_key(
    plan_digest: str | RepairPlan,
    base_revision_sha256: str,
    approved_actor: str,
) -> str:
    digest = plan_digest.plan_digest if isinstance(plan_digest, RepairPlan) else plan_digest
    if not digest or not base_revision_sha256 or not approved_actor:
        raise AlineaError(
            "INVALID_EXECUTION_KEY_INPUT",
            "plan_digest, base_revision_sha256 and approved_actor must be non-empty",
            status_code=422,
        )
    material = digest + base_revision_sha256 + approved_actor
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _validate_anchor(issue: Issue, fresh: ElementRef) -> None:
    original = issue.element_ref
    fields = (
        "revision_id",
        "kind",
        "paragraph_ordinal",
        "section_ordinal",
        "para_id",
        "text_sha256",
        "context_before_sha256",
        "context_after_sha256",
        "anchor_schema_version",
    )
    mismatches = [field for field in fields if getattr(original, field) != getattr(fresh, field)]
    if original.run_range != fresh.run_range:
        mismatches.append("run_range")
    if mismatches:
        raise AlineaError(
            "STALE_REPAIR_PLAN",
            f"Issue {issue.issue_id} does not match the fresh snapshot anchor",
            status_code=409,
            details={"issue_id": issue.issue_id, "fields": mismatches},
        )


def create_repair_plan(
    snapshot: DocumentSnapshot,
    issues: Sequence[Issue],
    rule_set: RuleSet,
    selected_issue_ids: Sequence[str] | None = None,
    *,
    project_id: str | None = None,
    plan_id: str | None = None,
    status: Literal["DRAFT", "APPROVED", "QUEUED", "RUNNING"] = "DRAFT",
    approved_at: datetime | None = None,
    approved_actor: str | None = None,
) -> RepairPlan:
    by_id: dict[str, Issue] = {}
    for issue in issues:
        if issue.issue_id in by_id:
            raise AlineaError(
                "INVALID_REPAIR_SELECTION",
                f"Duplicate issue id: {issue.issue_id}",
                status_code=422,
            )
        by_id[issue.issue_id] = issue

    if selected_issue_ids is None:
        selected = [
            issue.issue_id
            for issue in issues
            if issue.detection_status == "CONFIRMED_VIOLATION"
            and issue.repair.eligibility == "SAFE_SINGLE_TARGET"
        ]
    else:
        selected = list(selected_issue_ids)
    if not selected or len(set(selected)) != len(selected):
        raise AlineaError(
            "INVALID_REPAIR_SELECTION",
            "A repair plan needs a non-empty, duplicate-free issue selection",
            status_code=422,
        )

    base_sha256 = normalize_sha256(snapshot.sha256, field="snapshot.sha256")
    operations: list[RepairOperation] = []
    inspection_ids: set[str] = set()
    target_properties: set[tuple[str, int, str, int | None, int | None, str]] = set()
    for issue_id in selected:
        if issue_id not in by_id:
            raise AlineaError(
                "INVALID_REPAIR_SELECTION",
                f"Selected issue is not present in the inspection input: {issue_id}",
                status_code=422,
            )
        issue = by_id[issue_id]
        if (
            issue.detection_status != "CONFIRMED_VIOLATION"
            or issue.repair.eligibility != "SAFE_SINGLE_TARGET"
        ):
            raise AlineaError(
                "UNSAFE_REPAIR_OPERATION",
                "Only CONFIRMED_VIOLATION issues with SAFE_SINGLE_TARGET "
                "eligibility can be planned",
                status_code=422,
                details={"issue_id": issue_id},
            )
        if issue.revision_id != snapshot.revision_id:
            raise AlineaError(
                "STALE_REPAIR_PLAN",
                f"Issue {issue_id} belongs to another revision",
                status_code=409,
            )
        fresh = find_fresh_ref(snapshot, issue.element_ref)
        _validate_anchor(issue, fresh)
        matching_rules = [rule for rule in rule_set.rules if rule.rule_id == issue.rule_id]
        if len(matching_rules) != 1 or matching_rules[0].property != issue.property:
            raise AlineaError(
                "INVALID_REPAIR_SELECTION",
                f"Issue {issue_id} does not match exactly one rule-set rule",
                status_code=422,
            )
        patch = encode_property(issue.property, issue.expected.value)
        if patch.strategy == "DIRECT_RUN_PROPERTY":
            if fresh.kind != "paragraph" or fresh.run_range is None:
                raise AlineaError(
                    "UNSAFE_REPAIR_OPERATION",
                    "Run formatting requires an explicit paragraph run_range",
                    status_code=422,
                    details={"issue_id": issue_id},
                )
            if fresh.run_range.start >= fresh.run_range.end:
                raise AlineaError(
                    "UNSAFE_REPAIR_OPERATION",
                    "Run formatting requires a non-empty run_range",
                    status_code=422,
                )
            impact_scope = "EXACT_SELECTED_RUNS"
        elif patch.strategy == "DIRECT_PARAGRAPH_PROPERTY":
            if fresh.kind != "paragraph":
                raise AlineaError(
                    "UNSAFE_REPAIR_OPERATION",
                    "Paragraph formatting requires a paragraph target",
                    status_code=422,
                )
            impact_scope = "EXACT_SELECTED_PARAGRAPH"
        else:
            if fresh.kind != "section":
                raise AlineaError(
                    "UNSAFE_REPAIR_OPERATION",
                    "Section formatting requires an explicit section target",
                    status_code=422,
                )
            impact_scope = "EXACT_SELECTED_SECTION_WITH_REPACKAGING_RISK"

        run_start = fresh.run_range.start if fresh.run_range else None
        run_end = fresh.run_range.end if fresh.run_range else None
        target_key = (
            fresh.part_uri,
            fresh.paragraph_ordinal,
            fresh.kind,
            run_start,
            run_end,
            issue.property,
        )
        if target_key in target_properties:
            raise AlineaError(
                "INVALID_REPAIR_SELECTION",
                "Duplicate operations for one exact target and property are not allowed",
                status_code=422,
                details={"issue_id": issue_id, "property": issue.property},
            )
        target_properties.add(target_key)
        inspection_ids.add(issue.inspection_id)
        operations.append(
            RepairOperation(
                operation_id=f"op_{issue.issue_id}",
                issue_id=issue.issue_id,
                base_revision_sha256=base_sha256,
                rule_set_digest=rule_set.digest,
                target=fresh.model_copy(deep=True),
                property=issue.property,
                expected_before=normalize_property_value(
                    issue.property, _snapshot_before_value(snapshot, issue, fresh)
                ),
                desired_after=issue.expected.value,
                strategy=patch.strategy,
                impact_scope=impact_scope,
                allowed_xml_changes=patch.allowed_xml_changes,
                risk="medium" if fresh.kind == "section" else "low",
            )
        )

    if len(inspection_ids) != 1:
        raise AlineaError(
            "INVALID_REPAIR_SELECTION",
            "All selected issues must belong to one inspection",
            status_code=422,
        )
    if status == "DRAFT" and approved_at is not None:
        raise AlineaError(
            "INVALID_APPROVAL",
            "A DRAFT plan cannot carry approved_at",
            status_code=422,
        )
    if status != "DRAFT" and approved_at is None:
        raise AlineaError(
            "INVALID_APPROVAL",
            "An executable plan requires approved_at",
            status_code=422,
        )
    if approved_actor is not None and (not approved_actor or approved_at is None):
        raise AlineaError(
            "INVALID_APPROVAL",
            "approved_actor requires a non-empty actor and approved_at",
            status_code=422,
        )

    selected_nodes = {
        (
            operation.target.part_uri,
            operation.target.paragraph_ordinal,
            operation.target.kind,
            operation.target.run_range.start if operation.target.run_range else None,
            operation.target.run_range.end if operation.target.run_range else None,
        )
        for operation in operations
    }
    plan = RepairPlan(
        plan_id=plan_id or f"rp_{uuid4().hex}",
        project_id=project_id or rule_set.project_id,
        base_revision_id=snapshot.revision_id,
        inspection_id=next(iter(inspection_ids)),
        rule_set_id=rule_set.rule_set_id,
        rule_set_version=rule_set.version,
        rule_set_digest=rule_set.digest,
        status=status,
        plan_digest="",
        selected_issue_ids=selected,
        operations=operations,
        affected_node_count=len(selected_nodes),
        approved_at=approved_at,
    )
    digest = compute_plan_digest(plan)
    execution_key = (
        compute_execution_key(digest, base_sha256, approved_actor)
        if approved_actor is not None
        else None
    )
    return plan.model_copy(update={"plan_digest": digest, "execution_key": execution_key})
