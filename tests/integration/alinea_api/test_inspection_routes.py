from __future__ import annotations

import pytest
from alinea_contracts import AlineaError
from alinea_docx.inspector import DEFAULT_INSPECTOR_VERSION
from app.config import Settings, get_settings
from app.db import database
from app.db.models import InspectionRecord, Job, JobEvent, RepairPlanRecord
from app.main import create_app
from app.services.common import new_id, utc_now
from app.services.inspections import execute_inspection
from app.services.jobs import emit_job_event, mark_job_failed
from fastapi.testclient import TestClient
from sqlalchemy import func, select


def _demo(client: TestClient) -> dict[str, object]:
    response = client.post("/api/v1/demo", json={})
    assert response.status_code == 201, response.text
    return response.json()


@pytest.fixture
def api(tmp_path, monkeypatch):
    previous_url = str(database.engine.url)
    settings = Settings(
        database_url=f"sqlite:///{(tmp_path / 'inspection-routes.db').as_posix()}",
        storage_root=tmp_path / "storage",
        local_workers=1,
        llm_api_key="",
    )
    get_settings.cache_clear()
    dispatched: list[str] = []
    monkeypatch.setattr("app.routers.inspections.dispatch_job", lambda job_id: dispatched.append(job_id))
    try:
        with TestClient(create_app(settings)) as client:
            created = _demo(client)
            headers = {"Authorization": f"Bearer {created['token']}"}
            rules_response = client.get(
                f"/api/v1/projects/{created['project_id']}/rules", headers=headers
            )
            assert rules_response.status_code == 200, rules_response.text
            approve = client.put(
                f"/api/v1/projects/{created['project_id']}/rules/{created['rule_set_id']}/approve",
                headers=headers,
            )
            assert approve.status_code == 200, approve.text
            yield client, created, approve.json(), headers, dispatched
    finally:
        database.configure_database(previous_url)
        get_settings.cache_clear()


def _payload(
    created: dict[str, object], rules: dict[str, object], include_page_mapping: bool = False
) -> dict[str, object]:
    return {
        "revision_id": created["revision_id"],
        "rule_set_id": rules["rule_set_id"],
        "rule_set_version": rules["version"],
        "include_page_mapping": include_page_mapping,
    }


def _submit(
    client: TestClient,
    headers: dict[str, str],
    created: dict[str, object],
    rules: dict[str, object],
    key: str,
    include_page_mapping: bool = False,
):
    return client.post(
        f"/api/v1/projects/{created['project_id']}/inspections",
        headers={**headers, "Idempotency-Key": key},
        json=_payload(created, rules, include_page_mapping),
    )


def _succeed(
    job_id: str, preview: dict[str, object] | None = None
) -> tuple[str, dict[str, object]]:
    with database.session_scope() as db:
        job = db.get(Job, job_id)
        assert job is not None and job.result_id is not None
        record = db.get(InspectionRecord, job.result_id)
        assert record is not None
        record.status = "SUCCEEDED"
        record.summary_json = {"sentinel": "preserve-summary"}
        record.issues_json = [{"sentinel": "preserve-issues"}]
        record.preview_json = preview
        record.warnings_json = ["preserve-warning"]
        emit_job_event(
            db,
            job,
            event_type="job.completed",
            stage="SUCCEEDED",
            progress=100,
            message="Completed test inspection",
            result={"inspection_id": record.id},
        )
        return record.id, {
            "summary": record.summary_json,
            "issues": record.issues_json,
            "preview": record.preview_json,
            "warnings": record.warnings_json,
        }


def _assert_record_sentinel(inspection_id: str, sentinel: dict[str, object]) -> None:
    with database.session_scope() as db:
        record = db.get(InspectionRecord, inspection_id)
        assert record is not None
        assert record.status == "SUCCEEDED"
        assert record.summary_json == sentinel["summary"]
        assert record.issues_json == sentinel["issues"]
        assert record.preview_json == sentinel["preview"]
        assert record.warnings_json == sentinel["warnings"]


def test_successful_inspection_reuse_preserves_record_and_plan(api) -> None:
    client, created, rules, headers, dispatched = api
    first = _submit(client, headers, created, rules, "success-original")
    assert first.status_code == 202, first.text
    assert first.json()["reused"] is False
    job_id = first.json()["job_id"]
    inspection_id, sentinel = _succeed(job_id)
    with database.session_scope() as db:
        plan = RepairPlanRecord(
            id=new_id(),
            project_id=str(created["project_id"]),
            base_revision_id=str(created["revision_id"]),
            inspection_id=inspection_id,
            rule_set_id=str(rules["rule_set_id"]),
            rule_set_version=int(rules["version"]),
            rule_set_digest=str(rules["digest"]),
            status="SUCCEEDED",
            plan_digest="d" * 64,
            selected_issues_json=["preserve-issue"],
            operations_json=[{"sentinel": "preserve-plan"}],
            affected_node_count=1,
            approved_at=utc_now(),
            execution_key=f"execution-{new_id()}",
            result_revision_id=str(created["revision_id"]),
        )
        db.add(plan)
        plan_id = plan.id
    assert execute_inspection(job_id) == inspection_id
    completed_job = client.get(f"/api/v1/jobs/{job_id}", headers=headers).json()

    repeated = _submit(client, headers, created, rules, "success-reused")
    assert repeated.status_code == 202, repeated.text
    assert repeated.json()["reused"] is True
    assert repeated.json()["job_id"] == job_id
    assert repeated.json()["inspection_id"] == inspection_id
    replayed = _submit(client, headers, created, rules, "success-reused")
    assert replayed.json()["job_id"] == job_id
    assert client.get(f"/api/v1/jobs/{job_id}", headers=headers).json() == completed_job
    assert dispatched == [job_id]
    _assert_record_sentinel(inspection_id, sentinel)
    with database.session_scope() as db:
        plan = db.get(RepairPlanRecord, plan_id)
        assert plan is not None
        assert plan.status == "SUCCEEDED"
        assert plan.operations_json == [{"sentinel": "preserve-plan"}]
        assert plan.result_revision_id == created["revision_id"]
        inspection_count = db.scalar(select(func.count(InspectionRecord.id)))
        inspection_jobs = db.scalar(
            select(func.count(Job.id)).where(Job.job_type == "inspection")
        )
        assert inspection_count == 1
        assert inspection_jobs == 1


@pytest.mark.parametrize("active_status", ["QUEUED", "RUNNING"])
def test_active_inspection_job_is_reused(api, active_status: str) -> None:
    client, created, rules, headers, dispatched = api
    first = _submit(client, headers, created, rules, f"active-{active_status}")
    job_id = first.json()["job_id"]
    inspection_id = first.json()["inspection_id"]
    if active_status == "RUNNING":
        with database.session_scope() as db:
            job = db.get(Job, job_id)
            assert job is not None
            emit_job_event(
                db,
                job,
                event_type="job.started",
                stage="RUNNING",
                progress=5,
                message="Running test inspection",
            )

    repeated = _submit(client, headers, created, rules, f"active-{active_status}-new-key")
    assert repeated.status_code == 202, repeated.text
    assert repeated.json()["reused"] is True
    assert repeated.json()["job_id"] == job_id
    assert repeated.json()["inspection_id"] == inspection_id
    assert repeated.json()["status"] == active_status
    assert set(dispatched) == {job_id}
    with database.session_scope() as db:
        assert db.scalar(select(func.count(InspectionRecord.id))) == 1
        assert db.scalar(select(func.count(Job.id)).where(Job.job_type == "inspection")) == 1


def test_same_key_different_payload_conflicts(api) -> None:
    client, created, rules, headers, dispatched = api
    first = _submit(client, headers, created, rules, "same-key")
    conflict = _submit(
        client, headers, created, rules, "same-key", include_page_mapping=True
    )
    assert conflict.status_code == 409, conflict.text
    assert conflict.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"
    assert first.json()["reused"] is False
    assert dispatched == [first.json()["job_id"]]
    with database.session_scope() as db:
        assert db.scalar(select(func.count(InspectionRecord.id))) == 1
        assert db.scalar(select(func.count(Job.id)).where(Job.job_type == "inspection")) == 1


def test_mapping_incompatible_result_is_not_reused(api) -> None:
    client, created, rules, headers, dispatched = api
    first = _submit(client, headers, created, rules, "mapping-original")
    inspection_id, sentinel = _succeed(first.json()["job_id"])
    conflict = _submit(
        client, headers, created, rules, "mapping-conflict", include_page_mapping=True
    )
    assert conflict.status_code == 409, conflict.text
    assert conflict.json()["error"]["code"] == "INSPECTION_MAPPING_INCOMPATIBLE"
    structural = _submit(client, headers, created, rules, "mapping-structural")
    assert structural.status_code == 202, structural.text
    assert structural.json()["reused"] is True
    assert structural.json()["inspection_id"] == inspection_id
    assert dispatched == [first.json()["job_id"]]
    _assert_record_sentinel(inspection_id, sentinel)


def test_mapping_request_proof_and_completion_window_reuse_active_job(api) -> None:
    client, created, rules, headers, dispatched = api
    first = _submit(
        client, headers, created, rules, "mapping-degraded", include_page_mapping=True
    )
    job_id = first.json()["job_id"]
    inspection_id = first.json()["inspection_id"]
    with database.session_scope() as db:
        job = db.get(Job, job_id)
        record = db.get(InspectionRecord, inspection_id)
        assert job is not None and record is not None
        emit_job_event(
            db,
            job,
            event_type="job.started",
            stage="RUNNING",
            progress=90,
            message="Finalizing inspection",
        )
        record.status = "SUCCEEDED"
        record.summary_json = {"sentinel": "degraded"}
        record.preview_json = None

    finishing = _submit(
        client, headers, created, rules, "mapping-finishing", include_page_mapping=True
    )
    assert finishing.status_code == 202, finishing.text
    assert finishing.json()["reused"] is True
    assert finishing.json()["job_id"] == job_id
    assert finishing.json()["status"] == "RUNNING"
    with database.session_scope() as db:
        job = db.get(Job, job_id)
        assert job is not None
        emit_job_event(
            db,
            job,
            event_type="job.completed",
            stage="SUCCEEDED",
            progress=100,
            message="Completed degraded inspection",
            result={"inspection_id": inspection_id},
        )
    completed = _submit(
        client, headers, created, rules, "mapping-degraded-success", include_page_mapping=True
    )
    assert completed.status_code == 202, completed.text
    assert completed.json()["job_id"] == job_id
    assert completed.json()["status"] == "SUCCEEDED"
    assert dispatched == [job_id]
    with database.session_scope() as db:
        record = db.get(InspectionRecord, inspection_id)
        assert record is not None
        assert record.summary_json == {"sentinel": "degraded"}
        assert record.preview_json is None


def test_after_inspection_gets_real_cached_job_without_dispatch(api) -> None:
    client, created, rules, headers, dispatched = api
    inspection_id = new_id()
    with database.session_scope() as db:
        db.add(
            InspectionRecord(
                id=inspection_id,
                project_id=str(created["project_id"]),
                revision_id=str(created["revision_id"]),
                rule_set_id=str(rules["rule_set_id"]),
                rule_set_digest=str(rules["digest"]),
                inspector_version=DEFAULT_INSPECTOR_VERSION,
                status="SUCCEEDED",
                summary_json={"sentinel": "after-summary"},
                issues_json=[{"sentinel": "after-issue"}],
                preview_json={"include_page_mapping": True, "pdf_sha256": "a" * 64},
                warnings_json=["after-warning"],
                created_at=utc_now(),
            )
        )

    cached = _submit(
        client, headers, created, rules, "after-cached", include_page_mapping=True
    )
    assert cached.status_code == 202, cached.text
    assert cached.json()["reused"] is True
    assert cached.json()["inspection_id"] == inspection_id
    assert cached.json()["status"] == "SUCCEEDED"
    assert cached.json()["stage"] == "CACHED"
    assert cached.json()["status_url"] == f"/api/v1/jobs/{cached.json()['job_id']}"
    assert dispatched == []
    status = client.get(cached.json()["status_url"], headers=headers)
    assert status.status_code == 200
    assert status.json()["result"] == {"inspection_id": inspection_id}
    with database.session_scope() as db:
        events = list(
            db.scalars(
                select(JobEvent)
                .where(JobEvent.job_id == cached.json()["job_id"])
                .order_by(JobEvent.id)
            )
        )
        assert [event.payload_json["event"] for event in events] == [
            "job.queued",
            "job.completed",
        ]
        assert events[-1].stage == "CACHED"
    repeated = _submit(
        client, headers, created, rules, "after-cached-new-key", include_page_mapping=True
    )
    assert repeated.json()["job_id"] == cached.json()["job_id"]
    assert repeated.json()["reused"] is True
    assert dispatched == []
    with database.session_scope() as db:
        record = db.get(InspectionRecord, inspection_id)
        assert record is not None
        assert record.summary_json == {"sentinel": "after-summary"}
        assert record.issues_json == [{"sentinel": "after-issue"}]
        assert db.scalar(select(func.count(Job.id)).where(Job.job_type == "inspection")) == 1


def test_after_inspection_without_mapping_proof_conflicts(api) -> None:
    client, created, rules, headers, dispatched = api
    with database.session_scope() as db:
        db.add(
            InspectionRecord(
                id=new_id(),
                project_id=str(created["project_id"]),
                revision_id=str(created["revision_id"]),
                rule_set_id=str(rules["rule_set_id"]),
                rule_set_digest=str(rules["digest"]),
                inspector_version=DEFAULT_INSPECTOR_VERSION,
                status="SUCCEEDED",
                summary_json={"sentinel": "structure-only"},
                issues_json=[],
                preview_json=None,
                warnings_json=[],
                created_at=utc_now(),
            )
        )
    conflict = _submit(
        client, headers, created, rules, "after-no-mapping", include_page_mapping=True
    )
    assert conflict.status_code == 409, conflict.text
    assert conflict.json()["error"]["code"] == "INSPECTION_MAPPING_INCOMPATIBLE"
    assert dispatched == []
    with database.session_scope() as db:
        assert db.scalar(select(func.count(Job.id)).where(Job.job_type == "inspection")) == 0


def test_failed_inspection_requires_explicit_retry(api) -> None:
    client, created, rules, headers, dispatched = api
    first = _submit(client, headers, created, rules, "failed-original")
    job_id = first.json()["job_id"]
    inspection_id = first.json()["inspection_id"]
    with database.session_scope() as db:
        job = db.get(Job, job_id)
        record = db.get(InspectionRecord, inspection_id)
        assert job is not None and record is not None
        record.summary_json = {"sentinel": "failed-summary"}
        record.issues_json = [{"sentinel": "failed-issue"}]
        mark_job_failed(
            db,
            job,
            AlineaError("TEMPORARY", "Temporary failure", status_code=503, retryable=True),
        )

    repeated = _submit(client, headers, created, rules, "failed-new-submission")
    assert repeated.status_code == 202, repeated.text
    assert repeated.json()["reused"] is True
    assert repeated.json()["status"] == "FAILED"
    assert repeated.json()["job_id"] == job_id
    assert repeated.json()["inspection_id"] == inspection_id
    assert dispatched == [job_id]
    with database.session_scope() as db:
        record = db.get(InspectionRecord, inspection_id)
        assert record is not None
        assert record.status == "FAILED"
        assert record.summary_json == {"sentinel": "failed-summary"}
        assert record.issues_json == [{"sentinel": "failed-issue"}]
        assert db.scalar(select(func.count(Job.id)).where(Job.job_type == "inspection")) == 1


def test_cancelled_inspection_can_be_resubmitted_without_new_record(api) -> None:
    client, created, rules, headers, dispatched = api
    first = _submit(client, headers, created, rules, "cancel-original")
    old_job_id = first.json()["job_id"]
    inspection_id = first.json()["inspection_id"]
    with database.session_scope() as db:
        record = db.get(InspectionRecord, inspection_id)
        assert record is not None
        record.summary_json = {"sentinel": "unfinished"}
    cancelled = client.post(f"/api/v1/jobs/{old_job_id}/cancel", headers=headers)
    assert cancelled.status_code == 200, cancelled.text

    resubmitted = _submit(client, headers, created, rules, "cancel-new-submission")
    assert resubmitted.status_code == 202, resubmitted.text
    assert resubmitted.json()["reused"] is True
    assert resubmitted.json()["inspection_id"] == inspection_id
    assert resubmitted.json()["job_id"] != old_job_id
    assert resubmitted.json()["status"] == "QUEUED"
    new_job_id = resubmitted.json()["job_id"]
    assert dispatched == [old_job_id, new_job_id]
    with database.session_scope() as db:
        old_job = db.get(Job, old_job_id)
        record = db.get(InspectionRecord, inspection_id)
        assert old_job is not None and old_job.status == "CANCELLED"
        assert record is not None
        assert record.status == "QUEUED"
        assert record.summary_json == {"sentinel": "unfinished"}
        assert db.scalar(select(func.count(InspectionRecord.id))) == 1
        assert db.scalar(select(func.count(Job.id)).where(Job.job_type == "inspection")) == 2


def test_inspection_idempotency_is_isolated_by_project(api) -> None:
    client, created, rules, headers, dispatched = api
    other = _demo(client)
    other_headers = {"Authorization": f"Bearer {other['token']}"}
    other_rules_response = client.get(
        f"/api/v1/projects/{other['project_id']}/rules", headers=other_headers
    )
    assert other_rules_response.status_code == 200
    other_approve = client.put(
        f"/api/v1/projects/{other['project_id']}/rules/{other['rule_set_id']}/approve",
        headers=other_headers,
    )
    assert other_approve.status_code == 200
    other_rules = other_approve.json()

    first = _submit(client, headers, created, rules, "shared-key")
    second = _submit(client, other_headers, other, other_rules, "shared-key")
    assert first.status_code == 202 and second.status_code == 202
    assert first.json()["reused"] is False and second.json()["reused"] is False
    assert first.json()["job_id"] != second.json()["job_id"]
    assert first.json()["inspection_id"] != second.json()["inspection_id"]
    assert second.json()["project_id"] == other["project_id"]
    forbidden = client.get(
        f"/api/v1/inspections/{first.json()['inspection_id']}", headers=other_headers
    )
    assert forbidden.status_code == 403
    assert len(dispatched) == 2
