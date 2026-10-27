from __future__ import annotations

from app.db import database
from app.jobs.tasks import _run_job
from app.services.jobs import create_job
from app.services.projects import create_project


def test_job_is_claimed_atomically(tmp_path) -> None:
    previous = str(database.engine.url)
    database.configure_database(f"sqlite:///{(tmp_path / 'jobs.db').as_posix()}")
    database.create_all()
    try:
        with database.session_scope() as db:
            project, _ = create_project(db, "atomic-test")
            job, _ = create_job(db, project, "inspection", "once", {"value": 1})
            job_id = job.id
        calls = []
        first = _run_job(job_id, "inspection", lambda value: calls.append(value) or "result")
        second = _run_job(job_id, "inspection", lambda value: calls.append(value) or "other")
        assert first == second == "result"
        assert calls == [job_id]
    finally:
        database.configure_database(previous)
