<script setup lang="ts">
import { computed, nextTick, onMounted, ref, useId, watch } from 'vue'
import { useRoute } from 'vue-router'
import { ArrowRight, BookOpen, Check, CircleAlert, FilePlus2, LoaderCircle, Plus, Save, ShieldCheck, X } from 'lucide-vue-next'
import { useRulesStore } from '../stores/rules'
import { useJobStore } from '../stores/job'
import { errorMessage, formatDate, propertyLabel, roleLabel } from '../lib/format'
import type { FormatProperty, FormatRule, JsonValue, RuleConflict, Selector } from '../types/contracts'
import { parseRuleValue, type LineSpacingType } from '../lib/ruleValue'
import RuleEditorPanel from '../components/RuleEditorPanel.vue'
import StatusBadge from '../components/StatusBadge.vue'
import ErrorNotice from '../components/ErrorNotice.vue'
import EmptyState from '../components/EmptyState.vue'
import ConfirmDialog from '../components/ConfirmDialog.vue'

const route = useRoute()
const projectId = String(route.params.id)
const rules = useRulesStore()
const jobs = useJobStore()
const selectedRuleId = ref<string | null>(null)
const manualDialog = ref<HTMLDialogElement | null>(null)
const approveDialog = ref<InstanceType<typeof ConfirmDialog> | null>(null)
const manualName = ref('人工格式规则')
const manualSelector = ref<Selector>('body')
const manualProperty = ref<FormatProperty>('font.size_pt')
const manualExpected = ref('12')
const manualLineType = ref<LineSpacingType>('MULTIPLE')
const manualError = ref<string | null>(null)
const manualQuote = ref('')
const localError = ref<string | null>(null)
const loadedExtractionJob = ref<string | null>(null)
const manualTitleId = useId()
const isDirty = computed(() => rules.ruleSet ? rules.draftName !== rules.ruleSet.name || JSON.stringify(rules.draftRules) !== JSON.stringify(rules.ruleSet.rules) : false)
const extractionJob = computed(() => rules.extractionJobId ? jobs.jobs[rules.extractionJobId] : null)
const sources = computed(() => {
  const seen = new Set<string>()
  return rules.draftRules.map((rule) => rule.source).filter((source) => {
    const key = `${source.reference}:${source.page}:${source.quote}`
    if (seen.has(key)) return false
    seen.add(key)
    return true
  })
})
const enabledCount = computed(() => rules.draftRules.filter((rule) => rule.enabled).length)
watch(manualProperty, (property) => {
  manualError.value = null
  manualExpected.value = property === 'font.bold' ? 'true' : property === 'paragraph.alignment' ? 'left' : property === 'paragraph.line_spacing' ? '1.5' : property === 'font.size_pt' ? '12' : ''
})

async function loadRules(): Promise<void> {
  const result = await rules.load(projectId)
  if (result) selectedRuleId.value = result.rules[0]?.rule_id ?? null
}

onMounted(async () => {
  if (!rules.ruleSet) await loadRules()
  else selectedRuleId.value ??= rules.draftRules[0]?.rule_id ?? null
  try {
    await jobs.loadProjectJobs(projectId)
    if (!rules.extractionJobId) {
      const extraction = Object.values(jobs.jobs).filter((job) => job.job_type?.toUpperCase().includes('RULE')).sort((a, b) => (a.created_at ?? '').localeCompare(b.created_at ?? '')).at(-1)
      if (extraction) {
        rules.extractionJobId = extraction.job_id
        if (!['SUCCEEDED', 'FAILED', 'CANCELLED'].includes(extraction.status)) jobs.track(projectId, extraction.job_id)
      }
    }
  } catch {
    // The rule resource remains usable if the optional job history cannot load.
  }
})

watch(() => extractionJob.value?.status, async (status) => {
  const jobId = rules.extractionJobId
  if (status === 'SUCCEEDED' && jobId && loadedExtractionJob.value !== jobId) {
    loadedExtractionJob.value = jobId
    await loadRules()
  }
})

function selectRule(ruleId: string): void {
  selectedRuleId.value = ruleId
  const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches
  if (window.innerWidth < 1100) void nextTick(() => document.getElementById('rule-editor')?.scrollIntoView({ behavior: reduced ? 'auto' : 'smooth', block: 'start' }))
}

function resolveConflict(conflict: RuleConflict): void {
  const keep = selectedRuleId.value && conflict.rule_ids.includes(selectedRuleId.value) ? selectedRuleId.value : conflict.rule_ids[0]
  rules.disableOtherConflictingRules(conflict.rule_ids, keep)
  selectedRuleId.value = keep
}

async function saveRules(): Promise<void> {
  localError.value = null
  const saved = await rules.save(projectId)
  if (!saved) localError.value = '保存未完成，请根据错误信息调整后重试。'
}

async function requestApproval(): Promise<void> {
  localError.value = null
  if (isDirty.value) {
    const saved = await rules.save(projectId)
    if (!saved) return
  }
  if (rules.unresolvedConflicts.length) {
    localError.value = '请先解决所有冲突并保存草案。'
    return
  }
  const missingEvidence = rules.draftRules.find((rule) => rule.enabled && (!rule.source.reference.trim() || (rule.source.source_type !== 'preset' && !rule.source.quote.trim())))
  if (missingEvidence) {
    selectedRuleId.value = missingEvidence.rule_id
    localError.value = `规则 ${missingEvidence.rule_id} 缺少来源引用或规范原句，不能批准。`
    return
  }
  approveDialog.value?.open()
}

async function approveRules(): Promise<void> {
  localError.value = null
  try {
    await rules.approve(projectId)
    approveDialog.value?.close()
  } catch (error) {
    localError.value = errorMessage(error, '规则批准失败，请重试。')
    approveDialog.value?.close()
  }
}

function openManualDialog(): void {
  manualQuote.value = ''
  localError.value = null
  manualError.value = null
  manualDialog.value?.showModal()
}

function addManualRule(): void {
  if (!manualQuote.value.trim()) {
    manualError.value = '请填写规范原句。'
    return
  }
  let expected: JsonValue
  try {
    expected = parseRuleValue(manualProperty.value, manualExpected.value, manualLineType.value)
  } catch (error) {
    manualError.value = error instanceof Error ? error.message : '预期值无效。'
    return
  }
  const id = `manual_${crypto.randomUUID().replaceAll('-', '_')}`
  const rule: FormatRule = {
    rule_id: id, name: manualName.value, selector: manualSelector.value, property: manualProperty.value,
    operator: 'eq', expected, tolerance: 0, enabled: true, severity: 'ERROR', fix_policy: 'AUTO_WITH_APPROVAL',
    source: { source_type: 'manual', reference: '人工录入规范', page: null, quote: manualQuote.value.trim(), extraction_confidence: 1 },
    confidence: 1, exclusions: [],
  }
  rules.addManualRule(rule)
  selectedRuleId.value = id
  manualDialog.value?.close()
}
</script>

<template>
  <div class="rules-page motion-page">
    <header class="workspace-heading">
      <div><h1>检查规范</h1></div>
      <div class="button-group">
        <button type="button" class="button button-secondary" :disabled="!rules.ruleSet" @click="openManualDialog"><Plus :size="16" aria-hidden="true" /> 人工规则</button>
        <button type="button" class="button button-secondary" :disabled="!rules.ruleSet || rules.saving || !isDirty" @click="saveRules"><Save :size="16" aria-hidden="true" /> {{ rules.saving ? '保存中…' : '保存草案' }}</button>
        <button type="button" class="button button-primary" :disabled="!rules.ruleSet || rules.approving || !enabledCount || (rules.isApproved && !isDirty)" @click="requestApproval"><ShieldCheck :size="16" aria-hidden="true" /> {{ isDirty ? '保存并批准' : rules.isApproved ? '已批准' : '批准规范' }}</button>
        <RouterLink v-if="rules.isApproved" class="button button-accent" :to="`/projects/${projectId}/inspection`">前往检查 <ArrowRight :size="16" aria-hidden="true" /></RouterLink>
      </div>
    </header>

    <ErrorNotice v-if="rules.error || localError" :message="localError ?? rules.error ?? ''" />
    <div v-if="rules.notice" class="notice notice-info" role="status"><Check :size="18" aria-hidden="true" /><p>{{ rules.notice }}</p></div>
    <div v-if="extractionJob && !rules.ruleSet" class="panel extraction-state">
      <LoaderCircle v-if="!['SUCCEEDED', 'FAILED', 'CANCELLED'].includes(extractionJob.status)" class="spinner" :size="26" aria-hidden="true" />
      <CircleAlert v-else :size="26" aria-hidden="true" />
      <div><strong>规范规则提取：{{ extractionJob.stage ?? extractionJob.status }}</strong><p>{{ extractionJob.error_message ? errorMessage(extractionJob.error_message, '规范提取失败，请重试。') : extractionJob.message ? errorMessage(extractionJob.message, '规范提取任务正在处理中。') : '服务端任务状态将自动恢复；不会产生本地伪规则。' }}</p></div>
      <span v-if="extractionJob.progress !== undefined">{{ extractionJob.progress }}%</span>
    </div>
    <div v-if="rules.ruleSet" class="rules-meta">
      <div><span class="muted">规则集</span><strong>{{ rules.ruleSet.name }}</strong></div>
      <div><span class="muted">版本 / 状态</span><strong>v{{ rules.ruleSet.version }} <StatusBadge :status="rules.ruleSet.status" /></strong></div>
      <div><span class="muted">启用 / 总数</span><strong>{{ enabledCount }} / {{ rules.draftRules.length }}</strong></div>
    </div>

    <div v-if="rules.unresolvedConflicts.length" class="conflict-panel" aria-labelledby="conflict-title">
      <h2 id="conflict-title"><CircleAlert :size="18" aria-hidden="true" /> 未解决冲突（{{ rules.unresolvedConflicts.length }}）</h2>
      <article v-for="conflict in rules.unresolvedConflicts" :key="conflict.conflict_id">
        <div><strong>{{ conflict.property }}</strong><p>{{ conflict.reason }}</p><span class="mono">{{ conflict.rule_ids.join(' · ') }}</span></div>
        <button type="button" class="button button-secondary button-small" @click="resolveConflict(conflict)">保留当前项并停用其他冲突规则</button>
      </article>
      <p class="small muted mb-0">处理后请保存，再确认规范。</p>
    </div>

    <div v-if="rules.ruleSet" class="rules-workspace">
      <aside class="rule-sources" aria-labelledby="sources-heading">
        <div class="panel-header"><h2 id="sources-heading">规范来源</h2><BookOpen :size="17" aria-hidden="true" /></div>
        <details class="mobile-source-toggle" open>
          <summary>来源摘录（{{ sources.length }}）</summary>
          <ol>
            <li v-for="(source, index) in sources" :key="`${source.reference}-${source.page}-${index}`">
              <strong>{{ source.reference }}</strong><span>{{ source.page ? `第 ${source.page} 页` : source.source_type }}</span>
              <blockquote>{{ source.quote || '此来源没有原句；请在规则详情中补充。' }}</blockquote>
            </li>
          </ol>
        </details>
      </aside>
      <section class="rule-table-panel" aria-labelledby="rules-table-title">
        <h2 id="rules-table-title" class="sr-only">结构化规则表</h2>
        <div class="table-scroll">
          <table class="data-table">
            <caption>可编辑规则 {{ rules.draftRules.length }} 条</caption>
            <thead><tr><th scope="col">启用</th><th scope="col">规则 / 目标</th><th scope="col">属性 / 预期</th><th scope="col" class="container-optional">来源</th><th scope="col">修复</th></tr></thead>
            <tbody>
              <tr v-for="rule in rules.draftRules" :key="rule.rule_id" :class="{ 'is-selected': selectedRuleId === rule.rule_id }">
                <td><input class="checkbox" type="checkbox" :checked="rule.enabled" :aria-label="`启用 ${rule.name || rule.rule_id}`" @change="rules.updateRule(rule.rule_id, { enabled: ($event.target as HTMLInputElement).checked })" /></td>
                <td><button type="button" class="table-link" @click="selectRule(rule.rule_id)">{{ rule.name || rule.rule_id }}</button><span class="table-subline">{{ roleLabel(rule.selector) }} · {{ rule.rule_id }}</span></td>
                <td><strong>{{ propertyLabel(rule.property) }}</strong><span class="table-subline mono">{{ JSON.stringify(rule.expected) }} · {{ rule.operator }}</span></td>
                <td class="container-optional"><span>{{ rule.source.reference }}</span><span class="table-subline">{{ rule.source.page ? `第 ${rule.source.page} 页` : '无页码' }} · {{ Math.round(rule.confidence * 100) }}%</span></td>
                <td><StatusBadge :status="rule.fix_policy" :label="rule.fix_policy === 'AUTO_WITH_APPROVAL' ? '批准后修复' : rule.fix_policy === 'MANUAL_ONLY' ? '仅人工' : '不支持'" /><button type="button" class="button button-ghost button-small mt-1" @click="selectRule(rule.rule_id)">编辑</button></td>
              </tr>
            </tbody>
          </table>
        </div>
        <div v-if="!rules.draftRules.length" class="empty-state"><strong>规则集为空</strong><p>添加人工规则，或返回新建页提交其他规范。</p></div>
      </section>
      <aside id="rule-editor" class="rule-editor-panel" aria-label="规则详情编辑器"><RuleEditorPanel :rule-id="selectedRuleId" /></aside>
    </div>
    <EmptyState v-else-if="!rules.loading && !extractionJob" title="尚未生成规则集" description="请返回新建检查，提交预设、规范文本或文本型 PDF。"><RouterLink class="button button-primary" to="/new"><FilePlus2 :size="16" aria-hidden="true" /> 新建检查</RouterLink></EmptyState>
    <div v-if="rules.loading" class="loading"><LoaderCircle class="spinner" :size="20" aria-hidden="true" /> 正在读取服务端规则…</div>
    <p v-if="rules.ruleSet" class="rules-footnote">创建：{{ formatDate(rules.ruleSet.created_at) }} · 批准：{{ formatDate(rules.ruleSet.approved_at) }}</p>

    <dialog ref="manualDialog" class="native-dialog" :aria-labelledby="manualTitleId">
      <form @submit.prevent="addManualRule">
        <div class="dialog-header"><h2 :id="manualTitleId">添加人工规则</h2><button type="button" class="button button-ghost icon-button" aria-label="关闭人工规则对话框" @click="manualDialog?.close()"><X :size="18" aria-hidden="true" /></button></div>
        <div class="dialog-body">
          <ErrorNotice v-if="manualError" :message="manualError" />
          <div class="form-field"><label class="field-label" for="manual-name">规则名称</label><input id="manual-name" v-model="manualName" class="field" required /></div>
          <div class="form-field"><label class="field-label" for="manual-selector">目标角色</label><select id="manual-selector" v-model="manualSelector" class="field"><option value="body">正文</option><option value="heading_1">一级标题</option><option value="heading_2">二级标题</option><option value="heading_3">三级标题</option><option value="caption">图表题</option><option value="table_text">表格文字</option><option value="section">页面节</option></select></div>
          <div class="form-field"><label class="field-label" for="manual-property">属性</label><select id="manual-property" v-model="manualProperty" class="field"><option value="font.size_pt">字号（pt）</option><option value="font.eastAsia">中文字体</option><option value="font.ascii">西文字体</option><option value="font.bold">加粗（true / false）</option><option value="paragraph.line_spacing">行距</option><option value="paragraph.alignment">段落对齐</option></select></div>
          <div v-if="manualProperty === 'paragraph.line_spacing'" class="form-field"><label class="field-label" for="manual-line-type">行距类型</label><select id="manual-line-type" v-model="manualLineType" class="field"><option value="MULTIPLE">倍数行距</option><option value="EXACT">固定值（pt）</option><option value="AT_LEAST">最小值（pt）</option></select></div>
          <div class="form-field"><label class="field-label" for="manual-expected">预期值</label><select v-if="manualProperty === 'font.bold'" id="manual-expected" v-model="manualExpected" class="field"><option value="true">加粗</option><option value="false">不加粗</option></select><select v-else-if="manualProperty === 'paragraph.alignment'" id="manual-expected" v-model="manualExpected" class="field"><option value="left">左对齐</option><option value="center">居中</option><option value="right">右对齐</option><option value="justify">两端对齐</option><option value="distribute">分散对齐</option></select><input v-else id="manual-expected" v-model="manualExpected" class="field" required /></div>
          <div class="form-field"><label class="field-label" for="manual-quote">规范原句</label><textarea id="manual-quote" v-model="manualQuote" class="field" required placeholder="填写可核对的原句，作为此规则的证据" /></div>
        </div>
        <div class="dialog-actions"><button type="button" class="button button-secondary" @click="manualDialog?.close()">取消</button><button type="submit" class="button button-primary">加入草案</button></div>
      </form>
    </dialog>
    <ConfirmDialog ref="approveDialog" title="批准当前规则集？" confirm-label="批准规则集" :busy="rules.approving" description="批准只允许后续检查和创建修复计划，不会直接修改文档。任何规则变化都需要重新检查。" @confirm="approveRules">
    </ConfirmDialog>
  </div>
</template>

<style scoped>
.rules-page { padding: 28px clamp(16px, 3vw, 40px); }
.workspace-heading { display: flex; align-items: flex-end; justify-content: space-between; gap: 24px; margin-bottom: 24px; }
.workspace-heading h1 { margin-bottom: 8px; font-size: clamp(1.8rem, 1.4rem + 1.4vw, 2.5rem); }
.workspace-heading p { max-width: 68ch; margin-bottom: 0; color: #6b756d; }
.rules-meta { display: grid; grid-template-columns: 1.3fr .8fr .6fr; gap: 16px; padding: 14px 18px; margin-bottom: 18px; background: #fff; border: 1px solid #dfe3dc; border-radius: 8px; }
.rules-meta > div { min-width: 0; }
.rules-meta span, .rules-meta strong { display: block; }
.rules-meta .muted { margin-bottom: 4px; font-size: .68rem; }
.rules-meta strong { display: flex; align-items: center; gap: 7px; font-size: .82rem; }
.rules-meta .mono { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.rules-workspace { display: grid; grid-template-columns: 280px minmax(0, 1fr) 340px; min-height: 620px; background: #fff; border: 1px solid #dfe3dc; border-radius: 10px; overflow: hidden; }
.rule-sources { min-width: 0; border-right: 1px solid #dfe3dc; }
.rule-sources ol { max-height: 700px; padding: 0; margin: 0; overflow-y: auto; list-style: none; }
.rule-sources li { padding: 16px; border-bottom: 1px solid #e7ebe3; }
.rule-sources li > strong, .rule-sources li > span { display: block; }
.rule-sources li > strong { font-size: .8rem; overflow-wrap: anywhere; }
.rule-sources li > span { margin-top: 3px; color: #737c73; font-size: .68rem; }
.rule-sources blockquote { margin: 10px 0 0; color: #667467; font-family: 'Noto Serif SC', 'Source Han Serif SC', serif; font-size: .75rem; line-height: 1.8; }
.mobile-source-toggle summary { display: none; }
.rule-table-panel { min-width: 0; border-right: 1px solid #dfe3dc; }
.table-subline { display: block; margin-top: 4px; color: #737c73; font-size: .68rem; }
.rule-editor-panel { min-width: 0; max-height: 760px; overflow-y: auto; }
.conflict-panel { padding: 16px 18px; margin-bottom: 18px; color: #76501c; background: #fff9ef; border: 1px solid #e1c08e; border-radius: 8px; }
.conflict-panel h2 { display: flex; align-items: center; gap: 7px; margin-bottom: 12px; font-family: inherit; font-size: .9rem; }
.conflict-panel article { display: flex; align-items: center; justify-content: space-between; gap: 20px; padding: 12px 0; border-top: 1px solid #ecd8b8; }
.conflict-panel article p { margin: 4px 0; font-size: .8rem; }
.extraction-state { display: flex; align-items: center; gap: 16px; padding: 24px; margin-bottom: 20px; }
.extraction-state > div { flex: 1; }
.extraction-state p { margin: 4px 0 0; color: #6b756d; }
.rules-footnote { color: #737c73; font-size: .7rem; text-align: right; }
@media (max-width: 1200px) { .rules-workspace { grid-template-columns: 230px minmax(0, 1fr); } .rule-editor-panel { grid-column: 1 / -1; max-height: none; border-top: 1px solid #dfe3dc; } }
@media (max-width: 800px) { .workspace-heading { align-items: flex-start; flex-direction: column; } .rules-meta { grid-template-columns: repeat(2, minmax(0, 1fr)); } .rules-workspace { grid-template-columns: 1fr; } .rule-sources { border-right: 0; border-bottom: 1px solid #dfe3dc; } .mobile-source-toggle summary { display: block; padding: 12px 16px; cursor: pointer; font-weight: 650; } .rule-sources ol { max-height: 260px; } .rule-table-panel { border-right: 0; } .conflict-panel article { align-items: flex-start; flex-direction: column; } }
</style>
