import { defineStore } from 'pinia'
import { api } from '../lib/api'
import { errorMessage } from '../lib/format'
import { useToastStore } from './toast'
import type { FormatRule, RuleSet } from '../types/contracts'

interface RulesState {
  requestSerial: number
  ruleSet: RuleSet | null
  draftRules: FormatRule[]
  draftName: string
  loading: boolean
  saving: boolean
  approving: boolean
  extracting: boolean
  extractionJobId: string | null
  error: string | null
  notice: string | null
}

function cloneRules(rules: FormatRule[]): FormatRule[] {
  return rules.map((rule) => ({
    ...rule,
    source: { ...rule.source },
    exclusions: [...rule.exclusions],
  }))
}

export const useRulesStore = defineStore('rules', {
  state: (): RulesState => ({
    requestSerial: 0, ruleSet: null, draftRules: [], draftName: '', loading: false, saving: false,
    approving: false, extracting: false, extractionJobId: null, error: null, notice: null,
  }),
  getters: {
    ruleSetId: (state) => state.ruleSet?.rule_set_id ?? null,
    version: (state) => state.ruleSet?.version ?? null,
    approvalStatus: (state) => state.ruleSet?.status ?? 'MISSING',
    rules: (state) => state.draftRules,
    isApproved: (state) => state.ruleSet?.status === 'APPROVED',
    hasUnsavedChanges: (state) => state.ruleSet ? state.draftName !== state.ruleSet.name || JSON.stringify(state.draftRules) !== JSON.stringify(state.ruleSet.rules) : false,
    unresolvedConflicts: (state) => state.ruleSet?.conflicts.filter((conflict) => !conflict.resolved) ?? [],
    selectedRule: (state) => (ruleId: string | null) => state.draftRules.find((rule) => rule.rule_id === ruleId) ?? null,
  },
  actions: {
    async load(projectId: string): Promise<RuleSet | null> {
      const serial = ++this.requestSerial
      this.loading = true
      this.error = null
      try {
        const ruleSet = await api.getRules(projectId)
        if (serial !== this.requestSerial) return null
        this.ruleSet = ruleSet
        this.draftRules = cloneRules(ruleSet.rules)
        this.draftName = ruleSet.name
        return ruleSet
      } catch (error) {
        if (serial !== this.requestSerial) return null
        this.error = errorMessage(error)
        return null
      } finally {
        if (serial === this.requestSerial) this.loading = false
      }
    },
    async extract(projectId: string, guidelineId: string, presetId?: string): Promise<string> {
      const serial = this.requestSerial
      this.extracting = true
      this.error = null
      try {
        const response = await api.extractRules(projectId, guidelineId, presetId)
        if (serial !== this.requestSerial) throw new Error('项目已切换，请在当前项目重试。')
        this.extractionJobId = response.job_id
        return response.job_id
      } catch (error) {
        if (serial === this.requestSerial) this.error = errorMessage(error)
        throw error
      } finally {
        if (serial === this.requestSerial) this.extracting = false
      }
    },
    updateRule(ruleId: string, patch: Partial<FormatRule>): void {
      const index = this.draftRules.findIndex((rule) => rule.rule_id === ruleId)
      if (index >= 0) this.draftRules[index] = { ...this.draftRules[index], ...patch }
      if (this.ruleSet?.status === 'APPROVED') this.notice = '内容已编辑；保存并重新批准后，才能用于新检查或修复。'
    },
    addManualRule(rule: FormatRule): void {
      this.draftRules.push(rule)
      this.notice = '人工规则已加入草案，请保存并批准。'
    },
    disableOtherConflictingRules(ruleIds: string[], keepRuleId: string): void {
      this.draftRules = this.draftRules.map((rule) => ruleIds.includes(rule.rule_id) && rule.rule_id !== keepRuleId ? { ...rule, enabled: false } : rule)
      this.notice = '冲突规则已停用；保存后由服务端重新计算冲突。'
    },
    async save(projectId: string): Promise<RuleSet | null> {
      if (!this.ruleSet) return null
      const serial = this.requestSerial
      this.saving = true
      this.error = null
      try {
        const saved = await api.saveRules(projectId, this.ruleSet, this.draftRules, this.draftName)
        if (serial !== this.requestSerial) return null
        this.ruleSet = saved
        this.draftRules = cloneRules(saved.rules)
        this.draftName = saved.name
        this.notice = saved.status === 'APPROVED' ? '规则已保存。' : '草案已保存，请复核冲突并批准。'
        return saved
      } catch (error) {
        if (serial === this.requestSerial) this.error = errorMessage(error)
        return null
      } finally {
        if (serial === this.requestSerial) this.saving = false
      }
    },
    async approve(projectId: string): Promise<RuleSet> {
      if (!this.ruleSet) throw new Error('尚无可批准的规则集。')
      if (this.hasUnsavedChanges) throw new Error('规范有未保存修改，请先保存并重新批准。')
      if (this.unresolvedConflicts.length > 0) throw new Error('仍有未解决冲突，请编辑或停用冲突规则并保存。')
      const missingEvidence = this.draftRules.find((rule) => rule.enabled && (!rule.source.reference.trim() || (rule.source.source_type !== 'preset' && !rule.source.quote.trim())))
      if (missingEvidence) throw new Error(`规则 ${missingEvidence.rule_id} 缺少来源引用或规范原句，不能批准。`)
      this.approving = true
      const serial = this.requestSerial
      this.error = null
      try {
        const approved = await api.approveRules(projectId, this.ruleSet.rule_set_id)
        if (serial !== this.requestSerial) throw new Error('项目已切换，请在当前项目重试。')
        this.ruleSet = approved
        this.draftRules = cloneRules(approved.rules)
        this.draftName = approved.name
        this.notice = `规则集 v${approved.version} 已批准。`
        useToastStore().push('success', '规则集已批准')
        return approved
      } catch (error) {
        if (serial === this.requestSerial) this.error = errorMessage(error)
        throw error
      } finally {
        if (serial === this.requestSerial) this.approving = false
      }
    },
    reset(): void {
      this.requestSerial += 1
      this.loading = false
      this.saving = false
      this.approving = false
      this.extracting = false
      this.ruleSet = null
      this.draftRules = []
      this.draftName = ''
      this.extractionJobId = null
      this.error = null
      this.notice = null
    },
  },
})
