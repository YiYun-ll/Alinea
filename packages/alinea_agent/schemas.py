from __future__ import annotations

from typing import Literal

from alinea_contracts import FormatRule
from pydantic import BaseModel, ConfigDict, Field


class GuidelinePage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    page: int = Field(ge=1)
    text: str


class GuidelineInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reference: str
    source_type: Literal["user_text", "pdf", "manual"] = "user_text"
    text: str
    pages: list[GuidelinePage] = Field(default_factory=list)


class RuleExtractionResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rules: list[FormatRule] = Field(default_factory=list)
    uncertainties: list[str] = Field(default_factory=list)


class AgentRunMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    trace_id: str
    model: str
    duration_ms: int = Field(ge=0)
    rule_count: int = Field(ge=0)
    retry_count: int = Field(ge=0, le=1)
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)


class ExtractionOutcome(BaseModel):
    model_config = ConfigDict(extra="forbid")

    extraction: RuleExtractionResult
    metadata: AgentRunMetadata
