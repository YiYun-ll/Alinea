from __future__ import annotations

import hashlib
from typing import Any

from alinea_contracts import (
    AlineaError,
    DocumentSnapshot,
    InspectionResult,
    Issue,
    RuleSet,
)
from alinea_docx.inspector import DEFAULT_INSPECTOR_VERSION, inspect_document
from alinea_mapping import LibreOfficeRenderer, locate_issues
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.database import session_scope
from app.db.models import InspectionRecord, Job, Project, Revision
from app.schemas import InspectionCreate

from .common import (
    add_audit,
    new_id,
    read_snapshot,
    require_found,
    require_ownership,
    storage,
    utc_now,
)
from .jobs import create_job, emit_job_event, existing_job, report_progress
from .rules import approved_ruleset
from .serializers import ruleset_contract


def require_revision(db: Session, project: Project, revision_id: str) -> Revision:
    revision = require_found(
        db.get(Revision, revision_id), "REVISION_NOT_FOUND", "The document revision was not found"
    )
    require_ownership(project, revision.project_id)
    return revision


def require_inspection(db: Session, project: Project, inspection_id: str) -> InspectionRecord:
    inspection = require_found(
        db.get(InspectionRecord, inspection_id),
        "INSPECTION_NOT_FOUND",
        "The inspection was not found",
    )
    require_ownership(project, inspection.project_id)
    return inspection


def _state_conflict(message: str) -> AlineaError:
    return AlineaError("INSPECTION_STATE_CONFLICT", message, status_code=409)


def _job_inspection(db: Session, project: Project, job: Job) -> InspectionRecord:
    if not job.result_id:
        raise _state_conflict("The inspection job does not reference an inspection")
    return require_inspection(db, project, job.result_id)


def _matching_inspection(
    db: Session, project: Project, revision_id: str, rule_set_digest: str
) -> InspectionRecord | None:
    return db.scalar(
        select(InspectionRecord).where(
            InspectionRecord.project_id == project.id,
            InspectionRecord.revision_id == revision_id,
            InspectionRecord.rule_set_digest == rule_set_digest,
            InspectionRecord.inspector_version == DEFAULT_INSPECTOR_VERSION,
        )
    )


def _inspection_jobs(db: Session, record: InspectionRecord) -> list[Job]:
    return list(
        db.scalars(
            select(Job)
            .where(
                Job.project_id == record.project_id,
                Job.job_type == "inspection",
                Job.result_id == record.id,
            )
            .order_by(Job.created_at, Job.id)
        )
    )


def _validate_mapping(
    db: Session,
    record: InspectionRecord,
    job: Job | None,
    include_page_mapping: bool,
) -> None:
    if not include_page_mapping:
        return
    preview = record.preview_json
    if preview and preview.get("include_page_mapping") is True:
        return
    if job is not None and _job_request(db, job.id).get("include_page_mapping") is True:
        return
    raise AlineaError(
        "INSPECTION_MAPPING_INCOMPATIBLE",
        "The existing inspection cannot satisfy page mapping; use a mapping-enabled inspection",
        status_code=409,
    )


def _reuse_same_key(
    db: Session,
    project: Project,
    payload: InspectionCreate,
    idempotency_key: str,
    request: dict[str, Any],
) -> tuple[Job, InspectionRecord, bool] | None:
    existing = existing_job(db, project.id, "inspection", idempotency_key)
    if existing is None:
        return None
    job, _ = create_job(
        db,
        project,
        "inspection",
        idempotency_key,
        request,
        result_id=existing.result_id,
    )
    record = _job_inspection(db, project, job)
    _validate_mapping(db, record, job, payload.include_page_mapping)
    return job, record, True


def _cached_job(
    db: Session,
    project: Project,
    record: InspectionRecord,
    idempotency_key: str,
    request: dict[str, Any],
) -> tuple[Job, InspectionRecord, bool]:
    with db.begin_nested():
        job, created = create_job(
            db, project, "inspection", idempotency_key, request, result_id=record.id
        )
        if created:
            emit_job_event(
                db,
                job,
                event_type="job.completed",
                stage="CACHED",
                progress=100,
                message="Reused completed inspection",
                result={"inspection_id": record.id},
            )
            add_audit(db, project.id, "inspection.reused", job=job, entity_id=record.id)
            db.flush()
    if not created and job.result_id != record.id:
        raise _state_conflict("The idempotent job references a different inspection")
    return job, record, True


def _new_queued_job(
    db: Session,
    project: Project,
    record: InspectionRecord,
    idempotency_key: str,
    request: dict[str, Any],
) -> tuple[Job, InspectionRecord, bool]:
    with db.begin_nested():
        job, created = create_job(
            db, project, "inspection", idempotency_key, request, result_id=record.id
        )
        if created:
            record.status = "QUEUED"
            add_audit(db, project.id, "inspection.queued", job=job, entity_id=record.id)
            db.flush()
    if not created and job.result_id != record.id:
        raise _state_conflict("The idempotent job references a different inspection")
    return job, record, True


def _reuse_inspection(
    db: Session,
    project: Project,
    record: InspectionRecord,
    payload: InspectionCreate,
    idempotency_key: str,
    request: dict[str, Any],
) -> tuple[Job, InspectionRecord, bool]:
    jobs = _inspection_jobs(db, record)
    active = [job for job in jobs if job.status in {"QUEUED", "RUNNING"}]
    succeeded = [job for job in jobs if job.status == "SUCCEEDED"]
    if active:
        if record.status not in {"QUEUED", "RUNNING", "SUCCEEDED"}:
            raise _state_conflict("The inspection status does not match its active job")
        if succeeded and record.status != "SUCCEEDED":
            raise _state_conflict("The inspection status does not match its successful job")
        job = active[-1]
        _validate_mapping(db, record, job, payload.include_page_mapping)
        return job, record, True
    if record.status == "SUCCEEDED":
        if succeeded:
            job = succeeded[-1]
            _validate_mapping(db, record, job, payload.include_page_mapping)
            return job, record, True
        if jobs:
            raise _state_conflict("A succeeded inspection has no successful inspection job")
        _validate_mapping(db, record, None, payload.include_page_mapping)
        return _cached_job(db, project, record, idempotency_key, request)
    if succeeded:
        raise _state_conflict("The inspection status does not match its successful job")
    if record.status == "FAILED":
        failed = [job for job in jobs if job.status == "FAILED"]
        if not failed:
            raise _state_conflict("A failed inspection has no failed job available for retry")
        job = failed[-1]
        _validate_mapping(db, record, job, payload.include_page_mapping)
        return job, record, True
    latest = jobs[-1] if jobs else None
    if (
        latest is not None
        and latest.status == "CANCELLED"
        and record.status in {"QUEUED", "RUNNING", "CANCELLED"}
    ):
        return _new_queued_job(db, project, record, idempotency_key, request)
    raise _state_conflict("The existing inspection cannot be reused in its current state")


def _create_or_reuse_inspection(
    db: Session,
    project: Project,
    payload: InspectionCreate,
    idempotency_key: str,
    request: dict[str, Any],
    revision: Revision,
    rule_set_digest: str,
) -> tuple[Job, InspectionRecord, bool]:
    record = _matching_inspection(db, project, revision.id, rule_set_digest)
    if record is not None:
        return _reuse_inspection(db, project, record, payload, idempotency_key, request)
    with db.begin_nested():
        job, created = create_job(db, project, "inspection", idempotency_key, request)
        if not created:
            record = _job_inspection(db, project, job)
            _validate_mapping(db, record, job, payload.include_page_mapping)
            return job, record, True
        record = InspectionRecord(
            id=new_id(),
            project_id=project.id,
            revision_id=revision.id,
            rule_set_id=payload.rule_set_id,
            rule_set_digest=rule_set_digest,
            inspector_version=DEFAULT_INSPECTOR_VERSION,
            status="QUEUED",
            summary_json={},
            issues_json=[],
            preview_json={"include_page_mapping": payload.include_page_mapping},
            warnings_json=[],
            created_at=utc_now(),
        )
        db.add(record)
        db.flush()
        job.result_id = record.id
        add_audit(db, project.id, "inspection.queued", job=job, entity_id=record.id)
        db.flush()
    return job, record, False


def create_inspection(
    db: Session, project: Project, payload: InspectionCreate, idempotency_key: str
) -> tuple[Job, InspectionRecord, bool]:
    request = payload.model_dump(mode="json")
    existing = _reuse_same_key(db, project, payload, idempotency_key, request)
    if existing is not None:
        return existing
    revision = require_revision(db, project, payload.revision_id)
    rule_record = approved_ruleset(db, project, payload.rule_set_id, payload.rule_set_version)
    try:
        return _create_or_reuse_inspection(
            db, project, payload, idempotency_key, request, revision, rule_record.digest
        )
    except IntegrityError:
        existing = _reuse_same_key(db, project, payload, idempotency_key, request)
        if existing is not None:
            return existing
        record = _matching_inspection(db, project, revision.id, rule_record.digest)
        if record is None:
            raise
        return _reuse_inspection(db, project, record, payload, idempotency_key, request)


def render_revision_preview(
    project: Project,
    revision: Revision,
    snapshot: DocumentSnapshot,
    issues: list[Issue],
) -> tuple[list[Issue], dict[str, Any] | None, list[str]]:
    settings = get_settings()
    renderer = LibreOfficeRenderer(
        settings.soffice_path,
        timeout_seconds=settings.render_timeout_seconds,
        max_pages=settings.max_pages,
        cache_dir=settings.storage_root / "_render-cache",
    )
    try:
        artifact = renderer.render(
            storage().path_for(revision.storage_key), settings.storage_root / "_renders"
        )
        key = storage().build_key(
            project.id,
            "previews",
            revision.id,
            f"{artifact.pdf_sha256}.pdf",
            profile_id=artifact.render_profile_id,
        )
        try:
            storage().copy_from(artifact.pdf_path, key)
        except FileExistsError:
            if hashlib.sha256(storage().read(key)).hexdigest() != artifact.pdf_sha256:
                raise AlineaError("PREVIEW_INTEGRITY_ERROR", "The stored preview digest does not match") from None
        mapped = locate_issues(
            snapshot,
            issues,
            storage().path_for(key),
            artifact.pdf_sha256,
            artifact.render_profile_id,
        )
        preview = {
            **artifact.model_dump(mode="json"),
            "storage_key": key,
            "include_page_mapping": True,
        }
        return mapped, preview, list(artifact.warnings)
    except AlineaError as exc:
        degraded = locate_issues(snapshot, issues, None, None, None)
        return degraded, None, [f"{exc.code}: {exc.message}"]


def _job_request(db: Session, job_id: str) -> dict[str, Any]:
    from app.db.models import JobEvent

    event = db.scalar(
        select(JobEvent).where(JobEvent.job_id == job_id).order_by(JobEvent.id).limit(1)
    )
    payload = event.payload_json.get("request_payload") if event else None
    return dict(payload) if isinstance(payload, dict) else {}


def execute_inspection(job_id: str) -> str:
    with session_scope() as db:
        job = db.get(Job, job_id)
        if job is None:
            raise AlineaError("JOB_NOT_FOUND", "The inspection job was not found", status_code=404)
        project = db.get(Project, job.project_id)
        assert project is not None
        record = require_inspection(db, project, str(job.result_id))
        if record.status == "SUCCEEDED":
            return record.id
        request = _job_request(db, job_id)
        revision = require_revision(db, project, record.revision_id)
        rule_record = approved_ruleset(
            db, project, record.rule_set_id, int(request["rule_set_version"])
        )
        ruleset: RuleSet = ruleset_contract(rule_record)
        if ruleset.digest != record.rule_set_digest:
            raise AlineaError("STALE_RULE_SET", "The approved rules changed", status_code=409)
        report_progress(job_id, "PARSING", 15, "Reading immutable DOCX snapshot")
        snapshot = read_snapshot(project.id, revision.id)
        if snapshot.sha256 != revision.sha256:
            raise AlineaError("STALE_REVISION", "The revision content changed", status_code=409)
        report_progress(job_id, "INSPECTING", 35, "Evaluating approved formatting rules")
        result: InspectionResult = inspect_document(
            snapshot, ruleset, inspection_id=record.id, inspector_version=record.inspector_version
        )
        issues = list(result.issues)
        preview = None
        warnings = list(result.warnings)
        if request.get("include_page_mapping", True):
            report_progress(job_id, "RENDERING", 60, "Rendering revision-specific PDF")
            issues, preview, render_warnings = render_revision_preview(
                project, revision, snapshot, issues
            )
            warnings.extend(render_warnings)
            report_progress(job_id, "MAPPING", 85, "Mapping issues to the exact preview")
        else:
            from alinea_mapping import locate_issues as degrade

            issues = degrade(snapshot, issues, None, None, None)
        summary = result.summary.model_dump(mode="json")
        summary.update(
            located=sum(issue.location.status == "LOCATED" for issue in issues),
            ambiguous=sum(issue.location.status == "AMBIGUOUS" for issue in issues),
            unlocated=sum(
                issue.location.status in {"UNLOCATED", "NOT_RENDERED"} for issue in issues
            ),
        )
        record.status = "SUCCEEDED"
        record.issues_json = [issue.model_dump(mode="json") for issue in issues]
        record.summary_json = summary
        record.preview_json = preview
        record.warnings_json = warnings
        job.result_id = record.id
        add_audit(
            db,
            project.id,
            "inspection.completed",
            job=job,
            actor="WORKER",
            entity_id=record.id,
            details={"summary": summary, "warning_count": len(warnings)},
        )
        return record.id
