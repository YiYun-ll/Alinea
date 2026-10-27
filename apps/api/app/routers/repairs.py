from __future__ import annotations

from alinea_contracts import AlineaError
from fastapi import APIRouter, Header, status

from app.dependencies import Database, ProjectAuth
from app.jobs.runner import dispatch_job
from app.schemas import RepairPlanApprove, RepairPlanCreate
from app.services.jobs import job_out
from app.services.repairs import approve_plan, create_plan, enqueue_repair, require_plan
from app.services.serializers import plan_out

router = APIRouter(tags=["repairs"])


@router.post("/projects/{project_id}/repair-plans", status_code=status.HTTP_201_CREATED)
def create(
    payload: RepairPlanCreate,
    project: ProjectAuth, db: Database,
) -> dict[str, object]:
    record = create_plan(db, project, payload)
    db.commit()
    return plan_out(record)


@router.get("/repair-plans/{plan_id}")
def get(
    plan_id: str,
    project: ProjectAuth, db: Database,
) -> dict[str, object]:
    return plan_out(require_plan(db, project, plan_id))


@router.post("/repair-plans/{plan_id}/approve")
def approve(
    plan_id: str,
    payload: RepairPlanApprove,
    project: ProjectAuth, db: Database,
) -> dict[str, object]:
    record = approve_plan(db, project, require_plan(db, project, plan_id), payload.plan_digest)
    db.commit()
    return plan_out(record)


@router.post("/repair-plans/{plan_id}/execute", status_code=status.HTTP_202_ACCEPTED)
def execute(
    plan_id: str,
    project: ProjectAuth,
    db: Database,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> dict[str, object]:
    if not idempotency_key:
        raise AlineaError("IDEMPOTENCY_KEY_REQUIRED", "Idempotency-Key is required", status_code=400)
    record = require_plan(db, project, plan_id)
    job = enqueue_repair(db, project, record)
    db.commit()
    if job.status == "QUEUED":
        dispatch_job(job.id)
    return {**job_out(db, job), "status_url": f"/api/v1/jobs/{job.id}"}
