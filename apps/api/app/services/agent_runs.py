from __future__ import annotations

from typing import Any

from alinea_agent.contracts import AgentBudget, AgentOutcome
from alinea_agent.orchestrator import AlineaAgentOrchestrator
from alinea_contracts import AlineaError
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.database import session_scope
from app.db.models import AgentEvent, AgentRun, Guideline, Job, Project
from app.schemas import AgentRunCreate

from .agent_tools import AgentTools, _target_id
from .common import add_audit, isoformat, new_id, request_digest, require_found, require_ownership, utc_now
from .inspections import require_inspection, require_revision
from .jobs import create_job, enforce_job_capacity
from .rules import _new_draft, require_ruleset, validated_rules


def require_agent_run(db: Session, project: Project, run_id: str) -> AgentRun:
    run = require_found(db.get(AgentRun, run_id), "AGENT_RUN_NOT_FOUND", "Agent run not found")
    require_ownership(project, run.project_id)
    return run


def _append_event(
    db: Session,
    run: AgentRun,
    event_type: str,
    status: str,
    payload: dict[str, Any],
) -> None:
    sequence = db.scalar(select(func.max(AgentEvent.sequence)).where(AgentEvent.run_id == run.id)) or 0
    db.add(
        AgentEvent(
            run_id=run.id,
            sequence=sequence + 1,
            event_type=event_type,
            status=status,
            payload_json=payload,
            created_at=utc_now(),
        )
    )


def _validate_context(db: Session, project: Project, payload: AgentRunCreate) -> dict[str, Any]:
    context: dict[str, Any] = {"messages": []}
    if payload.guideline_id:
        guideline = require_found(db.get(Guideline, payload.guideline_id), "GUIDELINE_NOT_FOUND", "Guideline not found")
        require_ownership(project, guideline.project_id)
        context["guideline_id"] = guideline.id
    if payload.revision_id:
        context["revision_id"] = require_revision(db, project, payload.revision_id).id
    if payload.rule_set_id:
        ruleset = require_ruleset(db, project, payload.rule_set_id)
        context["rule_set_id"] = ruleset.id
        context["rule_set_version"] = ruleset.version
        context["rule_set_status"] = ruleset.status
    if payload.inspection_id:
        context["inspection_id"] = require_inspection(db, project, payload.inspection_id).id
    return context


def create_agent_run(
    db: Session, project: Project, payload: AgentRunCreate
) -> tuple[AgentRun, Job, bool]:
    require_ownership(project, project.id)
    enforce_job_capacity(db, project.id)
    context = _validate_context(db, project, payload)
    settings = get_settings()
    run = AgentRun(
        id=new_id(),
        project_id=project.id,
        status="QUEUED",
        objective=payload.objective,
        input_digest=request_digest({"objective": payload.objective, "context": context}),
        context_json=context,
        model=settings.llm_model,
        created_at=utc_now(),
        updated_at=utc_now(),
    )
    db.add(run)
    db.flush()
    _append_event(db, run, "run.created", "QUEUED", {"objective": payload.objective})
    job, created = create_job(
        db, project, "agent_run", f"agent:{run.id}:0", {"run_id": run.id}, result_id=run.id
    )
    add_audit(db, project.id, "agent_run.created", job=job, entity_id=run.id)
    return run, job, created


def resume_agent_run(db: Session, project: Project, run: AgentRun, message: str) -> tuple[Job, bool]:
    if run.status not in {"NEEDS_CLARIFICATION", "FAILED", "SUCCEEDED"}:
        raise AlineaError("AGENT_RUN_ACTIVE", "The Agent run is still active", status_code=409)
    context = dict(run.context_json)
    messages = list(context.get("messages", []))
    messages.append(message)
    if sum(len(item) for item in messages) > get_settings().agent_max_characters:
        raise AlineaError("AGENT_BUDGET_EXCEEDED", "Agent conversation budget exceeded", status_code=429)
    context["messages"] = messages
    context["attempt"] = int(context.get("attempt", 0)) + 1
    run.context_json = context
    run.input_digest = request_digest({"objective": run.objective, "context": context})
    run.status = "QUEUED"
    run.clarification_json = []
    run.error_code = None
    run.error_message = None
    run.finished_at = None
    run.updated_at = utc_now()
    _append_event(db, run, "run.resumed", "QUEUED", {"message": message})
    job, created = create_job(
        db,
        project,
        "agent_run",
        f"agent:{run.id}:{context['attempt']}",
        {"run_id": run.id},
        result_id=run.id,
    )
    return job, created


def agent_run_out(db: Session, run: AgentRun) -> dict[str, Any]:
    events = db.scalars(select(AgentEvent).where(AgentEvent.run_id == run.id).order_by(AgentEvent.sequence)).all()
    latest_job = db.scalar(
        select(Job).where(Job.job_type == "agent_run", Job.result_id == run.id).order_by(Job.created_at.desc()).limit(1)
    )
    return {
        "run_id": run.id,
        "project_id": run.project_id,
        "status": run.status,
        "objective": run.objective,
        "context": run.context_json,
        "result": run.result_json,
        "clarifications": run.clarification_json,
        "model": run.model,
        "step_count": run.step_count,
        "tool_call_count": run.tool_call_count,
        "input_tokens": run.input_tokens,
        "output_tokens": run.output_tokens,
        "duration_ms": run.duration_ms,
        "error_code": run.error_code,
        "error_message": run.error_message,
        "job_id": latest_job.id if latest_job else None,
        "created_at": isoformat(run.created_at),
        "updated_at": isoformat(run.updated_at),
        "completed_at": isoformat(run.finished_at),
        "events": [
            {
                "sequence": event.sequence,
                "event_type": event.event_type,
                "tool_name": event.tool_name,
                "status": event.status,
                "duration_ms": event.duration_ms,
                "payload": event.payload_json,
                "created_at": isoformat(event.created_at),
            }
            for event in events
        ],
    }


def _validated_outcome(db: Session, project: Project, run: AgentRun, outcome: AgentOutcome) -> dict[str, Any]:
    result = outcome.model_dump(mode="json")
    tool_events = db.scalars(select(AgentEvent).where(AgentEvent.run_id == run.id)).all()
    inspection_event = next((item for item in reversed(tool_events) if item.tool_name == "run_inspection"), None)
    plan_event = next((item for item in reversed(tool_events) if item.tool_name == "preview_repair_plan"), None)
    if inspection_event:
        result["inspection_id"] = inspection_event.payload_json.get("output", {}).get("inspection_id")
    if plan_event:
        result["repair_plan_id"] = plan_event.payload_json.get("output", {}).get("plan_id")
    if outcome.rules:
        guideline_id = run.context_json.get("guideline_id")
        if not guideline_id:
            raise AlineaError("AGENT_CONTEXT_REQUIRED", "A guideline is required for rule output", status_code=422)
        guideline = require_found(db.get(Guideline, guideline_id), "GUIDELINE_NOT_FOUND", "Guideline not found")
        require_ownership(project, guideline.project_id)
        rules = validated_rules(outcome.rules)
        existing_id = run.result_json.get("rule_set_id")
        if existing_id:
            result["rule_set_id"] = existing_id
        else:
            record = _new_draft(
                db,
                project,
                name=guideline.source_filename or "Agent rule draft",
                rules=rules,
                guideline_id=guideline.id,
            )
            result["rule_set_id"] = record.id
    if outcome.role_suggestions:
        revision_id = run.context_json.get("revision_id") or project.active_revision_id
        if not revision_id:
            raise AlineaError("AGENT_CONTEXT_REQUIRED", "A revision is required for role suggestions", status_code=422)
        revision = require_revision(db, project, revision_id)
        from .common import read_snapshot

        snapshot = read_snapshot(project.id, revision.id)
        valid_targets = {
            _target_id(item.element_ref.part_uri, item.element_ref.paragraph_ordinal)
            for item in snapshot.paragraphs
        }
        suggestions = [item for item in outcome.role_suggestions if item.target in valid_targets]
        result["role_suggestions"] = [item.model_dump(mode="json") for item in suggestions]
        result["role_revision_id"] = revision.id
    return result


def execute_agent_run(job_id: str) -> str:
    with session_scope() as db:
        job = require_found(db.get(Job, job_id), "JOB_NOT_FOUND", "Job not found")
        run = require_found(db.get(AgentRun, str(job.result_id)), "AGENT_RUN_NOT_FOUND", "Agent run not found")
        project = require_found(db.get(Project, job.project_id), "PROJECT_NOT_FOUND", "Project not found")
        require_ownership(project, run.project_id)
        settings = get_settings()
        api_key = settings.llm_api_key.get_secret_value()
        if not api_key:
            raise AlineaError("LLM_NOT_CONFIGURED", "No LLM API key is configured", status_code=503, retryable=True)
        run.status = "RUNNING"
        run.error_code = None
        run.error_message = None
        run.updated_at = utc_now()
        _append_event(db, run, "run.started", "RUNNING", {"model": settings.llm_model})
        objective = run.objective
        context = dict(run.context_json)
    try:
        orchestrator = AlineaAgentOrchestrator(
            base_url=settings.llm_base_url,
            api_key=api_key,
            model=settings.llm_model,
            timeout_seconds=settings.llm_timeout_seconds,
            budget=AgentBudget(
                max_steps=settings.agent_max_steps,
                max_tool_calls=settings.agent_max_tool_calls,
                max_characters=settings.agent_max_characters,
                max_paragraph_candidates=settings.agent_max_paragraph_candidates,
            ),
        )
        completed = orchestrator.run(
            objective=objective,
            context=context,
            tools=AgentTools(project.id, run.id),
        )
    except (ValidationError, ValueError) as exc:
        error = AlineaError("AGENT_OUTPUT_INVALID", "The model returned an invalid result", status_code=422)
        _fail_run(run.id, error)
        raise error from exc
    except AlineaError as exc:
        _fail_run(run.id, exc)
        raise
    except Exception as exc:
        error = AlineaError(
            "AGENT_MODEL_FAILED", "The Agent could not complete this run", status_code=503, retryable=True
        )
        _fail_run(run.id, error)
        raise error from exc
    with session_scope() as db:
        run = db.get(AgentRun, run.id)
        project = db.get(Project, project.id)
        assert run is not None and project is not None
        result = _validated_outcome(db, project, run, completed.outcome)
        run.result_json = result
        run.clarification_json = [item.model_dump(mode="json") for item in completed.outcome.clarifications]
        run.status = "NEEDS_CLARIFICATION" if completed.outcome.clarifications else "SUCCEEDED"
        run.step_count += completed.step_count
        run.input_tokens += completed.input_tokens
        run.output_tokens += completed.output_tokens
        run.duration_ms += completed.duration_ms
        run.finished_at = utc_now()
        run.updated_at = run.finished_at
        _append_event(
            db,
            run,
            "run.completed",
            run.status,
            {"message": completed.outcome.message, "recommended_action": completed.outcome.recommended_action},
        )
        add_audit(
            db,
            project.id,
            "agent_run.completed",
            job=job,
            actor="WORKER",
            entity_id=run.id,
            details={"status": run.status, "tool_calls": run.tool_call_count},
        )
        return run.id


def _fail_run(run_id: str, error: AlineaError) -> None:
    with session_scope() as db:
        run = db.get(AgentRun, run_id)
        if run is None:
            return
        run.status = "FAILED"
        run.error_code = error.code
        run.error_message = error.message
        run.finished_at = utc_now()
        run.updated_at = run.finished_at
        _append_event(db, run, "run.failed", "FAILED", {"error_code": error.code, "message": error.message})
