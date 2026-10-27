from __future__ import annotations

from typing import Literal

from alinea_contracts.models import QualityGateResult
from pydantic import BaseModel, ConfigDict


class RepairApplyResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plan_id: str
    plan_digest: str
    status: Literal["PATCHED", "BLOCKED"]
    publishable: bool
    candidate_path: str | None
    base_sha256: str
    candidate_sha256: str | None
    execution_key: str | None
    changed_parts: list[str]
    gates: list[QualityGateResult]
