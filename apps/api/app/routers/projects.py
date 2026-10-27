from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.orm import Session

from app.auth import get_project_auth
from app.db.database import get_db
from app.db.models import Project
from app.schemas import ProjectCreate
from app.services.common import project_lock, require_active
from app.services.projects import create_project, delete_project
from app.services.serializers import project_out

router = APIRouter(prefix="/projects", tags=["projects"])


@router.post("", status_code=status.HTTP_201_CREATED)
def create(
    payload: ProjectCreate,
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, object]:
    project, token = create_project(db, payload.name)
    db.commit()
    return {**project_out(db, project), "token": token}


@router.get("/{project_id}")
def get(
    project: Annotated[Project, Depends(get_project_auth)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, object]:
    require_active(project)
    return project_out(db, project)


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove(
    project: Annotated[Project, Depends(get_project_auth)],
    db: Annotated[Session, Depends(get_db)],
) -> Response:
    require_active(project)
    with project_lock(project.id):
        delete_project(db, project)
        db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
