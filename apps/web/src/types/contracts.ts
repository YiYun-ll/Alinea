export type JsonValue = null | boolean | number | string | unknown[] | { [key: string]: unknown }

export interface RunRange {
  start: number
  end: number
}

export interface ElementRef {
  revision_id: string
  part_uri: string
  kind: 'paragraph' | 'section'
  xml_path: string
  container_path: string[]
  paragraph_ordinal: number
  run_range: RunRange | null
  section_ordinal: number | null
  para_id: string | null
  text_sha256: string
  context_before_sha256: string | null
  context_after_sha256: string | null
  text_excerpt: string
  anchor_schema_version: string
}

export type ResolutionStatus = 'RESOLVED' | 'UNRESOLVED' | 'UNSUPPORTED' | 'CONFLICTED'
export type PropertyOrigin = 'DIRECT' | 'CHARACTER_STYLE' | 'PARAGRAPH_STYLE' | 'BASED_ON' | 'DOC_DEFAULT' | 'THEME' | 'NUMBERING' | 'UNKNOWN'

export interface ResolvedProperty {
  property: string
  value: JsonValue
  status: ResolutionStatus
  origin: PropertyOrigin
  origin_ref: string | null
  raw_ooxml_value: string | null
  provenance: Array<Record<string, JsonValue>>
  reason: string | null
}

export interface RunNode {
  index: number
  text: string
  character_style_id: string | null
  effective: Record<string, ResolvedProperty>
  unsupported_features: string[]
}

export type SemanticRole = 'body' | 'heading_1' | 'heading_2' | 'heading_3' | 'caption' | 'table_text' | 'reference' | 'unknown'

export interface ParagraphNode {
  element_ref: ElementRef
  text: string
  normalized_text: string
  p_style_id: string | null
  semantic_role: SemanticRole
  role_confidence: number
  inside_table: boolean
  runs: RunNode[]
  effective: Record<string, ResolvedProperty>
  unsupported_features: string[]
}

export interface SectionNode {
  element_ref: ElementRef
  effective: Record<string, ResolvedProperty>
}

export interface PartDescriptor {
  part_uri: string
  content_type: string | null
  size: number
  sha256: string
}

export interface StyleNode {
  style_id: string
  style_type: 'paragraph' | 'character' | 'table' | 'numbering' | 'unknown'
  name: string | null
  based_on: string | null
  default: boolean
}

export interface DocumentSnapshot {
  revision_id: string
  sha256: string
  parts: PartDescriptor[]
  paragraphs: ParagraphNode[]
  sections: SectionNode[]
  styles: Record<string, StyleNode>
  unsupported_features: string[]
  fingerprints: Record<string, string>
  package_inventory: Record<string, JsonValue>
  renderer_profile_id: string | null
}

export interface SourceRef {
  source_type: 'manual' | 'preset' | 'user_text' | 'pdf' | 'docx_template' | 'agent'
  reference: string
  page: number | null
  quote: string
  extraction_confidence: number | null
}

export type Selector = 'body' | 'heading_1' | 'heading_2' | 'heading_3' | 'caption' | 'table_text' | 'section'
export type FormatProperty = 'font.eastAsia' | 'font.ascii' | 'font.size_pt' | 'font.bold' | 'paragraph.alignment' | 'paragraph.first_line_indent_chars' | 'paragraph.first_line_indent_mm' | 'paragraph.left_indent_mm' | 'paragraph.right_indent_mm' | 'paragraph.line_spacing' | 'paragraph.space_before_pt' | 'paragraph.space_after_pt' | 'section.margin_top_mm' | 'section.margin_bottom_mm' | 'section.margin_left_mm' | 'section.margin_right_mm' | 'section.page_width_mm' | 'section.page_height_mm'

export interface FormatRule {
  rule_id: string
  name: string
  selector: Selector
  property: FormatProperty
  operator: 'eq' | 'in' | 'between'
  expected: JsonValue
  tolerance: number
  enabled: boolean
  severity: 'ERROR' | 'WARNING' | 'INFO'
  fix_policy: 'AUTO_WITH_APPROVAL' | 'MANUAL_ONLY' | 'UNSUPPORTED'
  source: SourceRef
  confidence: number
  exclusions: string[]
}

export interface RuleConflict {
  conflict_id: string
  rule_ids: string[]
  property: string
  reason: string
  resolved: boolean
}

export interface RuleSet {
  rule_set_id: string
  project_id: string
  version: number
  name: string
  status: 'DRAFT' | 'APPROVED'
  digest: string
  rules: FormatRule[]
  conflicts: RuleConflict[]
  guideline_id: string | null
  created_at: string | null
  approved_at: string | null
}

export interface ValueEvidence {
  value: JsonValue
  unit: string | null
  origin: string | null
  raw_ooxml_value: string | null
  reason: string | null
}

export interface RepairEligibility {
  eligibility: 'SAFE_SINGLE_TARGET' | 'NEEDS_REVIEW' | 'UNSUPPORTED'
  requires_approval: boolean
  reason: string | null
}

export interface LocationFragment {
  page_index: number
  page_size_pt: Record<string, number>
  rects_normalized: number[][]
}

export type LocationStatus = 'LOCATED' | 'AMBIGUOUS' | 'UNLOCATED' | 'NOT_RENDERED' | 'PENDING'

export interface LocationMapping {
  issue_id: string
  revision_id: string
  preview_pdf_sha256: string | null
  renderer_profile_id: string | null
  status: LocationStatus
  page_index: number | null
  fragments: LocationFragment[]
  score: number | null
  candidate_count: number
  anchor_excerpt: string
  method: string
  reason: string | null
}

export interface Issue {
  issue_id: string
  inspection_id: string
  revision_id: string
  rule_id: string
  element_ref: ElementRef
  property: FormatProperty
  actual: ValueEvidence
  expected: ValueEvidence
  detection_status: 'CONFIRMED_VIOLATION' | 'POSSIBLE_VIOLATION' | 'UNKNOWN'
  severity: 'ERROR' | 'WARNING' | 'INFO'
  repair: RepairEligibility
  location: LocationMapping
  source: SourceRef
  fingerprint: string
  fix_status: 'OPEN' | 'PLANNED' | 'FIXED' | 'STILL_FAILING' | 'IGNORED' | 'NEEDS_REVIEW'
}

export interface InspectionSummary {
  violations: number
  unverifiable: number
  fixable: number
  evaluated_rules: number
  skipped_rules: number
  located: number
  ambiguous: number
  unlocated: number
}

export interface RenderArtifact {
  pdf_path: string
  pdf_sha256: string
  render_profile_id: string
  page_count: number
  warnings: string[]
}

export interface RepairOperation {
  operation_id: string
  issue_id: string
  base_revision_sha256: string
  rule_set_digest: string
  target: ElementRef
  property: FormatProperty
  expected_before: JsonValue
  desired_after: JsonValue
  strategy: 'DIRECT_RUN_PROPERTY' | 'DIRECT_PARAGRAPH_PROPERTY' | 'DIRECT_SECTION_PROPERTY'
  impact_scope: string
  allowed_xml_changes: string[]
  risk: 'low' | 'medium' | 'high'
}

export interface RepairPlan {
  plan_id: string
  project_id: string
  base_revision_id: string
  inspection_id: string
  rule_set_id: string
  rule_set_version: number
  rule_set_digest: string
  status: 'DRAFT' | 'APPROVED' | 'QUEUED' | 'RUNNING' | 'SUCCEEDED' | 'FAILED' | 'STALE'
  plan_digest: string
  selected_issue_ids: string[]
  operations: RepairOperation[]
  affected_node_count: number
  approved_at: string | null
  execution_key: string | null
  result_revision_id: string | null
}

export interface QualityGateResult {
  gate: 'G0' | 'G1' | 'G2' | 'G3' | 'G4' | 'G5'
  status: 'PASS' | 'WARN' | 'FAIL' | 'NOT_RUN'
  details: Record<string, JsonValue>
}

export interface VerificationReport {
  revision_id: string
  base_revision_id: string
  inspection_id: string | null
  before_inspection_id: string | null
  status: 'PASS' | 'PARTIAL' | 'BLOCKED' | 'INDETERMINATE'
  selected_count: number
  resolved_count: number
  remaining_count: number
  gates: QualityGateResult[]
  operations: RepairOperation[]
  warnings: string[]
  renderer_profile_id: string | null
  original_sha256: string
  revision_sha256: string
  generated_at: string
}

export interface InspectionResult {
  inspection_id: string
  revision_id: string
  rule_set_id: string
  rule_set_digest: string
  inspector_version: string
  status: 'RUNNING' | 'SUCCEEDED' | 'FAILED'
  issues: Issue[]
  summary: InspectionSummary
  preview: RenderArtifact | null
  warnings: string[]
  created_at: string
}

export interface Revision {
  revision_id: string
  project_id?: string
  parent_revision_id?: string | null
  sha256?: string
  status?: string
  kind?: string
  original_filename?: string | null
  created_at?: string
}

export interface Project {
  project_id: string
  name: string
  status?: string
  original_revision_id?: string | null
  revision_id?: string | null
  active_revision_id?: string | null
  revisions?: Revision[]
  created_at?: string
  expires_at?: string | null
}

export interface ProjectCreated extends Project {
  token: string
}

export interface DocumentUpload {
  revision_id: string
  status?: string
  sha256?: string
}

export interface Guideline {
  guideline_id: string
  name?: string | null
  kind?: string
}

export interface DemoResponse extends ProjectCreated {
  revision_id: string
  rule_set_id: string
}

export interface Job {
  job_id: string
  project_id?: string
  job_type?: string
  status: 'CREATED' | 'PENDING' | 'QUEUED' | 'RUNNING' | 'SUCCEEDED' | 'FAILED' | 'CANCELLED'
  retryable?: boolean
  progress?: number
  stage?: string | null
  message?: string | null
  error_code?: string | null
  error_message?: string | null
  inspection_id?: string | null
  result_revision_id?: string | null
  result?: {
    revision_id?: string
    result_revision_id?: string
    inspection_id?: string
    rule_set_id?: string
  } | null
  created_at?: string
  started_at?: string | null
  updated_at?: string | null
  completed_at?: string | null
}

export interface AuditEvent {
  id?: string
  audit_id?: string
  project_id: string
  job_id?: string | null
  actor?: string
  actor_type?: string
  action?: string
  event_type?: string
  entity_id?: string | null
  details?: Record<string, JsonValue>
  details_json?: Record<string, JsonValue>
  created_at: string
}

export interface Artifact {
  kind: string
  url: string
  sha256: string
}

export interface ApiErrorBody {
  code: string
  message: string
  request_id?: string
  retryable: boolean
  details?: Record<string, JsonValue>
}

export type AgentRunStatus = 'QUEUED' | 'RUNNING' | 'NEEDS_CLARIFICATION' | 'SUCCEEDED' | 'FAILED'
export type AgentAction = 'NONE' | 'REVIEW_RULES' | 'REVIEW_INSPECTION' | 'REVIEW_REPAIR' | 'REVIEW_RESULTS'

export interface AgentClarification {
  question_id: string
  question: string
  context: string
}

export interface AgentRoleSuggestion {
  target: string
  role: SemanticRole
  confidence: number
  evidence: string
}

export interface AgentResult {
  message: string
  rules?: FormatRule[]
  uncertainties?: string[]
  role_suggestions?: AgentRoleSuggestion[]
  recommended_action: AgentAction
  rule_set_id?: string
  inspection_id?: string
  repair_plan_id?: string
  role_revision_id?: string
}

export interface AgentEvent {
  sequence: number
  event_type: string
  tool_name: string | null
  status: string
  duration_ms: number
  payload: Record<string, JsonValue>
  created_at: string
}

export interface AgentRun {
  run_id: string
  project_id: string
  status: AgentRunStatus
  objective: string
  context: {
    guideline_id?: string
    revision_id?: string
    rule_set_id?: string
    rule_set_version?: number
    inspection_id?: string
    messages?: string[]
  }
  result: AgentResult | Record<string, never>
  clarifications: AgentClarification[]
  model: string
  step_count: number
  tool_call_count: number
  input_tokens: number
  output_tokens: number
  duration_ms: number
  error_code: string | null
  error_message: string | null
  job_id: string | null
  created_at: string
  updated_at: string
  completed_at: string | null
  events: AgentEvent[]
}

export interface AgentRunInput {
  objective: string
  guideline_id?: string
  revision_id?: string
  rule_set_id?: string
  inspection_id?: string
}
