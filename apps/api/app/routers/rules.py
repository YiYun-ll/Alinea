from __future__ import annotations

from typing import Annotated, Any

from alinea_contracts.errors import AlineaError
from fastapi import APIRouter, Depends, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.datastructures import UploadFile as StarletteUploadFile

from app.auth import get_project_auth
from app.config import get_settings
from app.db.database import get_db
from app.db.models import Guideline, Project, RuleSetRecord
from app.jobs.runner import dispatch_job
from app.schemas import ExtractRulesRequest, GuidelineCreate, ManualRuleSetCreate, RuleSetUpdate
from app.services.common import (
    isoformat,
    require_active,
    require_found,
    require_ownership,
    safe_filename,
)
from app.services.jobs import create_job, enforce_job_capacity
from app.services.rules import (
    approve_draft,
    create_guideline,
    create_manual_draft,
    create_pdf_guideline,
    load_preset,
    require_ruleset,
    save_draft,
)
from app.services.serializers import ruleset_out

router = APIRouter(prefix="/projects/{project_id}", tags=["rules"])


def _guideline_out(guideline: Guideline) -> dict[str, object]:
    return {
        "guideline_id": guideline.id,
        "name": guideline.source_filename,
        "kind": guideline.kind,
        "created_at": isoformat(guideline.created_at),
    }


def _owned_guideline(db: Session, project: Project, guideline_id: str) -> Guideline:
    guideline = require_found(
        db.get(Guideline, guideline_id),
        "GUIDELINE_NOT_FOUND",
        "The guideline was not found",
    )
    require_ownership(project, guideline.project_id)
    return guideline


@router.post("/guidelines", status_code=status.HTTP_201_CREATED)
async def create_guideline_endpoint(
    request: Request,
    project: Annotated[Project, Depends(get_project_auth)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, object]:
    require_active(project)
    content_type = request.headers.get("content-type", "")
    if content_type.startswith("multipart/form-data"):
        form = await request.form()
        file = form.get("file")
        if not isinstance(file, StarletteUploadFile):
            raise AlineaError("VALIDATION_ERROR", "A PDF file field is required", status_code=422)
        filename = safe_filename(file.filename, "guideline.pdf")
        if not filename.lower().endswith(".pdf"):
            raise AlineaError(
                "UNSUPPORTED_FILE_FORMAT", "Only PDF guidelines are supported", status_code=415
            )
        maximum = get_settings().max_file_bytes
        data = await file.read(maximum + 1)
        if len(data) > maximum:
            raise AlineaError(
                "FILE_TOO_LARGE", "The PDF exceeds the configured limit", status_code=413
            )
        guideline = create_pdf_guideline(db, project, data, filename)
    else:
        payload = GuidelineCreate.model_validate(await request.json())
        guideline = create_guideline(
            db,
            project,
            kind=payload.kind,
            name=payload.name,
            preset_id=payload.preset_id,
            text=payload.text,
        )
    db.commit()
    return _guideline_out(guideline)


@router.post("/rules/extract", status_code=status.HTTP_202_ACCEPTED)
def extract(
    payload: ExtractRulesRequest,
    project: Annotated[Project, Depends(get_project_auth)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    require_active(project)
    guideline = _owned_guideline(db, project, payload.guideline_id)
    if payload.preset_id:
        load_preset(payload.preset_id)
    enforce_job_capacity(db, project.id)
    request_payload = payload.model_dump(mode="json")
    job, created = create_job(
        db,
        project,
        "rule_extraction",
        None,
        request_payload,
    )
    db.commit()
    if created:
        dispatch_job(job.id)
    return {
        "job_id": job.id,
        "status": job.status,
        "status_url": f"/api/v1/jobs/{job.id}",
        "events_url": f"/api/v1/jobs/{job.id}/events",
        "guideline_id": guideline.id,
    }


@router.get("/rules")
def latest(
    project: Annotated[Project, Depends(get_project_auth)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, object]:
    require_active(project)
    record = db.scalar(
        select(RuleSetRecord)
        .where(RuleSetRecord.project_id == project.id)
        .order_by(RuleSetRecord.version.desc())
        .limit(1)
    )
    record = require_found(record, "RULE_SET_NOT_FOUND", "No rule set has been created")
    return ruleset_out(record)


@router.get("/rulesets/{rule_set_id}")
def get_ruleset(
    rule_set_id: str,
    project: Annotated[Project, Depends(get_project_auth)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, object]:
    return ruleset_out(require_ruleset(db, project, rule_set_id))


@router.post("/rulesets", status_code=status.HTTP_201_CREATED)
def create_manual_ruleset(
    payload: ManualRuleSetCreate,
    project: Annotated[Project, Depends(get_project_auth)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, object]:
    require_active(project)
    record = create_manual_draft(
        db,
        project,
        name=payload.name,
        rules=payload.rules,
        guideline_id=payload.guideline_id,
    )
    db.commit()
    return ruleset_out(record)


@router.put("/rulesets/{rule_set_id}")
def update_ruleset(
    rule_set_id: str,
    payload: RuleSetUpdate,
    project: Annotated[Project, Depends(get_project_auth)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, object]:
    require_active(project)
    record = require_ruleset(db, project, rule_set_id)
    saved = save_draft(db, project, record, name=payload.name, rules=payload.rules)
    db.commit()
    return ruleset_out(saved)


@router.put("/rules/{rule_set_id}/approve")
def approve(
    rule_set_id: str,
    project: Annotated[Project, Depends(get_project_auth)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, object]:
    require_active(project)
    record = require_ruleset(db, project, rule_set_id)
    approved = approve_draft(db, project, record)
    db.commit()
    return ruleset_out(approved)
