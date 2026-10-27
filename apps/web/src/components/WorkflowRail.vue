<script setup lang="ts">
import { computed } from 'vue'
import { RouterLink, useRoute } from 'vue-router'
import { Check } from 'lucide-vue-next'
import { useProjectStore } from '../stores/project'
import { useRulesStore } from '../stores/rules'
import { useInspectionStore } from '../stores/inspection'
import { useRepairStore } from '../stores/repair'

interface WorkflowStep {
  id: 'rules' | 'inspection' | 'repairs' | 'results'
  label: string
  shortLabel: string
  hint: string
}

const route = useRoute()
const project = useProjectStore()
const rules = useRulesStore()
const inspection = useInspectionStore()
const repair = useRepairStore()
const projectId = computed(() => String(route.params.id))
const steps: WorkflowStep[] = [
  { id: 'rules', label: '确认规范', shortLabel: '规范', hint: '查看来源、编辑并批准规范' },
  { id: 'inspection', label: '检查与选择', shortLabel: '检查', hint: '检查文档并选择要修复的问题' },
  { id: 'repairs', label: '批准与修复', shortLabel: '修复', hint: '核对差异，独立批准并执行' },
  { id: 'results', label: '报告与下载', shortLabel: '报告', hint: '查看复检、对照文档并下载' },
]
const latestResultId = computed(() => {
  if (repair.plan?.result_revision_id) return repair.plan.result_revision_id
  const active = project.revisions().find((revision) => revision.revision_id === project.activeRevisionId && ['PUBLISHED', 'PARTIAL_PUBLISHED'].includes(revision.kind ?? ''))
  if (active) return active.revision_id
  return project.revisions().filter((revision) => ['PUBLISHED', 'PARTIAL_PUBLISHED'].includes(revision.kind ?? '')).at(-1)?.revision_id ?? null
})

function isCurrent(step: WorkflowStep): boolean {
  return route.name === step.id
}

function isComplete(step: WorkflowStep): boolean {
  if (step.id === 'rules') return rules.isApproved
  if (step.id === 'inspection') return Boolean(inspection.result || latestResultId.value)
  if (step.id === 'repairs') return Boolean(latestResultId.value)
  return false
}

function isAvailable(step: WorkflowStep): boolean {
  return step.id !== 'results' || Boolean(latestResultId.value)
}

function target(step: WorkflowStep): string {
  const suffix = step.id === 'results' ? `results/${latestResultId.value}` : step.id
  return `/projects/${projectId.value}/${suffix}`
}
</script>

<template>
  <nav class="workflow-rail" aria-label="检查工作流程">
    <ol>
      <li v-for="(step, index) in steps" :key="step.id" :class="{ 'is-current': isCurrent(step), 'is-complete': isComplete(step) }">
        <component
          :is="isAvailable(step) ? RouterLink : 'button'"
          :to="isAvailable(step) ? target(step) : undefined"
          :type="isAvailable(step) ? undefined : 'button'"
          :disabled="!isAvailable(step)"
          class="workflow-step"
          :class="{ 'is-disabled': !isAvailable(step) }"
          :aria-label="step.label"
          :aria-current="isCurrent(step) ? 'step' : undefined"
          :title="isAvailable(step) ? step.hint : '完成修复后可查看报告与下载'"
        >
          <span class="workflow-marker" aria-hidden="true"><Check v-if="isComplete(step)" :size="14" /><span v-else>{{ String(index + 1).padStart(2, '0') }}</span></span>
          <span class="workflow-label"><span class="workflow-label-full">{{ step.label }}</span><span class="workflow-label-short">{{ step.shortLabel }}</span></span>
        </component>
      </li>
    </ol>
  </nav>
</template>

<style scoped>
.workflow-rail { position: sticky; inset-block-start: 0; z-index: 20; padding: 10px clamp(14px, 3vw, 40px); background: rgba(255, 255, 255, .96); border-bottom: 1px solid #e1e5eb; box-shadow: 0 4px 16px rgba(39, 52, 73, .03); backdrop-filter: blur(14px); }
.workflow-rail ol { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 8px; max-width: 1040px; padding: 0; margin: 0 auto; list-style: none; }
.workflow-rail li { position: relative; min-width: 0; }
.workflow-rail li:not(:last-child)::after { position: absolute; inset-block-start: 50%; inset-inline-end: -5px; width: 10px; height: 1px; content: ''; background: #cfd7e2; }
.workflow-step { display: flex; align-items: center; justify-content: center; gap: 9px; width: 100%; min-height: 44px; padding: 7px 10px; color: #6b7482; background: transparent; border: 1px solid transparent; border-radius: 7px; font-size: .8125rem; text-decoration: none; transition: color var(--motion-fast) ease, background-color var(--motion-fast) ease, border-color var(--motion-fast) ease, translate var(--motion-fast) var(--motion-ease-out); }
.workflow-step:hover:not(.is-disabled) { color: #273449; background: #f2f5f9; translate: 0 -1px; }
.workflow-marker { display: grid; place-items: center; flex: 0 0 26px; width: 26px; height: 26px; color: #6b7482; border: 1px solid #cfd5de; border-radius: 50%; font-family: ui-monospace, monospace; font-size: .65rem; transition: color var(--motion-base) ease, background-color var(--motion-base) ease, border-color var(--motion-base) ease; }
.workflow-label-short { display: none; }
.workflow-rail li.is-current .workflow-step { color: #273449; background: #edf2f9; border-color: #d1dce9; font-weight: 650; }
.workflow-rail li.is-current .workflow-marker { color: #fff; background: #5675a8; border-color: #5675a8; }
.workflow-rail li.is-complete:not(.is-current) .workflow-marker { color: #1d6c55; background: #edf7f2; border-color: #a7cec0; }
.workflow-step.is-disabled { cursor: not-allowed; opacity: .55; }
@media (max-width: 640px) {
  .workflow-rail { padding: 8px 10px; }
  .workflow-rail ol { gap: 3px; }
  .workflow-rail li:not(:last-child)::after { display: none; }
  .workflow-step { flex-direction: column; gap: 4px; min-height: 56px; padding: 6px 3px; font-size: .72rem; }
  .workflow-marker { width: 22px; height: 22px; flex-basis: 22px; font-size: .6rem; }
  .workflow-label-full { display: none; }
  .workflow-label-short { display: inline; }
}
</style>
