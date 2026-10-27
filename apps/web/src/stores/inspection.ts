import { computed, ref, shallowRef } from 'vue'
import { defineStore } from 'pinia'
import { api, createIdempotencyKey } from '../lib/api'
import { errorMessage, isRepairable, propertyLabel } from '../lib/format'
import type { InspectionAccepted } from '../lib/api'
import type { InspectionResult, InspectionSummary, Issue, Job, RuleSet } from '../types/contracts'

export type IssueCategoryFilter = 'all' | 'font' | 'paragraph' | 'section'

export const useInspectionStore = defineStore('inspection', () => {
  const inspectionId = ref<string | null>(null)
  const result = shallowRef<InspectionResult | null>(null)
  const issues = shallowRef<Issue[]>([])
  const summary = shallowRef<InspectionSummary | null>(null)
  const selectedIssueIds = ref<string[]>([])
  const focusedIssueId = ref<string | null>(null)
  const query = ref('')
  const severity = ref<'ALL' | Issue['severity']>('ALL')
  const category = ref<IssueCategoryFilter>('all')
  const location = ref<'ALL' | Issue['location']['status']>('ALL')
  const repairableOnly = ref(false)
  const loading = ref(false)
  const starting = ref(false)
  const error = ref<string | null>(null)
  const jobId = ref<string | null>(null)
  let requestSerial = 0

  const filteredIssues = computed<Issue[]>(() => {
    const normalizedQuery = query.value.trim().toLocaleLowerCase()
    return issues.value.filter((issue) => {
      if (severity.value !== 'ALL' && issue.severity !== severity.value) return false
      if (location.value !== 'ALL' && issue.location.status !== location.value) return false
      if (repairableOnly.value && !isRepairable(issue)) return false
      if (category.value !== 'all' && !issue.property.startsWith(`${category.value}.`)) return false
      if (!normalizedQuery) return true
      const haystack = [issue.issue_id, issue.rule_id, propertyLabel(issue.property), issue.element_ref.text_excerpt, issue.location.anchor_excerpt, issue.source.quote, JSON.stringify(issue.actual.value), JSON.stringify(issue.expected.value)].join(' ').toLocaleLowerCase()
      return haystack.includes(normalizedQuery)
    })
  })
  const focusedIssue = computed<Issue | null>(() => issues.value.find((issue) => issue.issue_id === focusedIssueId.value) ?? null)
  const selectedCount = computed(() => selectedIssueIds.value.length)
  const fixableCount = computed(() => issues.value.filter(isRepairable).length)

  async function start(projectId: string, revisionId: string, ruleSet: RuleSet): Promise<InspectionAccepted> {
    if (ruleSet.status !== 'APPROVED') throw new Error('规则集尚未批准，不能开始检查。')
    const serial = ++requestSerial
    starting.value = true
    error.value = null
    try {
      const accepted = await api.createInspection(projectId, revisionId, ruleSet, createIdempotencyKey())
      if (serial === requestSerial) {
        inspectionId.value = accepted.inspection_id
        jobId.value = accepted.job_id
        result.value = null
        issues.value = []
        summary.value = null
        clearSelection()
        focusedIssueId.value = null
      }
      return accepted
    } catch (cause) {
      if (serial === requestSerial) error.value = errorMessage(cause)
      throw cause
    } finally {
      if (serial === requestSerial) starting.value = false
    }
  }

  async function retry(projectId: string): Promise<Job> {
    if (!jobId.value) throw new Error('没有可重试的检查任务。')
    const serial = ++requestSerial
    starting.value = true
    error.value = null
    try {
      const retried = await api.retryJob(projectId, jobId.value)
      if (serial === requestSerial) {
        jobId.value = retried.job_id
        result.value = null
        issues.value = []
        summary.value = null
        clearSelection()
        focusedIssueId.value = null
      }
      return retried
    } catch (cause) {
      if (serial === requestSerial) error.value = errorMessage(cause)
      throw cause
    } finally {
      if (serial === requestSerial) starting.value = false
    }
  }

  async function load(projectId: string, id: string, revisionId?: string): Promise<void> {
    const serial = ++requestSerial
    loading.value = true
    error.value = null
    try {
      const [inspectionResult, firstPage] = await Promise.all([api.getInspection(projectId, id), api.getIssues(projectId, id)])
      if (serial !== requestSerial) return
      if (inspectionResult.status !== 'SUCCEEDED') throw new Error('检查尚未成功完成，请重新提交或安全重试。')
      if (revisionId && inspectionResult.revision_id !== revisionId) throw new Error('检查结果与当前修订版不一致，已停止加载。')
      const loadedIssues = [...firstPage.data]
      let page = 2
      while (loadedIssues.length < firstPage.total && page <= 100) {
        const next = await api.getIssues(projectId, id, page)
        if (serial !== requestSerial) return
        if (next.data.length === 0) break
        loadedIssues.push(...next.data)
        page += 1
      }
      inspectionId.value = id
      result.value = inspectionResult
      issues.value = loadedIssues
      summary.value = firstPage.summary ?? inspectionResult.summary
      clearSelection()
      focusedIssueId.value = loadedIssues[0]?.issue_id ?? null
    } catch (cause) {
      if (serial !== requestSerial) return
      error.value = errorMessage(cause)
      throw cause
    } finally {
      if (serial === requestSerial) loading.value = false
    }
  }

  function clearSelection(): void {
    selectedIssueIds.value = []
  }

  function clearForRevisionChange(): void {
    clearSelection()
    focusedIssueId.value = null
  }

  function toggleSelected(issueId: string): void {
    const issue = issues.value.find((item) => item.issue_id === issueId)
    if (!issue || !isRepairable(issue)) return
    selectedIssueIds.value = selectedIssueIds.value.includes(issueId) ? selectedIssueIds.value.filter((id) => id !== issueId) : [...selectedIssueIds.value, issueId]
  }

  function selectAllFixable(): void {
    selectedIssueIds.value = issues.value.filter(isRepairable).map((issue) => issue.issue_id)
  }

  function focusIssue(issueId: string): void {
    if (issues.value.some((issue) => issue.issue_id === issueId)) focusedIssueId.value = issueId
  }

  function focusNext(direction: 1 | -1): Issue | null {
    const visible = filteredIssues.value
    if (visible.length === 0) return null
    const current = visible.findIndex((issue) => issue.issue_id === focusedIssueId.value)
    const next = current < 0 ? 0 : (current + direction + visible.length) % visible.length
    focusedIssueId.value = visible[next].issue_id
    return visible[next]
  }

  function reset(): void {
    requestSerial += 1
    loading.value = false
    starting.value = false
    inspectionId.value = null
    result.value = null
    issues.value = []
    summary.value = null
    jobId.value = null
    clearSelection()
    focusedIssueId.value = null
    error.value = null
  }

  return {
    inspectionId, result, issues, summary, selectedIssueIds, focusedIssueId, query, severity,
    category, location, repairableOnly, loading, starting, error, jobId, filteredIssues,
    focusedIssue, selectedCount, fixableCount, start, retry, load, clearSelection, clearForRevisionChange,
    toggleSelected, selectAllFixable, focusIssue, focusNext, reset,
  }
})
