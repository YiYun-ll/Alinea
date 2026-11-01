import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import { api } from '../lib/api'
import { errorMessage } from '../lib/format'
import type { AgentRun, AgentRunInput } from '../types/contracts'
import { useInspectionStore } from './inspection'
import { useJobStore } from './job'
import { useRepairStore } from './repair'
import { useRulesStore } from './rules'

export const useAgentStore = defineStore('agent', () => {
  const runs = ref<AgentRun[]>([])
  const activeRunId = ref<string | null>(null)
  const loading = ref(false)
  const sending = ref(false)
  const error = ref<string | null>(null)
  const activeRun = computed(() => runs.value.find((run) => run.run_id === activeRunId.value) ?? null)
  let requestSerial = 0
  let timer: ReturnType<typeof setTimeout> | null = null

  function stopPolling(): void {
    if (timer) clearTimeout(timer)
    timer = null
  }

  function accept(run: AgentRun, activate = false): void {
    const index = runs.value.findIndex((item) => item.run_id === run.run_id)
    if (index >= 0) runs.value[index] = run
    else runs.value.unshift(run)
    if (activate) activeRunId.value = run.run_id
  }

  async function synchronize(projectId: string, run: AgentRun): Promise<void> {
    const ruleSetId = 'rule_set_id' in run.result ? run.result.rule_set_id : undefined
    const inspectionId = 'inspection_id' in run.result ? run.result.inspection_id : undefined
    const planId = 'repair_plan_id' in run.result ? run.result.repair_plan_id : undefined
    if (ruleSetId) await useRulesStore().load(projectId)
    if (planId) {
      await useRepairStore().loadPlan(projectId, planId)
      return
    }
    if (!inspectionId) return
    const inspection = useInspectionStore()
    try {
      await inspection.load(projectId, inspectionId)
    } catch {
      const jobs = useJobStore()
      await jobs.loadProjectJobs(projectId)
      const job = Object.values(jobs.jobs).find((item) => item.inspection_id === inspectionId)
      if (job && !['SUCCEEDED', 'FAILED', 'CANCELLED'].includes(job.status)) jobs.track(projectId, job.job_id)
    }
  }

  async function poll(projectId: string, runId: string): Promise<void> {
    stopPolling()
    const serial = requestSerial
    try {
      const run = await api.getAgentRun(projectId, runId)
      if (serial !== requestSerial) return
      accept(run)
      if (['QUEUED', 'RUNNING'].includes(run.status)) {
        timer = setTimeout(() => { void poll(projectId, runId) }, 900)
      } else {
        await synchronize(projectId, run)
      }
    } catch (cause) {
      if (serial === requestSerial) error.value = errorMessage(cause)
    }
  }

  async function load(projectId: string): Promise<void> {
    const serial = ++requestSerial
    stopPolling()
    loading.value = true
    error.value = null
    try {
      const response = await api.listAgentRuns(projectId)
      if (serial !== requestSerial) return
      runs.value = response.runs
      const current = response.runs.find((run) => run.run_id === activeRunId.value)
      const active = current ?? response.runs.find((run) => ['QUEUED', 'RUNNING', 'NEEDS_CLARIFICATION'].includes(run.status)) ?? response.runs[0]
      activeRunId.value = active?.run_id ?? null
      if (active && ['QUEUED', 'RUNNING'].includes(active.status)) void poll(projectId, active.run_id)
      else if (active) await synchronize(projectId, active)
    } catch (cause) {
      if (serial === requestSerial) error.value = errorMessage(cause)
    } finally {
      if (serial === requestSerial) loading.value = false
    }
  }

  async function start(projectId: string, input: AgentRunInput): Promise<AgentRun> {
    if (sending.value) throw new Error('智能体正在处理上一个请求。')
    const serial = ++requestSerial
    stopPolling()
    sending.value = true
    error.value = null
    try {
      const run = await api.createAgentRun(projectId, input)
      if (serial !== requestSerial) throw new Error('项目已切换，请刷新后重试。')
      accept(run, true)
      void poll(projectId, run.run_id)
      return run
    } catch (cause) {
      if (serial === requestSerial) error.value = errorMessage(cause)
      throw cause
    } finally {
      if (serial === requestSerial) sending.value = false
    }
  }

  async function answer(projectId: string, message: string): Promise<void> {
    const run = activeRun.value
    if (!run || sending.value || !message.trim()) return
    sending.value = true
    error.value = null
    const serial = ++requestSerial
    stopPolling()
    try {
      const resumed = await api.answerAgentRun(projectId, run.run_id, message.trim())
      if (serial !== requestSerial) return
      accept(resumed, true)
      void poll(projectId, resumed.run_id)
    } catch (cause) {
      if (serial === requestSerial) error.value = errorMessage(cause)
      throw cause
    } finally {
      if (serial === requestSerial) sending.value = false
    }
  }

  function select(runId: string): void {
    activeRunId.value = runId
  }

  function newTask(): void {
    activeRunId.value = null
    error.value = null
  }

  function reset(): void {
    requestSerial += 1
    stopPolling()
    runs.value = []
    activeRunId.value = null
    loading.value = false
    sending.value = false
    error.value = null
  }

  return { runs, activeRunId, activeRun, loading, sending, error, load, start, answer, select, newTask, reset }
})
