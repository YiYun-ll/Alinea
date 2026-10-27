<script setup lang="ts">
import { computed, ref } from 'vue'
import { CheckSquare, ChevronRight, ListFilter, LocateFixed, Search, Square, Wrench } from 'lucide-vue-next'
import { useInspectionStore } from '../stores/inspection'
import { useRulesStore } from '../stores/rules'
import { useRepairStore } from '../stores/repair'
import { formatValue, isRepairable, locationLabel, makeIssueNumber, propertyLabel, roleLabel } from '../lib/format'
import StatusBadge from './StatusBadge.vue'
import EmptyState from './EmptyState.vue'
import DisclosurePanel from './DisclosurePanel.vue'
import type { Issue } from '../types/contracts'

const emit = defineEmits<{ focus: [issue: Issue]; plan: [] }>()
const inspection = useInspectionStore()
const rules = useRulesStore()
const repair = useRepairStore()
const filtersOpen = ref(false)
const focusedAnnouncement = computed(() => inspection.focusedIssue ? `当前 ${makeIssueNumber(inspection.focusedIssue.issue_id, inspection.issues)}，${propertyLabel(inspection.focusedIssue.property)}` : '')

function focus(issue: Issue): void {
  inspection.focusIssue(issue.issue_id)
  emit('focus', issue)
}

function navigate(direction: 1 | -1): void {
  const issue = inspection.focusNext(direction)
  if (issue) emit('focus', issue)
}
</script>

<template>
  <div class="issue-panel-content">
    <div class="issue-filters">
      <div class="filter-title"><ListFilter :size="16" aria-hidden="true" /><strong>选择要修复的问题</strong><span>{{ inspection.filteredIssues.length }} / {{ inspection.issues.length }}</span></div>
      <label class="search-field">
        <span class="sr-only">搜索问题、摘录或规范</span><Search :size="16" aria-hidden="true" />
        <input v-model="inspection.query" type="search" placeholder="搜索问题或文字证据" />
      </label>
      <div class="category-buttons" aria-label="按问题类别筛选">
        <button v-for="item in [{ id: 'all', label: '全部' }, { id: 'font', label: '字体' }, { id: 'paragraph', label: '段落' }, { id: 'section', label: '页面' }]" :key="item.id" type="button" :aria-pressed="inspection.category === item.id" @click="inspection.category = item.id as typeof inspection.category">{{ item.label }}</button>
      </div>
      <DisclosurePanel class="filter-disclosure" title="更多筛选" description="按严重性或定位状态查看" :open="filtersOpen" @toggle="filtersOpen = !filtersOpen">
        <div class="filter-row">
          <label><span class="sr-only">严重程度</span><select v-model="inspection.severity" class="field"><option value="ALL">全部严重性</option><option value="ERROR">确认违规</option><option value="WARNING">警告</option><option value="INFO">信息</option></select></label>
          <label><span class="sr-only">定位状态</span><select v-model="inspection.location" class="field"><option value="ALL">全部定位状态</option><option value="LOCATED">位置已验证</option><option value="AMBIGUOUS">位置有歧义</option><option value="UNLOCATED">未定位</option><option value="NOT_RENDERED">未渲染</option><option value="PENDING">定位中</option></select></label>
        </div>
      </DisclosurePanel>
      <label class="checkbox-label"><input v-model="inspection.repairableOnly" class="checkbox" type="checkbox" /> 仅看可定向修复</label>
    </div>

    <EmptyState v-if="inspection.filteredIssues.length === 0" title="没有符合筛选的问题" description="调整搜索或筛选条件；未定位的问题不会被删除。" />
    <ol v-else class="issue-list motion-stagger" aria-label="问题列表，使用上下方向键切换" @keydown.up.prevent="navigate(-1)" @keydown.down.prevent="navigate(1)">
      <li v-for="issue in inspection.filteredIssues" :key="issue.issue_id" :class="{ focused: inspection.focusedIssueId === issue.issue_id }">
        <label class="issue-checkbox" :title="isRepairable(issue) ? '选择以纳入修复计划' : '此问题不可自动修复'">
          <input class="checkbox" type="checkbox" :checked="inspection.selectedIssueIds.includes(issue.issue_id)" :disabled="!isRepairable(issue)" :aria-label="`选择 ${makeIssueNumber(issue.issue_id, inspection.issues)} 纳入修复`" @change="inspection.toggleSelected(issue.issue_id)" />
        </label>
        <button type="button" class="issue-focus motion-button" :aria-pressed="inspection.focusedIssueId === issue.issue_id" @click="focus(issue)">
          <span class="issue-topline"><span class="issue-number">{{ makeIssueNumber(issue.issue_id, inspection.issues) }}</span><StatusBadge :status="issue.severity" /><StatusBadge :status="issue.location.status" :label="locationLabel(issue.location.status)" /></span>
          <strong>{{ propertyLabel(issue.property) }}</strong>
          <span class="issue-rule">{{ rules.draftRules.find((rule) => rule.rule_id === issue.rule_id)?.name || issue.rule_id }} · {{ roleLabel(rules.draftRules.find((rule) => rule.rule_id === issue.rule_id)?.selector ?? 'unknown') }}</span>
          <span class="issue-values">{{ formatValue(issue.actual.value, issue.actual.unit) }} <ChevronRight :size="12" aria-hidden="true" /> {{ formatValue(issue.expected.value, issue.expected.unit) }}</span>
          <span class="issue-excerpt">{{ issue.element_ref.text_excerpt || issue.location.anchor_excerpt || '无文字摘录；请查看结构定位。' }}</span>
        </button>
      </li>
    </ol>
    <div class="selection-toolbar">
      <div><strong>已选 {{ inspection.selectedCount }} 项</strong><span>仅可修复项可勾选</span></div>
      <div class="button-group">
        <button type="button" class="button button-ghost button-small" :disabled="!inspection.fixableCount" @click="inspection.selectAllFixable"><CheckSquare :size="14" aria-hidden="true" /> 全可修</button>
        <button type="button" class="button button-ghost button-small" :disabled="!inspection.selectedCount" @click="inspection.clearSelection"><Square :size="14" aria-hidden="true" /> 清空</button>
      </div>
      <button type="button" class="button button-primary w-full" :disabled="!inspection.selectedCount || repair.creating" @click="emit('plan')"><Wrench :size="16" aria-hidden="true" /> {{ repair.creating ? '正在生成计划…' : '生成修复计划' }}</button>
      <span v-if="inspection.summary?.unlocated" class="degraded-count"><LocateFixed :size="13" aria-hidden="true" /> {{ inspection.summary.unlocated }} 项页面未定位，仍保留摘录</span>
    </div>
    <div class="sr-only" aria-live="polite">{{ focusedAnnouncement }}</div>
  </div>
</template>

<style scoped>
.issue-panel-content { min-height: 0; height: 100%; display: flex; flex-direction: column; }
.issue-filters { padding: 14px; background: #fff; border-bottom: 1px solid #d8dde5; }
.filter-title { display: flex; align-items: center; gap: 7px; margin-bottom: 12px; }
.filter-title span { margin-left: auto; color: #6b7482; font-size: .72rem; }
.search-field { display: flex; align-items: center; gap: 7px; padding: 0 10px; border: 1px solid #aeb8c6; border-radius: 6px; }
.search-field input { width: 100%; min-width: 0; min-height: 38px; padding: 0; background: transparent; border: 0; outline: 0; }
.search-field:focus-within { outline: 3px solid #d98b27; outline-offset: 2px; }
.category-buttons { display: grid; grid-template-columns: repeat(4, 1fr); gap: 3px; margin: 10px 0; padding: 3px; background: #edf0f4; border-radius: 6px; }
.category-buttons button { min-height: 30px; padding: 3px; color: #536174; background: transparent; border: 0; border-radius: 4px; font-size: .75rem; }
.category-buttons button[aria-pressed='true'] { color: #273449; background: #fff; box-shadow: 0 1px 2px rgba(39, 52, 73, .12); font-weight: 700; }
.filter-disclosure { margin: 4px 0 8px; }
.filter-disclosure :deep(.disclosure-trigger) { min-height: 36px; padding-block: 4px; }
.filter-disclosure :deep(.disclosure-trigger small) { font-size: .68rem; }
.filter-row { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 7px; }
.filter-row .field { min-height: 34px; padding: 5px; font-size: .7rem; }
.issue-list { min-height: 120px; flex: 1; padding: 0; margin: 0; overflow-y: auto; list-style: none; }
.issue-list li { display: flex; align-items: flex-start; gap: 3px; padding: 10px 8px 10px 10px; background: #fff; border-bottom: 1px solid #e1e5eb; }
.issue-list li.focused { background: #f0f3f8; box-shadow: inset 3px 0 #5675a8; }
.issue-checkbox { padding-top: 8px; }
.issue-focus { min-width: 0; flex: 1; display: flex; flex-direction: column; align-items: flex-start; gap: 5px; padding: 5px 7px; background: transparent; border: 0; text-align: left; }
.issue-topline { width: 100%; display: flex; align-items: center; flex-wrap: wrap; gap: 4px; }
.issue-topline .status:last-child { margin-left: auto; }
.issue-number { color: #5675a8; font-family: ui-monospace, monospace; font-size: .7rem; font-weight: 700; }
.issue-focus > strong { font-size: .875rem; }
.issue-rule { max-width: 100%; color: #5e6979; font-size: .7rem; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.issue-values { display: inline-flex; align-items: center; gap: 4px; font-family: ui-monospace, monospace; font-size: .7rem; }
.issue-excerpt { display: -webkit-box; overflow: hidden; color: #6b7482; font-family: 'Noto Serif SC', 'Source Han Serif SC', serif; font-size: .72rem; -webkit-box-orient: vertical; -webkit-line-clamp: 2; }
.selection-toolbar { padding: 12px 14px; background: #fff; border-top: 1px solid #cfd5de; }
.selection-toolbar > div:first-child { display: flex; justify-content: space-between; margin-bottom: 8px; font-size: .75rem; }
.selection-toolbar > div:first-child span { color: #6b7482; }
.selection-toolbar .button-group { margin-bottom: 10px; }
.degraded-count { display: flex; align-items: center; gap: 4px; margin-top: 9px; color: #76501c; font-size: .68rem; }
</style>
