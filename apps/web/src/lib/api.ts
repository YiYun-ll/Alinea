import { getProjectToken } from './auth'
import type {
  Artifact,
  AuditEvent,
  DemoResponse,
  DocumentUpload,
  FormatRule,
  Guideline,
  InspectionResult,
  InspectionSummary,
  Issue,
  Job,
  JsonValue,
  Project,
  ProjectCreated,
  RepairPlan,
  Revision,
  RuleSet,
  VerificationReport,
} from '../types/contracts'

const API_BASE = (import.meta.env.VITE_API_BASE_URL as string | undefined)?.replace(/\/$/, '') ?? '/api/v1'

interface RequestOptions {
  method?: 'GET' | 'POST' | 'PUT' | 'DELETE'
  projectId?: string
  json?: JsonValue
  form?: FormData
  headers?: Record<string, string>
  signal?: AbortSignal
}

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly code: string,
    readonly retryable: boolean,
    readonly requestId?: string,
    readonly details?: Record<string, JsonValue>,
  ) {
    super(message)
    this.name = 'ApiError'
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null
}

function stringValue(value: unknown): string | undefined {
  return typeof value === 'string' ? value : undefined
}

async function errorFromResponse(response: Response): Promise<ApiError> {
  const payload: unknown = await response.clone().json().catch(() => null)
  const root = isRecord(payload) ? payload : null
  const nested = root && isRecord(root.error) ? root.error : root
  const message = nested ? stringValue(nested.message) : undefined
  const code = nested ? stringValue(nested.code) : undefined
  const requestId = nested ? stringValue(nested.request_id) : undefined
  const retryable = nested && typeof nested.retryable === 'boolean' ? nested.retryable : response.status >= 500
  const details = nested && isRecord(nested.details) ? nested.details as Record<string, JsonValue> : undefined
  return new ApiError(message ?? `请求失败（HTTP ${response.status}）`, response.status, code ?? 'HTTP_ERROR', retryable, requestId, details)
}

async function fetchResponse(path: string, options: RequestOptions = {}): Promise<Response> {
  const headers = new Headers(options.headers)
  if (options.projectId) {
    const token = getProjectToken(options.projectId)
    if (!token) {
      throw new ApiError('此项目的本地访问凭证不存在或已失效，请重新创建项目。', 401, 'SESSION_EXPIRED', false)
    }
    headers.set('Authorization', `Bearer ${token}`)
  }
  let body: BodyInit | undefined
  if (options.form) {
    body = options.form
  } else if (options.json !== undefined) {
    headers.set('Content-Type', 'application/json')
    body = JSON.stringify(options.json)
  }
  let response: Response
  try {
    response = await fetch(`${API_BASE}${path}`, {
      method: options.method ?? 'GET',
      headers,
      body,
      signal: options.signal,
    })
  } catch (error) {
    if (error instanceof Error && error.name === 'AbortError') throw error
    throw new ApiError('无法连接服务器，请检查网络后重试。', 0, 'NETWORK_ERROR', true)
  }
  if (!response.ok) throw await errorFromResponse(response)
  return response
}

async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const response = await fetchResponse(path, options)
  if (response.status === 204) return undefined as T
  return await response.json() as T
}

async function requestBlob(path: string, options: RequestOptions = {}): Promise<{ blob: Blob; filename: string | null }> {
  const response = await fetchResponse(path, options)
  const disposition = response.headers.get('Content-Disposition')
  const match = disposition?.match(/filename\*?=(?:UTF-8''|")?([^";]+)/i)
  return { blob: await response.blob(), filename: match?.[1] ? decodeURIComponent(match[1]) : null }
}

function id(value: string): string {
  return encodeURIComponent(value)
}

function projectPath(projectId: string, suffix: string): string {
  return `/projects/${id(projectId)}${suffix}`
}

export interface InspectionAccepted {
  job_id: string
  inspection_id: string
  status?: string
  reused?: boolean
}

export interface IssuePage {
  data: Issue[]
  total: number
  summary: InspectionSummary
}

export type GuidelineInput =
  | { kind: 'preset'; preset_id: string; name?: string }
  | { kind: 'text'; text: string; name?: string }
  | { kind: 'pdf'; file: File; name?: string }

export const api = {
  createProject(name: string): Promise<ProjectCreated> {
    return request<ProjectCreated>('/projects', { method: 'POST', json: { name } })
  },
  createDemo(): Promise<DemoResponse> {
    return request<DemoResponse>('/demo', { method: 'POST' })
  },
  getProject(projectId: string): Promise<Project> {
    return request<Project>(projectPath(projectId, ''), { projectId })
  },
  deleteProject(projectId: string): Promise<void> {
    return request<void>(projectPath(projectId, ''), { method: 'DELETE', projectId })
  },
  uploadDocument(projectId: string, file: File): Promise<DocumentUpload> {
    const form = new FormData()
    form.append('file', file)
    return request<DocumentUpload>(projectPath(projectId, '/documents'), { method: 'POST', projectId, form })
  },
  createGuideline(projectId: string, input: GuidelineInput): Promise<Guideline> {
    if (input.kind === 'pdf') {
      const form = new FormData()
      form.append('file', input.file)
      return request<Guideline>(projectPath(projectId, '/guidelines'), { method: 'POST', projectId, form })
    }
    const json: Record<string, JsonValue> = { kind: input.kind }
    if (input.kind === 'preset') json.preset_id = input.preset_id
    if (input.kind === 'text') json.text = input.text
    if (input.name) json.name = input.name
    return request<Guideline>(projectPath(projectId, '/guidelines'), { method: 'POST', projectId, json })
  },
  extractRules(projectId: string, guidelineId: string, presetId?: string): Promise<{ job_id: string }> {
    const json: Record<string, JsonValue> = { guideline_id: guidelineId }
    if (presetId) json.preset_id = presetId
    return request<{ job_id: string }>(projectPath(projectId, '/rules/extract'), { method: 'POST', projectId, json })
  },
  getRules(projectId: string): Promise<RuleSet> {
    return request<RuleSet>(projectPath(projectId, '/rules'), { projectId })
  },
  saveRules(projectId: string, ruleSet: RuleSet, rules: FormatRule[], name: string): Promise<RuleSet> {
    return request<RuleSet>(projectPath(projectId, `/rulesets/${id(ruleSet.rule_set_id)}`), {
      method: 'PUT', projectId, json: { name, rules: rules as unknown as JsonValue },
    })
  },
  approveRules(projectId: string, ruleSetId: string): Promise<RuleSet> {
    return request<RuleSet>(projectPath(projectId, `/rules/${id(ruleSetId)}/approve`), { method: 'PUT', projectId })
  },
  createInspection(projectId: string, revisionId: string, ruleSet: RuleSet, idempotencyKey: string): Promise<InspectionAccepted> {
    return request<InspectionAccepted>(projectPath(projectId, '/inspections'), {
      method: 'POST', projectId, headers: { 'Idempotency-Key': idempotencyKey },
      json: { revision_id: revisionId, rule_set_id: ruleSet.rule_set_id, rule_set_version: ruleSet.version, include_page_mapping: true },
    })
  },
  getInspection(projectId: string, inspectionId: string): Promise<InspectionResult> {
    return request<InspectionResult>(`/inspections/${id(inspectionId)}`, { projectId })
  },
  getIssues(projectId: string, inspectionId: string, page = 1, pageSize = 200): Promise<IssuePage> {
    return request<IssuePage>(`/inspections/${id(inspectionId)}/issues?page=${page}&page_size=${pageSize}`, { projectId })
  },
  async getPreview(projectId: string, revisionId: string): Promise<ArrayBuffer> {
    const response = await fetchResponse(`/revisions/${id(revisionId)}/preview`, { projectId })
    return response.arrayBuffer()
  },
  createRepairPlan(projectId: string, baseRevisionId: string, inspectionId: string, selectedIssueIds: string[]): Promise<RepairPlan> {
    return request<RepairPlan>(projectPath(projectId, '/repair-plans'), {
      method: 'POST', projectId,
      json: { base_revision_id: baseRevisionId, inspection_id: inspectionId, selected_issue_ids: selectedIssueIds },
    })
  },
  approveRepairPlan(projectId: string, plan: RepairPlan): Promise<RepairPlan> {
    return request<RepairPlan>(`/repair-plans/${id(plan.plan_id)}/approve`, {
      method: 'POST', projectId, json: { plan_digest: plan.plan_digest },
    })
  },
  getRepairPlan(projectId: string, planId: string): Promise<RepairPlan> {
    return request<RepairPlan>(`/repair-plans/${id(planId)}`, { projectId })
  },
  executeRepairPlan(projectId: string, planId: string, idempotencyKey: string): Promise<{ job_id: string }> {
    return request<{ job_id: string }>(`/repair-plans/${id(planId)}/execute`, {
      method: 'POST', projectId, headers: { 'Idempotency-Key': idempotencyKey },
    })
  },
  getJob(projectId: string, jobId: string): Promise<Job> {
    return request<Job>(`/jobs/${id(jobId)}`, { projectId })
  },
  getProjectJobs(projectId: string): Promise<{ data: Job[] }> {
    return request<{ data: Job[] }>(projectPath(projectId, '/jobs'), { projectId })
  },
  retryJob(projectId: string, jobId: string): Promise<Job> {
    return request<Job>(`/jobs/${id(jobId)}/retry`, { method: 'POST', projectId })
  },
  cancelJob(projectId: string, jobId: string): Promise<Job> {
    return request<Job>(`/jobs/${id(jobId)}/cancel`, { method: 'POST', projectId })
  },
  getProjectAudit(projectId: string): Promise<{ data: AuditEvent[] }> {
    return request<{ data: AuditEvent[] }>(projectPath(projectId, '/audit-events'), { projectId })
  },
  getProjectRevisions(projectId: string): Promise<{ data: Revision[] }> {
    return request<{ data: Revision[] }>(projectPath(projectId, '/revisions'), { projectId })
  },
  getReport(projectId: string, revisionId: string): Promise<VerificationReport> {
    return request<VerificationReport>(`/revisions/${id(revisionId)}/report`, { projectId })
  },
  downloadReport(projectId: string, revisionId: string): Promise<{ blob: Blob; filename: string | null }> {
    return requestBlob(`/revisions/${id(revisionId)}/report?format=markdown`, { projectId })
  },
  downloadRevision(projectId: string, revisionId: string): Promise<{ blob: Blob; filename: string | null }> {
    return requestBlob(`/revisions/${id(revisionId)}/download`, { projectId })
  },
  getArtifacts(projectId: string, revisionId: string): Promise<{ data: Artifact[] }> {
    return request<{ data: Artifact[] }>(`/revisions/${id(revisionId)}/artifacts`, { projectId })
  },
  async downloadArtifact(projectId: string, artifact: Artifact): Promise<{ blob: Blob; filename: string | null }> {
    const target = new URL(artifact.url, window.location.origin)
    if (target.origin === window.location.origin) {
      return requestBlob(`${target.pathname}${target.search}`, { projectId })
    }
    const response = await fetch(target)
    if (!response.ok) throw await errorFromResponse(response)
    return { blob: await response.blob(), filename: null }
  },
}

export function createIdempotencyKey(): string {
  return crypto.randomUUID()
}
