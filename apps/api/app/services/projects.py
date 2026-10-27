from __future__ import annotations

from datetime import timedelta

from sqlalchemy.orm import Session

from app.auth import issue_project_token
from app.config import get_settings
from app.db.models import Project

from .common import add_audit, new_id, storage, utc_now


def create_project(db: Session, name: str) -> tuple[Project, str]:
    now = utc_now()
    project = Project(
        id=new_id(),
        name=name,
        status="ACTIVE",
        token_hash="",
        active_revision_id=None,
        created_at=now,
        expires_at=now + timedelta(hours=get_settings().project_ttl_hours),
    )
    token = issue_project_token(project)
    db.add(project)
    db.flush()
    add_audit(db, project.id, "project.created", entity_id=project.id)
    return project, token


def delete_project(db: Session, project: Project) -> None:
    project_id = project.id
    db.delete(project)
    db.flush()
    storage().delete_project(project_id)
