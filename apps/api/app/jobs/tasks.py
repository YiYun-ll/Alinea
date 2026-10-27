from __future__ import annotations

import logging
from collections.abc import Callable

from alinea_contracts.errors import AlineaError
from sqlalchemy import update

from app.db.database import session_scope
from app.db.models import Job
from app.services.jobs import TERMINAL_JOB_STATUSES, emit_job_event, mark_job_failed


def _run_job(job_id: str, expected_type: str, action: Callable[[str], str]) -> str | None:
    with session_scope() as db:
        job = db.get(Job, job_id)
        if job is None:
            return None
        if job.job_type != expected_type:
            raise ValueError(f"Job {job_id} is not a {expected_type} job")
        claimed = db.execute(
            update(Job)
            .where(Job.id == job_id, Job.status == "QUEUED")
            .values(status="RUNNING")
        )
        if claimed.rowcount != 1:
            db.refresh(job)
            return job.result_id
        job.status = "RUNNING"
        job.error_code = None
        job.error_message = None
        emit_job_event(
            db,
            job,
            event_type="job.started",
            stage="RUNNING",
            progress=max(job.progress, 1),
            message="Background execution started",
        )
    try:
        result_id = action(job_id)
    except AlineaError as exc:
        with session_scope() as db:
            job = db.get(Job, job_id)
            if job is not None and job.status not in TERMINAL_JOB_STATUSES:
                mark_job_failed(db, job, exc)
        return None
    except Exception as exc:
        logging.getLogger("alinea.jobs").exception(
            "Background job failed job_id=%s error_type=%s", job_id, type(exc).__name__
        )
        with session_scope() as db:
            job = db.get(Job, job_id)
            if job is not None and job.status not in TERMINAL_JOB_STATUSES:
                mark_job_failed(
                    db,
                    job,
                    AlineaError(
                        "INTERNAL_ERROR",
                        "The background job failed unexpectedly",
                        status_code=500,
                        retryable=True,
                    ),
                )
        return None
    with session_scope() as db:
        job = db.get(Job, job_id)
        if job is None or job.status in TERMINAL_JOB_STATUSES:
            return result_id
        job.result_id = result_id
        if job.job_type == "rule_extraction":
            result = {"rule_set_id": result_id}
        elif job.job_type == "inspection":
            result = {"inspection_id": result_id}
        else:
            result = {"revision_id": result_id, "result_revision_id": result_id}
        emit_job_event(
            db,
            job,
            event_type="job.completed",
            stage="SUCCEEDED",
            progress=100,
            message="Background execution completed",
            result=result,
        )
    return result_id


def rule_extraction_job(job_id: str) -> str | None:
    from app.services.rules import execute_rule_extraction

    return _run_job(job_id, "rule_extraction", execute_rule_extraction)


def inspect_document_job(job_id: str) -> str | None:
    from app.services.inspections import execute_inspection

    return _run_job(job_id, "inspection", execute_inspection)


def repair_plan_job(job_id: str) -> str | None:
    from app.services.repairs import execute_repair

    return _run_job(job_id, "repair", execute_repair)


def execute_job(job_id: str) -> str | None:
    with session_scope() as db:
        job = db.get(Job, job_id)
        if job is None:
            return None
        job_type = job.job_type
    handlers = {
        "rule_extraction": rule_extraction_job,
        "inspection": inspect_document_job,
        "repair": repair_plan_job,
    }
    handler = handlers.get(job_type)
    if handler is None:
        with session_scope() as db:
            job = db.get(Job, job_id)
            if job is not None:
                mark_job_failed(
                    db,
                    job,
                    AlineaError(
                        "UNKNOWN_JOB_TYPE", "The job type is not supported", status_code=500
                    ),
                )
        return None
    return handler(job_id)
