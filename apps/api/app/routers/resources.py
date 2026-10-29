from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import AsyncIterator
from pathlib import Path

from alinea_contracts import AlineaError
from fastapi import APIRouter, Query, Request, status
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.database import session_scope
from app.db.models import AuditEvent, InspectionRecord, Job, JobEvent, Project, Revision
from app.dependencies import Database, ProjectAuth
from app.services.common import require_found, require_ownership, safe_filename, storage
from app.services.documents import create_document_revision
from app.services.inspections import require_revision
from app.services.jobs import cancel_job, job_event_out, job_out, retry_job
from app.services.projects import create_project
from app.services.rules import create_guideline, create_preset_draft
from app.services.serializers import audit_out, project_out, revision_out

router = APIRouter(tags=["resources"])


def _job(db: Session, project: Project, job_id: str) -> Job:
    job = require_found(db.get(Job, job_id), "JOB_NOT_FOUND", "The job was not found")
    require_ownership(project, job.project_id)
    return job


def _downloadable(revision: Revision) -> None:
    if revision.kind not in {"ORIGINAL", "PUBLISHED", "PARTIAL_PUBLISHED"}:
        raise AlineaError("REPAIR_VALIDATION_FAILED", "This candidate is not published", status_code=403)


def _latest_preview(db: Session, revision_id: str, sha256: str | None = None) -> InspectionRecord | None:
    query = select(InspectionRecord).where(
        InspectionRecord.revision_id == revision_id,
        InspectionRecord.status == "SUCCEEDED",
        InspectionRecord.preview_json["storage_key"].as_string().is_not(None),
    )
    if sha256 is not None:
        query = query.where(InspectionRecord.preview_json["pdf_sha256"].as_string() == sha256)
    return db.scalar(
        query
        .order_by(InspectionRecord.created_at.desc(), InspectionRecord.id.desc())
        .limit(1)
    )


@router.post("/demo", status_code=status.HTTP_201_CREATED)
def demo(db: Database) -> dict[str, object]:
    source = Path(__file__).resolve().parents[4] / "examples" / "alinea-demo.docx"
    project, token = create_project(db, "Alinea 演示论文")
    revision = create_document_revision(db, project, source.read_bytes(), source.name)
    guideline = create_guideline(
        db, project, kind="preset", name="演示论文假想规范", preset_id="thesis_demo"
    )
    ruleset = create_preset_draft(db, project, guideline, "thesis_demo")
    db.commit()
    return {
        **project_out(db, project),
        "token": token,
        "revision_id": revision.id,
        "rule_set_id": ruleset.id,
    }


@router.get("/jobs/{job_id}")
def get_job(
    job_id: str,
    project: ProjectAuth, db: Database,
) -> dict[str, object]:
    return job_out(db, _job(db, project, job_id))


@router.post("/jobs/{job_id}/retry", status_code=status.HTTP_202_ACCEPTED)
def retry(
    job_id: str,
    project: ProjectAuth, db: Database,
) -> dict[str, object]:
    new_job = retry_job(db, project, _job(db, project, job_id))
    db.commit()
    from app.jobs.runner import dispatch_job

    dispatch_job(new_job.id)
    return {**job_out(db, new_job), "retry_of": job_id}


@router.post("/jobs/{job_id}/cancel")
def cancel(
    job_id: str,
    project: ProjectAuth, db: Database,
) -> dict[str, object]:
    job = cancel_job(db, project, _job(db, project, job_id))
    db.commit()
    return job_out(db, job)


@router.get("/jobs/{job_id}/events")
async def job_events(
    job_id: str,
    request: Request,
    project: ProjectAuth, db: Database,
) -> StreamingResponse:
    _job(db, project, job_id)
    last_id = int(request.headers.get("Last-Event-ID", "0") or 0)

    async def stream() -> AsyncIterator[str]:
        nonlocal last_id
        for _ in range(600):
            await asyncio.sleep(0.5)
            with session_scope() as session:
                events = list(
                    session.scalars(
                        select(JobEvent)
                        .where(JobEvent.job_id == job_id, JobEvent.id > last_id)
                        .order_by(JobEvent.id)
                    )
                )
                job = session.get(Job, job_id)
                terminal = job is None or job.status in {"SUCCEEDED", "FAILED", "CANCELLED"}
                for event in events:
                    last_id = event.id
                    event_type, data = job_event_out(event)
                    yield f"id: {last_id}\nevent: {event_type}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
                if terminal and not events:
                    return
        yield 'event: timeout\ndata: {"message":"SSE window closed; query the job for authoritative status"}\n\n'

    return StreamingResponse(stream(), media_type="text/event-stream")


@router.get("/projects/{project_id}/jobs")
def project_jobs(
    project: ProjectAuth, db: Database
) -> dict[str, object]:
    jobs = list(
        db.scalars(select(Job).where(Job.project_id == project.id).order_by(Job.created_at.desc()))
    )
    events_by_job: dict[str, list[JobEvent]] = {job.id: [] for job in jobs}
    if jobs:
        events = db.scalars(
            select(JobEvent)
            .where(JobEvent.job_id.in_(events_by_job))
            .order_by(JobEvent.job_id, JobEvent.id)
        )
        for event in events:
            events_by_job[event.job_id].append(event)
    return {
        "data": [job_out(db, job, events_by_job[job.id]) for job in jobs]
    }


@router.get("/projects/{project_id}/audit-events")
def project_audit(
    project: ProjectAuth, db: Database
) -> dict[str, object]:
    events = db.scalars(
        select(AuditEvent).where(AuditEvent.project_id == project.id).order_by(AuditEvent.created_at)
    )
    return {"data": [audit_out(event) for event in events]}


@router.get("/projects/{project_id}/revisions")
def project_revisions(
    project: ProjectAuth, db: Database
) -> dict[str, object]:
    revisions = db.scalars(
        select(Revision).where(Revision.project_id == project.id).order_by(Revision.created_at)
    )
    return {"data": [revision_out(revision) for revision in revisions]}


@router.get("/revisions/{revision_id}/download")
def download(
    revision_id: str,
    project: ProjectAuth, db: Database,
) -> FileResponse:
    revision = require_revision(db, project, revision_id)
    _downloadable(revision)
    return FileResponse(
        storage().path_for(revision.storage_key),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        filename=safe_filename(revision.original_filename, "document.docx"),
    )


@router.get("/revisions/{revision_id}/preview")
def preview(
    revision_id: str,
    project: ProjectAuth, db: Database,
    sha256: str | None = Query(default=None, pattern=r"^[0-9a-f]{64}$"),
) -> FileResponse:
    revision = require_revision(db, project, revision_id)
    inspection = _latest_preview(db, revision.id, sha256)
    key = inspection.preview_json.get("storage_key") if inspection and inspection.preview_json else None
    if not key:
        raise AlineaError("PREVIEW_NOT_READY", "No PDF preview is available for this revision", status_code=404)
    return FileResponse(storage().path_for(key), media_type="application/pdf", filename="preview.pdf")


@router.get("/revisions/{revision_id}/report")
def report(
    revision_id: str,
    project: ProjectAuth,
    db: Database,
    format: str = "json",
) -> object:
    revision = require_revision(db, project, revision_id)
    if not revision.report_storage_key:
        raise AlineaError("REPORT_NOT_FOUND", "No verification report exists", status_code=404)
    if format == "markdown":
        key = revision.report_storage_key.replace("validation.json", "summary.md")
        return FileResponse(
            storage().path_for(key), media_type="text/markdown; charset=utf-8", filename="verification.md"
        )
    if format != "json":
        raise AlineaError("VALIDATION_ERROR", "Report format must be json or markdown", status_code=422)
    return json.loads(storage().read(revision.report_storage_key))


@router.get("/revisions/{revision_id}/artifacts")
def artifacts(
    revision_id: str,
    project: ProjectAuth, db: Database,
) -> dict[str, object]:
    revision = require_revision(db, project, revision_id)
    values = []
    if revision.kind in {"ORIGINAL", "PUBLISHED", "PARTIAL_PUBLISHED"}:
        values.append(
            {
                "kind": "docx",
                "url": f"/api/v1/revisions/{revision.id}/download",
                "sha256": revision.sha256,
            }
        )
    inspection = _latest_preview(db, revision.id)
    key = inspection.preview_json.get("storage_key") if inspection and inspection.preview_json else None
    if key:
        values.append(
            {
                "kind": "pdf",
                "url": f"/api/v1/revisions/{revision.id}/preview",
                "sha256": hashlib.sha256(storage().read(key)).hexdigest(),
            }
        )
    if revision.report_storage_key:
        values.extend(
            [
                {
                    "kind": "report_json",
                    "url": f"/api/v1/revisions/{revision.id}/report",
                    "sha256": hashlib.sha256(storage().read(revision.report_storage_key)).hexdigest(),
                },
                {
                    "kind": "report_markdown",
                    "url": f"/api/v1/revisions/{revision.id}/report?format=markdown",
                    "sha256": hashlib.sha256(
                        storage().read(revision.report_storage_key.replace("validation.json", "summary.md"))
                    ).hexdigest(),
                },
            ]
        )
    return {"data": values}
