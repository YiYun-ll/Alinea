from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from alinea_contracts.errors import AlineaError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import Settings
from app.db.database import session_scope
from app.db.models import InspectionRecord, Job, JobEvent, Project, RepairPlanRecord

from .common import add_audit, isoformat, new_id, request_digest, utc_now

TERMINAL_JOB_STATUSES = {"SUCCEEDED", "FAILED", "CANCELLED"}


def _job_by_key(db: Session, project_id: str, job_type: str, key: str) -> Job | None:
    return db.scalar(
        select(Job).where(
            Job.project_id == project_id,
            Job.job_type == job_type,
            Job.idempotency_key == key,
        )
    )


def existing_job(db: Session, project_id: str, job_type: str, key: str) -> Job | None:
    return _job_by_key(db, project_id, job_type, key)


def _event_data(event: JobEvent) -> dict[str, Any]:
    return {
        "job_id": event.job_id,
        "stage": event.stage,
        "progress": event.progress,
        "message": event.message,
        **event.payload_json,
    }


def emit_job_event(
    db: Session,
    job: Job,
    *,
    event_type: str,
    stage: str | None,
    progress: int,
    message: str | None = None,
    result: dict[str, Any] | None = None,
    retryable: bool = False,
) -> JobEvent:
    job.status = {
        "job.started": "RUNNING",
        "job.completed": "SUCCEEDED",
        "job.failed": "FAILED",
        "job.cancelled": "CANCELLED",
    }.get(event_type, job.status)
    job.stage = stage
    job.progress = max(0, min(100, progress))
    job.updated_at = utc_now()
    if event_type in {"job.completed", "job.failed", "job.cancelled"}:
        job.finished_at = job.updated_at
    payload: dict[str, Any] = {
        "event": event_type,
        "job_id": job.id,
        "status": job.status,
        "retryable": retryable,
    }
    if result is not None:
        payload["result"] = result
    event = JobEvent(
        job_id=job.id,
        stage=stage,
        progress=job.progress,
        message=message,
        payload_json=payload,
        created_at=utc_now(),
    )
    db.add(event)
    db.flush()
    return event


def create_job(
    db: Session,
    project: Project,
    job_type: str,
    idempotency_key: str | None,
    request_payload: dict[str, Any],
    *,
    result_id: str | None = None,
) -> tuple[Job, bool]:
    key = idempotency_key or new_id()
    digest = request_digest(request_payload)
    existing = _job_by_key(db, project.id, job_type, key)
    if existing is not None:
        first_event = db.scalar(
            select(JobEvent).where(JobEvent.job_id == existing.id).order_by(JobEvent.id).limit(1)
        )
        previous_digest = first_event.payload_json.get("request_digest") if first_event else None
        if previous_digest is not None and previous_digest != digest:
            raise AlineaError(
                "IDEMPOTENCY_CONFLICT",
                "The Idempotency-Key was already used for a different request",
                status_code=409,
            )
        return existing, False
    job = Job(
        id=new_id(),
        project_id=project.id,
        job_type=job_type,
        status="QUEUED",
        stage="QUEUED",
        progress=0,
        result_id=result_id,
        idempotency_key=key,
        created_at=utc_now(),
        updated_at=utc_now(),
    )
    db.add(job)
    db.flush()
    event = emit_job_event(
        db,
        job,
        event_type="job.queued",
        stage="QUEUED",
        progress=0,
        message="Job accepted",
    )
    event.payload_json = {
        **event.payload_json,
        "request_digest": digest,
        "request_payload": request_payload,
    }
    db.flush()
    return job, True


def enforce_job_capacity(db: Session, project_id: str, maximum: int = 20) -> None:
    active = db.scalar(
        select(func.count(Job.id)).where(
            Job.project_id == project_id,
            Job.status.in_(["QUEUED", "RUNNING"]),
        )
    )
    if (active or 0) >= maximum:
        raise AlineaError(
            "TOO_MANY_JOBS",
            "Too many jobs are queued for this project; retry after an active job completes",
            status_code=429,
            retryable=True,
        )


def job_out(
    db: Session, job: Job, events: Sequence[JobEvent] | None = None
) -> dict[str, Any]:
    if events is None:
        events = list(
            db.scalars(select(JobEvent).where(JobEvent.job_id == job.id).order_by(JobEvent.id))
        )
    latest = events[-1] if events else None
    started = next(
        (event for event in events if event.payload_json.get("event") == "job.started"), None
    )
    result = latest.payload_json.get("result") if latest else None
    if result is None and job.result_id:
        if job.job_type == "inspection":
            result = {"inspection_id": job.result_id}
        elif job.job_type == "rule_extraction":
            result = {"rule_set_id": job.result_id}
        elif job.job_type == "repair":
            result = {"revision_id": job.result_id, "result_revision_id": job.result_id}
    return {
        "job_id": job.id,
        "project_id": job.project_id,
        "job_type": job.job_type,
        "status": job.status,
        "retryable": job.status == "FAILED" and bool(latest and latest.payload_json.get("retryable")),
        "progress": job.progress,
        "stage": job.stage,
        "message": latest.message if latest else None,
        "error_code": job.error_code,
        "error_message": job.error_message,
        "inspection_id": (result or {}).get("inspection_id"),
        "result_revision_id": (result or {}).get("result_revision_id"),
        "result": result,
        "created_at": isoformat(job.created_at),
        "started_at": isoformat(started.created_at) if started else None,
        "updated_at": isoformat(job.updated_at),
        "completed_at": isoformat(job.finished_at),
    }


def job_event_out(event: JobEvent) -> tuple[str, dict[str, Any]]:
    event_type = str(event.payload_json.get("event") or "job.progress")
    return event_type, _event_data(event)


def report_progress(job_id: str, stage: str, progress: int, message: str) -> None:
    with session_scope() as db:
        job = db.get(Job, job_id)
        if job is None or job.status in TERMINAL_JOB_STATUSES:
            return
        emit_job_event(
            db,
            job,
            event_type="job.progress",
            stage=stage,
            progress=progress,
            message=message,
        )


def mark_job_failed(db: Session, job: Job, error: AlineaError) -> None:
    job.error_code = error.code
    job.error_message = error.message
    result = None
    if job.result_id:
        if job.job_type == "inspection":
            result = {"inspection_id": job.result_id}
        elif job.job_type == "repair":
            result = {"revision_id": job.result_id, "result_revision_id": job.result_id}
    if job.job_type == "inspection" and job.result_id:
        inspection = db.get(InspectionRecord, job.result_id)
        if inspection is not None and inspection.status != "SUCCEEDED":
            inspection.status = "FAILED"
    if job.job_type == "repair":
        plan = _repair_plan_for_job(db, job)
        if plan is not None and plan.status not in {"SUCCEEDED", "FAILED"}:
            plan.status = "FAILED"
    if job.job_type == "agent_run" and job.result_id:
        from app.db.models import AgentRun

        run = db.get(AgentRun, job.result_id)
        if run is not None and run.status not in {"SUCCEEDED", "NEEDS_CLARIFICATION"}:
            run.status = "FAILED"
            run.error_code = error.code
            run.error_message = error.message
            run.finished_at = utc_now()
    emit_job_event(
        db,
        job,
        event_type="job.failed",
        stage="FAILED",
        progress=job.progress,
        message=error.message,
        result=result,
        retryable=error.retryable,
    )
    add_audit(
        db,
        job.project_id,
        "job.failed",
        job=job,
        actor="WORKER",
        entity_id=job.result_id,
        details={"error_code": error.code},
    )


def _request_payload(db: Session, job_id: str) -> dict[str, Any]:
    event = db.scalar(
        select(JobEvent).where(JobEvent.job_id == job_id).order_by(JobEvent.id).limit(1)
    )
    payload = event.payload_json.get("request_payload") if event else None
    return dict(payload) if isinstance(payload, dict) else {}


def _repair_plan_for_job(db: Session, job: Job) -> RepairPlanRecord | None:
    request = _request_payload(db, job.id)
    plan_id = request.get("plan_id")
    plan = db.get(RepairPlanRecord, plan_id) if isinstance(plan_id, str) else None
    if plan is None or plan.project_id != job.project_id or plan.plan_digest != request.get("plan_digest"):
        return None
    return plan


def retry_job(db: Session, project: Project, job: Job) -> Job:
    retried = existing_job(db, project.id, job.job_type, f"retry:{job.id}")
    if retried is not None:
        return retried
    if job.status != "FAILED":
        raise AlineaError("JOB_NOT_RETRYABLE", "Only failed jobs can be retried", status_code=409)
    failed_event = db.scalar(
        select(JobEvent)
        .where(JobEvent.job_id == job.id, JobEvent.payload_json["event"].as_string() == "job.failed")
        .order_by(JobEvent.id.desc())
        .limit(1)
    )
    if failed_event is None or not failed_event.payload_json.get("retryable", False):
        raise AlineaError(
            "JOB_NOT_RETRYABLE", "This failure is not safe to retry", status_code=409
        )
    request = _request_payload(db, job.id)
    if not request:
        raise AlineaError("JOB_RETRY_UNSUPPORTED", "The original request is unavailable", status_code=409)
    if job.job_type == "inspection":
        inspection = db.get(InspectionRecord, str(job.result_id))
        if inspection is None:
            raise AlineaError("INSPECTION_NOT_FOUND", "The inspection no longer exists", status_code=404)
        inspection.status = "QUEUED"
        inspection.issues_json = []
        inspection.summary_json = {}
        inspection.preview_json = {
            "include_page_mapping": bool(request.get("include_page_mapping", True))
        }
        inspection.warnings_json = []
    elif job.job_type == "repair":
        plan = _repair_plan_for_job(db, job)
        if plan is None:
            raise AlineaError("REPAIR_PLAN_NOT_FOUND", "The plan no longer exists", status_code=404)
        if project.active_revision_id != plan.base_revision_id:
            raise AlineaError("STALE_REPAIR_PLAN", "The base revision changed", status_code=409)
        plan.status = "APPROVED"
        plan.result_revision_id = None
    elif job.job_type != "rule_extraction":
        raise AlineaError("JOB_RETRY_UNSUPPORTED", "This job type cannot be retried", status_code=409)
    new_job, _ = create_job(
        db,
        project,
        job.job_type,
        f"retry:{job.id}",
        request,
        result_id=job.result_id,
    )
    add_audit(
        db,
        project.id,
        "job.retried",
        job=new_job,
        actor="USER",
        entity_id=job.id,
        details={"retry_of": job.id},
    )
    db.flush()
    return new_job


def cancel_job(db: Session, project: Project, job: Job) -> Job:
    if job.status != "QUEUED":
        raise AlineaError(
            "JOB_NOT_CANCELLABLE", "Only queued jobs can be cancelled safely", status_code=409
        )
    emit_job_event(
        db,
        job,
        event_type="job.cancelled",
        stage="CANCELLED",
        progress=job.progress,
        message="Cancelled before execution",
    )
    add_audit(db, project.id, "job.cancelled", job=job, actor="USER", entity_id=job.id)
    db.flush()
    return job


def recover_jobs(settings: Settings) -> list[str]:
    from app.jobs.runner import dispatch_job

    local_ids: list[str] = []
    with session_scope() as db:
        jobs = list(db.scalars(select(Job).where(Job.status.in_(["QUEUED", "RUNNING"]))).all())
        for job in jobs:
            if settings.redis_url:
                if job.status == "RUNNING":
                    mark_job_failed(
                        db,
                        job,
                        AlineaError(
                            "WORKER_RESTARTED",
                            "The worker may have restarted; retry after checking the result",
                            status_code=503,
                            retryable=True,
                        ),
                    )
                continue
            job.status = "QUEUED"
            job.error_code = None
            job.error_message = None
            job.finished_at = None
            emit_job_event(
                db,
                job,
                event_type="job.recovered",
                stage="QUEUED",
                progress=job.progress,
                message="Recovered after API restart",
            )
            local_ids.append(job.id)
    for job_id in local_ids:
        dispatch_job(job_id)
    return local_ids

