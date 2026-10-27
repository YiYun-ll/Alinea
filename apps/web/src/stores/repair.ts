import { defineStore } from 'pinia'
import { api, ApiError, createIdempotencyKey } from '../lib/api'
import { errorMessage } from '../lib/format'
import type { RepairPlan } from '../types/contracts'
import { useInspectionStore } from './inspection'
import { useJobStore } from './job'
import { useProjectStore } from './project'
import { useRulesStore } from './rules'
import { useToastStore } from './toast'

interface RepairState {
  plan: RepairPlan | null
  jobId: string | null
  executionKey: string | null
  creating: boolean
  approving: boolean
  executing: boolean
  error: string | null
}

export const useRepairStore = defineStore('repair', {
  state: (): RepairState => ({ plan: null, jobId: null, executionKey: null, creating: false, approving: false, executing: false, error: null }),
  getters: {
    approvalStatus: (state) => state.plan?.status ?? 'MISSING',
    planDigest: (state) => state.plan?.plan_digest ?? null,
  },
  actions: {
    validateApprovalBindings(): void {
      const project = useProjectStore()
      const rules = useRulesStore()
      const inspection = useInspectionStore()
      if (!rules.ruleSet || rules.ruleSet.status !== 'APPROVED') throw new Error('规则未批准，不能创建或执行修复。')
      if (!inspection.result || !inspection.inspectionId) throw new Error('请先完成当前版本的检查。')
      if (inspection.result.revision_id !== project.activeRevisionId) throw new Error('检查结果不属于当前修订版，请重新检查。')
      if (inspection.result.rule_set_digest !== rules.ruleSet.digest) throw new Error('规则已变化，请使用当前批准规则重新检查。')
      if (this.plan) {
        if (this.plan.base_revision_id !== project.activeRevisionId) throw new Error('修复计划的原文版本已失效。')
        if (this.plan.rule_set_digest !== rules.ruleSet.digest) throw new Error('修复计划的规则摘要已失效。')
        if (this.plan.inspection_id !== inspection.inspectionId) throw new Error('修复计划与当前检查不一致。')
      }
    },
    async createPlan(projectId: string): Promise<RepairPlan> {
      if (this.creating) throw new Error('修复计划正在生成，请稍候。')
      const project = useProjectStore()
      const inspection = useInspectionStore()
      this.plan = null
      this.jobId = null
      this.executionKey = null
      this.validateApprovalBindings()
      if (!project.activeRevisionId || !inspection.inspectionId) throw new Error('缺少当前版本或检查标识。')
      if (inspection.selectedIssueIds.length === 0) throw new Error('请至少选择一项可修复问题。')
      this.creating = true
      this.error = null
      try {
        this.plan = await api.createRepairPlan(projectId, project.activeRevisionId, inspection.inspectionId, inspection.selectedIssueIds)
        return this.plan
      } catch (error) {
        this.error = errorMessage(error)
        throw error
      } finally {
        this.creating = false
      }
    },
    async approve(projectId: string): Promise<RepairPlan> {
      if (this.approving) throw new Error('修复计划正在批准，请稍候。')
      if (!this.plan || this.plan.status !== 'DRAFT') throw new Error('只有草案状态的修复计划可以批准。')
      this.validateApprovalBindings()
      this.approving = true
      this.error = null
      try {
        this.plan = await api.approveRepairPlan(projectId, this.plan)
        useToastStore().push('success', '修复计划已批准', '版本与操作 digest 已确认，可以执行。')
        return this.plan
      } catch (error) {
        if (error instanceof ApiError && error.code === 'STALE_REPAIR_PLAN' && this.plan) this.plan.status = 'STALE'
        this.error = errorMessage(error)
        throw error
      } finally {
        this.approving = false
      }
    },
    async execute(projectId: string): Promise<string> {
      if (this.executing) throw new Error('修复任务正在提交，请稍候。')
      if (!this.plan || this.plan.status !== 'APPROVED' || !this.plan.approved_at) throw new Error('修复计划尚未独立批准，不能执行。')
      this.validateApprovalBindings()
      this.executing = true
      this.error = null
      try {
        this.executionKey ??= createIdempotencyKey()
        const accepted = await api.executeRepairPlan(projectId, this.plan.plan_id, this.executionKey)
        this.jobId = accepted.job_id
        this.plan = { ...this.plan, status: 'QUEUED', execution_key: this.executionKey }
        useToastStore().push('info', '修复任务已提交', '服务端正在执行白名单补丁与质量复检。')
        useJobStore().track(projectId, accepted.job_id)
        return accepted.job_id
      } catch (error) {
        if (error instanceof ApiError && error.code === 'STALE_REPAIR_PLAN' && this.plan) this.plan.status = 'STALE'
        this.error = errorMessage(error)
        throw error
      } finally {
        this.executing = false
      }
    },
    reset(): void {
      this.plan = null
      this.jobId = null
      this.executionKey = null
      this.error = null
    },
  },
})
