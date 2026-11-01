from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import get_project_auth
from app.db.database import get_db
from app.db.models import AgentRun, Project
from app.jobs.runner import dispatch_job
from app.schemas import AgentRunCreate, AgentRunMessage
from app.services.agent_runs import agent_run_out, create_agent_run, require_agent_run, resume_agent_run
from app.services.common import require_active

router = APIRouter(prefix="/projects/{project_id}/agent", tags=["agent"])


@router.post("/runs", status_code=status.HTTP_202_ACCEPTED)
def create_run(
    payload: AgentRunCreate,
    project: Annotated[Project, Depends(get_project_auth)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, object]:
    require_active(project)
    run, job, created = create_agent_run(db, project, payload)
    result = agent_run_out(db, run)
    db.commit()
    if created:
        dispatch_job(job.id)
    return result


@router.get("/runs")
def list_runs(
    project: Annotated[Project, Depends(get_project_auth)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, object]:
    runs = db.scalars(
        select(AgentRun).where(AgentRun.project_id == project.id).order_by(AgentRun.created_at.desc()).limit(20)
    ).all()
    return {"runs": [agent_run_out(db, run) for run in runs]}


@router.get("/runs/{run_id}")
def get_run(
    run_id: str,
    project: Annotated[Project, Depends(get_project_auth)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, object]:
    return agent_run_out(db, require_agent_run(db, project, run_id))


@router.post("/runs/{run_id}/messages", status_code=status.HTTP_202_ACCEPTED)
def resume_run(
    run_id: str,
    payload: AgentRunMessage,
    project: Annotated[Project, Depends(get_project_auth)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, object]:
    require_active(project)
    run = require_agent_run(db, project, run_id)
    job, created = resume_agent_run(db, project, run, payload.message)
    result = agent_run_out(db, run)
    db.commit()
    if created:
        dispatch_job(job.id)
    return result
