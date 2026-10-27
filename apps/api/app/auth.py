from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime
from typing import Annotated

from alinea_contracts.errors import AlineaError
from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.db.models import Project

bearer_scheme = HTTPBearer(auto_error=False)


def generate_project_token() -> str:
    return secrets.token_urlsafe(32)


def hash_project_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def issue_project_token(project: Project) -> str:
    token = generate_project_token()
    project.token_hash = hash_project_token(token)
    return token


def _error(code: str, message: str, status_code: int) -> AlineaError:
    return AlineaError(code, message, status_code=status_code)


def authenticate_project(
    db: Session,
    token: str,
    project_id: str | None = None,
) -> Project:
    if not token:
        raise _error("UNAUTHORIZED", "A valid Bearer project token is required.", 401)
    project = db.scalar(select(Project).where(Project.token_hash == hash_project_token(token)))
    if project is None:
        raise _error("UNAUTHORIZED", "A valid Bearer project token is required.", 401)
    expires_at = project.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    if expires_at <= datetime.now(UTC):
        raise _error("SESSION_EXPIRED", "The project session has expired.", 401)
    if project_id is not None and project.id != project_id:
        raise _error("FORBIDDEN", "The token does not grant access to this project.", 403)
    return project


def get_project_auth(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    db: Annotated[Session, Depends(get_db)],
) -> Project:
    token = ""
    if credentials is not None and credentials.scheme.lower() == "bearer":
        token = credentials.credentials
    project_id = request.path_params.get("project_id") or request.path_params.get("p")
    return authenticate_project(db, token, project_id)
