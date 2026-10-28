import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { api } from '../lib/api'
import { useProjectStore } from './project'
import { useInspectionStore } from './inspection'
import { useRulesStore } from './rules'
import { useJobStore } from './job'
import type { InspectionResult, Issue, Job, RuleSet } from '../types/contracts'

beforeEach(() => {
  vi.restoreAllMocks()
  localStorage.clear()
  setActivePinia(createPinia())
})

const summary = { violations: 2, unverifiable: 0, fixable: 2, evaluated_rules: 2, skipped_rules: 0, located: 0, ambiguous: 0, unlocated: 2 }
const result: InspectionResult = { inspection_id: 'inspection', revision_id: 'rev', rule_set_id: 'rules', rule_set_digest: 'digest', inspector_version: '1', status: 'SUCCEEDED', issues: [], summary, preview: null, warnings: [], created_at: '' }
function issue(id: string, property: Issue['property']): Issue {
  return { issue_id: id, property, detection_status: 'CONFIRMED_VIOLATION', fix_status: 'OPEN', repair: { eligibility: 'SAFE_SINGLE_TARGET', requires_approval: true, reason: null } } as Issue
}

describe('workspace regressions', () => {
  it('preserves selection and focus only when the refreshed evidence identity is unchanged', async () => {
    const inspection = useInspectionStore()
    const items = [issue('font', 'font.size_pt'), issue('paragraph', 'paragraph.alignment')]
    vi.spyOn(api, 'getInspection').mockResolvedValue(result)
    vi.spyOn(api, 'getIssues').mockResolvedValue({ data: items, total: items.length, summary })
    await inspection.load('project', 'inspection', 'rev')
    inspection.toggleSelected('font')
    inspection.focusIssue('paragraph')
    await inspection.load('project', 'inspection', 'rev')
    expect(inspection.selectedIssueIds).toEqual(['font'])
    expect(inspection.focusedIssueId).toBe('paragraph')
    vi.mocked(api.getInspection).mockResolvedValue({ ...result, inspection_id: 'new-inspection' })
    await inspection.load('project', 'new-inspection', 'rev')
    expect(inspection.selectedIssueIds).toEqual([])
  })

  it('selects only visible repairable issues and retains earlier selections from other filters', () => {
    const inspection = useInspectionStore()
    inspection.issues = [issue('font', 'font.size_pt'), issue('paragraph', 'paragraph.alignment')]
    inspection.category = 'font'
    inspection.selectAllFixable()
    expect(inspection.selectedIssueIds).toEqual(['font'])
    inspection.category = 'paragraph'
    inspection.selectAllFixable()
    expect(inspection.selectedIssueIds).toEqual(['font', 'paragraph'])
  })

  it('clears old project evidence and filters even when a newly created project is already active', () => {
    const inspection = useInspectionStore()
    inspection.result = result
    inspection.query = 'old text'
    inspection.selectedIssueIds = ['font']
    useRulesStore().draftName = 'old rules'
    useProjectStore().acceptCreated({ project_id: 'new', name: 'New', token: 'test-token' })
    expect(inspection.result).toBeNull()
    expect(inspection.query).toBe('')
    expect(useRulesStore().draftName).toBe('')
    expect(inspection.selectedIssueIds).toEqual([])
  })

  it('ignores a pending poll after the user leaves the project and does not schedule another timer', async () => {
    const jobs = useJobStore()
    let resolve!: (job: Job) => void
    vi.spyOn(api, 'getJob').mockReturnValue(new Promise((done) => { resolve = done }))
    const pending = jobs.poll('old', 'job', 0)
    jobs.stopAll()
    resolve({ job_id: 'job', project_id: 'old', status: 'RUNNING' })
    await pending
    expect(jobs.jobs).toEqual({})
    expect(jobs.timers.size).toBe(0)
  })

  it('ignores an old rules request after project state was reset', async () => {
    const rules = useRulesStore()
    let resolve!: (ruleSet: RuleSet) => void
    vi.spyOn(api, 'getRules').mockReturnValue(new Promise((done) => { resolve = done }))
    const pending = rules.load('old')
    rules.reset()
    resolve({ rule_set_id: 'old-rules', rules: [] } as unknown as RuleSet)
    await pending
    expect(rules.ruleSet).toBeNull()
    expect(rules.loading).toBe(false)
  })
})
