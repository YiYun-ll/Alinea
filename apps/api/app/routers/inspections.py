from __future__ import annotations

from typing import Annotated

from alinea_contracts import AlineaError
from fastapi import APIRouter, Header, Query, status

from app.dependencies import Database, ProjectAuth
from app.jobs.runner import dispatch_job
from app.schemas import InspectionCreate
from app.services.common import project_lock
from app.services.inspections import create_inspection, require_inspection
from app.services.jobs import job_out
from app.services.serializers import inspection_out

router = APIRouter(tags=["inspections"])


@router.post("/projects/{project_id}/inspections", status_code=status.HTTP_202_ACCEPTED)
def create(
    payload: InspectionCreate,
    project: ProjectAuth,
    db: Database,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> dict[str, object]:
    if not idempotency_key:
        raise AlineaError("IDEMPOTENCY_KEY_REQUIRED", "Idempotency-Key is required", status_code=400)
    with project_lock(project.id):
        job, inspection, reused = create_inspection(db, project, payload, idempotency_key)
        db.commit()
    if job.status == "QUEUED":
        dispatch_job(job.id)
    return {
        **job_out(db, job),
        "inspection_id": inspection.id,
        "reused": reused,
        "status_url": f"/api/v1/jobs/{job.id}",
        "events_url": f"/api/v1/jobs/{job.id}/events",
    }


@router.get("/inspections/{inspection_id}")
def get(
    inspection_id: str,
    project: ProjectAuth, db: Database,
) -> dict[str, object]:
    return inspection_out(require_inspection(db, project, inspection_id))


@router.get("/inspections/{inspection_id}/issues")
def issues(
    inspection_id: str,
    project: ProjectAuth,
    db: Database,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    severity: str | None = None,
    property_name: str | None = Query(default=None, alias="property"),
    location_status: str | None = None,
    fixable: bool | None = None,
    page_index: int | None = Query(default=None, ge=0),
) -> dict[str, object]:
    inspection = require_inspection(db, project, inspection_id)
    values = inspection.issues_json
    if severity:
        values = [value for value in values if value["severity"] == severity]
    if property_name:
        values = [value for value in values if value["property"] == property_name]
    if location_status:
        values = [value for value in values if value["location"]["status"] == location_status]
    if fixable is not None:
        values = [
            value
            for value in values
            if (value["repair"]["eligibility"] == "SAFE_SINGLE_TARGET") == fixable
        ]
    if page_index is not None:
        values = [
            value
            for value in values
            if value["location"].get("page_index") == page_index
            or any(fragment["page_index"] == page_index for fragment in value["location"]["fragments"])
        ]
    total = len(values)
    start = (page - 1) * page_size
    return {
        "data": values[start : start + page_size],
        "page": page,
        "page_size": page_size,
        "total": total,
        "summary": inspection.summary_json,
    }


@router.get("/inspections/{inspection_id}/locations")
def locations(
    inspection_id: str,
    project: ProjectAuth, db: Database,
) -> dict[str, object]:
    inspection = require_inspection(db, project, inspection_id)
    return {
        "data": [
            {"issue_id": value["issue_id"], **value["location"]}
            for value in inspection.issues_json
        ]
    }
