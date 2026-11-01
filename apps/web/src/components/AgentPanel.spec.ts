import { beforeEach, describe, expect, it } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { mount } from '@vue/test-utils'
import AgentPanel from './AgentPanel.vue'
import { useAgentStore } from '../stores/agent'
import type { AgentRun } from '../types/contracts'

const run: AgentRun = {
  run_id: 'run-1', project_id: 'project-1', status: 'SUCCEEDED', objective: '解析规范',
  context: {}, result: { message: '已生成 3 条规则，请审阅。', recommended_action: 'REVIEW_RULES' },
  clarifications: [], model: 'test', step_count: 3, tool_call_count: 1,
  input_tokens: 10, output_tokens: 20, duration_ms: 30, error_code: null, error_message: null,
  job_id: 'job-1', created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z',
  completed_at: '2026-01-01T00:00:01Z', events: [
    {
      sequence: 1, event_type: 'run.created', tool_name: null, status: 'QUEUED', duration_ms: 0,
      payload: {}, created_at: '2026-01-01T00:00:00Z',
    },
    {
      sequence: 2, event_type: 'tool.completed', tool_name: 'validate_rule_candidates', status: 'SUCCEEDED',
      duration_ms: 4, payload: {}, created_at: '2026-01-01T00:00:01Z',
    },
    {
      sequence: 3, event_type: 'run.completed', tool_name: null, status: 'SUCCEEDED', duration_ms: 0,
      payload: { message: '已生成 3 条规则，请审阅。' }, created_at: '2026-01-01T00:00:02Z',
    },
  ],
}

beforeEach(() => setActivePinia(createPinia()))

describe('AgentPanel', () => {
  it('keeps the conversation primary and tool details progressively disclosed', () => {
    const agent = useAgentStore()
    agent.runs = [run]
    agent.activeRunId = run.run_id
    const wrapper = mount(AgentPanel, {
      props: { projectId: 'project-1' },
      global: { stubs: { RouterLink: { template: '<a><slot /></a>' } } },
    })
    expect(wrapper.text()).toContain('已生成 3 条规则，请审阅。')
    expect(wrapper.text()).toContain('审阅规则')
    expect(wrapper.find('details').attributes('open')).toBeUndefined()
    expect(wrapper.text()).toContain('校验规则与证据')
    expect(wrapper.find('textarea').attributes('placeholder')).toBe('继续当前任务…')
    expect(wrapper.find('button[aria-label="新建智能体任务"]').exists()).toBe(true)
  })
})
