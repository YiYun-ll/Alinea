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
  requestSerial: number
  restoring: boolean
  plan: RepairPlan | null
  jobId: string | null
  executionKey: string | null
  creating: boolean
  approving: boolean
  executing: boolean
  error: string | null
}

export const useRepairStore = defineStore('repair', {
  state: (): RepairState => ({ requestSerial: 0, restoring: false, plan: null, jobId: null, executionKey: null, creating: false, approving: false, executing: false, error: null }),
  getters: {
    approvalStatus: (state) => state.plan?.status ?? 'MISSING',
    planDigest: (state) => state.plan?.plan_digest ?? null,
  },
  actions: {
    remember(projectId: string): void {
      if (this.plan) localStorage.setItem(`alinea:repair:${projectId}`, JSON.stringify({ planId: this.plan.plan_id, jobId: this.jobId }))
    },
    async restore(projectId: string): Promise<void> {
      if (this.plan || this.restoring) return
      const saved = localStorage.getItem(`alinea:repair:${projectId}`)
      if (!saved) return
      const serial = ++this.requestSerial
      this.restoring = true
      this.error = null
      try {
        const pointer: unknown = JSON.parse(saved)
        if (!pointer || typeof pointer !== 'object' || !('planId' in pointer) || typeof pointer.planId !== 'string') return
        const plan = await api.getRepairPlan(projectId, pointer.planId)
        if (serial !== this.requestSerial) return
        const rules = useRulesStore()
        if (!rules.ruleSet) await rules.load(projectId)
        if (serial !== this.requestSerial) return
        if (['DRAFT', 'APPROVED'].includes(plan.status)) {
          useProjectStore().setActiveRevision(plan.base_revision_id)
          await useInspectionStore().load(projectId, plan.inspection_id, plan.base_revision_id)
          if (serial !== this.requestSerial) return
        }
        this.plan = plan
        this.executionKey = plan.execution_key
        if ('jobId' in pointer && typeof pointer.jobId === 'string') {
          this.jobId = pointer.jobId
          useJobStore().track(projectId, pointer.jobId)
        }
      } catch (error) {
        if (serial === this.requestSerial) this.error = errorMessage(error, '修复计划读取失败，请重试。')
      } finally {
        if (serial === this.requestSerial) this.restoring = false
      }
    },
    validateApprovalBindings(): void {
      const project = useProjectStore()
      const rules = useRulesStore()
      const inspection = useInspectionStore()
      if (!rules.ruleSet || rules.ruleSet.status !== 'APPROVED') throw new Error('规则未批准，不能创建或执行修复。')
      if (rules.hasUnsavedChanges) throw new Error('规范有未保存修改，请先保存并重新检查。')
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
      const serial = ++this.requestSerial
      this.error = null
      try {
        const plan = await api.createRepairPlan(projectId, project.activeRevisionId, inspection.inspectionId, inspection.selectedIssueIds)
        if (serial !== this.requestSerial) throw new Error('项目已切换，请在当前项目重试。')
        this.plan = plan
        this.remember(projectId)
        return this.plan
      } catch (error) {
        if (serial === this.requestSerial) this.error = errorMessage(error)
        throw error
      } finally {
        if (serial === this.requestSerial) this.creating = false
      }
    },
    async approve(projectId: string): Promise<RepairPlan> {
      if (this.approving) throw new Error('修复计划正在批准，请稍候。')
      if (!this.plan || this.plan.status !== 'DRAFT') throw new Error('只有草案状态的修复计划可以批准。')
      this.validateApprovalBindings()
      this.approving = true
      const serial = ++this.requestSerial
      this.error = null
      try {
        const plan = await api.approveRepairPlan(projectId, this.plan)
        if (serial !== this.requestSerial) throw new Error('项目已切换，请在当前项目重试。')
        this.plan = plan
        this.remember(projectId)
        useToastStore().push('success', '修复计划已批准')
        return this.plan
      } catch (error) {
        if (serial === this.requestSerial) {
          if (error instanceof ApiError && error.code === 'STALE_REPAIR_PLAN' && this.plan) this.plan.status = 'STALE'
          this.error = errorMessage(error)
        }
        throw error
      } finally {
        if (serial === this.requestSerial) this.approving = false
      }
    },
    async execute(projectId: string): Promise<string> {
      if (this.executing) throw new Error('修复任务正在提交，请稍候。')
      if (!this.plan || this.plan.status !== 'APPROVED' || !this.plan.approved_at) throw new Error('修复计划尚未独立批准，不能执行。')
      this.validateApprovalBindings()
      this.executing = true
      const serial = ++this.requestSerial
      this.error = null
      try {
        this.executionKey ??= createIdempotencyKey()
        const accepted = await api.executeRepairPlan(projectId, this.plan.plan_id, this.executionKey)
        if (serial !== this.requestSerial) throw new Error('项目已切换，请在任务记录中查看执行结果。')
        this.jobId = accepted.job_id
        this.plan = { ...this.plan, status: 'QUEUED', execution_key: this.executionKey }
        this.remember(projectId)
        useToastStore().push('info', '修复任务已提交')
        useJobStore().track(projectId, accepted.job_id)
        return accepted.job_id
      } catch (error) {
        if (serial === this.requestSerial) {
          if (error instanceof ApiError && error.code === 'STALE_REPAIR_PLAN' && this.plan) this.plan.status = 'STALE'
          this.error = errorMessage(error)
        }
        throw error
      } finally {
        if (serial === this.requestSerial) this.executing = false
      }
    },
    reset(): void {
      this.requestSerial += 1
      this.restoring = false
      this.creating = false
      this.approving = false
      this.executing = false
      this.plan = null
      this.jobId = null
      this.executionKey = null
      this.error = null
    },
  },
})
