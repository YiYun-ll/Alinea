from __future__ import annotations

import hashlib
from datetime import timedelta
from types import SimpleNamespace

import pytest
from alinea_contracts import AlineaError, Issue, QualityGateResult, RenderArtifact
from app.config import Settings, get_settings
from app.db import database
from app.db.models import InspectionRecord, Job, Project, RepairPlanRecord, RuleSetRecord
from app.jobs.tasks import inspect_document_job, repair_plan_job
from app.main import create_app
from app.services.common import new_id, read_snapshot, storage, utc_now
from app.services.inspections import render_revision_preview
from app.services.jobs import mark_job_failed
from fastapi.testclient import TestClient


@pytest.fixture
def repair_api(tmp_path, monkeypatch):
    previous_url = str(database.engine.url)
    settings = Settings(
        database_url=f"sqlite:///{(tmp_path / 'regressions.db').as_posix()}",
        storage_root=tmp_path / "objects",
        llm_api_key="",
    )
    get_settings.cache_clear()
    monkeypatch.setattr("app.routers.inspections.dispatch_job", lambda _job_id: None)
    monkeypatch.setattr("app.routers.repairs.dispatch_job", lambda _job_id: None)
    monkeypatch.setattr("app.jobs.runner.dispatch_job", lambda _job_id: None)
    try:
        with TestClient(create_app(settings)) as client:
            created = client.post("/api/v1/demo").json()
            headers = {"Authorization": f"Bearer {created['token']}"}
            project_path = f"/api/v1/projects/{created['project_id']}"
            rules = client.put(f"{project_path}/rules/{created['rule_set_id']}/approve", headers=headers).json()
            submitted = client.post(
                f"{project_path}/inspections",
                headers={**headers, "Idempotency-Key": "initial"},
                json={
                    "revision_id": created["revision_id"],
                    "rule_set_id": rules["rule_set_id"],
                    "rule_set_version": rules["version"],
                    "include_page_mapping": False,
                },
            )
            assert submitted.status_code == 202, submitted.text
            inspection_id = submitted.json()["inspection_id"]
            inspect_document_job(submitted.json()["job_id"])
            issues = client.get(f"/api/v1/inspections/{inspection_id}/issues", headers=headers).json()["data"]
            selected = next(
                issue
                for issue in issues
                if issue["repair"]["eligibility"] == "SAFE_SINGLE_TARGET"
                and issue["detection_status"] == "CONFIRMED_VIOLATION"
            )
            response = client.post(
                f"{project_path}/repair-plans",
                headers=headers,
                json={
                    "base_revision_id": created["revision_id"],
                    "inspection_id": inspection_id,
                    "selected_issue_ids": [selected["issue_id"]],
                },
            )
            assert response.status_code == 201, response.text
            plan = response.json()
            approved = client.post(
                f"/api/v1/repair-plans/{plan['plan_id']}/approve",
                headers=headers,
                json={"plan_digest": plan["plan_digest"]},
            )
            assert approved.status_code == 200, approved.text
            queued = client.post(
                f"/api/v1/repair-plans/{plan['plan_id']}/execute", headers={**headers, "Idempotency-Key": "execute"}
            )
            assert queued.status_code == 202, queued.text
            yield client, created, headers, selected, inspection_id, plan, queued.json()["job_id"]
    finally:
        database.configure_database(previous_url)
        get_settings.cache_clear()


def test_repair_can_be_retried_after_a_retry_also_fails(repair_api):
    client, _, headers, _, _, plan, job_id = repair_api
    with database.session_scope() as db:
        mark_job_failed(db, db.get(Job, job_id), AlineaError("TEMPORARY", "temporary", retryable=True))
    first = client.post(f"/api/v1/jobs/{job_id}/retry", headers=headers)
    assert first.status_code == 202, first.text
    retry_id = first.json()["job_id"]
    with database.session_scope() as db:
        mark_job_failed(db, db.get(Job, retry_id), AlineaError("TEMPORARY", "temporary", retryable=True))
        assert db.get(RepairPlanRecord, plan["plan_id"]).status == "FAILED"
    second = client.post(f"/api/v1/jobs/{retry_id}/retry", headers=headers)
    assert second.status_code == 202, second.text
    assert second.json()["job_id"] not in {job_id, retry_id}


def test_blocked_repair_keeps_its_diagnostic_report_and_does_not_publish(repair_api, monkeypatch):
    client, created, headers, _, _, plan, job_id = repair_api
    monkeypatch.setattr(
        "app.services.repairs.apply_approved_patch",
        lambda *_args, **_kwargs: SimpleNamespace(
            publishable=False,
            candidate_path=None,
            gates=[QualityGateResult(gate="G2", status="FAIL", details={"reason": "text changed"})],
        ),
    )
    repair_plan_job(job_id)
    job = client.get(f"/api/v1/jobs/{job_id}", headers=headers).json()
    assert job["status"] == "FAILED"
    assert job["result_revision_id"], "The blocked candidate diagnostic must survive rollback"
    revision = job["result_revision_id"]
    report = client.get(f"/api/v1/revisions/{revision}/report", headers=headers)
    assert report.status_code == 200, report.text
    assert report.json()["status"] == "BLOCKED"
    assert client.get(f"/api/v1/revisions/{revision}/download", headers=headers).status_code == 403
    project = client.get(f"/api/v1/projects/{created['project_id']}", headers=headers).json()
    assert project["active_revision_id"] == created["revision_id"]
    assert client.get(f"/api/v1/repair-plans/{plan['plan_id']}", headers=headers).json()["status"] == "FAILED"


def test_new_structural_inspection_does_not_hide_an_existing_pdf(repair_api):
    client, created, headers, _, inspection_id, _, _ = repair_api
    pdf = b"%PDF-test-preview"
    key = storage().build_key(
        created["project_id"], "previews", created["revision_id"], "preview.pdf", profile_id="test-profile"
    )
    storage().write(key, pdf)
    with database.session_scope() as db:
        original = db.get(InspectionRecord, inspection_id)
        original.preview_json = {"storage_key": key, "pdf_sha256": hashlib.sha256(pdf).hexdigest()}
        rule = RuleSetRecord(
            id=new_id(),
            project_id=created["project_id"],
            version=2,
            name="other",
            status="APPROVED",
            digest="c" * 64,
            rules_json=[],
            conflicts_json=[],
            created_at=utc_now(),
        )
        db.add(rule)
        db.flush()
        db.add(
            InspectionRecord(
                id=new_id(),
                project_id=created["project_id"],
                revision_id=created["revision_id"],
                rule_set_id=rule.id,
                rule_set_digest=rule.digest,
                inspector_version=original.inspector_version,
                status="SUCCEEDED",
                summary_json={},
                issues_json=[],
                preview_json=None,
                warnings_json=[],
                created_at=utc_now() + timedelta(seconds=1),
            )
        )
    response = client.get(f"/api/v1/revisions/{created['revision_id']}/preview", headers=headers)
    assert response.status_code == 200, response.text
    assert response.content == pdf
    new_pdf = b"%PDF-new-render-profile"
    new_digest = hashlib.sha256(new_pdf).hexdigest()
    new_key = storage().build_key(
        created["project_id"], "previews", created["revision_id"], "new.pdf", profile_id="new-profile"
    )
    storage().write(new_key, new_pdf)
    with database.session_scope() as db:
        original = db.get(InspectionRecord, inspection_id)
        db.add(
            InspectionRecord(
                id=new_id(),
                project_id=original.project_id,
                revision_id=original.revision_id,
                rule_set_id=original.rule_set_id,
                rule_set_digest=original.rule_set_digest,
                inspector_version="another-render-test",
                status="SUCCEEDED",
                summary_json={},
                issues_json=[],
                preview_json={"storage_key": new_key, "pdf_sha256": new_digest},
                warnings_json=[],
                created_at=utc_now() + timedelta(seconds=2),
            )
        )
    pinned = client.get(
        f"/api/v1/revisions/{created['revision_id']}/preview",
        headers=headers,
        params={"sha256": hashlib.sha256(pdf).hexdigest()},
    )
    assert pinned.status_code == 200 and pinned.content == pdf
    latest = client.get(f"/api/v1/revisions/{created['revision_id']}/preview", headers=headers)
    assert latest.status_code == 200 and latest.content == new_pdf
    unknown = client.get(
        f"/api/v1/revisions/{created['revision_id']}/preview", headers=headers, params={"sha256": "0" * 64}
    )
    assert unknown.status_code == 404


def test_repeated_render_of_same_revision_reuses_immutable_pdf(repair_api, tmp_path, monkeypatch):
    _, created, _, _, _, _, _ = repair_api
    source = tmp_path / "rendered.pdf"
    source.write_bytes(b"%PDF-rendered")
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    artifact = RenderArtifact(pdf_path=str(source), pdf_sha256=digest, render_profile_id="same-profile", page_count=1)
    monkeypatch.setattr(
        "app.services.inspections.LibreOfficeRenderer",
        lambda *_args, **_kwargs: SimpleNamespace(render=lambda *_args: artifact),
    )
    monkeypatch.setattr("app.services.inspections.locate_issues", lambda _snapshot, issues, *_args: issues)
    with database.session_scope() as db:
        from app.db.models import Revision

        project = db.get(Project, created["project_id"])
        revision = db.get(Revision, created["revision_id"])
        snapshot = read_snapshot(project.id, revision.id)
        _, first, _ = render_revision_preview(project, revision, snapshot, [])
        _, second, _ = render_revision_preview(project, revision, snapshot, [])
        assert first["pdf_sha256"] == second["pdf_sha256"] == digest
        source.write_bytes(b"%PDF-new-output")
        artifact.pdf_sha256 = hashlib.sha256(source.read_bytes()).hexdigest()
        _, changed, _ = render_revision_preview(project, revision, snapshot, [])
        assert changed["storage_key"] != first["storage_key"]
        assert storage().read(first["storage_key"]) == b"%PDF-rendered"


def test_explicit_app_storage_settings_are_used_by_services(repair_api, tmp_path):
    _, created, _, _, _, _, _ = repair_api
    assert (tmp_path / "objects" / "projects" / created["project_id"]).is_dir()


@pytest.mark.parametrize("detection", ["UNKNOWN", "POSSIBLE_VIOLATION"])
def test_unverifiable_selected_target_is_not_reported_as_resolved(repair_api, monkeypatch, detection):
    client, _, headers, selected, _, _, job_id = repair_api
    original_inspect = __import__("app.services.repairs", fromlist=["inspect_document"]).inspect_document

    def uncertain(snapshot, ruleset, **kwargs):
        result = original_inspect(snapshot, ruleset, **kwargs)
        issue = Issue.model_validate(selected).model_copy(
            update={
                "detection_status": detection,
                "revision_id": snapshot.revision_id,
                "inspection_id": kwargs["inspection_id"],
            }
        )
        return result.model_copy(update={"issues": [issue]})

    monkeypatch.setattr("app.services.repairs.inspect_document", uncertain)
    monkeypatch.setattr(
        "app.services.repairs.render_revision_preview",
        lambda _project, _revision, _snapshot, issues: (issues, {"render_profile_id": "test-profile"}, []),
    )
    revision = repair_plan_job(job_id)
    report = client.get(f"/api/v1/revisions/{revision}/report", headers=headers)
    assert report.status_code == 200, report.text
    assert report.json()["status"] == "INDETERMINATE"
    assert report.json()["resolved_count"] == 0
    assert report.json()["remaining_count"] == 1
