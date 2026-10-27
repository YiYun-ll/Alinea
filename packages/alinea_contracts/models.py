from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class RunRange(ContractModel):
    start: int = Field(ge=0)
    end: int = Field(ge=0)


class ElementRef(ContractModel):
    revision_id: str
    part_uri: str
    kind: Literal["paragraph", "section"]
    xml_path: str
    container_path: list[str] = Field(default_factory=list)
    paragraph_ordinal: int = Field(ge=0)
    run_range: RunRange | None = None
    section_ordinal: int | None = Field(default=None, ge=0)
    para_id: str | None = None
    text_sha256: str
    context_before_sha256: str | None = None
    context_after_sha256: str | None = None
    text_excerpt: str = ""
    anchor_schema_version: str = "1.0"


class ResolvedProperty(ContractModel):
    property: str
    value: JsonValue = None
    status: Literal["RESOLVED", "UNRESOLVED", "UNSUPPORTED", "CONFLICTED"]
    origin: Literal[
        "DIRECT",
        "CHARACTER_STYLE",
        "PARAGRAPH_STYLE",
        "BASED_ON",
        "DOC_DEFAULT",
        "THEME",
        "NUMBERING",
        "UNKNOWN",
    ] = "UNKNOWN"
    origin_ref: str | None = None
    raw_ooxml_value: str | None = None
    provenance: list[dict[str, JsonValue]] = Field(default_factory=list)
    reason: str | None = None


class RunNode(ContractModel):
    index: int = Field(ge=0)
    text: str
    character_style_id: str | None = None
    effective: dict[str, ResolvedProperty] = Field(default_factory=dict)
    unsupported_features: list[str] = Field(default_factory=list)


class ParagraphNode(ContractModel):
    element_ref: ElementRef
    text: str
    normalized_text: str
    p_style_id: str | None = None
    semantic_role: Literal[
        "body",
        "heading_1",
        "heading_2",
        "heading_3",
        "caption",
        "table_text",
        "reference",
        "unknown",
    ]
    role_confidence: float = Field(ge=0, le=1)
    inside_table: bool = False
    runs: list[RunNode] = Field(default_factory=list)
    effective: dict[str, ResolvedProperty] = Field(default_factory=dict)
    unsupported_features: list[str] = Field(default_factory=list)


class SectionNode(ContractModel):
    element_ref: ElementRef
    effective: dict[str, ResolvedProperty] = Field(default_factory=dict)


class PartDescriptor(ContractModel):
    part_uri: str
    content_type: str | None = None
    size: int = Field(ge=0)
    sha256: str


class StyleNode(ContractModel):
    style_id: str
    style_type: Literal["paragraph", "character", "table", "numbering", "unknown"]
    name: str | None = None
    based_on: str | None = None
    default: bool = False


class DocumentSnapshot(ContractModel):
    revision_id: str
    sha256: str
    parts: list[PartDescriptor]
    paragraphs: list[ParagraphNode]
    sections: list[SectionNode]
    styles: dict[str, StyleNode]
    unsupported_features: list[str] = Field(default_factory=list)
    fingerprints: dict[str, str] = Field(default_factory=dict)
    package_inventory: dict[str, JsonValue] = Field(default_factory=dict)
    renderer_profile_id: str | None = None


class SourceRef(ContractModel):
    source_type: Literal["manual", "preset", "user_text", "pdf", "docx_template", "agent"]
    reference: str
    page: int | None = Field(default=None, ge=1)
    quote: str = ""
    extraction_confidence: float | None = Field(default=None, ge=0, le=1)


Selector = Literal[
    "body",
    "heading_1",
    "heading_2",
    "heading_3",
    "caption",
    "table_text",
    "section",
]

FormatProperty = Literal[
    "font.eastAsia",
    "font.ascii",
    "font.size_pt",
    "font.bold",
    "paragraph.alignment",
    "paragraph.first_line_indent_chars",
    "paragraph.first_line_indent_mm",
    "paragraph.left_indent_mm",
    "paragraph.right_indent_mm",
    "paragraph.line_spacing",
    "paragraph.space_before_pt",
    "paragraph.space_after_pt",
    "section.margin_top_mm",
    "section.margin_bottom_mm",
    "section.margin_left_mm",
    "section.margin_right_mm",
    "section.page_width_mm",
    "section.page_height_mm",
]


class FormatRule(ContractModel):
    rule_id: str = Field(pattern=r"^[A-Za-z0-9_-]+$")
    name: str = ""
    selector: Selector
    property: FormatProperty
    operator: Literal["eq", "in", "between"] = "eq"
    expected: JsonValue
    tolerance: float = Field(default=0, ge=0)
    enabled: bool = True
    severity: Literal["ERROR", "WARNING", "INFO"] = "ERROR"
    fix_policy: Literal["AUTO_WITH_APPROVAL", "MANUAL_ONLY", "UNSUPPORTED"] = "AUTO_WITH_APPROVAL"
    source: SourceRef
    confidence: float = Field(default=1, ge=0, le=1)
    exclusions: list[str] = Field(default_factory=list)


class RuleConflict(ContractModel):
    conflict_id: str
    rule_ids: list[str]
    property: str
    reason: str
    resolved: bool = False


class RuleSet(ContractModel):
    rule_set_id: str
    project_id: str
    version: int = Field(ge=1)
    name: str
    status: Literal["DRAFT", "APPROVED"]
    digest: str
    rules: list[FormatRule]
    conflicts: list[RuleConflict] = Field(default_factory=list)
    guideline_id: str | None = None
    created_at: datetime | None = None
    approved_at: datetime | None = None


class ValueEvidence(ContractModel):
    value: JsonValue = None
    unit: str | None = None
    origin: str | None = None
    raw_ooxml_value: str | None = None
    reason: str | None = None


class RepairEligibility(ContractModel):
    eligibility: Literal["SAFE_SINGLE_TARGET", "NEEDS_REVIEW", "UNSUPPORTED"]
    requires_approval: bool = True
    reason: str | None = None


class LocationFragment(ContractModel):
    page_index: int = Field(ge=0)
    page_size_pt: dict[str, float]
    rects_normalized: list[list[float]]


class LocationMapping(ContractModel):
    issue_id: str = ""
    revision_id: str
    preview_pdf_sha256: str | None = None
    renderer_profile_id: str | None = None
    status: Literal["LOCATED", "AMBIGUOUS", "UNLOCATED", "NOT_RENDERED", "PENDING"]
    page_index: int | None = Field(default=None, ge=0)
    fragments: list[LocationFragment] = Field(default_factory=list)
    score: float | None = None
    candidate_count: int = 0
    anchor_excerpt: str = ""
    method: str = "TEXT_ANCHOR_CONTEXT"
    reason: str | None = None


class Issue(ContractModel):
    issue_id: str
    inspection_id: str
    revision_id: str
    rule_id: str
    element_ref: ElementRef
    property: FormatProperty
    actual: ValueEvidence
    expected: ValueEvidence
    detection_status: Literal["CONFIRMED_VIOLATION", "POSSIBLE_VIOLATION", "UNKNOWN"]
    severity: Literal["ERROR", "WARNING", "INFO"]
    repair: RepairEligibility
    location: LocationMapping
    source: SourceRef
    fingerprint: str
    fix_status: Literal[
        "OPEN",
        "PLANNED",
        "FIXED",
        "STILL_FAILING",
        "IGNORED",
        "NEEDS_REVIEW",
    ] = "OPEN"


class InspectionSummary(ContractModel):
    violations: int = 0
    unverifiable: int = 0
    fixable: int = 0
    evaluated_rules: int = 0
    skipped_rules: int = 0
    located: int = 0
    ambiguous: int = 0
    unlocated: int = 0


class RenderArtifact(ContractModel):
    pdf_path: str
    pdf_sha256: str
    render_profile_id: str
    page_count: int = Field(ge=0)
    warnings: list[str] = Field(default_factory=list)


class RepairOperation(ContractModel):
    operation_id: str
    issue_id: str
    base_revision_sha256: str
    rule_set_digest: str
    target: ElementRef
    property: FormatProperty
    expected_before: JsonValue
    desired_after: JsonValue
    strategy: Literal["DIRECT_RUN_PROPERTY", "DIRECT_PARAGRAPH_PROPERTY", "DIRECT_SECTION_PROPERTY"]
    impact_scope: str
    allowed_xml_changes: list[str]
    risk: Literal["low", "medium", "high"] = "low"


class RepairPlan(ContractModel):
    plan_id: str
    project_id: str
    base_revision_id: str
    inspection_id: str
    rule_set_id: str
    rule_set_version: int
    rule_set_digest: str
    status: Literal["DRAFT", "APPROVED", "QUEUED", "RUNNING", "SUCCEEDED", "FAILED", "STALE"]
    plan_digest: str
    selected_issue_ids: list[str]
    operations: list[RepairOperation]
    affected_node_count: int
    approved_at: datetime | None = None
    execution_key: str | None = None
    result_revision_id: str | None = None


class QualityGateResult(ContractModel):
    gate: Literal["G0", "G1", "G2", "G3", "G4", "G5"]
    status: Literal["PASS", "WARN", "FAIL", "NOT_RUN"]
    details: dict[str, JsonValue] = Field(default_factory=dict)


class VerificationReport(ContractModel):
    revision_id: str
    base_revision_id: str
    inspection_id: str | None = None
    before_inspection_id: str | None = None
    status: Literal["PASS", "PARTIAL", "BLOCKED", "INDETERMINATE"]
    selected_count: int = 0
    resolved_count: int = 0
    remaining_count: int = 0
    gates: list[QualityGateResult]
    operations: list[RepairOperation] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    renderer_profile_id: str | None = None
    original_sha256: str
    revision_sha256: str
    generated_at: datetime


class InspectionResult(ContractModel):
    inspection_id: str
    revision_id: str
    rule_set_id: str
    rule_set_digest: str
    inspector_version: str
    status: Literal["RUNNING", "SUCCEEDED", "FAILED"]
    issues: list[Issue]
    summary: InspectionSummary
    preview: RenderArtifact | None = None
    warnings: list[str] = Field(default_factory=list)
    created_at: datetime
