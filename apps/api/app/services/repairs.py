from __future__ import annotations

from typing import Any

from alinea_contracts import (
    AlineaError,
    Issue,
    QualityGateResult,
    RepairPlan,
    VerificationReport,
)
from alinea_docx import parse_docx
from alinea_docx.inspector import DEFAULT_INSPECTOR_VERSION, inspect_document
from alinea_repair import (
    apply_approved_patch,
    compute_execution_key,
    compute_plan_digest,
)
from alinea_repair import (
    create_repair_plan as build_repair_plan,
)
from sqlalchemy.orm import Session

from app.db.database import session_scope
from app.db.models import (
    InspectionRecord,
    Job,
    Project,
    QualityGateRun,
    RepairPlanRecord,
    Revision,
    RuleSetRecord,
)
from app.schemas import RepairPlanCreate

from .common import (
    add_audit,
    canonical_json,
    new_id,
    project_lock,
    read_snapshot,
    require_found,
    require_ownership,
    safe_filename,
    storage,
    utc_now,
    write_snapshot,
)
from .inspections import render_revision_preview, require_inspection, require_revision
from .jobs import _request_payload, create_job, existing_job, report_progress
from .rules import approved_ruleset
from .serializers import plan_contract, ruleset_contract


def require_plan(db: Session, project: Project, plan_id: str) -> RepairPlanRecord:
    record = require_found(
        db.get(RepairPlanRecord, plan_id), "REPAIR_PLAN_NOT_FOUND", "The repair plan was not found"
    )
    require_ownership(project, record.project_id)
    return record


def create_plan(db: Session, project: Project, payload: RepairPlanCreate) -> RepairPlanRecord:
    revision = require_revision(db, project, payload.base_revision_id)
    inspection = require_inspection(db, project, payload.inspection_id)
    if inspection.revision_id != revision.id or inspection.status != "SUCCEEDED":
        raise AlineaError("STALE_REPAIR_PLAN", "The inspection does not match the base", status_code=409)
    rule_record = db.get(RuleSetRecord, inspection.rule_set_id)
    if rule_record is None:
        raise AlineaError("RULE_SET_NOT_FOUND", "The rule set was not found", status_code=404)
    ruleset = ruleset_contract(rule_record)
    snapshot = read_snapshot(project.id, revision.id)
    issues = [Issue.model_validate(value) for value in inspection.issues_json]
    plan = build_repair_plan(
        snapshot,
        issues,
        ruleset,
        payload.selected_issue_ids,
        project_id=project.id,
        plan_id=new_id(),
    )
    record = RepairPlanRecord(
        id=plan.plan_id,
        project_id=project.id,
        base_revision_id=revision.id,
        inspection_id=inspection.id,
        rule_set_id=ruleset.rule_set_id,
        rule_set_version=ruleset.version,
        rule_set_digest=ruleset.digest,
        status="DRAFT",
        plan_digest=plan.plan_digest,
        selected_issues_json=plan.selected_issue_ids,
        operations_json=[operation.model_dump(mode="json") for operation in plan.operations],
        affected_node_count=plan.affected_node_count,
    )
    db.add(record)
    db.flush()
    add_audit(db, project.id, "repair_plan.created", entity_id=record.id)
    return record


def approve_plan(db: Session, project: Project, record: RepairPlanRecord, digest: str) -> RepairPlanRecord:
    if digest != record.plan_digest or digest != compute_plan_digest(plan_contract(record)):
        raise AlineaError("PLAN_DIGEST_MISMATCH", "The plan digest is invalid", status_code=409)
    if record.status == "APPROVED":
        return record
    if record.status != "DRAFT":
        raise AlineaError("STALE_REPAIR_PLAN", "Only a current draft can be approved", status_code=409)
    revision = require_revision(db, project, record.base_revision_id)
    if project.active_revision_id != revision.id:
        record.status = "STALE"
        raise AlineaError("STALE_REPAIR_PLAN", "The base revision is no longer active", status_code=409)
    approved_ruleset(db, project, record.rule_set_id, record.rule_set_version)
    if db.get(type(record), record.id) is None:
        raise AlineaError("REPAIR_PLAN_NOT_FOUND", "The plan was not found", status_code=404)
    record.approved_at = utc_now()
    record.execution_key = compute_execution_key(
        record.plan_digest, revision.sha256, f"project:{project.id}"
    )
    record.status = "APPROVED"
    add_audit(db, project.id, "repair_plan.approved", entity_id=record.id)
    db.flush()
    return record


def enqueue_repair(db: Session, project: Project, record: RepairPlanRecord) -> Job:
    if record.status not in {"APPROVED", "QUEUED", "RUNNING", "SUCCEEDED"} or not record.approved_at:
        raise AlineaError("REPAIR_NOT_APPROVED", "Approve the plan before execution", status_code=409)
    if project.active_revision_id != record.base_revision_id and record.status != "SUCCEEDED":
        record.status = "STALE"
        raise AlineaError("STALE_REPAIR_PLAN", "The plan base is stale", status_code=409)
    assert record.execution_key is not None
    payload = {"plan_id": record.id, "plan_digest": record.plan_digest}
    existing = existing_job(db, project.id, "repair", record.execution_key)
    if existing is not None:
        return existing
    job, _ = create_job(db, project, "repair", record.execution_key, payload)
    if record.status == "APPROVED":
        record.status = "QUEUED"
    add_audit(db, project.id, "repair.queued", job=job, entity_id=record.id)
    return job


def _target_key(issue: Issue) -> tuple[Any, ...]:
    reference = issue.element_ref
    return (
        issue.rule_id,
        issue.property,
        reference.part_uri,
        reference.paragraph_ordinal,
        reference.run_range.start if reference.run_range else None,
        reference.run_range.end if reference.run_range else None,
    )


def _write_report(
    db: Session,
    revision: Revision,
    report: VerificationReport,
) -> None:
    json_key = storage().build_key(
        revision.project_id, "reports", revision.id, "validation.json"
    )
    markdown_key = storage().build_key(revision.project_id, "reports", revision.id, "summary.md")
    storage().write(json_key, canonical_json(report.model_dump(mode="json")).encode("utf-8"))
    lines = [
        "# Alinea verification report",
        "",
        f"- Revision: `{report.revision_id}`",
        f"- Status: **{report.status}**",
        "- Selected / resolved / remaining: "
        f"{report.selected_count} / {report.resolved_count} / {report.remaining_count}",
        f"- Original SHA-256: `{report.original_sha256}`",
        f"- Revision SHA-256: `{report.revision_sha256}`",
        "",
        "## Quality gates",
        "",
        "| Gate | Status | Details |",
        "|---|---|---|",
        *[
            f"| {gate.gate} | {gate.status} | `{canonical_json(gate.details)[:800]}` |"
            for gate in report.gates
        ],
        "",
        "## Warnings",
        "",
        *(report.warnings or ["None"]),
        "",
        "Page count differences alone do not prove damage. Microsoft Word may paginate differently.",
    ]
    storage().write(markdown_key, "\n".join(lines).encode("utf-8"))
    revision.report_storage_key = json_key
    for gate in report.gates:
        db.add(
            QualityGateRun(
                id=new_id(),
                candidate_revision_id=revision.id,
                gate=gate.gate,
                status=gate.status,
                details_json=gate.details,
                created_at=utc_now(),
            )
        )


def _blocked_revision(
    db: Session,
    project: Project,
    plan: RepairPlan,
    parent: Revision,
    candidate_id: str,
    candidate_key: str,
    gates: list[QualityGateResult],
) -> Revision:
    revision = Revision(
        id=candidate_id,
        project_id=project.id,
        parent_revision_id=parent.id,
        original_filename=parent.original_filename,
        sha256="0" * 64,
        storage_key=candidate_key,
        kind="CANDIDATE",
        validation_status="BLOCKED",
        created_at=utc_now(),
    )
    db.add(revision)
    db.flush()
    report = VerificationReport(
        revision_id=candidate_id,
        base_revision_id=parent.id,
        before_inspection_id=plan.inspection_id,
        status="BLOCKED",
        selected_count=len(plan.selected_issue_ids),
        resolved_count=0,
        remaining_count=len(plan.selected_issue_ids),
        gates=gates,
        operations=plan.operations,
        warnings=["A hard integrity gate failed; the candidate was not published."],
        original_sha256=parent.sha256,
        revision_sha256="0" * 64,
        generated_at=utc_now(),
    )
    _write_report(db, revision, report)
    return revision


def execute_repair(job_id: str) -> str:
    with project_lock(_project_id_for_job(job_id)), session_scope() as db:
        job = db.get(Job, job_id)
        if job is None:
            raise AlineaError("JOB_NOT_FOUND", "The repair job was not found", status_code=404)
        request = _request_payload(db, job_id)
        plan_id = request.get("plan_id")
        record = db.get(RepairPlanRecord, plan_id) if isinstance(plan_id, str) else None
        if record is None or record.project_id != job.project_id:
            raise AlineaError("REPAIR_PLAN_NOT_FOUND", "The approved plan was not found", status_code=404)
        project = db.get(Project, record.project_id, with_for_update=True)
        assert project is not None
        if record.status == "SUCCEEDED" and record.result_revision_id:
            return record.result_revision_id
        if record.status not in {"APPROVED", "QUEUED", "RUNNING"} or not record.approved_at:
            raise AlineaError("REPAIR_NOT_APPROVED", "The plan is not executable", status_code=409)
        base = require_revision(db, project, record.base_revision_id)
        if project.active_revision_id != base.id:
            record.status = "STALE"
            raise AlineaError("STALE_REPAIR_PLAN", "The plan base is stale", status_code=409)
        rule_record = approved_ruleset(db, project, record.rule_set_id, record.rule_set_version)
        if rule_record.digest != record.rule_set_digest:
            raise AlineaError("STALE_REPAIR_PLAN", "The rule set digest is stale", status_code=409)
        plan: RepairPlan = plan_contract(record)
        if compute_plan_digest(plan) != record.plan_digest:
            raise AlineaError("PLAN_DIGEST_MISMATCH", "The plan content changed", status_code=409)
        snapshot = read_snapshot(project.id, base.id)
        record.status = "RUNNING"
        report_progress(job_id, "PATCHING", 20, "Applying approved OOXML properties")
        candidate_id = new_id()
        candidate_key = storage().build_key(project.id, "repairs", candidate_id, "candidate.docx")
        result = apply_approved_patch(
            storage().path_for(base.storage_key),
            storage().path_for(candidate_key),
            snapshot,
            plan,
            approved_actor=f"project:{project.id}",
        )
        if not result.publishable or not result.candidate_path:
            blocked = _blocked_revision(
                db, project, plan, base, candidate_id, candidate_key, result.gates
            )
            record.status = "FAILED"
            job.result_id = blocked.id
            raise AlineaError(
                "REPAIR_VALIDATION_FAILED", "A hard integrity gate blocked publication", status_code=422
            )
        report_progress(job_id, "REINSPECTING", 50, "Reparsing and checking the candidate")
        published_key = storage().build_key(project.id, "revisions", candidate_id, "document.docx")
        storage().copy(candidate_key, published_key)
        candidate_path = storage().path_for(published_key)
        candidate_snapshot = parse_docx(candidate_path, revision_id=candidate_id)
        write_snapshot(project.id, candidate_snapshot)
        ruleset = ruleset_contract(rule_record)
        before = require_inspection(db, project, record.inspection_id)
        after_id = new_id()
        after_result = inspect_document(
            candidate_snapshot,
            ruleset,
            inspection_id=after_id,
            inspector_version=DEFAULT_INSPECTOR_VERSION,
        )
        before_issues = [Issue.model_validate(value) for value in before.issues_json]
        selected_keys = {
            _target_key(issue)
            for issue in before_issues
            if issue.issue_id in set(plan.selected_issue_ids)
        }
        old_confirmed = {
            _target_key(issue)
            for issue in before_issues
            if issue.detection_status == "CONFIRMED_VIOLATION"
        }
        new_confirmed = {
            _target_key(issue)
            for issue in after_result.issues
            if issue.detection_status == "CONFIRMED_VIOLATION"
        }
        unresolved = selected_keys & new_confirmed
        introduced = new_confirmed - old_confirmed
        report_progress(job_id, "RENDERING", 72, "Rendering and mapping the candidate revision")
        revision = Revision(
            id=candidate_id,
            project_id=project.id,
            parent_revision_id=base.id,
            original_filename=safe_filename(
                base.original_filename.rsplit(".docx", 1)[0] + "-repaired.docx", "repaired.docx"
            ),
            sha256=result.candidate_sha256 or candidate_snapshot.sha256,
            storage_key=published_key,
            kind="PUBLISHED",
            validation_status="INDETERMINATE",
            created_at=utc_now(),
        )
        mapped, preview, warnings = render_revision_preview(
            project, revision, candidate_snapshot, list(after_result.issues)
        )
        summary = after_result.summary.model_dump(mode="json")
        summary.update(
            located=sum(issue.location.status == "LOCATED" for issue in mapped),
            ambiguous=sum(issue.location.status == "AMBIGUOUS" for issue in mapped),
            unlocated=sum(
                issue.location.status in {"UNLOCATED", "NOT_RENDERED"} for issue in mapped
            ),
        )
        after = InspectionRecord(
            id=after_id,
            project_id=project.id,
            revision_id=candidate_id,
            rule_set_id=ruleset.rule_set_id,
            rule_set_digest=ruleset.digest,
            inspector_version=DEFAULT_INSPECTOR_VERSION,
            status="SUCCEEDED",
            summary_json=summary,
            issues_json=[issue.model_dump(mode="json") for issue in mapped],
            preview_json=preview,
            warnings_json=warnings,
            created_at=utc_now(),
        )
        static_pass = not unresolved and not introduced
        status = "PASS" if static_pass and preview else ("PARTIAL" if not static_pass else "INDETERMINATE")
        g5 = QualityGateResult(
            gate="G5",
            status="PASS" if status == "PASS" else "WARN",
            details={
                "selected_unresolved": len(unresolved),
                "introduced_violations": len(introduced),
                "after_inspection_id": after_id,
                "rendered": preview is not None,
            },
        )
        report = VerificationReport(
            revision_id=candidate_id,
            base_revision_id=base.id,
            inspection_id=after_id,
            before_inspection_id=before.id,
            status=status,
            selected_count=len(selected_keys),
            resolved_count=len(selected_keys) - len(unresolved),
            remaining_count=len(unresolved),
            gates=[*result.gates, g5],
            operations=plan.operations,
            warnings=warnings,
            renderer_profile_id=(preview or {}).get("render_profile_id") if preview else None,
            original_sha256=base.sha256,
            revision_sha256=revision.sha256,
            generated_at=utc_now(),
        )
        revision.validation_status = status
        db.add(revision)
        db.flush()
        db.add(after)
        db.flush()
        _write_report(db, revision, report)
        project.active_revision_id = revision.id
        record.status = "SUCCEEDED"
        record.result_revision_id = revision.id
        job.result_id = revision.id
        add_audit(
            db,
            project.id,
            "repair.completed",
            job=job,
            actor="WORKER",
            entity_id=revision.id,
            details={"status": status, "resolved_count": report.resolved_count},
        )
        return revision.id


def _project_id_for_job(job_id: str) -> str:
    with session_scope() as db:
        job = db.get(Job, job_id)
        if job is None:
            raise AlineaError("JOB_NOT_FOUND", "The repair job was not found", status_code=404)
        return job.project_id
