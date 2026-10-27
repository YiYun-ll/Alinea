<script setup lang="ts">
import { computed } from 'vue'
import { CircleAlert, FileSearch, LocateFixed, MapPin, Wrench } from 'lucide-vue-next'
import { useInspectionStore } from '../stores/inspection'
import { useRulesStore } from '../stores/rules'
import { formatValue, isRepairable, locationLabel, makeIssueNumber, propertyLabel } from '../lib/format'
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
  if (!inspection.selectedIssueIds.includes(issue.value.issue_id)) inspection.toggleSelected(issue.value.issue_id)
  emit('plan')
}
</script>

<template>
  <div v-if="issue" class="issue-detail">
    <div class="detail-heading">
      <div><span class="issue-id">{{ makeIssueNumber(issue.issue_id, inspection.issues) }}</span><h2>{{ propertyLabel(issue.property) }}</h2></div>
      <StatusBadge :status="issue.detection_status" />
    </div>
    <div class="detail-badges"><StatusBadge :status="issue.fix_status" /><StatusBadge :status="issue.repair.eligibility" /><StatusBadge :status="issue.location.status" :label="locationLabel(issue.location.status)" /></div>
    <div v-if="degradedMessage" class="notice notice-warn"><CircleAlert :size="18" class="shrink-0" aria-hidden="true" /><p>{{ degradedMessage }}</p></div>

    <section aria-labelledby="values-title">
      <h3 id="values-title">格式证据</h3>
      <dl class="definition-list">
        <dt>实际有效值</dt><dd><span class="code-value actual-value">{{ formatValue(issue.actual.value, issue.actual.unit) }}</span></dd>
        <dt>规则预期值</dt><dd><span class="code-value">{{ formatValue(issue.expected.value, issue.expected.unit) }}</span></dd>
        <dt>值来源</dt><dd>{{ issue.actual.origin ?? '来源未提供' }}</dd>
        <dt>原始 OOXML</dt><dd class="mono">{{ issue.actual.raw_ooxml_value ?? '未提供' }}</dd>
        <dt>证据说明</dt><dd>{{ issue.actual.reason ?? issue.expected.reason ?? '无补充说明' }}</dd>
      </dl>
    </section>

    <section aria-labelledby="location-title">
      <h3 id="location-title">定位与对象</h3>
      <dl class="definition-list">
        <dt>页码</dt><dd>{{ issue.location.status === 'LOCATED' && issue.location.page_index !== null ? `第 ${issue.location.page_index + 1} 页` : '页面未验证' }}</dd>
        <dt>段落序号</dt><dd>第 {{ issue.element_ref.paragraph_ordinal + 1 }} 段（0 基索引 {{ issue.element_ref.paragraph_ordinal }}）</dd>
        <dt>定位分数</dt><dd>{{ issue.location.score ?? '未提供' }} <span class="muted">（非概率）</span></dd>
        <dt>候选数</dt><dd>{{ issue.location.candidate_count }}</dd>
        <dt>OOXML 部件</dt><dd class="mono">{{ issue.element_ref.part_uri }}</dd>
      </dl>
      <button v-if="issue.location.status === 'LOCATED'" type="button" class="button button-secondary button-small mt-3" @click="emit('locate', issue)"><LocateFixed :size="14" aria-hidden="true" /> 定位到页面</button>
    </section>

    <section aria-labelledby="excerpt-title">
      <h3 id="excerpt-title">原文摘录</h3>
      <blockquote class="excerpt">{{ issue.element_ref.text_excerpt || issue.location.anchor_excerpt || '此对象没有可用文字摘录。' }}</blockquote>
    </section>

    <section aria-labelledby="source-title">
      <h3 id="source-title">规则来源</h3>
      <p class="source-name"><FileSearch :size="15" aria-hidden="true" /> {{ rule?.name || issue.rule_id }}</p>
      <dl class="definition-list">
        <dt>引用</dt><dd>{{ issue.source.reference }}</dd>
        <dt>页码</dt><dd>{{ issue.source.page ? `第 ${issue.source.page} 页` : '不适用' }}</dd>
      </dl>
      <blockquote class="excerpt source-quote">{{ issue.source.quote || '未提供规范原句；请在规则审阅页补充证据。' }}</blockquote>
    </section>

    <section aria-labelledby="action-title">
      <h3 id="action-title">建议动作</h3>
      <p class="muted small">{{ issue.repair.reason ?? (isRepairable(issue) ? '可创建定向修复计划；执行前仍需独立批准。' : '此问题需要人工处理，前端不会自动改写。') }}</p>
      <button type="button" class="button button-primary w-full" :disabled="!isRepairable(issue)" @click="selectForRepair"><Wrench :size="15" aria-hidden="true" /> {{ inspection.selectedIssueIds.includes(issue.issue_id) ? '已选择，查看修复计划' : '选择此项并生成计划' }}</button>
    </section>
    <p class="renderer-note"><MapPin :size="13" aria-hidden="true" /> 位置状态、违规状态与修复资格独立呈现。</p>
  </div>
  <EmptyState v-else title="选择一个问题" description="右侧将显示格式证据、来源与定位降级说明。" />
</template>

<style scoped>
.issue-detail { height: 100%; padding: 18px; overflow-y: auto; background: #fff; }
.detail-heading { display: flex; align-items: flex-start; justify-content: space-between; gap: 10px; }
.detail-heading h2 { margin: 5px 0 0; font-size: 1.35rem; }
.issue-id { color: #5675a8; font-family: ui-monospace, monospace; font-size: .72rem; font-weight: 700; }
.detail-badges { display: flex; flex-wrap: wrap; gap: 5px; margin: 14px 0 18px; }
.issue-detail section { padding: 18px 0; border-top: 1px solid #e1e5eb; }
.issue-detail h3 { margin-bottom: 12px; font-family: inherit; font-size: .8rem; font-weight: 750; }
.actual-value { color: #8d3d3d; border-color: #ddb0b0; background: #fff5f5; text-decoration: line-through; text-decoration-thickness: 1px; }
.source-name { display: flex; align-items: center; gap: 6px; font-size: .8rem; font-weight: 650; }
.source-quote { margin-top: 12px; font-size: .78rem; }
.renderer-note { display: flex; gap: 5px; margin: 10px 0 0; color: #6b7482; font-size: .68rem; }
</style>
