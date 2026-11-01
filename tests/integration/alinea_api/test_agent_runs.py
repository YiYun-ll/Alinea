from __future__ import annotations

import json
from typing import Any

import pytest
from alinea_agent.contracts import AgentOutcome, ClarificationQuestion, RoleSuggestion
from alinea_agent.orchestrator import OrchestratorResult
from app.config import Settings, get_settings
from app.db import database
from app.db.models import RepairPlanRecord
from app.jobs.tasks import agent_run_job, inspect_document_job
from app.main import create_app
from app.services.agent_tools import AgentTools
from fastapi.testclient import TestClient


@pytest.fixture
def agent_api(tmp_path, monkeypatch):
    previous_url = str(database.engine.url)
    settings = Settings(
        database_url=f"sqlite:///{(tmp_path / 'agent.db').as_posix()}",
        storage_root=tmp_path / "objects",
        llm_api_key="test-only",
    )
    get_settings.cache_clear()
    monkeypatch.setattr("app.routers.agent.dispatch_job", lambda _job_id: None)
    monkeypatch.setattr("app.jobs.runner.dispatch_job", lambda _job_id: None)
    try:
        with TestClient(create_app(settings)) as client:
            created = client.post("/api/v1/demo").json()
            headers = {"Authorization": f"Bearer {created['token']}"}
            yield client, created, headers
    finally:
        database.configure_database(previous_url)
        get_settings.cache_clear()


def _result(outcome: AgentOutcome) -> OrchestratorResult:
    return OrchestratorResult(
        outcome=outcome,
        step_count=1,
        input_tokens=10,
        output_tokens=20,
        duration_ms=30,
    )


class FakeOrchestrator:
    def __init__(self, **_kwargs: Any) -> None:
        pass

    def run(self, *, objective: str, context: dict[str, Any], tools: AgentTools) -> OrchestratorResult:
        if "澄清" in objective and not context["messages"]:
            return _result(
                AgentOutcome(
                    message="需要确认适用范围",
                    clarifications=[ClarificationQuestion(question_id="scope", question="摘要也适用吗？")],
                )
            )
        if "规则" in objective:
            source = tools.read_guideline_sections(context["guideline_id"])
            rules = [
                {
                    "rule_id": "body_size",
                    "selector": "body",
                    "property": "font.size_pt",
                    "expected": 12,
                    "source": {
                        "source_type": "user_text",
                        "reference": source["reference"],
                        "quote": "正文 12 pt",
                    },
                }
            ]
            validated = tools.validate_rule_candidates(context["guideline_id"], json.dumps(rules))
            return _result(
                AgentOutcome(message="规则草案已生成", rules=validated["rules"], recommended_action="REVIEW_RULES")
            )
        if "检查" in objective:
            started = tools.run_inspection(
                context["revision_id"], context["rule_set_id"], context["rule_set_version"]
            )
            return _result(
                AgentOutcome(
                    message=f"检查已提交：{started['inspection_id']}", recommended_action="REVIEW_INSPECTION"
                )
            )
        if "角色" in objective:
            structure = tools.get_document_structure_summary(context["revision_id"])
            target = structure["ambiguous_paragraphs"][0]["target"]
            return _result(
                AgentOutcome(
                    message="已生成角色建议",
                    role_suggestions=[
                        RoleSuggestion(target=target, role="body", confidence=0.7, evidence="段落样式与正文一致"),
                        RoleSuggestion(target="invented:999", role="caption", confidence=0.9, evidence="伪造目标"),
                    ],
                )
            )
        if "计划" in objective:
            inspection = tools.get_inspection_summary(context["inspection_id"])
            selected = next(
                issue["issue_id"]
                for issue in inspection["issues"]
                if issue["detection_status"] == "CONFIRMED_VIOLATION"
                and issue["repair_eligibility"] == "SAFE_SINGLE_TARGET"
            )
            plan = tools.preview_repair_plan(inspection["inspection_id"], [selected])
            return _result(
                AgentOutcome(
                    message=f"修复草案已生成：{plan['plan_id']}", recommended_action="REVIEW_REPAIR"
                )
            )
        return _result(AgentOutcome(message="已回答补充问题"))


def _start(client, headers, project_id, **payload):
    response = client.post(f"/api/v1/projects/{project_id}/agent/runs", headers=headers, json=payload)
    assert response.status_code == 202, response.text
    run = response.json()
    agent_run_job(run["job_id"])
    completed = client.get(
        f"/api/v1/projects/{project_id}/agent/runs/{run['run_id']}", headers=headers
    )
    assert completed.status_code == 200, completed.text
    return completed.json()


def test_agent_tool_loop_covers_rules_roles_inspection_and_draft_plan(agent_api, monkeypatch):
    client, created, headers = agent_api
    monkeypatch.setattr("app.services.agent_runs.AlineaAgentOrchestrator", FakeOrchestrator)
    project_id = created["project_id"]
    guideline = client.post(
        f"/api/v1/projects/{project_id}/guidelines",
        headers=headers,
        json={"kind": "text", "name": "真实规范", "text": "正文 12 pt"},
    ).json()
    rule_run = _start(
        client,
        headers,
        project_id,
        objective="生成规则",
        guideline_id=guideline["guideline_id"],
    )
    assert rule_run["status"] == "SUCCEEDED"
    rule_set_id = rule_run["result"]["rule_set_id"]
    assert any(event["tool_name"] == "validate_rule_candidates" for event in rule_run["events"])
    client.put(f"/api/v1/projects/{project_id}/rules/{rule_set_id}/approve", headers=headers)
    inspection_run = _start(
        client,
        headers,
        project_id,
        objective="执行检查",
        revision_id=created["revision_id"],
        rule_set_id=rule_set_id,
    )
    inspection_id = inspection_run["result"]["message"].split("：")[-1]
    with database.session_scope() as db:
        from app.db.models import Job
        from sqlalchemy import select

        inspection_job = db.scalar(select(Job).where(Job.result_id == inspection_id, Job.job_type == "inspection"))
        assert inspection_job is not None
        inspection_job_id = inspection_job.id
    inspect_document_job(inspection_job_id)
    role_run = _start(
        client,
        headers,
        project_id,
        objective="分析角色",
        revision_id=created["revision_id"],
    )
    assert len(role_run["result"]["role_suggestions"]) == 1
    assert role_run["result"]["role_revision_id"] == created["revision_id"]
    plan_run = _start(
        client,
        headers,
        project_id,
        objective="准备计划",
        inspection_id=inspection_id,
    )
    plan_id = plan_run["result"]["message"].split("：")[-1]
    with database.session_scope() as db:
        plan = db.get(RepairPlanRecord, plan_id)
        assert plan is not None and plan.status == "DRAFT"
    project = client.get(f"/api/v1/projects/{project_id}", headers=headers).json()
    assert project["active_revision_id"] == created["revision_id"]


def test_agent_clarification_can_be_answered_and_resumed(agent_api, monkeypatch):
    client, created, headers = agent_api
    monkeypatch.setattr("app.services.agent_runs.AlineaAgentOrchestrator", FakeOrchestrator)
    run = _start(client, headers, created["project_id"], objective="需要澄清")
    assert run["status"] == "NEEDS_CLARIFICATION"
    response = client.post(
        f"/api/v1/projects/{created['project_id']}/agent/runs/{run['run_id']}/messages",
        headers=headers,
        json={"message": "摘要不适用"},
    )
    assert response.status_code == 202, response.text
    agent_run_job(response.json()["job_id"])
    completed = client.get(
        f"/api/v1/projects/{created['project_id']}/agent/runs/{run['run_id']}", headers=headers
    ).json()
    assert completed["status"] == "SUCCEEDED"
    assert completed["context"]["messages"] == ["摘要不适用"]


def test_agent_tools_reject_cross_project_references(agent_api):
    client, created, headers = agent_api
    other = client.post("/api/v1/demo").json()
    response = client.post(
        f"/api/v1/projects/{created['project_id']}/agent/runs",
        headers=headers,
        json={"objective": "检查", "revision_id": other["revision_id"]},
    )
    assert response.status_code == 403
    accepted = client.post(
        f"/api/v1/projects/{created['project_id']}/agent/runs",
        headers=headers,
        json={"objective": "检查"},
    ).json()
    tools = AgentTools(created["project_id"], accepted["run_id"])
    with pytest.raises(Exception) as caught:
        tools.get_document_structure_summary(other["revision_id"])
    assert getattr(caught.value, "code", None) == "FORBIDDEN"
    run = client.get(
        f"/api/v1/projects/{created['project_id']}/agent/runs/{accepted['run_id']}", headers=headers
    ).json()
    failed_tool = next(event for event in run["events"] if event["tool_name"] == "get_document_structure_summary")
    assert failed_tool["status"] == "FAILED"
    assert failed_tool["payload"]["error_code"] == "FORBIDDEN"


def test_agent_tool_budget_stops_additional_calls(agent_api, monkeypatch):
    client, created, headers = agent_api
    monkeypatch.setattr(
        "app.services.agent_tools.get_settings", lambda: Settings(agent_max_tool_calls=1)
    )
    accepted = client.post(
        f"/api/v1/projects/{created['project_id']}/agent/runs",
        headers=headers,
        json={"objective": "检查"},
    ).json()
    tools = AgentTools(created["project_id"], accepted["run_id"])
    tools.get_project_context()
    with pytest.raises(Exception) as caught:
        tools.get_project_context()
    assert getattr(caught.value, "code", None) == "AGENT_BUDGET_EXCEEDED"


def test_agent_run_requires_model_configuration(agent_api, monkeypatch):
    client, created, headers = agent_api
    monkeypatch.setattr("app.services.agent_runs.get_settings", lambda: Settings(llm_api_key=""))
    response = client.post(
        f"/api/v1/projects/{created['project_id']}/agent/runs",
        headers=headers,
        json={"objective": "生成规则"},
    )
    run = response.json()
    agent_run_job(run["job_id"])
    failed = client.get(
        f"/api/v1/projects/{created['project_id']}/agent/runs/{run['run_id']}", headers=headers
    ).json()
    assert failed["status"] == "FAILED"
    assert failed["error_code"] == "LLM_NOT_CONFIGURED"


def test_agent_complex_document_structure_and_inspection(agent_api, monkeypatch):
    from pathlib import Path

    client, created, headers = agent_api
    monkeypatch.setattr("app.services.agent_runs.AlineaAgentOrchestrator", FakeOrchestrator)
    project_id = created["project_id"]
    fixture = Path("tests/fixtures/data/alinea-agent-complex.docx")
    with fixture.open("rb") as stream:
        uploaded = client.post(
            f"/api/v1/projects/{project_id}/documents",
            headers=headers,
            files={
                "file": (
                    fixture.name,
                    stream,
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                )
            },
        )
    assert uploaded.status_code == 201, uploaded.text
    revision_id = uploaded.json()["revision_id"]
    role_run = _start(client, headers, project_id, objective="分析角色", revision_id=revision_id)
    assert role_run["status"] == "SUCCEEDED"
    assert role_run["result"]["role_revision_id"] == revision_id
    assert len(role_run["result"]["role_suggestions"]) <= 20
    approved = client.get(f"/api/v1/projects/{project_id}/rules", headers=headers).json()
    client.put(f"/api/v1/projects/{project_id}/rules/{approved['rule_set_id']}/approve", headers=headers)
    dispatched: list[str] = []
    monkeypatch.setattr("app.jobs.runner.dispatch_job", lambda job_id: dispatched.append(job_id))
    inspection_run = _start(
        client,
        headers,
        project_id,
        objective="执行检查",
        revision_id=revision_id,
        rule_set_id=approved["rule_set_id"],
    )
    inspection_id = inspection_run["result"]["inspection_id"]
    assert len(dispatched) == 1
    with database.session_scope() as db:
        from app.db.models import Job
        from sqlalchemy import select

        job = db.scalar(select(Job).where(Job.result_id == inspection_id, Job.job_type == "inspection"))
        assert job is not None
        job_id = job.id
    inspect_document_job(job_id)
    inspection = client.get(f"/api/v1/inspections/{inspection_id}", headers=headers).json()
    assert inspection["status"] == "SUCCEEDED"
    assert inspection["revision_id"] == revision_id
    assert inspection["summary"]["evaluated_rules"] > 0
    project = client.get(f"/api/v1/projects/{project_id}", headers=headers).json()
    assert project["active_revision_id"] == revision_id
