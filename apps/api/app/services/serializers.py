from __future__ import annotations

from alinea_contracts.models import RepairPlan, RuleSet
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import (
    AuditEvent,
    InspectionRecord,
    Project,
    RepairPlanRecord,
    Revision,
    RuleSetRecord,
)

from .common import isoformat


def revision_out(revision: Revision) -> dict[str, object]:
    return {
        "revision_id": revision.id,
        "project_id": revision.project_id,
        "parent_revision_id": revision.parent_revision_id,
        "sha256": revision.sha256,
        "status": revision.validation_status,
        "kind": revision.kind,
        "original_filename": revision.original_filename,
        "created_at": isoformat(revision.created_at),
    }


def project_out(db: Session, project: Project) -> dict[str, object]:
    revisions = list(
        db.scalars(
            select(Revision)
            .where(Revision.project_id == project.id)
            .order_by(Revision.created_at.desc(), Revision.id.desc())
        )
    )
    originals = [revision for revision in revisions if revision.kind == "ORIGINAL"]
    original_id = originals[0].id if originals else None
    return {
        "project_id": project.id,
        "name": project.name,
        "status": project.status,
        "original_revision_id": original_id,
        "revision_id": project.active_revision_id or original_id,
        "active_revision_id": project.active_revision_id,
        "revisions": [revision_out(revision) for revision in revisions],
        "created_at": isoformat(project.created_at),
        "expires_at": isoformat(project.expires_at),
    }


def ruleset_contract(record: RuleSetRecord) -> RuleSet:
    return RuleSet(
        rule_set_id=record.id,
        project_id=record.project_id,
        version=record.version,
        name=record.name,
        status=record.status,
        digest=record.digest,
        rules=record.rules_json,
        conflicts=record.conflicts_json,
        guideline_id=record.guideline_id,
        created_at=record.created_at,
        approved_at=record.approved_at,
    )


def ruleset_out(record: RuleSetRecord) -> dict[str, object]:
    return ruleset_contract(record).model_dump(mode="json")


def inspection_out(record: InspectionRecord) -> dict[str, object]:
    preview = None
    if record.preview_json and record.preview_json.get("pdf_sha256"):
        preview = dict(record.preview_json)
        preview["pdf_path"] = f"/api/v1/revisions/{record.revision_id}/preview"
        preview.pop("storage_key", None)
        preview.pop("include_page_mapping", None)
    return {
        "inspection_id": record.id,
        "revision_id": record.revision_id,
        "rule_set_id": record.rule_set_id,
        "rule_set_digest": record.rule_set_digest,
        "inspector_version": record.inspector_version,
        "status": record.status,
        "issues": record.issues_json,
        "summary": record.summary_json,
        "preview": preview,
        "warnings": record.warnings_json,
        "created_at": isoformat(record.created_at),
    }


def plan_contract(record: RepairPlanRecord) -> RepairPlan:
    return RepairPlan(
        plan_id=record.id,
        project_id=record.project_id,
        base_revision_id=record.base_revision_id,
        inspection_id=record.inspection_id,
        rule_set_id=record.rule_set_id,
        rule_set_version=record.rule_set_version,
        rule_set_digest=record.rule_set_digest,
        status=record.status,
        plan_digest=record.plan_digest,
        selected_issue_ids=record.selected_issues_json,
        operations=record.operations_json,
        affected_node_count=record.affected_node_count,
        approved_at=record.approved_at,
        execution_key=record.execution_key,
        result_revision_id=record.result_revision_id,
    )


def plan_out(record: RepairPlanRecord) -> dict[str, object]:
    return plan_contract(record).model_dump(mode="json")


def audit_out(event: AuditEvent) -> dict[str, object]:
    return {
        "id": event.id,
        "audit_id": event.id,
        "project_id": event.project_id,
        "job_id": event.job_id,
        "actor": event.actor,
        "actor_type": event.actor,
        "action": event.event_type,
        "event_type": event.event_type,
        "entity_id": event.details_json.get("entity_id"),
        "details": event.details_json,
        "details_json": event.details_json,
        "created_at": isoformat(event.created_at),
    }
