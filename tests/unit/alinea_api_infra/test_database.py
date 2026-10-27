from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from app.db.database import session_scope
from app.db.models import (
    AuditEvent,
    Base,
    Guideline,
    InspectionRecord,
    Job,
    JobEvent,
    Project,
    QualityGateRun,
    RepairPlanRecord,
    Revision,
    RuleSetRecord,
)
from sqlalchemy import DateTime, func, inspect, select, text
from sqlalchemy.exc import IntegrityError

MODELS = (
    Project,
    Revision,
    Guideline,
    RuleSetRecord,
    InspectionRecord,
    RepairPlanRecord,
    QualityGateRun,
    Job,
    JobEvent,
    AuditEvent,
)


def _graph(database):
    names = ("project", "revision", "guideline", "ruleset", "inspection", "job")
    ids = {name: str(uuid4()) for name in names}
    expires = datetime.now(UTC) + timedelta(hours=1)
    with session_scope() as db:
        db.add(
            Project(
                id=ids["project"],
                name="Infrastructure",
                token_hash="a" * 64,
                expires_at=expires,
            )
        )
        db.flush()
        db.add_all(
            [
                Revision(
                    id=ids["revision"],
                    project_id=ids["project"],
                    original_filename="source.docx",
                    sha256="b" * 64,
                    storage_key="projects/source",
                    kind="ORIGINAL",
                    validation_status="VALID",
                ),
                Guideline(
                    id=ids["guideline"],
                    project_id=ids["project"],
                    kind="TEXT",
                    text_content="Body font",
                ),
            ]
        )
        db.flush()
        db.add(
            RuleSetRecord(
                id=ids["ruleset"],
                project_id=ids["project"],
                version=1,
                name="Rules",
                status="APPROVED",
                digest="c" * 64,
                rules_json=[{"rule_id": "body-font"}],
                conflicts_json=[],
                guideline_id=ids["guideline"],
            )
        )
        db.flush()
        db.add(
            InspectionRecord(
                id=ids["inspection"],
                project_id=ids["project"],
                revision_id=ids["revision"],
                rule_set_id=ids["ruleset"],
                rule_set_digest="c" * 64,
                inspector_version="1.0",
                status="SUCCEEDED",
                summary_json={"violations": 1},
                issues_json=[{"issue_id": "issue-1"}],
                preview_json={"page_count": 1},
                warnings_json=["example"],
            )
        )
        db.flush()
        db.add_all(
            [
                RepairPlanRecord(
                    project_id=ids["project"],
                    base_revision_id=ids["revision"],
                    inspection_id=ids["inspection"],
                    rule_set_id=ids["ruleset"],
                    rule_set_version=1,
                    rule_set_digest="c" * 64,
                    status="DRAFT",
                    plan_digest="d" * 64,
                    selected_issues_json=["issue-1"],
                    operations_json=[{"operation_id": "operation-1"}],
                    affected_node_count=1,
                    execution_key="execute-once",
                ),
                QualityGateRun(
                    candidate_revision_id=ids["revision"],
                    gate="G1",
                    status="PASS",
                    details_json={"ok": True},
                ),
                Job(
                    id=ids["job"],
                    project_id=ids["project"],
                    job_type="INSPECTION",
                    status="QUEUED",
                    stage="QUEUED",
                    idempotency_key="inspect-once",
                ),
            ]
        )
        db.flush()
        db.add_all(
            [
                JobEvent(
                    job_id=ids["job"],
                    stage="QUEUED",
                    progress=0,
                    message="Queued",
                    payload_json={"progress": 0},
                ),
                AuditEvent(
                    project_id=ids["project"],
                    job_id=ids["job"],
                    actor="anonymous",
                    event_type="job.created",
                    details_json={"job_type": "INSPECTION"},
                ),
            ]
        )
    return ids


def test_init_db_creates_all_tables_and_sqlite_foreign_keys(database):
    expected = {table.name for table in Base.metadata.sorted_tables}
    assert set(inspect(database.engine).get_table_names()) == expected
    assert (database.engine.url.database) is not None
    with database.SessionLocal() as db:
        assert db.scalar(text("PRAGMA foreign_keys")) == 1
    database.init_db()


def test_every_entity_round_trips_json(database):
    _graph(database)
    with database.SessionLocal() as db:
        for model in MODELS:
            assert db.scalar(select(func.count()).select_from(model)) == 1
        inspection = db.scalar(select(InspectionRecord))
        assert inspection.summary_json == {"violations": 1}
        assert inspection.issues_json == [{"issue_id": "issue-1"}]
        event = db.scalar(select(JobEvent))
        assert isinstance(event.id, int)


def test_datetime_columns_are_timezone_aware():
    for table in Base.metadata.tables.values():
        for column in table.columns:
            if isinstance(column.type, DateTime):
                assert column.type.timezone is True


def test_unique_constraints(database):
    ids = _graph(database)
    with pytest.raises(IntegrityError):
        with session_scope() as db:
            db.add(
                RuleSetRecord(
                    project_id=ids["project"],
                    version=1,
                    name="Duplicate",
                    digest="e" * 64,
                )
            )
    with pytest.raises(IntegrityError):
        with session_scope() as db:
            db.add(
                InspectionRecord(
                    project_id=ids["project"],
                    revision_id=ids["revision"],
                    rule_set_id=ids["ruleset"],
                    rule_set_digest="c" * 64,
                    inspector_version="1.0",
                    status="SUCCEEDED",
                )
            )
    with pytest.raises(IntegrityError):
        with session_scope() as db:
            db.add(
                Job(
                    project_id=ids["project"],
                    job_type="INSPECTION",
                    idempotency_key="inspect-once",
                )
            )
    with pytest.raises(IntegrityError):
        with session_scope() as db:
            db.add(
                RepairPlanRecord(
                    project_id=ids["project"],
                    base_revision_id=ids["revision"],
                    inspection_id=ids["inspection"],
                    rule_set_id=ids["ruleset"],
                    rule_set_version=1,
                    rule_set_digest="c" * 64,
                    plan_digest="f" * 64,
                    execution_key="execute-once",
                )
            )


def test_foreign_keys_and_progress_check_are_enforced(database):
    with pytest.raises(IntegrityError):
        with session_scope() as db:
            db.add(
                Revision(
                    project_id=str(uuid4()),
                    original_filename="orphan.docx",
                    sha256="0" * 64,
                    storage_key="projects/orphan",
                    kind="ORIGINAL",
                    validation_status="PENDING",
                )
            )
    ids = _graph(database)
    with pytest.raises(IntegrityError):
        with session_scope() as db:
            db.add(Job(project_id=ids["project"], job_type="RENDER", progress=101))
