from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utc_now() -> datetime:
    return datetime.now(UTC)


def new_uuid() -> str:
    return str(uuid4())


class Base(DeclarativeBase):
    metadata = MetaData(
        naming_convention={
            "ix": "ix_%(column_0_label)s",
            "uq": "uq_%(table_name)s_%(column_0_name)s",
            "ck": "ck_%(table_name)s_%(constraint_name)s",
            "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
            "pk": "pk_%(table_name)s",
        }
    )


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    name: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(32), default="ACTIVE")
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    active_revision_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Revision(Base):
    __tablename__ = "document_revisions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    parent_revision_id: Mapped[str | None] = mapped_column(
        ForeignKey("document_revisions.id", ondelete="SET NULL"), nullable=True
    )
    original_filename: Mapped[str] = mapped_column(String(1024))
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    storage_key: Mapped[str] = mapped_column(String(1024))
    kind: Mapped[str] = mapped_column(String(32))
    validation_status: Mapped[str] = mapped_column(String(32))
    report_storage_key: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class Guideline(Base):
    __tablename__ = "guidelines"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(32))
    source_filename: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    text_content: Mapped[str | None] = mapped_column(Text, nullable=True)
    storage_key: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class RuleSetRecord(Base):
    __tablename__ = "rule_sets"
    __table_args__ = (
        UniqueConstraint("project_id", "version", name="project_version"),
        CheckConstraint("version >= 1", name="version_positive"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    version: Mapped[int] = mapped_column(Integer)
    name: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(32), default="DRAFT")
    digest: Mapped[str] = mapped_column(String(64))
    rules_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    conflicts_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    guideline_id: Mapped[str | None] = mapped_column(
        ForeignKey("guidelines.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class InspectionRecord(Base):
    __tablename__ = "inspections"
    __table_args__ = (
        UniqueConstraint(
            "revision_id",
            "rule_set_digest",
            "inspector_version",
            name="revision_ruleset_inspector",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    revision_id: Mapped[str] = mapped_column(
        ForeignKey("document_revisions.id", ondelete="CASCADE"), index=True
    )
    rule_set_id: Mapped[str] = mapped_column(ForeignKey("rule_sets.id"))
    rule_set_digest: Mapped[str] = mapped_column(String(64))
    inspector_version: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32))
    summary_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    issues_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    preview_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    warnings_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class RepairPlanRecord(Base):
    __tablename__ = "repair_plans"
    __table_args__ = (
        CheckConstraint("affected_node_count >= 0", name="affected_nodes_nonnegative"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    base_revision_id: Mapped[str] = mapped_column(ForeignKey("document_revisions.id"))
    inspection_id: Mapped[str] = mapped_column(ForeignKey("inspections.id"))
    rule_set_id: Mapped[str] = mapped_column(ForeignKey("rule_sets.id"))
    rule_set_version: Mapped[int] = mapped_column(Integer)
    rule_set_digest: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32), default="DRAFT")
    plan_digest: Mapped[str] = mapped_column(String(64))
    selected_issues_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    operations_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    affected_node_count: Mapped[int] = mapped_column(Integer, default=0)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    execution_key: Mapped[str | None] = mapped_column(String(255), unique=True, nullable=True)
    result_revision_id: Mapped[str | None] = mapped_column(
        ForeignKey("document_revisions.id", ondelete="SET NULL"), nullable=True
    )


class QualityGateRun(Base):
    __tablename__ = "quality_gate_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    candidate_revision_id: Mapped[str] = mapped_column(
        ForeignKey("document_revisions.id", ondelete="CASCADE"), index=True
    )
    gate: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16))
    details_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = (
        UniqueConstraint(
            "project_id", "job_type", "idempotency_key", name="project_type_idempotency"
        ),
        CheckConstraint("progress >= 0 AND progress <= 100", name="progress_range"),
        Index("ix_jobs_project_status", "project_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    job_type: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32), default="QUEUED")
    stage: Mapped[str | None] = mapped_column(String(64), nullable=True)
    progress: Mapped[int] = mapped_column(Integer, default=0)
    result_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class JobEvent(Base):
    __tablename__ = "job_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    stage: Mapped[str | None] = mapped_column(String(64), nullable=True)
    progress: Mapped[int] = mapped_column(Integer, default=0)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    job_id: Mapped[str | None] = mapped_column(
        ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True
    )
    actor: Mapped[str] = mapped_column(String(64))
    event_type: Mapped[str] = mapped_column(String(128))
    details_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
