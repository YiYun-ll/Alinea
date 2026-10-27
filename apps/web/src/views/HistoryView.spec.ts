import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import { api } from '../lib/api'
import { useJobStore } from '../stores/job'
import { useToastStore } from '../stores/toast'
import type { Job } from '../types/contracts'
import HistoryView from './HistoryView.vue'

vi.mock('../lib/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../lib/api')>()
  return {
    ...actual,
    api: {
      getProjectJobs: vi.fn(), getProjectRevisions: vi.fn(), getProjectAudit: vi.fn(),
      retryJob: vi.fn(), cancelJob: vi.fn(),
    },
  }
})

const mockedApi = vi.mocked(api)
const failed: Job = {
  job_id: 'failed-1', project_id: 'project-1', job_type: 'repair', status: 'FAILED',
  retryable: true, progress: 20, error_code: 'TEMPORARY_FAILURE', error_message: 'Temporary failure',
}
const queued: Job = {
  job_id: 'queued-1', project_id: 'project-1', job_type: 'inspection', status: 'QUEUED', progress: 0,
}

async function mountHistory() {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [{ path: '/projects/:id/history', component: HistoryView }],
  })
  await router.push('/projects/project-1/history')
  await router.isReady()
  const wrapper = mount(HistoryView, { global: { plugins: [router] } })
  await flushPromises()
  return wrapper
}

describe('HistoryView', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    setActivePinia(createPinia())
    localStorage.clear()
    mockedApi.getProjectJobs.mockResolvedValue({ data: [failed, queued] })
    mockedApi.getProjectRevisions.mockResolvedValue({ data: [] })
    mockedApi.getProjectAudit.mockResolvedValue({ data: [] })
  })

  it('retries safe failures idempotently and cancels queued work', async () => {
    const jobs = useJobStore()
    vi.spyOn(jobs, 'track').mockImplementation(() => {})
    const retried = { ...failed, job_id: 'retry-1', status: 'QUEUED' as const, retryable: false }
    const cancelled = { ...queued, status: 'CANCELLED' as const }
    mockedApi.retryJob.mockResolvedValue(retried)
    mockedApi.cancelJob.mockResolvedValue(cancelled)
    const wrapper = await mountHistory()
    expect(wrapper.text()).not.toContain('Temporary failure')
    expect(wrapper.text()).toContain('任务未完成，请查看状态后重试。')

    const retryButton = wrapper.get('button[aria-label="重试任务 failed-1"]')
    await retryButton.trigger('click')
    await retryButton.trigger('click')
    await flushPromises()
    expect(mockedApi.retryJob).toHaveBeenCalledTimes(1)
    expect(mockedApi.retryJob).toHaveBeenCalledWith('project-1', 'failed-1')
    expect(jobs.track).toHaveBeenCalledWith('project-1', 'retry-1')
    expect(wrapper.text()).toContain('retry-1')
    expect(useToastStore().items.some((item) => item.title === '已提交安全重试')).toBe(true)

    mockedApi.getProjectJobs.mockResolvedValue({ data: [failed, retried, cancelled] })
    await wrapper.get('button[aria-label="取消任务 queued-1"]').trigger('click')
    await flushPromises()
    expect(mockedApi.cancelJob).toHaveBeenCalledWith('project-1', 'queued-1')
    expect(wrapper.find('button[aria-label="取消任务 queued-1"]').exists()).toBe(false)
    expect(useToastStore().items.some((item) => item.title === '任务已取消')).toBe(true)
  })
})
