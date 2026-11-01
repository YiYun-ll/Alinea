from __future__ import annotations

import json
import time
from collections import Counter
from collections.abc import Callable
from typing import Any

from alinea_agent.interpreter import enforce_rule_evidence
from alinea_agent.schemas import GuidelineInput, GuidelinePage
from alinea_contracts import AlineaError
from alinea_docx.rules import find_conflicts
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.database import session_scope
from app.db.models import (
    AgentEvent,
    AgentRun,
    Guideline,
    InspectionRecord,
    Project,
    RepairPlanRecord,
    Revision,
    RuleSetRecord,
)
from app.schemas import InspectionCreate, RepairPlanCreate

from .common import read_snapshot, require_found, require_ownership, storage, utc_now
from .inspections import create_inspection, require_inspection, require_revision
from .repairs import create_plan, require_plan
from .rules import extract_pdf_pages, validated_rules
from .serializers import plan_out


def _target_id(part_uri: str, ordinal: int) -> str:
    return f"{part_uri}:{ordinal}"


def _brief(value: Any) -> Any:
    if isinstance(value, str):
        return value if len(value) <= 300 else value[:297] + "..."
    if isinstance(value, list):
        return [_brief(item) for item in value[:20]]
    if isinstance(value, dict):
        return {key: _brief(item) for key, item in value.items() if key not in {"text", "text_content"}}
    return value


class AgentTools:
    def __init__(self, project_id: str, run_id: str) -> None:
        self.project_id = project_id
        self.run_id = run_id

    def _execute(
        self,
        name: str,
        arguments: dict[str, Any],
        action: Callable[[Session, Project], dict[str, Any]],
    ) -> dict[str, Any]:
        started = time.monotonic()
        result: dict[str, Any] = {}
        error: Exception | None = None
        with session_scope() as db:
            run = require_found(db.get(AgentRun, self.run_id), "AGENT_RUN_NOT_FOUND", "Agent run not found")
            project = require_found(db.get(Project, self.project_id), "PROJECT_NOT_FOUND", "Project not found")
            require_ownership(project, run.project_id)
            if run.tool_call_count >= get_settings().agent_max_tool_calls:
                raise AlineaError("AGENT_BUDGET_EXCEEDED", "Agent tool budget exceeded", status_code=429)
            run.tool_call_count += 1
            try:
                result = action(db, project)
                status = "SUCCEEDED"
                payload = {"input": _brief(arguments), "output": _brief(result)}
            except Exception as exc:
                error = exc
                status = "FAILED"
                payload = {
                    "input": _brief(arguments),
                    "error_code": exc.code if isinstance(exc, AlineaError) else "TOOL_FAILED",
                    "error": str(exc)[:300],
                }
            sequence = db.scalar(
                select(func.max(AgentEvent.sequence)).where(AgentEvent.run_id == self.run_id)
            ) or 0
            db.add(
                AgentEvent(
                    run_id=self.run_id,
                    sequence=sequence + 1,
                    event_type="tool.completed",
                    tool_name=name,
                    status=status,
                    duration_ms=round((time.monotonic() - started) * 1000),
                    payload_json=payload,
                    created_at=utc_now(),
                )
            )
        if error is not None:
            raise error
        return result

    @staticmethod
    def _owned_guideline(db: Session, project: Project, guideline_id: str) -> Guideline:
        guideline = require_found(db.get(Guideline, guideline_id), "GUIDELINE_NOT_FOUND", "Guideline not found")
        require_ownership(project, guideline.project_id)
        return guideline

    def get_project_context(self) -> dict[str, Any]:
        def action(db: Session, project: Project) -> dict[str, Any]:
            guidelines = db.scalars(select(Guideline).where(Guideline.project_id == project.id)).all()
            revisions = db.scalars(select(Revision).where(Revision.project_id == project.id)).all()
            rulesets = db.scalars(select(RuleSetRecord).where(RuleSetRecord.project_id == project.id)).all()
            inspections = db.scalars(select(InspectionRecord).where(InspectionRecord.project_id == project.id)).all()
            return {
                "active_revision_id": project.active_revision_id,
                "guidelines": [
                    {"guideline_id": item.id, "name": item.source_filename, "kind": item.kind}
                    for item in guidelines[-10:]
                ],
                "revisions": [
                    {"revision_id": item.id, "kind": item.kind, "validation_status": item.validation_status}
                    for item in revisions[-10:]
                ],
                "rulesets": [
                    {"rule_set_id": item.id, "version": item.version, "status": item.status}
                    for item in rulesets[-10:]
                ],
                "inspections": [
                    {
                        "inspection_id": item.id,
                        "revision_id": item.revision_id,
                        "rule_set_id": item.rule_set_id,
                        "status": item.status,
                    }
                    for item in inspections[-10:]
                ],
            }

        return self._execute("get_project_context", {}, action)

    def read_guideline_sections(self, guideline_id: str, start_page: int = 1, end_page: int = 3) -> dict[str, Any]:
        def action(db: Session, project: Project) -> dict[str, Any]:
            if start_page < 1 or end_page < start_page or end_page - start_page > 5:
                raise AlineaError("INVALID_TOOL_ARGUMENT", "Read at most six guideline pages", status_code=422)
            guideline = self._owned_guideline(db, project, guideline_id)
            if guideline.kind == "pdf" and guideline.storage_key:
                pages = extract_pdf_pages(storage().read(guideline.storage_key))
            else:
                pages = [GuidelinePage(page=1, text=guideline.text_content or "")]
            selected = [page for page in pages if start_page <= page.page <= end_page]
            remaining = 12000
            content: list[dict[str, Any]] = []
            for page in selected:
                text = page.text[:remaining]
                content.append({"page": page.page, "text": text})
                remaining -= len(text)
                if remaining <= 0:
                    break
            return {
                "guideline_id": guideline.id,
                "reference": guideline.source_filename or guideline.id,
                "source_type": "pdf" if guideline.kind == "pdf" else "user_text",
                "total_pages": len(pages),
                "pages": content,
                "truncated": remaining <= 0 or len(selected) < end_page - start_page + 1,
            }

        return self._execute(
            "read_guideline_sections",
            {"guideline_id": guideline_id, "start_page": start_page, "end_page": end_page},
            action,
        )

    def validate_rule_candidates(self, guideline_id: str, rules_json: str) -> dict[str, Any]:
        def action(db: Session, project: Project) -> dict[str, Any]:
            if len(rules_json) > 50000:
                raise AlineaError("INVALID_TOOL_ARGUMENT", "Rule candidate payload is too large", status_code=422)
            raw = json.loads(rules_json)
            if not isinstance(raw, list):
                raise AlineaError("INVALID_TOOL_ARGUMENT", "rules_json must contain a JSON array", status_code=422)
            rules = validated_rules(raw)
            guideline = self._owned_guideline(db, project, guideline_id)
            pages = (
                extract_pdf_pages(storage().read(guideline.storage_key))
                if guideline.kind == "pdf" and guideline.storage_key
                else []
            )
            source = GuidelineInput(
                reference=guideline.source_filename or guideline.id,
                source_type="pdf" if guideline.kind == "pdf" else "user_text",
                text=guideline.text_content or "",
                pages=pages,
            )
            uncertainties = enforce_rule_evidence(rules, source)
            return {
                "rules": [rule.model_dump(mode="json") for rule in rules],
                "uncertainties": uncertainties,
                "conflicts": [item.model_dump(mode="json") for item in find_conflicts(rules)],
            }

        return self._execute(
            "validate_rule_candidates", {"guideline_id": guideline_id, "rules_json": rules_json}, action
        )

    def get_document_structure_summary(self, revision_id: str) -> dict[str, Any]:
        def action(db: Session, project: Project) -> dict[str, Any]:
            revision = require_revision(db, project, revision_id)
            snapshot = read_snapshot(project.id, revision.id)
            candidates = sorted(snapshot.paragraphs, key=lambda item: item.role_confidence)
            selected = candidates[: get_settings().agent_max_paragraph_candidates]
            roles = Counter(item.semantic_role for item in snapshot.paragraphs)
            return {
                "revision_id": revision.id,
                "sha256": snapshot.sha256,
                "paragraph_count": len(snapshot.paragraphs),
                "section_count": len(snapshot.sections),
                "roles": dict(roles),
                "styles": [
                    {"style_id": style.style_id, "name": style.name, "type": style.style_type}
                    for style in list(snapshot.styles.values())[:40]
                ],
                "ambiguous_paragraphs": [
                    {
                        "target": _target_id(item.element_ref.part_uri, item.element_ref.paragraph_ordinal),
                        "current_role": item.semantic_role,
                        "confidence": item.role_confidence,
                        "style_id": item.p_style_id,
                        "excerpt": item.text[:160],
                    }
                    for item in selected
                    if item.text.strip()
                ],
            }

        return self._execute("get_document_structure_summary", {"revision_id": revision_id}, action)

    def run_inspection(self, revision_id: str, rule_set_id: str, rule_set_version: int) -> dict[str, Any]:
        from app.jobs.runner import dispatch_job

        def action(db: Session, project: Project) -> dict[str, Any]:
            payload = InspectionCreate(
                revision_id=revision_id,
                rule_set_id=rule_set_id,
                rule_set_version=rule_set_version,
                include_page_mapping=True,
            )
            key = f"agent:{self.run_id}:{revision_id}:{rule_set_id}:{rule_set_version}"
            job, inspection, _reused = create_inspection(db, project, payload, key)
            return {"job_id": job.id, "inspection_id": inspection.id, "status": job.status}

        result = self._execute(
            "run_inspection",
            {"revision_id": revision_id, "rule_set_id": rule_set_id, "rule_set_version": rule_set_version},
            action,
        )
        if result["status"] == "QUEUED":
            dispatch_job(result["job_id"])
        return result

    def get_inspection_summary(self, inspection_id: str) -> dict[str, Any]:
        def action(db: Session, project: Project) -> dict[str, Any]:
            inspection = require_inspection(db, project, inspection_id)
            return {
                "inspection_id": inspection.id,
                "revision_id": inspection.revision_id,
                "rule_set_id": inspection.rule_set_id,
                "status": inspection.status,
                "summary": inspection.summary_json,
                "warnings": inspection.warnings_json,
                "issues": [
                    {
                        "issue_id": issue["issue_id"],
                        "rule_id": issue["rule_id"],
                        "property": issue["property"],
                        "detection_status": issue["detection_status"],
                        "repair_eligibility": issue["repair"]["eligibility"],
                        "excerpt": issue["location"].get("anchor_excerpt", "")[:100],
                    }
                    for issue in inspection.issues_json[:100]
                ],
            }

        return self._execute("get_inspection_summary", {"inspection_id": inspection_id}, action)

    def preview_repair_plan(self, inspection_id: str, selected_issue_ids: list[str]) -> dict[str, Any]:
        def action(db: Session, project: Project) -> dict[str, Any]:
            inspection = require_inspection(db, project, inspection_id)
            for existing in db.scalars(
                select(RepairPlanRecord).where(RepairPlanRecord.inspection_id == inspection.id)
            ):
                if existing.selected_issues_json == selected_issue_ids and existing.status != "STALE":
                    return plan_out(existing)
            payload = RepairPlanCreate(
                base_revision_id=inspection.revision_id,
                inspection_id=inspection.id,
                selected_issue_ids=selected_issue_ids,
            )
            return plan_out(create_plan(db, project, payload))

        return self._execute(
            "preview_repair_plan",
            {"inspection_id": inspection_id, "selected_issue_ids": selected_issue_ids},
            action,
        )

    def get_repair_plan(self, plan_id: str) -> dict[str, Any]:
        return self._execute(
            "get_repair_plan", {"plan_id": plan_id}, lambda db, project: plan_out(require_plan(db, project, plan_id))
        )

    def get_verification_report(self, revision_id: str) -> dict[str, Any]:
        def action(db: Session, project: Project) -> dict[str, Any]:
            revision = require_revision(db, project, revision_id)
            if not revision.report_storage_key:
                raise AlineaError("REPORT_NOT_FOUND", "No verification report is available", status_code=404)
            report = json.loads(storage().read(revision.report_storage_key))
            return {
                "revision_id": revision.id,
                "status": report["status"],
                "selected_count": report["selected_count"],
                "resolved_count": report["resolved_count"],
                "remaining_count": report["remaining_count"],
                "gates": report["gates"],
                "warnings": report["warnings"],
            }

        return self._execute("get_verification_report", {"revision_id": revision_id}, action)
