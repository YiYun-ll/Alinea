import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import { useJobStore } from '../stores/job'
import { useRepairStore } from '../stores/repair'
import { useToastStore } from '../stores/toast'
import type { Job, RepairPlan } from '../types/contracts'
import RepairsView from './RepairsView.vue'

const plan: RepairPlan = {
  plan_id: 'plan-1', project_id: 'project-1', base_revision_id: 'rev-1', inspection_id: 'inspection-1',
  rule_set_id: 'rules-1', rule_set_version: 1, rule_set_digest: 'rules-digest', status: 'QUEUED',
  plan_digest: 'plan-digest', selected_issue_ids: ['issue-1'], operations: [], affected_node_count: 0,
  approved_at: '2026-01-01T00:00:00Z', execution_key: 'execution-key', result_revision_id: null,
}

function repairJob(status: Job['status']): Job {
  return {
    job_id: 'job-1', project_id: 'project-1', job_type: 'repair', status,
    result_revision_id: status === 'SUCCEEDED' ? 'rev-2' : null,
    error_message: status === 'FAILED' ? 'Repair execution failed' : null,
  }
}

async function mountRepairs(status: Job['status']) {
  const repair = useRepairStore()
  const jobs = useJobStore()
  repair.plan = { ...plan }
  repair.jobId = 'job-1'
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/projects/:id/repairs', component: RepairsView },
      { path: '/projects/:id/inspection', component: { template: '<div />' } },
      { path: '/projects/:id/results/:revisionId', component: { template: '<div />' } },
    ],
  })
  await router.push('/projects/project-1/repairs')
  await router.isReady()
  const wrapper = mount(RepairsView, { global: { plugins: [router] } })
  jobs.jobs['job-1'] = repairJob(status)
  await flushPromises()
  return { wrapper, jobs }
}

describe('RepairsView', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    setActivePinia(createPinia())
  })

  it('shows only one completion toast when the same terminal job is restored again', async () => {
    const push = vi.spyOn(useToastStore(), 'push')
    const { jobs } = await mountRepairs('SUCCEEDED')
    expect(push).toHaveBeenCalledTimes(1)

    delete jobs.jobs['job-1']
    await flushPromises()
    jobs.jobs['job-1'] = repairJob('SUCCEEDED')
    await flushPromises()

    expect(push).toHaveBeenCalledTimes(1)
  })

  it('localizes failed job details and offers a route back to rebuild the plan', async () => {
    const { wrapper } = await mountRepairs('FAILED')

    expect(wrapper.text()).not.toContain('Repair execution failed')
    expect(wrapper.text()).toContain('修复任务未完成，请重试。')
    expect(wrapper.get('a[href="/projects/project-1/inspection"]').text()).toContain('返回检查并重建计划')
  })
})
