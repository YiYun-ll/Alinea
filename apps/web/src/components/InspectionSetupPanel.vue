<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { ArrowRight, BookOpenCheck, FileText, ShieldCheck } from 'lucide-vue-next'
import { useProjectStore } from '../stores/project'
import { useRulesStore } from '../stores/rules'
import { useInspectionStore } from '../stores/inspection'
import { useJobStore } from '../stores/job'
import { errorMessage } from '../lib/format'
import ConfirmDialog from './ConfirmDialog.vue'
import ErrorNotice from './ErrorNotice.vue'
import ProgressBar from './ProgressBar.vue'

const props = defineProps<{ projectId: string }>()
const emit = defineEmits<{ start: [] }>()
const project = useProjectStore()
const rules = useRulesStore()
const inspection = useInspectionStore()
const jobs = useJobStore()
const approveDialog = ref<InstanceType<typeof ConfirmDialog> | null>(null)
const localError = ref<string | null>(null)
const submitting = ref(false)
const extractionJob = computed(() => rules.extractionJobId ? jobs.jobs[rules.extractionJobId] : null)
const extractionMessage = computed(() => extractionJob.value?.message
  ? errorMessage(extractionJob.value.message, '规范提取任务正在处理中。')
  : '正在读取规范提取任务。')
const preparing = computed(() => !rules.ruleSet && (rules.loading || ['QUEUED', 'RUNNING'].includes(extractionJob.value?.status ?? '')))
const needsApproval = computed(() => !rules.isApproved || rules.hasUnsavedChanges)
const enabledCount = computed(() => rules.draftRules.filter((rule) => rule.enabled).length)
const visibleError = computed(() => localError.value || (!preparing.value ? rules.error : null))
const canStart = computed(() => Boolean(project.activeRevisionId && rules.ruleSet && enabledCount.value && !preparing.value && !inspection.starting && !rules.approving && !submitting.value))

onMounted(async () => {
  try {
    await jobs.loadProjectJobs(props.projectId)
    if (!rules.extractionJobId) {
      const extraction = Object.values(jobs.jobs)
        .filter((job) => job.job_type === 'rule_extraction')
        .sort((a, b) => (a.created_at ?? '').localeCompare(b.created_at ?? ''))
        .at(-1)
      if (extraction) rules.extractionJobId = extraction.job_id
    }
    const job = extractionJob.value
    if (job && ['QUEUED', 'RUNNING'].includes(job.status)) jobs.track(props.projectId, job.job_id)
    if (job?.status === 'SUCCEEDED' && !rules.ruleSet && !rules.loading) await rules.load(props.projectId)
  } catch (error) {
    localError.value = errorMessage(error)
  }
})

watch(() => extractionJob.value?.status, async (status) => {
  if (status === 'SUCCEEDED') {
    localError.value = null
    const loaded = await rules.load(props.projectId)
    if (!loaded) localError.value = '规范已生成，但读取失败，请重试。'
  } else if (status === 'FAILED') {
    localError.value = errorMessage(extractionJob.value?.error_message, '规范提取失败，请检查来源后重试。')
  }
})

function requestStart(): void {
  localError.value = null
  if (needsApproval.value) approveDialog.value?.open()
  else emit('start')
}

async function approveAndStart(): Promise<void> {
  if (submitting.value) return
  submitting.value = true
  localError.value = null
  try {
    if (rules.hasUnsavedChanges) {
      const saved = await rules.save(props.projectId)
      if (!saved) throw new Error('规范保存失败，请检查来源和冲突后再试。')
    }
    await rules.approve(props.projectId)
    await approveDialog.value?.close()
    emit('start')
  } catch (error) {
    localError.value = errorMessage(error)
    await approveDialog.value?.close()
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <section class="inspection-setup" aria-labelledby="setup-title">
    <div class="setup-intro">
      <h2 id="setup-title">确认本次检查</h2>
      <p>核对文档与规范，即可开始。</p>
      <RouterLink class="button button-ghost button-small" :to="`/projects/${projectId}/rules`">查看或编辑完整规则 <ArrowRight :size="14" aria-hidden="true" /></RouterLink>
    </div>
    <div class="setup-action">
      <div v-if="preparing" class="setup-preparing" role="status">
        <strong>正在准备规范</strong>
        <p>规则生成后，仍需你确认再开始检查。</p>
        <ProgressBar :value="extractionJob?.progress ?? null" label="规范提取进度" :message="extractionMessage" />
      </div>
      <template v-else>
        <dl class="setup-facts">
          <div><dt><FileText :size="15" aria-hidden="true" /> 文档</dt><dd>{{ project.project?.name ?? '正在恢复' }}</dd></div>
          <div><dt><BookOpenCheck :size="15" aria-hidden="true" /> 规范</dt><dd>{{ rules.ruleSet?.name ?? '尚未生成' }}<span v-if="rules.ruleSet"> · v{{ rules.ruleSet.version }}</span></dd></div>
          <div><dt><ShieldCheck :size="15" aria-hidden="true" /> 规则</dt><dd>{{ enabledCount }} 项启用 <span class="setup-status" :class="{ approved: rules.isApproved && !needsApproval }">{{ needsApproval ? '待确认' : '已批准' }}</span></dd></div>
        </dl>
        <ErrorNotice v-if="visibleError" :message="visibleError ?? ''" retry-label="重新读取规范" @retry="rules.load(projectId)" />

        <button type="button" class="button button-primary setup-start" :disabled="!canStart" @click="requestStart">{{ needsApproval ? '批准规范并开始检查' : '开始检查' }}<ArrowRight :size="17" aria-hidden="true" /></button>
      </template>
    </div>
    <ConfirmDialog ref="approveDialog" title="批准规范并开始检查？" confirm-label="批准并检查" :busy="submitting" description="将批准当前规范版本并立即开始检查，不会修改原稿。修复计划和执行仍需你单独批准。" @confirm="approveAndStart">
      <p class="small">规范：{{ rules.ruleSet?.name }} · v{{ rules.ruleSet?.version }} · {{ enabledCount }} 项启用</p>
    </ConfirmDialog>
  </section>
</template>

<style scoped>
.inspection-setup { display: grid; grid-template-columns: minmax(0, 1.1fr) minmax(300px, .9fr); margin: clamp(20px, 4vw, 48px) auto; max-width: 1100px; overflow: hidden; background: #fff; border: 1px solid #d9e0d6; border-radius: 12px;  }
.setup-intro { padding: clamp(26px, 4vw, 44px); background: #f4f6f0; border-right: 1px solid #dfe3dc; }
.setup-intro h2 { margin-bottom: 14px; font-size: clamp(1.7rem, 1.4rem + 1vw, 2.35rem); }
.setup-intro > p { max-width: 34ch; color: #6b756d; line-height: 1.8; }
.setup-source { display: flex; align-items: flex-start; gap: 8px; margin: 26px 0 14px; color: #456653; font-size: .75rem; line-height: 1.65; }
.setup-source svg { flex-shrink: 0; margin-top: 3px; }
.setup-action { align-self: center; padding: clamp(24px, 3.5vw, 38px); }
.setup-facts { display: grid; gap: 18px; margin: 0 0 22px; }
.setup-facts dt { display: flex; align-items: center; gap: 6px; margin-bottom: 4px; color: #737c73; font-size: .72rem; }
.setup-facts dd { margin: 0; color: #25352e; font-size: .875rem; overflow-wrap: anywhere; }
.setup-status { display: inline-block; margin-left: 6px; padding: 1px 6px; color: #76501c; background: #fff7e9; border-radius: 4px; font-size: .7rem; }
.setup-status.approved { color: #1d6c55; background: #edf7f2; }
.setup-consent { display: flex; align-items: flex-start; gap: 7px; margin-bottom: 20px; color: #667467; }
.setup-consent svg { flex-shrink: 0; margin-top: 3px; color: #278267; }
.setup-consent p { margin: 0; font-size: .75rem; line-height: 1.7; }
.setup-start { width: 100%; min-height: 48px; }
.setup-preparing > p { color: #737c73; font-size: .8rem; }
.setup-preparing .job-progress { margin-top: 20px; }
@media (max-width: 800px) {
  .inspection-setup { grid-template-columns: 1fr; margin: 16px 12px 28px; }
  .setup-intro { padding: 24px; border-right: 0; border-bottom: 1px solid #dfe3dc; }
  .setup-intro > p { max-width: none; }
  .setup-source { margin-top: 18px; }
}
</style>
