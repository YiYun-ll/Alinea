from __future__ import annotations

import json
from typing import Literal

from alinea_contracts import FormatRule
from pydantic import BaseModel, ConfigDict, Field


def parse_model_json[ModelT: BaseModel](value: str, output_type: type[ModelT]) -> ModelT:
    text = value.strip()
    if text.startswith("```"):
        text = text.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    try:
        return output_type.model_validate_json(text)
    except Exception:
        start = text.find("{")
        if start < 0:
            raise
        decoded, _ = json.JSONDecoder().raw_decode(text[start:])
        return output_type.model_validate(decoded)


class ClarificationQuestion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question_id: str = Field(min_length=1, max_length=80)
    question: str = Field(min_length=1, max_length=500)
    context: str = Field(default="", max_length=500)


class RoleSuggestion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target: str = Field(min_length=1, max_length=200)
    role: Literal[
        "body", "heading_1", "heading_2", "heading_3", "caption", "table_text", "reference", "unknown"
    ]
    confidence: float = Field(ge=0, le=1)
    evidence: str = Field(min_length=1, max_length=300)


class AgentOutcome(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str = Field(min_length=1, max_length=4000)
    rules: list[FormatRule] = Field(default_factory=list)
    uncertainties: list[str] = Field(default_factory=list)
    clarifications: list[ClarificationQuestion] = Field(default_factory=list)
    role_suggestions: list[RoleSuggestion] = Field(default_factory=list)
    selected_issue_ids: list[str] = Field(default_factory=list)
    recommended_action: Literal[
        "NONE", "REVIEW_RULES", "REVIEW_INSPECTION", "REVIEW_REPAIR", "REVIEW_RESULTS"
    ] = "NONE"


class AgentBudget(BaseModel):
    max_steps: int = Field(default=10, ge=1, le=20)
    max_tool_calls: int = Field(default=12, ge=1, le=30)
    max_characters: int = Field(default=4000, ge=100, le=32000)
    max_paragraph_candidates: int = Field(default=20, ge=1, le=50)
