from __future__ import annotations

import pytest
from alinea_contracts import AlineaError
from app.config import Settings
from app.db.models import InspectionRecord, Job, JobEvent, Revision, RuleSetRecord
from app.services.common import new_id, utc_now
from app.services.jobs import (
    cancel_job,
    create_job,
    emit_job_event,
    mark_job_failed,
    recover_jobs,
    retry_job,
)
from app.services.projects import create_project
from sqlalchemy import select


def test_retry_cancel_and_local_recovery(database, monkeypatch) -> None:
    with database.session_scope() as db:
        project, _ = create_project(db, "lifecycle")
        original, _ = create_job(
            db, project, "rule_extraction", "original", {"guideline_id": "guide"}
        )
        mark_job_failed(
            db,
            original,
            AlineaError(
                "LLM_EXTRACTION_FAILED", "temporary", status_code=503, retryable=True
            ),
        )
        retried = retry_job(db, project, original)
        assert retried.id != original.id
        assert retried.status == "QUEUED"
        assert retry_job(db, project, original).id == retried.id
        cancelled = cancel_job(db, project, retried)
        assert cancelled.status == "CANCELLED"
        running, _ = create_job(db, project, "rule_extraction", "running", {"guideline_id": "guide"})
        running.status = "RUNNING"
        recovered_id = running.id

    dispatched = []
    monkeypatch.setattr("app.jobs.runner.dispatch_job", lambda job_id: dispatched.append(job_id))
    recovered = recover_jobs(Settings(redis_url=""))
    assert recovered == [recovered_id]
    assert dispatched == [recovered_id]
    with database.session_scope() as db:
        assert db.get(Job, recovered_id).status == "QUEUED"


def test_failed_or_running_jobs_cannot_be_retried_or_cancelled(database) -> None:
    with database.session_scope() as db:
        project, _ = create_project(db, "lifecycle-guards")
        running, _ = create_job(db, project, "rule_extraction", "running", {"guideline_id": "guide"})
        running.status = "RUNNING"
        with pytest.raises(AlineaError, match="Only failed jobs"):
            retry_job(db, project, running)
        with pytest.raises(AlineaError, match="Only queued jobs"):
            cancel_job(db, project, running)
        failed, _ = create_job(db, project, "rule_extraction", "failed", {"guideline_id": "guide"})
        mark_job_failed(db, failed, AlineaError("RULE_CONFLICT", "logical", status_code=409))
        with pytest.raises(AlineaError, match="not safe to retry"):
            retry_job(db, project, failed)


def test_rq_running_job_requires_manual_retry(database) -> None:
    with database.session_scope() as db:
        project, _ = create_project(db, "rq-recovery")
        job, _ = create_job(db, project, "rule_extraction", "rq", {"guideline_id": "guide"})
        job.status = "RUNNING"
        job_id = job.id
    assert recover_jobs(Settings(redis_url="redis://example:6379/0") ) == []
    with database.session_scope() as db:
        recovered = db.get(Job, job_id)
        assert recovered.status == "FAILED"
        assert recovered.error_code == "WORKER_RESTARTED"
        failed_event = db.scalar(select(JobEvent).where(JobEvent.job_id == job_id).order_by(JobEvent.id.desc()))
        assert failed_event.payload_json["retryable"] is True


def test_successful_retry_is_returned_before_inspection_history_is_reset(database) -> None:
    with database.session_scope() as db:
        project, _ = create_project(db, "retry-success")
        revision = Revision(
            id=new_id(),
            project_id=project.id,
            original_filename="original.docx",
            sha256="a" * 64,
            storage_key="original.docx",
            kind="ORIGINAL",
            validation_status="NOT_RUN",
            created_at=utc_now(),
        )
        rules = RuleSetRecord(
            id=new_id(),
            project_id=project.id,
            version=1,
            name="retry-rules",
            status="APPROVED",
            digest="b" * 64,
            rules_json=[],
            conflicts_json=[],
            created_at=utc_now(),
            approved_at=utc_now(),
        )
        inspection = InspectionRecord(
            id=new_id(),
            project_id=project.id,
            revision_id=revision.id,
            rule_set_id=rules.id,
            rule_set_digest=rules.digest,
            inspector_version="test-inspector",
            status="QUEUED",
            summary_json={},
            issues_json=[],
            preview_json={"include_page_mapping": False},
            warnings_json=[],
            created_at=utc_now(),
        )
        db.add_all([revision, rules])
        db.flush()
        db.add(inspection)
        db.flush()
        original, _ = create_job(
            db,
            project,
            "inspection",
            "inspection-original",
            {
                "revision_id": revision.id,
                "rule_set_id": rules.id,
                "rule_set_version": 1,
                "include_page_mapping": False,
            },
            result_id=inspection.id,
        )
        mark_job_failed(
            db,
            original,
            AlineaError("TEMPORARY", "temporary", status_code=503, retryable=True),
        )
        retried = retry_job(db, project, original)
        inspection.status = "SUCCEEDED"
        inspection.summary_json = {"sentinel": "summary"}
        inspection.issues_json = [{"sentinel": "issue"}]
        inspection.preview_json = {"include_page_mapping": False, "sentinel": "preview"}
        inspection.warnings_json = ["sentinel-warning"]
        emit_job_event(
            db,
            retried,
            event_type="job.completed",
            stage="SUCCEEDED",
            progress=100,
            message="Retry completed",
            result={"inspection_id": inspection.id},
        )

        duplicate = retry_job(db, project, original)

        assert duplicate.id == retried.id
        assert duplicate.status == "SUCCEEDED"
        assert inspection.status == "SUCCEEDED"
        assert inspection.summary_json == {"sentinel": "summary"}
        assert inspection.issues_json == [{"sentinel": "issue"}]
        assert inspection.preview_json == {"include_page_mapping": False, "sentinel": "preview"}
        assert inspection.warnings_json == ["sentinel-warning"]
