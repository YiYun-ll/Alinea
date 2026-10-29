<script setup lang="ts">
import { computed } from 'vue'
import { ArrowRight, CircleAlert, LocateFixed, Wrench } from 'lucide-vue-next'
import { useInspectionStore } from '../stores/inspection'
import { useRulesStore } from '../stores/rules'
import { formatValue, isRepairable, makeIssueNumber, propertyLabel } from '../lib/format'
import StatusBadge from './StatusBadge.vue'
import EmptyState from './EmptyState.vue'
import type { Issue } from '../types/contracts'

const emit = defineEmits<{ locate: [issue: Issue]; plan: [] }>()
const inspection = useInspectionStore()
const rules = useRulesStore()
const issue = computed(() => inspection.focusedIssue)
const rule = computed(() => issue.value ? rules.draftRules.find((item) => item.rule_id === issue.value?.rule_id) : null)
const degradedMessage = computed(() => {
  const status = issue.value?.location.status
  if (status === 'AMBIGUOUS') return '找到多个可能位置。文档结构定位可用，但页面坐标未验证，因此不绘制高亮框。'
  if (status === 'UNLOCATED') return '未找到可信页面位置。保留段落摘录、当前值和期望值，不以猜测坐标代替证据。'
  if (status === 'NOT_RENDERED') return 'PDF 未成功渲染。结构化检测证据仍可审阅，页面修复预览受限。'
  if (status === 'PENDING') return '页面定位尚未完成，当前不绘制高亮框。'
  return null
})

function selectForRepair(): void {
  if (!issue.value || !isRepairable(issue.value)) return
  inspection.toggleSelected(issue.value.issue_id)
}
</script>

<template>
  <div v-if="issue" class="issue-detail">
    <div class="detail-heading"><div><span class="issue-id">{{ makeIssueNumber(issue.issue_id, inspection.issues) }}</span><h2>{{ propertyLabel(issue.property) }}</h2></div><StatusBadge v-if="!isRepairable(issue)" :status="issue.repair.eligibility" /></div>
    <div class="value-comparison" aria-label="当前值与规范值"><div><span>当前</span><strong>{{ formatValue(issue.actual.value, issue.actual.unit) }}</strong></div><ArrowRight :size="16" aria-hidden="true" /><div><span>规范</span><strong>{{ formatValue(issue.expected.value, issue.expected.unit) }}</strong></div></div>
    <div v-if="degradedMessage" class="notice notice-warn"><CircleAlert :size="16" aria-hidden="true" /><p>{{ degradedMessage }}</p></div>
    <section>
      <div class="detail-section-heading"><h3>原文</h3><button v-if="issue.location.status === 'LOCATED'" type="button" class="text-link locate-link" @click="emit('locate', issue)"><LocateFixed :size="13" aria-hidden="true" />第 {{ (issue.location.page_index ?? 0) + 1 }} 页</button></div>
      <blockquote class="excerpt">{{ issue.element_ref.text_excerpt || issue.location.anchor_excerpt || '此对象没有文字摘录。' }}</blockquote>
    </section>
    <section><h3>规范依据</h3><p class="source-name">{{ rule?.name || issue.rule_id }}</p><blockquote class="excerpt source-quote">{{ issue.source.quote || '未提供规范原句，请核对来源。' }}</blockquote><p class="source-reference">{{ issue.source.reference }}<template v-if="issue.source.page"> · 第 {{ issue.source.page }} 页</template></p></section>
    <details class="technical-evidence"><summary>定位与格式详情</summary><dl class="definition-list"><dt>值来源</dt><dd>{{ issue.actual.origin ?? '未提供' }}</dd><dt>原始格式</dt><dd class="mono">{{ issue.actual.raw_ooxml_value ?? '未提供' }}</dd><dt>说明</dt><dd>{{ issue.actual.reason ?? issue.expected.reason ?? '无补充说明' }}</dd><dt>段落</dt><dd>第 {{ issue.element_ref.paragraph_ordinal + 1 }} 段</dd><dt>定位分数</dt><dd>{{ issue.location.score ?? '未提供' }}（非概率）</dd><dt>候选数</dt><dd>{{ issue.location.candidate_count }}</dd><dt>部件</dt><dd class="mono">{{ issue.element_ref.part_uri }}</dd></dl></details>
    <div class="detail-action"><p v-if="!isRepairable(issue)" class="muted small">{{ issue.repair.reason ?? '此项需人工处理。' }}</p><button type="button" class="button button-secondary w-full" :disabled="!isRepairable(issue)" :aria-pressed="inspection.selectedIssueIds.includes(issue.issue_id)" @click="selectForRepair"><Wrench :size="15" aria-hidden="true" />{{ inspection.selectedIssueIds.includes(issue.issue_id) ? '从修复中移除' : '加入修复' }}</button></div>
  </div>
  <EmptyState v-else title="选择一个问题" />
</template>
<style scoped>
.issue-detail { width: 100%; height: 100%; padding: 22px; overflow-y: auto; background: var(--white); }
.detail-heading { display: flex; justify-content: space-between; align-items: flex-start; gap: 8px; }
.detail-heading h2 { margin: 6px 0 0; font-size: 1.25rem; }
.issue-id { color: var(--muted); font-size: .7rem; font-variant-numeric: tabular-nums; }
.value-comparison { display: grid; grid-template-columns: 1fr auto 1fr; align-items: center; gap: 12px; margin: 24px 0; }
.value-comparison > div { min-width: 0; }
.value-comparison span { display: block; color: var(--muted); font-size: .68rem; margin-bottom: 6px; }
.value-comparison strong { font-size: .94rem; font-weight: 500; overflow-wrap: anywhere; }
.value-comparison > div:last-child strong { color: var(--accent); }
.value-comparison > svg { color: #9fadc0; }
.issue-detail section { padding-block: 20px; border-top: 1px solid var(--line); }
.issue-detail h3 { margin: 0 0 12px; font-family: inherit; font-size: .75rem; font-weight: 500; }
.detail-section-heading { display: flex; justify-content: space-between; align-items: baseline; }
.locate-link { padding: 0; border: 0; background: transparent; font-size: .7rem; }
.excerpt { padding: 12px 14px; border-left-width: 2px; border-left-color: #cbd6e5; font-size: .8rem; line-height: 1.9; }
.source-name { margin-bottom: 8px; font-size: .75rem; }
.source-reference { margin: 10px 0 0; color: var(--muted); font-size: .68rem; overflow-wrap: anywhere; }
.technical-evidence { border-top: 1px solid var(--line); font-size: .75rem; }
.technical-evidence summary { padding-block: 16px; cursor: pointer; color: var(--muted); }
.technical-evidence .definition-list { margin-bottom: 18px; font-size: .72rem; }
.detail-action { margin-top: 12px; }
</style>
