import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useInspectionStore } from './inspection'
import { useProjectStore } from './project'
import { api, ApiError } from '../lib/api'
import { useJobStore } from './job'
import { useRepairStore } from './repair'
import type { InspectionResult, Project, RuleSet } from '../types/contracts'

beforeEach(() => {
  vi.restoreAllMocks()
  setActivePinia(createPinia())
  localStorage.clear()
})

describe('revision and rule invariants', () => {
  it('clears selected and focused issues when the revision changes', () => {
    const inspection = useInspectionStore()
    const project = useProjectStore()
    inspection.selectedIssueIds = ['issue-1', 'issue-2']
    inspection.focusedIssueId = 'issue-1'
    project.activeRevisionId = 'rev-1'
    project.setActiveRevision('rev-2')
    expect(inspection.selectedIssueIds).toEqual([])
    expect(inspection.focusedIssueId).toBeNull()
  })

  it('never starts inspection with an unapproved ruleset', async () => {
    const inspection = useInspectionStore()
    const ruleSet: RuleSet = {
      rule_set_id: 'rules-1', project_id: 'project-1', version: 1, name: 'draft',
      status: 'DRAFT', digest: 'digest', rules: [], conflicts: [], guideline_id: null,
      created_at: null, approved_at: null,
    }
    await expect(inspection.start('project-1', 'rev-1', ruleSet)).rejects.toThrow('尚未批准')
  })

  it('returns a reused inspection without starting duplicate work', async () => {
    const inspection = useInspectionStore()
    const ruleSet: RuleSet = {
      rule_set_id: 'rules-1', project_id: 'project-1', version: 1, name: 'approved',
      status: 'APPROVED', digest: 'digest', rules: [], conflicts: [], guideline_id: null,
      created_at: null, approved_at: '2026-01-01T00:00:00Z',
    }
    const accepted = { job_id: 'job-1', inspection_id: 'inspection-1', status: 'SUCCEEDED', reused: true }
    const create = vi.spyOn(api, 'createInspection').mockResolvedValue(accepted)
    inspection.selectedIssueIds = ['obsolete']
    const response = await inspection.start('project-1', 'rev-1', ruleSet)
    expect(response).toEqual(accepted)
    expect(create).toHaveBeenCalledOnce()
    expect(inspection.jobId).toBe('job-1')
    expect(inspection.selectedIssueIds).toEqual([])
  })
})

describe('job recovery and repair submission guards', () => {
  it.each([401, 403, 404])('removes a restored active job after terminal HTTP %i', async (status) => {
    localStorage.setItem('alinea:active-jobs:project-1', JSON.stringify(['job-1', 'job-2']))
    vi.spyOn(api, 'getJob').mockRejectedValue(new ApiError('Not found', status, 'HTTP_ERROR', false))
    const jobs = useJobStore()

    await jobs.poll('project-1', 'job-1', 0)

    expect(JSON.parse(localStorage.getItem('alinea:active-jobs:project-1') ?? '[]')).toEqual(['job-2'])
    expect(jobs.timers.has('project-1:job-1')).toBe(false)
  })

  it('does not issue duplicate create or approve requests while busy', async () => {
    const repair = useRepairStore()
    const create = vi.spyOn(api, 'createRepairPlan')
    const approve = vi.spyOn(api, 'approveRepairPlan')
    repair.creating = true
    repair.approving = true

    await expect(repair.createPlan('project-1')).rejects.toThrow('正在生成')
    await expect(repair.approve('project-1')).rejects.toThrow('正在批准')
    expect(create).not.toHaveBeenCalled()
    expect(approve).not.toHaveBeenCalled()
  })
})

describe('stale async responses', () => {
  it('does not let an older project load replace the current project', async () => {
    const project = useProjectStore()
    let resolveOld!: (value: Project) => void
    let resolveNew!: (value: Project) => void
    vi.spyOn(api, 'getProject').mockImplementation((projectId) => new Promise<Project>((resolve) => {
      if (projectId === 'old') resolveOld = resolve
      else resolveNew = resolve
    }))

    const oldLoad = project.load('old')
    const newLoad = project.load('new')
    resolveNew({ project_id: 'new', name: '新项目', active_revision_id: 'rev-new' })
    await newLoad
    resolveOld({ project_id: 'old', name: '旧项目', active_revision_id: 'rev-old' })
    await oldLoad

    expect(project.projectId).toBe('new')
    expect(project.activeRevisionId).toBe('rev-new')
  })

  it('does not restore an inspection after the store was reset', async () => {
    const inspection = useInspectionStore()
    const result: InspectionResult = {
      inspection_id: 'old', revision_id: 'rev-old', rule_set_id: 'rules', rule_set_digest: 'digest',
      inspector_version: '1', status: 'SUCCEEDED', issues: [],
      summary: { violations: 0, unverifiable: 0, fixable: 0, evaluated_rules: 0, skipped_rules: 0, located: 0, ambiguous: 0, unlocated: 0 },
      preview: null, warnings: [], created_at: '2026-01-01T00:00:00Z',
    }
    let resolveInspection!: (value: InspectionResult) => void
    vi.spyOn(api, 'getInspection').mockReturnValue(new Promise((resolve) => { resolveInspection = resolve }))
    vi.spyOn(api, 'getIssues').mockResolvedValue({ data: [], total: 0, summary: result.summary })

    const loading = inspection.load('old-project', 'old', 'rev-old')
    inspection.reset()
    resolveInspection(result)
    await loading

    expect(inspection.inspectionId).toBeNull()
    expect(inspection.result).toBeNull()
    expect(inspection.error).toBeNull()
  })
})
