from __future__ import annotations

import io
import json
import unicodedata
from pathlib import Path
from typing import Any

import pdfplumber
from alinea_agent.interpreter import RuleInterpreter
from alinea_agent.schemas import GuidelineInput, GuidelinePage
from alinea_contracts.errors import AlineaError
from alinea_contracts.models import FormatRule, RuleSet
from alinea_docx.rules import compute_ruleset_digest, find_conflicts, validate_rule
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.database import session_scope
from app.db.models import Guideline, Job, JobEvent, Project, RuleSetRecord
from app.storage.local import LocalStorage

from .common import add_audit, new_id, require_ownership, storage, utc_now
from .jobs import report_progress
from .serializers import ruleset_contract

_PRESET_ROOT = Path(__file__).resolve().parents[4] / "packages" / "format-rules"


def _invalid_rule(exc: Exception) -> AlineaError:
    return AlineaError(
        "INVALID_RULE_VALUE",
        "One or more formatting rules are invalid",
        status_code=422,
        details={"reason": str(exc)[:2000]},
    )


def validated_rules(values: list[dict[str, Any] | FormatRule]) -> list[FormatRule]:
    try:
        return [validate_rule(value) for value in values]
    except (ValidationError, ValueError, TypeError) as exc:
        raise _invalid_rule(exc) from exc


def load_preset(preset_id: str) -> RuleSet:
    path = _PRESET_ROOT / f"{preset_id}.json"
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AlineaError(
            "PRESET_NOT_FOUND",
            "The requested formatting preset does not exist or is unreadable",
            status_code=404,
        ) from exc
    try:
        rules = validated_rules(raw.get("rules", []))
        preset = RuleSet.model_validate(
            {**raw, "rules": [rule.model_dump(mode="json") for rule in rules]}
        )
    except (ValidationError, ValueError, TypeError) as exc:
        raise AlineaError(
            "PRESET_INVALID",
            "The formatting preset failed local schema validation",
            status_code=500,
        ) from exc
    return preset


def create_guideline(
    db: Session,
    project: Project,
    *,
    kind: str,
    name: str | None,
    preset_id: str | None = None,
    text: str | None = None,
) -> Guideline:
    if kind == "preset":
        assert preset_id is not None
        preset = load_preset(preset_id)
        guideline = Guideline(
            id=new_id(),
            project_id=project.id,
            kind=kind,
            source_filename=name or preset.name,
            text_content=preset_id,
            created_at=utc_now(),
        )
    elif kind == "text":
        assert text is not None and text.strip()
        guideline = Guideline(
            id=new_id(),
            project_id=project.id,
            kind=kind,
            source_filename=name or "Pasted guideline",
            text_content=text,
            created_at=utc_now(),
        )
    else:
        raise AlineaError(
            "UNSUPPORTED_GUIDELINE", "Only preset, text and PDF are supported", status_code=415
        )
    db.add(guideline)
    db.flush()
    add_audit(db, project.id, "guideline.created", entity_id=guideline.id, details={"kind": kind})
    return guideline


def extract_pdf_pages(data: bytes) -> list[GuidelinePage]:
    settings = get_settings()
    if len(data) > settings.max_file_bytes:
        raise AlineaError("FILE_TOO_LARGE", "The PDF exceeds the configured limit", status_code=413)
    if not data.startswith(b"%PDF-"):
        raise AlineaError(
            "UNSUPPORTED_FILE_FORMAT", "A valid PDF file is required", status_code=415
        )
    try:
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            if len(pdf.pages) > settings.max_pages:
                raise AlineaError(
                    "PDF_TOO_MANY_PAGES",
                    "The PDF exceeds the configured page limit",
                    status_code=413,
                    details={"max_pages": settings.max_pages},
                )
            pages = [
                GuidelinePage(page=index, text=page.extract_text() or "")
                for index, page in enumerate(pdf.pages, start=1)
            ]
    except AlineaError:
        raise
    except Exception as exc:
        raise AlineaError(
            "PDF_PARSE_FAILED",
            "The PDF cannot be parsed as a text guideline",
            status_code=422,
        ) from exc
    if not any(page.text.strip() for page in pages):
        raise AlineaError(
            "GUIDELINE_EMPTY_TEXT",
            "The PDF contains no extractable guideline text; OCR is not supported",
            status_code=422,
        )
    return pages


def create_pdf_guideline(
    db: Session,
    project: Project,
    data: bytes,
    filename: str,
) -> Guideline:
    pages = extract_pdf_pages(data)
    guideline_id = new_id()
    key = LocalStorage.build_key(project.id, "guidelines", guideline_id, "source.pdf")
    storage().write(key, data)
    text = "\n\n".join(f"[page={page.page}]\n{page.text}" for page in pages)
    guideline = Guideline(
        id=guideline_id,
        project_id=project.id,
        kind="pdf",
        source_filename=filename,
        text_content=text,
        storage_key=key,
        created_at=utc_now(),
    )
    db.add(guideline)
    db.flush()
    add_audit(
        db,
        project.id,
        "guideline.created",
        entity_id=guideline.id,
        details={"kind": "pdf", "page_count": len(pages)},
    )
    return guideline


def _next_version(db: Session, project_id: str) -> int:
    return (
        db.scalar(
            select(func.max(RuleSetRecord.version)).where(RuleSetRecord.project_id == project_id)
        )
        or 0
    ) + 1


def _new_draft(
    db: Session,
    project: Project,
    *,
    name: str,
    rules: list[FormatRule],
    guideline_id: str | None,
) -> RuleSetRecord:
    normalized = [rule.model_dump(mode="json") for rule in validated_rules(rules)]
    record = RuleSetRecord(
        id=new_id(),
        project_id=project.id,
        version=_next_version(db, project.id),
        name=name,
        status="DRAFT",
        digest=compute_ruleset_digest(normalized),
        rules_json=normalized,
        conflicts_json=[item.model_dump(mode="json") for item in find_conflicts(normalized)],
        guideline_id=guideline_id,
        created_at=utc_now(),
    )
    db.add(record)
    db.flush()
    add_audit(
        db,
        project.id,
        "rule_set.drafted",
        entity_id=record.id,
        details={"version": record.version, "digest": record.digest, "rule_count": len(normalized)},
    )
    return record


def create_preset_draft(
    db: Session,
    project: Project,
    guideline: Guideline,
    preset_id: str,
) -> RuleSetRecord:
    preset = load_preset(preset_id)
    return _new_draft(
        db,
        project,
        name=preset.name,
        rules=list(preset.rules),
        guideline_id=guideline.id,
    )


def create_manual_draft(
    db: Session,
    project: Project,
    *,
    name: str,
    rules: list[FormatRule],
    guideline_id: str | None,
) -> RuleSetRecord:
    if guideline_id is not None:
        guideline = db.get(Guideline, guideline_id)
        if guideline is None:
            raise AlineaError("GUIDELINE_NOT_FOUND", "The guideline was not found", status_code=404)
        require_ownership(project, guideline.project_id)
    return _new_draft(db, project, name=name, rules=rules, guideline_id=guideline_id)


def save_draft(
    db: Session,
    project: Project,
    record: RuleSetRecord,
    *,
    name: str,
    rules: list[FormatRule],
) -> RuleSetRecord:
    normalized = [rule.model_dump(mode="json") for rule in validated_rules(rules)]
    digest = compute_ruleset_digest(normalized)
    conflicts = [item.model_dump(mode="json") for item in find_conflicts(normalized)]
    if record.status == "APPROVED":
        return _new_draft(
            db,
            project,
            name=name,
            rules=rules,
            guideline_id=record.guideline_id,
        )
    record.name = name
    record.rules_json = normalized
    record.digest = digest
    record.conflicts_json = conflicts
    record.approved_at = None
    add_audit(db, project.id, "rule_set.edited", entity_id=record.id, details={"digest": digest})
    db.flush()
    return record


def _normalized_text(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).split())


def approve_draft(db: Session, project: Project, record: RuleSetRecord) -> RuleSetRecord:
    if record.status == "APPROVED":
        return record
    rules = validated_rules(record.rules_json)
    if not any(rule.enabled for rule in rules):
        raise AlineaError(
            "EMPTY_RULE_SET",
            "At least one enabled rule is required before approval",
            status_code=422,
        )
    digest = compute_ruleset_digest(rules)
    if digest != record.digest:
        raise AlineaError("RULE_SET_CHANGED", "The rule-set digest is stale", status_code=409)
    conflicts = find_conflicts(rules)
    if conflicts:
        record.conflicts_json = [item.model_dump(mode="json") for item in conflicts]
        raise AlineaError(
            "RULE_CONFLICTS_UNRESOLVED",
            "Resolve all rule conflicts before approval",
            status_code=409,
            details={"conflict_ids": [item.conflict_id for item in conflicts]},
        )
    guideline = db.get(Guideline, record.guideline_id) if record.guideline_id else None
    source_text = _normalized_text(guideline.text_content or "") if guideline else ""
    invalid_evidence: list[str] = []
    for rule in rules:
        if not rule.enabled or rule.source.source_type in {"manual", "preset", "docx_template"}:
            continue
        if not guideline or _normalized_text(rule.source.quote) not in source_text:
            invalid_evidence.append(rule.rule_id)
    if invalid_evidence:
        raise AlineaError(
            "RULE_EVIDENCE_INVALID",
            "Some enabled rules lack verifiable source evidence",
            status_code=422,
            details={"rule_ids": invalid_evidence},
        )
    record.status = "APPROVED"
    record.approved_at = utc_now()
    record.conflicts_json = []
    add_audit(
        db,
        project.id,
        "rule_set.approved",
        entity_id=record.id,
        details={"version": record.version, "digest": record.digest},
    )
    db.flush()
    return record


def _job_request(db: Session, job_id: str) -> dict[str, Any]:
    event = db.scalar(
        select(JobEvent).where(JobEvent.job_id == job_id).order_by(JobEvent.id).limit(1)
    )
    payload = event.payload_json.get("request_payload") if event else None
    return dict(payload) if isinstance(payload, dict) else {}


def execute_rule_extraction(job_id: str) -> str:
    with session_scope() as db:
        job = db.get(Job, job_id)
        if job is None:
            raise AlineaError("JOB_NOT_FOUND", "The extraction job was not found", status_code=404)
        request = _job_request(db, job_id)
        guideline = db.get(Guideline, str(request.get("guideline_id", "")))
        if guideline is None:
            raise AlineaError("GUIDELINE_NOT_FOUND", "The guideline was not found", status_code=404)
        require_ownership(db.get(Project, job.project_id), guideline.project_id)
        report_progress(job_id, "EXTRACTING", 20, "Interpreting formatting rules")
        preset_id = request.get("preset_id")
        if guideline.kind == "preset":
            preset_id = preset_id or guideline.text_content
        if preset_id:
            project = db.get(Project, job.project_id)
            assert project is not None
            record = create_preset_draft(db, project, guideline, str(preset_id))
            job.result_id = record.id
            return record.id
        settings = get_settings()
        api_key = settings.llm_api_key.get_secret_value()
        if not api_key:
            raise AlineaError(
                "LLM_NOT_CONFIGURED",
                "No LLM API key is configured; use a preset or create manual draft rules instead",
                status_code=503,
            )
        if guideline.kind == "pdf":
            if not guideline.storage_key:
                raise AlineaError(
                    "GUIDELINE_NOT_FOUND", "The source PDF is unavailable", status_code=404
                )
            pages = extract_pdf_pages(storage().read(guideline.storage_key))
            text = "\n\n".join(page.text for page in pages)
            source_type = "pdf"
        else:
            pages = []
            text = guideline.text_content or ""
            source_type = "user_text"
        interpreter = RuleInterpreter(
            base_url=settings.llm_base_url,
            api_key=api_key,
            model=settings.llm_model,
            timeout_seconds=settings.llm_timeout_seconds,
        )
        outcome = interpreter.extract(
            GuidelineInput(
                reference=guideline.source_filename or guideline.id,
                source_type=source_type,
                text=text,
                pages=pages,
            )
        )
        project = db.get(Project, job.project_id)
        assert project is not None
        record = _new_draft(
            db,
            project,
            name=guideline.source_filename or "Extracted rules",
            rules=outcome.extraction.rules,
            guideline_id=guideline.id,
        )
        job.result_id = record.id
        add_audit(
            db,
            project.id,
            "rule_set.agent_extracted",
            job=job,
            actor="WORKER",
            entity_id=record.id,
            details={
                "trace_id": outcome.metadata.trace_id,
                "duration_ms": outcome.metadata.duration_ms,
                "rule_count": outcome.metadata.rule_count,
                "uncertainty_count": len(outcome.extraction.uncertainties),
            },
        )
        return record.id


def require_ruleset(db: Session, project: Project, rule_set_id: str) -> RuleSetRecord:
    record = db.get(RuleSetRecord, rule_set_id)
    if record is None:
        raise AlineaError("RULE_SET_NOT_FOUND", "The rule set was not found", status_code=404)
    require_ownership(project, record.project_id)
    return record


def approved_ruleset(
    db: Session, project: Project, rule_set_id: str, version: int
) -> RuleSetRecord:
    record = require_ruleset(db, project, rule_set_id)
    if record.status != "APPROVED" or record.version != version or record.approved_at is None:
        raise AlineaError(
            "RULE_SET_NOT_APPROVED",
            "The exact rule-set version must be approved before inspection",
            status_code=409,
        )
    contract = ruleset_contract(record)
    if compute_ruleset_digest(contract.rules) != record.digest:
        raise AlineaError(
            "RULE_SET_CHANGED", "The approved rule-set digest is invalid", status_code=409
        )
    return record
