<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import { ArrowRight, CheckCircle2, ChevronDown, LoaderCircle, Plus, Send, Sparkles, X } from 'lucide-vue-next'
import { useAgentStore } from '../stores/agent'
import { useInspectionStore } from '../stores/inspection'
import { useProjectStore } from '../stores/project'
import { useRulesStore } from '../stores/rules'
import { roleLabel } from '../lib/format'

const props = withDefaults(defineProps<{ projectId: string; mobile?: boolean }>(), { mobile: false })
const emit = defineEmits<{ close: [] }>()
const agent = useAgentStore()
const project = useProjectStore()
const rules = useRulesStore()
const inspection = useInspectionStore()
const input = ref('')
const content = ref<HTMLDivElement | null>(null)
const expandedTurns = ref<number[]>([])
const run = computed(() => agent.activeRun)
const busy = computed(() => agent.sending || run.value?.status === 'QUEUED' || run.value?.status === 'RUNNING')
const needsAnswer = computed(() => run.value?.status === 'NEEDS_CLARIFICATION')
const canAnswer = computed(() => run.value && !busy.value && ['NEEDS_CLARIFICATION', 'SUCCEEDED', 'FAILED'].includes(run.value.status))
const action = computed(() => {
  const result = run.value?.result
  if (!result || !('recommended_action' in result)) return null
  const base = `/projects/${props.projectId}`
  const destinations = {
    REVIEW_RULES: { path: `${base}/rules`, label: '审阅规则' },
    REVIEW_INSPECTION: { path: `${base}/inspection`, label: '查看检查' },
    REVIEW_REPAIR: { path: `${base}/repairs`, label: '审阅修复计划' },
    REVIEW_RESULTS: { path: `${base}/results/${project.activeRevisionId}`, label: '查看验证报告' },
    NONE: null,
  }
  return destinations[result.recommended_action]
})
const turns = computed(() => {
  if (!run.value) return []
  return run.value.events.flatMap((event) => {
    if (event.event_type === 'run.created') return [{ key: event.sequence, actor: 'user', text: run.value!.objective }]
    if (event.event_type === 'run.resumed') return [{ key: event.sequence, actor: 'user', text: String(event.payload.message ?? '') }]
    if (event.event_type === 'run.completed') return [{ key: event.sequence, actor: 'agent', text: String(event.payload.message ?? run.value!.error_message ?? '') }]
    if (event.event_type === 'run.failed') return [{ key: event.sequence, actor: 'agent', text: String(event.payload.message ?? run.value!.error_message ?? '任务未完成') }]
    return []
  })
})
const toolEvents = computed(() => run.value?.events.filter((event) => event.tool_name) ?? [])
const quickPrompts = computed(() => {
  const prompts = ['分析当前文档结构']
  if (rules.isApproved) prompts.push('检查当前文档格式')
  if (inspection.result?.status === 'SUCCEEDED') prompts.push('为可安全修复的问题准备计划')
  return prompts
})
const toolNames: Record<string, string> = {
  get_project_context: '读取项目上下文',
  read_guideline_sections: '读取规范原文',
  validate_rule_candidates: '校验规则与证据',
  get_document_structure_summary: '分析文档结构',
  run_inspection: '提交格式检查',
  get_inspection_summary: '读取检查结果',
  preview_repair_plan: '准备修复计划',
  get_repair_plan: '读取修复计划',
  get_verification_report: '读取验证报告',
}

watch(() => [run.value?.run_id, turns.value.length], async () => {
  await nextTick()
  const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches
  content.value?.scrollTo({ top: content.value.scrollHeight, behavior: reduced ? 'auto' : 'smooth' })
})

function newTask(): void {
  if (busy.value) return
  agent.newTask()
  input.value = ''
}

function selectTask(event: Event): void {
  const value = (event.target as HTMLSelectElement).value
  if (value) agent.select(value)
  else newTask()
}

async function submit(): Promise<void> {
  const objective = input.value.trim()
  if (!objective || busy.value) return
  try {
    if (canAnswer.value && run.value) {
      input.value = ''
      await agent.answer(props.projectId, objective)
      return
    }
    input.value = ''
    await agent.start(props.projectId, {
      objective,
      guideline_id: rules.ruleSet?.guideline_id ?? undefined,
      revision_id: project.activeRevisionId ?? undefined,
      rule_set_id: rules.ruleSet?.rule_set_id ?? undefined,
      inspection_id: inspection.inspectionId ?? undefined,
    })
  } catch {
    input.value = objective
  }
}

async function usePrompt(prompt: string): Promise<void> {
  input.value = prompt
  await submit()
}

function toggleTurn(key: number): void {
  expandedTurns.value = expandedTurns.value.includes(key)
    ? expandedTurns.value.filter((item) => item !== key)
    : [...expandedTurns.value, key]
}
</script>

<template>
  <aside class="agent-panel" aria-label="Alinea 智能体">
    <header class="agent-header">
      <div class="agent-title"><Sparkles :size="18" aria-hidden="true" /><strong>Alinea 智能体</strong></div>
      <div class="agent-header-actions">
        <button v-if="run" type="button" class="icon-button" aria-label="新建智能体任务" :disabled="busy" @click="newTask"><Plus :size="18" aria-hidden="true" /></button>
        <button type="button" class="icon-button agent-close" aria-label="关闭智能体" @click="emit('close')"><X :size="18" aria-hidden="true" /></button>
      </div>
    </header>

    <div v-if="agent.runs.length" class="agent-history">
      <select aria-label="选择智能体任务" :value="agent.activeRunId ?? ''" @change="selectTask">
        <option value="">新任务</option>
        <option v-for="item in agent.runs" :key="item.run_id" :value="item.run_id">{{ item.objective }}</option>
      </select>
      <ChevronDown :size="14" aria-hidden="true" />
    </div>

    <div ref="content" class="agent-content" aria-live="polite">
      <template v-if="run">
        <div class="agent-conversation">
          <div v-for="turn in turns" :key="turn.key" class="agent-turn" :data-actor="turn.actor">
            <p :class="{ 'is-clamped': turn.text.length > 220 && !expandedTurns.includes(turn.key) }">{{ turn.text }}</p>
            <button v-if="turn.text.length > 220" type="button" class="agent-expand" :aria-expanded="expandedTurns.includes(turn.key)" @click="toggleTurn(turn.key)">{{ expandedTurns.includes(turn.key) ? '收起' : '展开完整结论' }}</button>
          </div>
        </div>
        <div v-if="busy" class="agent-working" role="status">
          <LoaderCircle class="spinner" :size="18" aria-hidden="true" />
          <span>{{ run.tool_call_count ? `正在处理 · ${run.tool_call_count} 次工具调用` : '正在理解任务' }}</span>
        </div>
        <div v-if="needsAnswer" class="agent-questions">
          <div v-for="question in run.clarifications" :key="question.question_id">
            <strong>{{ question.question }}</strong>
            <p v-if="question.context">{{ question.context }}</p>
          </div>
        </div>
        <div v-if="run.result && 'role_suggestions' in run.result && run.result.role_suggestions?.length" class="agent-roles">
          <div v-for="suggestion in run.result.role_suggestions" :key="suggestion.target">
            <strong>{{ roleLabel(suggestion.role) }}</strong>
            <span>{{ Math.round(suggestion.confidence * 100) }}%</span>
            <p>{{ suggestion.evidence }}</p>
          </div>
        </div>
        <RouterLink v-if="action && !busy" class="agent-action" :to="action.path" @click="emit('close')">{{ action.label }}<ArrowRight :size="16" aria-hidden="true" /></RouterLink>
        <details v-if="toolEvents.length" class="agent-trace">
          <summary>执行过程 <span>{{ toolEvents.length }}</span></summary>
          <ol>
            <li v-for="event in toolEvents" :key="event.sequence" :data-status="event.status">
              <span class="trace-dot" aria-hidden="true" />
              <div><strong>{{ toolNames[event.tool_name ?? ''] ?? event.tool_name }}</strong><small>{{ event.status === 'SUCCEEDED' ? `${event.duration_ms} ms` : '未完成' }}</small></div>
            </li>
          </ol>
        </details>
      </template>
      <div v-else-if="!agent.loading" class="agent-empty">
        <CheckCircle2 :size="22" aria-hidden="true" />
        <p>从当前文档开始</p>
        <div class="agent-prompts">
          <button v-for="prompt in quickPrompts" :key="prompt" type="button" @click="usePrompt(prompt)">{{ prompt }}<ArrowRight :size="14" aria-hidden="true" /></button>
        </div>
      </div>
      <p v-if="agent.error" class="agent-failure" role="alert">{{ agent.error }}</p>
    </div>

    <form class="agent-composer" @submit.prevent="submit">
      <label class="sr-only" for="agent-input">{{ needsAnswer ? '回答智能体的问题' : run ? '继续当前任务' : '向智能体描述任务' }}</label>
      <textarea id="agent-input" v-model="input" rows="3" :disabled="busy" :autofocus="mobile" :placeholder="needsAnswer ? '回答上述问题…' : run ? '继续当前任务…' : '描述要完成的排版任务…'" @keydown.ctrl.enter.prevent="submit" />
      <div><span v-if="!busy">Ctrl + Enter</span><button type="submit" :aria-label="run ? '发送追问' : '发送任务'" :disabled="busy || !input.trim()"><Send :size="17" aria-hidden="true" /></button></div>
    </form>
  </aside>
</template>

<style scoped>
.agent-panel { display: flex; flex-direction: column; block-size: 100%; min-block-size: 0; color: #29394e; background: #fff; border-inline-start: 1px solid #dfe4ea; }
.agent-header { display: flex; flex-shrink: 0; align-items: center; justify-content: space-between; min-block-size: 60px; padding-inline: 20px 12px; border-block-end: 1px solid #edf0f4; }
.agent-title { display: flex; align-items: center; gap: 9px; font-size: .88rem; }
.agent-title svg { color: #4b6588; }
.agent-header-actions { display: flex; gap: 2px; }
.icon-button { display: inline-grid; place-items: center; inline-size: 36px; block-size: 36px; padding: 0; color: #748095; background: transparent; border: 0; border-radius: 6px; }
.icon-button:hover:not(:disabled) { color: #29394e; background: #f2f4f7; }
.agent-history { position: relative; flex-shrink: 0; margin: 12px 16px 0; }
.agent-history select { inline-size: 100%; padding: 8px 30px 8px 10px; color: #657184; background: #f7f8fa; border: 1px solid #e5e9ef; border-radius: 6px; font-size: .72rem; text-overflow: ellipsis; appearance: none; }
.agent-history svg { position: absolute; inset-inline-end: 10px; inset-block-start: 10px; pointer-events: none; }
.agent-content { flex: 1; min-block-size: 0; padding: 20px; overflow-y: auto; scrollbar-gutter: stable; overscroll-behavior: contain; }
.agent-conversation { display: flex; flex-direction: column; gap: 18px; }
.agent-turn { max-inline-size: 94%; }
.agent-turn p { margin: 0; font-size: .84rem; line-height: 1.85; white-space: pre-wrap; overflow-wrap: anywhere; }
.agent-turn p.is-clamped { display: -webkit-box; overflow: clip; line-clamp: 6; -webkit-line-clamp: 6; -webkit-box-orient: vertical; }
.agent-expand { padding: 4px 0; color: #4b6588; background: transparent; border: 0; font-size: .7rem; }
.agent-turn[data-actor='user'] { align-self: flex-end; padding: 10px 13px; color: #44536a; background: #f1f4f7; border-radius: 10px 10px 2px; }
.agent-turn[data-actor='user'] p { font-size: .76rem; line-height: 1.65; }
.agent-turn[data-actor='agent'] { padding-inline-end: 4px; }
.agent-working { display: flex; align-items: center; gap: 9px; margin-block-start: 20px; color: #4b6588; font-size: .76rem; }
.agent-questions { padding: 16px; margin-block-start: 18px; background: #f5f7fa; border-inline-start: 3px solid #4b6588; border-radius: 0 8px 8px 0; }
.agent-questions strong { font-size: .84rem; line-height: 1.8; }
.agent-questions p { margin: 8px 0 0; color: #748095; font-size: .76rem; line-height: 1.65; }
.agent-action { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 12px 0; margin-block-start: 20px; color: #4b6588; border-block-end: 1px solid #dfe4ea; font-size: .82rem; font-weight: 650; text-decoration: none; }
.agent-action:hover { color: #29394e; }
.agent-roles { margin-block-start: 18px; border-block-start: 1px solid #edf0f4; }
.agent-roles > div { display: grid; grid-template-columns: 1fr auto; gap: 4px 12px; padding-block: 12px; border-block-end: 1px solid #edf0f4; }
.agent-roles strong { font-size: .78rem; }
.agent-roles span { color: #748095; font-size: .7rem; }
.agent-roles p { grid-column: 1 / -1; margin: 0; color: #657184; font-size: .72rem; line-height: 1.6; }
.agent-trace { margin-block-start: 24px; }
.agent-trace summary { color: #748095; cursor: pointer; font-size: .72rem; }
.agent-trace summary span { margin-inline-start: 5px; color: #98a2b1; }
.agent-trace ol { padding: 0; margin: 16px 0 0; list-style: none; }
.agent-trace li { position: relative; display: flex; gap: 10px; padding-block-end: 15px; }
.agent-trace li:not(:last-child)::before { position: absolute; inset-inline-start: 3px; inset-block: 10px 0; content: ''; border-inline-start: 1px solid #e1e6ed; }
.trace-dot { z-index: 1; flex-shrink: 0; inline-size: 7px; block-size: 7px; margin-block-start: 5px; background: #8293a9; border-radius: 50%; }
.agent-trace li[data-status='FAILED'] .trace-dot { background: #a34d4d; }
.agent-trace strong { display: block; color: #657184; font-size: .7rem; font-weight: 550; }
.agent-trace small { display: block; margin-block-start: 2px; color: #98a2b1; font-size: .62rem; }
.agent-empty { padding-block-start: clamp(30px, 8vh, 90px); }
.agent-empty > svg { margin-block-end: 16px; color: #8293a9; }
.agent-empty > p { margin: 0 0 20px; font-family: 'Noto Serif SC', 'Source Han Serif SC', serif; font-size: 1.18rem; }
.agent-prompts { display: flex; flex-direction: column; }
.agent-prompts button { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 12px 0; color: #657184; background: transparent; border: 0; border-block-end: 1px solid #edf0f4; font-size: .76rem; text-align: start; }
.agent-prompts button:hover { color: #4b6588; }
.agent-failure { color: #914545; font-size: .78rem; line-height: 1.7; }
.agent-composer { flex-shrink: 0; padding: 14px 16px 16px; background: #fff; border-block-start: 1px solid #edf0f4; }
.agent-composer textarea { display: block; inline-size: 100%; min-block-size: 78px; max-block-size: 180px; padding: 12px; resize: vertical; color: #29394e; background: #f7f8fa; border: 1px solid #dfe4ea; border-radius: 8px; font: inherit; font-size: .8rem; line-height: 1.65; }
.agent-composer textarea:focus { background: #fff; border-color: #4b6588; outline: 2px solid #4b658820; }
.agent-composer > div { display: flex; align-items: center; justify-content: space-between; min-block-size: 34px; margin-block-start: 6px; }
.agent-composer > div > span { color: #a0a8b4; font-size: .62rem; }
.agent-composer button { display: inline-grid; place-items: center; inline-size: 36px; block-size: 34px; margin-inline-start: auto; color: #fff; background: #4b6588; border: 0; border-radius: 6px; }
.agent-composer button:disabled { color: #a7b0bb; background: #e8ebef; cursor: not-allowed; }
@media (min-width: 961px) { .agent-close { display: none; } }
</style>
