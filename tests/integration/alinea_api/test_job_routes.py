from __future__ import annotations

from alinea_contracts import AlineaError
from app.config import Settings, get_settings
from app.db import database
from app.db.models import Job, Project
from app.main import create_app
from app.services.common import new_id, utc_now
from app.services.jobs import create_job, job_out, mark_job_failed
from fastapi.testclient import TestClient
from sqlalchemy import event


def test_retry_and_cancel_routes_are_scoped_and_idempotent(tmp_path, monkeypatch) -> None:
    previous_url = str(database.engine.url)
    settings = Settings(
        database_url=f"sqlite:///{(tmp_path / 'routes.db').as_posix()}",
        storage_root=tmp_path / "storage",
        local_workers=1,
        llm_api_key="",
    )
    get_settings.cache_clear()
    monkeypatch.setattr("app.jobs.runner.dispatch_job", lambda job_id: None)
    try:
        with TestClient(create_app(settings)) as client:
            created = client.post("/api/v1/projects", json={"name": "job-routes"})
            assert created.status_code == 201
            project_id = created.json()["project_id"]
            headers = {"Authorization": f"Bearer {created.json()['token']}"}
            with database.session_scope() as db:
                project = db.get(Project, project_id)
                assert project is not None
                job, _ = create_job(db, project, "rule_extraction", "original", {"guideline_id": "guide"})
                mark_job_failed(
                    db,
                    job,
                    AlineaError("TEMPORARY_FAILURE", "temporary", status_code=503, retryable=True),
                )
                original_id = job.id
            retry = client.post(f"/api/v1/jobs/{original_id}/retry", headers=headers)
            assert retry.status_code == 202, retry.text
            new_id = retry.json()["job_id"]
            assert new_id != original_id
            assert retry.json()["retry_of"] == original_id
            cancel = client.post(f"/api/v1/jobs/{new_id}/cancel", headers=headers)
            assert cancel.status_code == 200, cancel.text
            assert cancel.json()["status"] == "CANCELLED"
            other = client.post("/api/v1/projects", json={"name": "other"})
            other_headers = {"Authorization": f"Bearer {other.json()['token']}"}
            forbidden = client.post(f"/api/v1/jobs/{original_id}/retry", headers=other_headers)
            assert forbidden.status_code == 403
    finally:
        database.configure_database(previous_url)
        get_settings.cache_clear()


def test_project_jobs_batch_events_and_match_single_job_serialization(tmp_path) -> None:
    previous_url = str(database.engine.url)
    settings = Settings(
        database_url=f"sqlite:///{(tmp_path / 'job-queries.db').as_posix()}",
        storage_root=tmp_path / "storage",
        local_workers=1,
        llm_api_key="",
    )
    get_settings.cache_clear()
    job_queries: list[str] = []
    event_queries: list[str] = []

    def count_queries(
        _connection, _cursor, statement: str, _parameters, _context, _executemany
    ) -> None:
        normalized = " ".join(statement.split()).upper()
        if "FROM JOBS" in normalized:
            job_queries.append(normalized)
        if "FROM JOB_EVENTS" in normalized:
            event_queries.append(normalized)

    try:
        with TestClient(create_app(settings)) as client:
            created = client.post("/api/v1/projects", json={"name": "job-queries"})
            assert created.status_code == 201
            project_id = created.json()["project_id"]
            headers = {"Authorization": f"Bearer {created.json()['token']}"}
            with database.session_scope() as db:
                project = db.get(Project, project_id)
                assert project is not None
                first, _ = create_job(
                    db, project, "rule_extraction", "query-first", {"guideline_id": "first"}
                )
                second, _ = create_job(
                    db, project, "rule_extraction", "query-second", {"guideline_id": "second"}
                )
                mark_job_failed(
                    db,
                    second,
                    AlineaError("TEMPORARY", "temporary", status_code=503, retryable=True),
                )
                empty = Job(
                    id=new_id(),
                    project_id=project.id,
                    job_type="rule_extraction",
                    status="QUEUED",
                    stage="QUEUED",
                    progress=0,
                    idempotency_key="query-empty",
                    created_at=utc_now(),
                    updated_at=utc_now(),
                )
                db.add(empty)
                db.flush()
                job_ids = [first.id, second.id, empty.id]
                empty_id = empty.id

            event.listen(database.engine, "before_cursor_execute", count_queries)
            try:
                response = client.get(f"/api/v1/projects/{project_id}/jobs", headers=headers)
            finally:
                event.remove(database.engine, "before_cursor_execute", count_queries)
            assert response.status_code == 200, response.text
            assert len(job_queries) == 1, job_queries
            assert len(event_queries) == 1, event_queries
            listed = {item["job_id"]: item for item in response.json()["data"]}
            assert set(listed) == set(job_ids)
            for job_id in job_ids:
                single = client.get(f"/api/v1/jobs/{job_id}", headers=headers)
                assert single.status_code == 200, single.text
                assert listed[job_id] == single.json()

            with database.session_scope() as db:
                empty = db.get(Job, empty_id)
                assert empty is not None
                job_queries.clear()
                event_queries.clear()
                event.listen(database.engine, "before_cursor_execute", count_queries)
                try:
                    direct = job_out(db, empty, [])
                finally:
                    event.remove(database.engine, "before_cursor_execute", count_queries)
                assert job_queries == []
                assert event_queries == []
                assert direct == listed[empty_id]
    finally:
        database.configure_database(previous_url)
        get_settings.cache_clear()
