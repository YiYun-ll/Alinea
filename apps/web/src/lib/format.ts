import { ApiError } from './api'
import type { FormatProperty, Issue, JsonValue, LocationStatus, SemanticRole } from '../types/contracts'

const propertyLabels: Record<FormatProperty, string> = {
  'font.eastAsia': '中文字体',
  'font.ascii': '西文字体',
  'font.size_pt': '字号',
  'font.bold': '字重',
  'paragraph.alignment': '段落对齐',
  'paragraph.first_line_indent_chars': '首行缩进（字符）',
  'paragraph.first_line_indent_mm': '首行缩进（毫米）',
  'paragraph.left_indent_mm': '左缩进',
  'paragraph.right_indent_mm': '右缩进',
  'paragraph.line_spacing': '行距',
  'paragraph.space_before_pt': '段前距',
  'paragraph.space_after_pt': '段后距',
  'section.margin_top_mm': '上边距',
  'section.margin_bottom_mm': '下边距',
  'section.margin_left_mm': '左边距',
  'section.margin_right_mm': '右边距',
  'section.page_width_mm': '页面宽度',
  'section.page_height_mm': '页面高度',
}

const roleLabels: Record<SemanticRole | 'section', string> = {
  body: '正文', heading_1: '一级标题', heading_2: '二级标题', heading_3: '三级标题',
  caption: '图表题', table_text: '表格文字', reference: '引文', unknown: '未分类', section: '页面节',
}

export function propertyLabel(property: FormatProperty): string {
  return propertyLabels[property]
}

export function roleLabel(role: SemanticRole | 'section'): string {
  return roleLabels[role]
}

export function formatValue(value: JsonValue, unit?: string | null): string {
  let formatted: string
  if (value === null) formatted = '未提供'
  else if (typeof value === 'boolean') formatted = value ? '是' : '否'
  else if (typeof value === 'object') formatted = JSON.stringify(value)
  else formatted = String(value)
  return unit && !formatted.endsWith(unit) ? `${formatted} ${unit}` : formatted
}

export function locationLabel(status: LocationStatus): string {
  const labels: Record<LocationStatus, string> = {
    LOCATED: '位置已验证', AMBIGUOUS: '多个候选位置', UNLOCATED: '页面位置未确定',
    NOT_RENDERED: '预览未渲染', PENDING: '正在定位',
  }
  return labels[status]
}

export function issueCategory(issue: Issue): 'font' | 'paragraph' | 'section' {
  if (issue.property.startsWith('font.')) return 'font'
  if (issue.property.startsWith('paragraph.')) return 'paragraph'
  return 'section'
}

export function isRepairable(issue: {
  repair: Issue['repair']
  detection_status: Issue['detection_status']
  fix_status: Issue['fix_status']
}): boolean {
  return issue.repair.eligibility === 'SAFE_SINGLE_TARGET' && issue.detection_status === 'CONFIRMED_VIOLATION' && issue.fix_status !== 'FIXED'
}

export function formatDate(value?: string | null): string {
  if (!value) return '时间未记录'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : new Intl.DateTimeFormat('zh-CN', { dateStyle: 'medium', timeStyle: 'short' }).format(date)
}

const apiErrorLabels: Record<string, string> = {
  NETWORK_ERROR: '无法连接服务器，请检查网络后重试。',
  SESSION_EXPIRED: '项目访问凭证不存在或已失效，请重新创建项目。',
  STALE_REPAIR_PLAN: '修复计划已失效，请返回检查并重新创建计划。',
  STALE_RULE_SET: '当前规范已变化，请重新检查后再继续。',
  STALE_REVISION: '文档版本已变化，请重新检查后再继续。',
  RULE_SET_CHANGED: '规范已变化，请保存并重新批准后再试。',
  RULESET_NOT_APPROVED: '规范尚未批准，请先批准当前规范。',
  RULE_CONFLICT: '规范存在未解决的冲突，请处理后再试。',
  PLAN_DIGEST_MISMATCH: '修复计划内容已变化，请重新创建计划。',
  REPAIR_NOT_APPROVED: '修复计划尚未批准，请先完成独立批准。',
  REPAIR_PLAN_NOT_FOUND: '修复计划不存在或已失效，请返回检查重新创建。',
  INSPECTION_NOT_FOUND: '检查结果不存在或已失效，请重新检查。',
  JOB_NOT_FOUND: '任务不存在或已过期，请刷新任务记录。',
  JOB_NOT_RETRYABLE: '当前任务不能重试，请刷新后查看可执行操作。',
  JOB_RETRY_UNSUPPORTED: '此任务不支持安全重试，请重新提交。',
  PROJECT_NOT_ACTIVE: '项目当前不可用，请刷新或重新创建项目。',
  FILE_TOO_LARGE: '文件超过大小限制，请选择较小的文件。',
  DOCX_ENCRYPTED: '不支持加密的 DOCX，请解除加密后重试。',
  DOCX_INVALID_ZIP: 'DOCX 文件结构无效，请重新保存文档后重试。',
  DOCX_READ_ERROR: '无法读取 DOCX，请检查文件后重试。',
  GUIDELINE_PARSE_FAILED: '无法从规范中提取文本，请检查文件内容。',
  VALIDATION_ERROR: '提交内容不符合要求，请检查后重试。',
  INTERNAL_ERROR: '服务器暂时无法完成操作，请稍后重试。',
}

const httpErrorLabels: Record<number, string> = {
  400: '请求内容有误，请检查后重试。',
  401: '登录状态或项目访问凭证已失效，请重新验证。',
  403: '当前操作没有访问权限。',
  404: '请求的内容不存在或已过期。',
  409: '当前状态已变化，请刷新后重试。',
  413: '文件超过大小限制，请选择较小的文件。',
  422: '提交内容不符合要求，请检查后重试。',
  429: '操作过于频繁，请稍后重试。',
  500: '服务器暂时无法完成操作，请稍后重试。',
  502: '服务暂时不可用，请稍后重试。',
  503: '服务暂时不可用，请稍后重试。',
  504: '服务器响应超时，请稍后重试。',
}

function chineseOrFallback(message: string | undefined, fallback: string): string {
  return message && /[\u3400-\u9fff]/.test(message) ? message : fallback
}

export function errorMessage(error: unknown, fallback = '操作未完成，请稍后重试。'): string {
  if (error instanceof ApiError) {
    const coded = apiErrorLabels[error.code]
    if (coded) return coded
    const statusMessage = httpErrorLabels[error.status]
    if (statusMessage) return statusMessage
    return chineseOrFallback(error.message, fallback)
  }
  const message = typeof error === 'string' ? error : error instanceof Error ? error.message : undefined
  if (error instanceof Error && error.name === 'AbortError') return '请求已取消，请重试。'
  if (message && /failed to fetch|networkerror|network request failed|load failed/i.test(message)) return apiErrorLabels.NETWORK_ERROR
  return chineseOrFallback(message, fallback)
}

export function makeIssueNumber(issueId: string, issues: Issue[]): string {
  const index = issues.findIndex((issue) => issue.issue_id === issueId)
  return `I-${String(Math.max(0, index) + 1).padStart(2, '0')}`
}
