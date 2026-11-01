from __future__ import annotations

from typing import Literal

from alinea_contracts.models import FormatRule
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class RequestModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ProjectCreate(RequestModel):
    name: str = Field(min_length=1, max_length=255)


class GuidelineCreate(RequestModel):
    kind: Literal["preset", "text"]
    preset_id: str | None = Field(default=None, pattern=r"^[a-z0-9_]+$")
    text: str | None = Field(default=None, max_length=100_000)
    name: str | None = Field(default=None, max_length=255)

    @model_validator(mode="after")
    def validate_source(self) -> GuidelineCreate:
        if self.kind == "preset" and not self.preset_id:
            raise ValueError("preset_id is required for a preset guideline")
        if self.kind == "text" and (self.text is None or not self.text.strip()):
            raise ValueError("text is required and cannot be empty for a text guideline")
        return self


class ExtractRulesRequest(RequestModel):
    guideline_id: str
    preset_id: str | None = Field(default=None, pattern=r"^[a-z0-9_]+$")


class RuleSetUpdate(RequestModel):
    name: str = Field(min_length=1, max_length=255)
    rules: list[FormatRule] = Field(max_length=500)


class ManualRuleSetCreate(RuleSetUpdate):
    guideline_id: str | None = None


class InspectionCreate(RequestModel):
    revision_id: str
    rule_set_id: str
    rule_set_version: int = Field(ge=1)
    include_page_mapping: bool = True


class RepairPlanCreate(RequestModel):
    base_revision_id: str
    inspection_id: str
    selected_issue_ids: list[str] = Field(min_length=1, max_length=500)

    @field_validator("selected_issue_ids")
    @classmethod
    def unique_issue_ids(cls, value: list[str]) -> list[str]:
        if len(set(value)) != len(value) or any(not item for item in value):
            raise ValueError("selected_issue_ids must be non-empty and duplicate-free")
        return value


class RepairPlanApprove(RequestModel):
    plan_digest: str = Field(min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")


class AgentRunCreate(RequestModel):
    objective: str = Field(min_length=1, max_length=4000)
    guideline_id: str | None = None
    revision_id: str | None = None
    rule_set_id: str | None = None
    inspection_id: str | None = None


class AgentRunMessage(RequestModel):
    message: str = Field(min_length=1, max_length=4000)
