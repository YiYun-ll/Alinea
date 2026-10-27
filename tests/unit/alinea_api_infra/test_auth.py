from __future__ import annotations

import base64
from datetime import UTC, datetime, timedelta
from typing import Annotated
from uuid import uuid4

import pytest
from alinea_contracts.errors import AlineaError
from app.auth import (
    authenticate_project,
    generate_project_token,
    get_project_auth,
    hash_project_token,
    issue_project_token,
)
from app.db.database import get_db, session_scope
from app.db.models import Project
from fastapi import Depends, FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient


def _create_project(database, *, expired: bool = False) -> tuple[str, str]:
    project = Project(
        id=str(uuid4()),
        name="Private project",
        token_hash="",
        expires_at=datetime.now(UTC) + timedelta(hours=-1 if expired else 1),
    )
    token = issue_project_token(project)
    with session_scope() as db:
        db.add(project)
    return project.id, token


def test_token_has_32_random_bytes_and_only_hash_is_persisted(database):
    project_id, token = _create_project(database)
    decoded = base64.urlsafe_b64decode(token + "=" * (-len(token) % 4))
    assert len(decoded) == 32
    assert token != generate_project_token()
    assert len(hash_project_token(token)) == 64
    with database.SessionLocal() as db:
        project = db.get(Project, project_id)
        assert project.token_hash == hash_project_token(token)
        assert token not in project.token_hash
        assert authenticate_project(db, token, project_id).id == project_id


def test_authentication_rejects_invalid_expired_and_cross_project_tokens(database):
    project_id, token = _create_project(database)
    other_id, _ = _create_project(database)
    _, expired_token = _create_project(database, expired=True)
    with database.SessionLocal() as db:
        with pytest.raises(AlineaError) as invalid:
            authenticate_project(db, "invalid")
        assert (invalid.value.code, invalid.value.status_code) == ("UNAUTHORIZED", 401)

        with pytest.raises(AlineaError) as expired:
            authenticate_project(db, expired_token)
        assert (expired.value.code, expired.value.status_code) == ("SESSION_EXPIRED", 401)

        with pytest.raises(AlineaError) as forbidden:
            authenticate_project(db, token, other_id)
        assert (forbidden.value.code, forbidden.value.status_code) == ("FORBIDDEN", 403)
        assert authenticate_project(db, token, project_id).id == project_id


def test_fastapi_bearer_dependency_and_project_binding(database):
    project_id, token = _create_project(database)
    other_id, _ = _create_project(database)
    app = FastAPI()

    @app.exception_handler(AlineaError)
    async def handle_alinea_error(_, error: AlineaError):
        return JSONResponse(status_code=error.status_code, content={"code": error.code})

    @app.get("/projects/{project_id}")
    def protected_project(
        project_id: str,
        project: Annotated[Project, Depends(get_project_auth)],
    ):
        return {"project_id": project.id, "path_project_id": project_id}

    def override_db():
        with database.SessionLocal() as db:
            yield db

    app.dependency_overrides[get_db] = override_db
    with TestClient(app) as client:
        response = client.get(
            f"/projects/{project_id}", headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 200
        assert response.json()["project_id"] == project_id

        assert client.get(f"/projects/{project_id}").status_code == 401
        basic = client.get(f"/projects/{project_id}", headers={"Authorization": "Basic invalid"})
        assert basic.status_code == 401
        assert basic.json()["code"] == "UNAUTHORIZED"

        mismatch = client.get(f"/projects/{other_id}", headers={"Authorization": f"Bearer {token}"})
        assert mismatch.status_code == 403
        assert mismatch.json()["code"] == "FORBIDDEN"
