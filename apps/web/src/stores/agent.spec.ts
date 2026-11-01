import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { flushPromises } from '@vue/test-utils'
import { api } from '../lib/api'
import type { AgentRun, RepairPlan } from '../types/contracts'
import { useAgentStore } from './agent'
import { useRepairStore } from './repair'

function makeRun(patch: Partial<AgentRun> = {}): AgentRun {
  return {
    run_id: 'run-1', project_id: 'project-1', status: 'SUCCEEDED', objective: '检查文档',
    context: {}, result: { message: '检查已提交', recommended_action: 'REVIEW_INSPECTION' },
    clarifications: [], model: 'test', step_count: 2, tool_call_count: 1,
    input_tokens: 10, output_tokens: 20, duration_ms: 30, error_code: null, error_message: null,
    job_id: 'job-1', created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z',
    completed_at: '2026-01-01T00:00:01Z', events: [], ...patch,
  }
}

beforeEach(() => {
  vi.restoreAllMocks()
  setActivePinia(createPinia())
})

describe('agent store', () => {
  it('restores the latest clarification and submits its answer to the same run', async () => {
    const waiting = makeRun({
      status: 'NEEDS_CLARIFICATION', result: {},
      clarifications: [{ question_id: 'scope', question: '摘要也适用吗？', context: '' }],
    })
    vi.spyOn(api, 'listAgentRuns').mockResolvedValue({ runs: [waiting] })
    vi.spyOn(api, 'getAgentRun').mockResolvedValue(makeRun())
    const answer = vi.spyOn(api, 'answerAgentRun').mockResolvedValue(makeRun())
    const store = useAgentStore()
    await store.load('project-1')
    expect(store.activeRunId).toBe('run-1')
    await store.answer('project-1', '摘要不适用')
    expect(answer).toHaveBeenCalledWith('project-1', 'run-1', '摘要不适用')
  })

  it('does not issue duplicate requests while sending', async () => {
    vi.spyOn(api, 'getAgentRun').mockResolvedValue(makeRun())
    const create = vi.spyOn(api, 'createAgentRun').mockResolvedValue(makeRun())
    const store = useAgentStore()
    store.sending = true
    await expect(store.start('project-1', { objective: '重复任务' })).rejects.toThrow('上一个请求')
    expect(create).not.toHaveBeenCalled()
  })

  it('drops stale polling responses after project reset', async () => {
    let resolve!: (run: AgentRun) => void
    vi.spyOn(api, 'listAgentRuns').mockResolvedValue({ runs: [makeRun({ status: 'RUNNING' })] })
    vi.spyOn(api, 'getAgentRun').mockImplementation(() => new Promise((done) => { resolve = done }))
    const store = useAgentStore()
    await store.load('project-1')
    store.reset()
    resolve(makeRun())
    await Promise.resolve()
    expect(store.runs).toEqual([])
    expect(store.activeRun).toBeNull()
  })

  it('does not let a background run replace a deliberately started new task', async () => {
    let resolve!: (run: AgentRun) => void
    vi.spyOn(api, 'listAgentRuns').mockResolvedValue({ runs: [makeRun({ status: 'RUNNING' })] })
    vi.spyOn(api, 'getAgentRun').mockImplementation(() => new Promise((done) => { resolve = done }))
    const store = useAgentStore()
    await store.load('project-1')
    store.newTask()
    resolve(makeRun())
    await flushPromises()
    expect(store.activeRunId).toBeNull()
    expect(store.runs[0].status).toBe('SUCCEEDED')
  })

  it('propagates answer failures so the composer can restore the message', async () => {
    const store = useAgentStore()
    store.runs = [makeRun()]
    store.activeRunId = 'run-1'
    vi.spyOn(api, 'answerAgentRun').mockRejectedValue(new Error('网络失败'))
    await expect(store.answer('project-1', '继续检查')).rejects.toThrow('网络失败')
    expect(store.error).toBe('网络失败')
  })

  it('restores an Agent-created repair plan for the approval workspace', async () => {
    const repair = useRepairStore()
    const loadPlan = vi.spyOn(repair, 'loadPlan').mockResolvedValue({ plan_id: 'plan-1' } as RepairPlan)
    vi.spyOn(api, 'listAgentRuns').mockResolvedValue({ runs: [makeRun({
      result: { message: '计划已生成', recommended_action: 'REVIEW_REPAIR', repair_plan_id: 'plan-1' },
    })] })
    const store = useAgentStore()
    await store.load('project-1')
    await flushPromises()
    expect(loadPlan).toHaveBeenCalledWith('project-1', 'plan-1')
  })
})
