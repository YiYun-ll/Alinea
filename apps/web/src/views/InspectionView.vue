<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ArrowRight, CheckCircle2, CircleAlert, ClipboardCheck, LoaderCircle, RefreshCw, ShieldAlert } from 'lucide-vue-next'
import { useProjectStore } from '../stores/project'
import { useRulesStore } from '../stores/rules'
import { useInspectionStore } from '../stores/inspection'
import { usePreviewStore } from '../stores/preview'
import { useRepairStore } from '../stores/repair'
import { useJobStore } from '../stores/job'
import { useToastStore } from '../stores/toast'
import { errorMessage, isRenderInfo } from '../lib/format'
import IssueListPanel from '../components/IssueListPanel.vue'
import IssueDetailPanel from '../components/IssueDetailPanel.vue'
import PdfDocumentViewer from '../components/PdfDocumentViewer.vue'
import InspectionSetupPanel from '../components/InspectionSetupPanel.vue'
import ErrorNotice from '../components/ErrorNotice.vue'
import EmptyState from '../components/EmptyState.vue'
import DisclosurePanel from '../components/DisclosurePanel.vue'
import ProgressBar from '../components/ProgressBar.vue'
import type { Issue, Revision } from '../types/contracts'

const route = useRoute()
const router = useRouter()
const projectId = String(route.params.id)
const project = useProjectStore()
const rules = useRulesStore()
const inspection = useInspectionStore()
const preview = usePreviewStore()
const repair = useRepairStore()
const jobs = useJobStore()
const mobilePane = ref<'issues' | 'document' | 'detail'>('issues')
const localError = ref<string | null>(null)
const loadedJobId = ref<string | null>(null)
const showRenderDetails = ref(false)
const inspectionJob = computed(() => inspection.jobId ? jobs.jobs[inspection.jobId] : null)
const inspectionMessage = computed(() => {
  const current = inspectionJob.value
  if (current?.error_message) return errorMessage(current.error_message, '检查未完成，请重试。')
  if (current?.message) return errorMessage(current.message, '检查任务正在处理中。')
  return '正在检查文档并生成预览…'
})
const revisionId = computed(() => project.activeRevisionId)
const showStart = computed(() => !inspection.result && !inspection.jobId && !inspection.loading)
const isOutdated = computed(() => Boolean(inspection.result && (rules.hasUnsavedChanges || (rules.ruleSet && inspection.result.rule_set_digest !== rules.ruleSet.digest))))
const generalWarnings = computed(() => inspection.result?.warnings.filter((warning) => !isRenderInfo(warning)) ?? [])
const renderDetails = computed(() => inspection.result?.warnings.filter(isRenderInfo).sort((a, b) => Number(b.startsWith('Render environment:')) - Number(a.startsWith('Render environment:'))) ?? [])

function storageKey(revision: string): string {
  return `alinea:inspection:${projectId}:${revision}`
}

function revisionLabel(revision: Revision, index: number): string {
  if (index === 0 && revision.kind === 'ORIGINAL') return '原稿'
  return `${revision.kind === 'ORIGINAL' ? '原稿' : '修订版'} ${index + 1}`
}

async function loadExisting(id: string, revision: string): Promise<void> {
  localError.value = null
  try {
    await inspection.load(projectId, id, revision)
    localStorage.setItem(storageKey(revision), id)
    if (!preview.pdfData || preview.revisionId !== revision) await preview.load(projectId, revision)
  } catch (error) {
    localError.value = errorMessage(error, '检查结果恢复失败，请重试。')
  }
}

onMounted(async () => {
  if (!rules.ruleSet) await rules.load(projectId)
  if (inspection.result && inspection.result.revision_id === revisionId.value && revisionId.value) {
    if (!preview.pdfData || preview.revisionId !== revisionId.value) await preview.load(projectId, revisionId.value)
    return
  }
  if (inspection.result) inspection.reset()
  if (revisionId.value) {
    const saved = localStorage.getItem(storageKey(revisionId.value))
    if (saved) {
      try {
        const history = await jobs.loadProjectJobs(projectId)
        const job = history.filter((job) => job.inspection_id === saved && job.job_type === 'inspection')
          .sort((a, b) => (a.created_at ?? '').localeCompare(b.created_at ?? '')).at(-1)
        if (job && job.status !== 'SUCCEEDED') {
          inspection.inspectionId = saved
          inspection.jobId = job.job_id
          if (['QUEUED', 'RUNNING'].includes(job.status)) jobs.track(projectId, job.job_id)
          return
        }
      } catch {
        // Existing completed results can still load if optional job history fails.
      }
      await loadExisting(saved, revisionId.value)
    }
  }
})

watch(() => inspectionJob.value?.status, async (status) => {
  const jobId = inspection.jobId
  const inspectionId = inspection.inspectionId
  if (status === 'SUCCEEDED' && jobId && inspectionId && loadedJobId.value !== jobId && revisionId.value) {
    loadedJobId.value = jobId
    await loadExisting(inspectionId, revisionId.value)
  }
})

watch(revisionId, async (revision, previous) => {
  if (!revision || revision === previous) return
  inspection.reset()
  repair.reset()
  preview.clear()
  loadedJobId.value = null
  const saved = localStorage.getItem(storageKey(revision))
  if (saved) await loadExisting(saved, revision)
})

async function startInspection(): Promise<void> {
  localError.value = null
  const revision = revisionId.value
  const ruleSet = rules.ruleSet
  if (!revision || !ruleSet || !rules.isApproved || rules.hasUnsavedChanges) {
    localError.value = '请先保存并批准当前规范，再开始检查。'
    return
  }
  if (inspection.starting) return
  try {
    const accepted = await inspection.start(projectId, revision, ruleSet)
    localStorage.setItem(storageKey(revision), accepted.inspection_id)
    if (accepted.status === 'SUCCEEDED') {
      loadedJobId.value = accepted.job_id
      await loadExisting(accepted.inspection_id, revision)
      if (accepted.reused) useToastStore().push('info', '已恢复相同检查', '文档和规范未变化，无需重复渲染。')
      return
    }
    if (inspection.jobId) jobs.track(projectId, inspection.jobId)
    if (accepted.reused) useToastStore().push('info', '继续已有检查', '已恢复此前的任务状态，不会重复执行。')
  } catch (error) {
    localError.value = errorMessage(error, '无法开始检查，请重试。')
  }
}

async function retryInspection(): Promise<void> {
  const inspectionId = inspection.inspectionId
  const revision = revisionId.value
  if (!inspectionJob.value?.retryable || !inspectionId || !revision) return
  localError.value = null
  try {
    const retried = await inspection.retry(projectId)
    jobs.jobs[retried.job_id] = retried
    loadedJobId.value = null
    if (retried.status === 'SUCCEEDED') await loadExisting(inspectionId, revision)
    else jobs.track(projectId, retried.job_id)
    useToastStore().push('info', '已提交安全重试', '原始文档、规范和检查绑定保持不变。')
  } catch (error) {
    localError.value = errorMessage(error, '检查重试失败，请稍后重试。')
  }
}

async function refreshInspection(): Promise<void> {
  if (!inspection.inspectionId || !revisionId.value || isOutdated.value) return
  await loadExisting(inspection.inspectionId, revisionId.value)
  if (!localError.value) useToastStore().push('success', '检查结果已刷新', '已保留当前选择。')
}

function beginNewInspection(): void {
  inspection.reset()
  repair.reset()
  preview.clear()
  loadedJobId.value = null
  localError.value = null
  mobilePane.value = 'document'
}

function focusIssue(issue: Issue): void {
  inspection.focusIssue(issue.issue_id)
  mobilePane.value = issue.location.status === 'LOCATED' ? 'document' : 'detail'
  if (issue.location.status === 'LOCATED') locateIssue(issue)
}

function locateIssue(issue: Issue): void {
  const fragment = issue.location.status === 'LOCATED' ? issue.location.fragments[0] : null
  if (fragment) {
    preview.page = fragment.page_index + 1
    mobilePane.value = 'document'
  }
}

function selectOverlay(issueId: string): void {
  inspection.focusIssue(issueId)
  mobilePane.value = 'detail'
}

async function createPlan(): Promise<void> {
  localError.value = null
  if (repair.creating) return
  if (isOutdated.value) {
    localError.value = '当前规范已变化，请先用新规范完成检查，再创建修复计划。'
    return
  }
  try {
    await repair.createPlan(projectId)
    await router.push(`/projects/${projectId}/repairs`)
  } catch (error) {
    localError.value = errorMessage(error, '修复计划创建失败，请重试。')
  }
}
</script>

<template>
  <div class="inspection-page motion-page" :class="{ 'has-mobile-action': inspection.result && inspection.selectedCount > 0 }">
    <header class="inspection-heading">
      <div><h1>{{ inspection.result ? '检查结果' : '文档检查' }}</h1></div>
      <div class="inspection-actions">
        <RouterLink class="rules-chip" :to="`/projects/${projectId}/rules`" :title="rules.ruleSet?.name"><ClipboardCheck :size="15" aria-hidden="true" /> {{ rules.ruleSet?.name ?? '规范未加载' }} <span>v{{ rules.ruleSet?.version ?? '—' }}</span></RouterLink>
        <label v-if="project.revisions().length > 1" class="revision-select"><span>版本</span><select class="field" aria-label="当前文档版本" :value="project.activeRevisionId" @change="project.setActiveRevision(($event.target as HTMLSelectElement).value)"><option v-for="(revision, index) in project.revisions()" :key="revision.revision_id" :value="revision.revision_id">{{ revisionLabel(revision, index) }}</option></select></label>
        <span v-if="isOutdated" class="status status-warn">规范已更新</span>
        <button v-if="inspection.result" type="button" class="button button-secondary button-small" :disabled="inspection.loading || isOutdated" @click="refreshInspection"><RefreshCw :size="14" aria-hidden="true" /> 刷新结果</button>
      </div>
    </header>
    <ErrorNotice v-if="inspection.error || preview.error || localError" :message="localError ?? inspection.error ?? preview.error ?? ''" />
    <div v-if="isOutdated" class="notice notice-warn"><ShieldAlert :size="18" aria-hidden="true" /><p>当前显示旧规范版本的结果，仅供查阅。请使用当前规范重新检查后再创建修复计划。</p><button type="button" class="button button-secondary button-small" @click="beginNewInspection">使用当前规范重新检查</button></div>

    <Transition name="view-panel">
      <InspectionSetupPanel v-if="showStart" :project-id="projectId" @start="startInspection" />
    </Transition>

    <div v-if="inspectionJob && !inspection.result" class="job-banner motion-fade" :class="{ 'is-error': inspectionJob.status === 'FAILED' }" role="status">
      <CircleAlert v-if="['FAILED', 'CANCELLED'].includes(inspectionJob.status)" :size="20" aria-hidden="true" />
      <LoaderCircle v-else class="spinner" :size="19" aria-hidden="true" />
      <div class="job-banner-content">
        <strong v-if="inspectionJob.status === 'FAILED'">检查未完成</strong>
        <strong v-else-if="inspectionJob.status === 'CANCELLED'">检查已取消，可重新提交</strong>
        <ProgressBar :value="inspectionJob.progress" label="检查进度" :message="inspectionMessage" />
      </div>
      <button v-if="inspectionJob.status === 'FAILED' && inspectionJob.retryable" type="button" class="button button-secondary button-small" :disabled="inspection.starting" @click="retryInspection">安全重试</button>
      <button v-else-if="inspectionJob.status === 'CANCELLED'" type="button" class="button button-secondary button-small" :disabled="inspection.starting" @click="startInspection">重新提交检查</button>
    </div>

    <template v-if="inspection.result">
      <div class="inspection-metrics metric-grid motion-stagger" aria-label="检查统计">
        <div class="metric"><span class="metric-value">{{ inspection.summary?.violations ?? 0 }}</span><span class="metric-label">明确违规</span></div>
        <div class="metric"><span class="metric-value">{{ inspection.summary?.unverifiable ?? 0 }}</span><span class="metric-label">无法验证</span></div>
        <div class="metric"><span class="metric-value">{{ inspection.summary?.fixable ?? 0 }}</span><span class="metric-label">可定向修复</span></div>
        <div class="metric"><span class="metric-value">{{ inspection.summary?.located ?? 0 }}</span><span class="metric-label">可信页面定位</span></div>
      </div>
      <div v-if="generalWarnings.length" class="notice notice-warn">
        <ShieldAlert :size="18" aria-hidden="true" />
        <div>
          <strong>检查警告</strong>
          <p v-for="warning in generalWarnings" :key="warning">{{ warning }}</p>
        </div>
      </div>
      <div v-if="renderDetails.length" class="render-disclosure">
        <DisclosurePanel v-if="renderDetails.length" title="渲染环境详情" :open="showRenderDetails" @toggle="showRenderDetails = !showRenderDetails">
          <p v-for="warning in renderDetails" :key="warning" class="warning-detail">{{ warning }}</p>
        </DisclosurePanel>
      </div>
      <nav class="mobile-workspace-nav" aria-label="检查台窗格">
        <button type="button" :aria-pressed="mobilePane === 'issues'" @click="mobilePane = 'issues'">问题（{{ inspection.filteredIssues.length }}）</button>
        <button type="button" :aria-pressed="mobilePane === 'document'" @click="mobilePane = 'document'">文档</button>
        <button type="button" :aria-pressed="mobilePane === 'detail'" @click="mobilePane = 'detail'">详情</button>
      </nav>
      <div class="inspection-workspace">
        <aside class="workspace-pane issues-pane" :class="{ 'is-active': mobilePane === 'issues' }" aria-label="问题列表"><IssueListPanel @focus="focusIssue" @plan="createPlan" /></aside>
        <section class="workspace-pane document-pane" :class="{ 'is-active': mobilePane === 'document' }" aria-label="文档预览">
          <PdfDocumentViewer
            v-model:page="preview.page" v-model:scale="preview.scale" v-model:rotation="preview.rotation"
            :data="preview.pdfData" :revision-id="inspection.result.revision_id" :issues="inspection.issues"
            :preview-sha256="inspection.result.preview?.pdf_sha256" :focused-issue-id="inspection.focusedIssueId"
            @select-issue="selectOverlay"
          />
        </section>
        <aside class="workspace-pane detail-pane" :class="{ 'is-active': mobilePane === 'detail' }" aria-label="问题证据详情"><IssueDetailPanel @locate="locateIssue" @plan="createPlan" /></aside>
      </div>
      <div v-if="!inspection.issues.length" class="inspection-empty"><CheckCircle2 :size="20" aria-hidden="true" /><span>本次检查未返回 Issue。请结合无法验证项与复检报告判断，不将“无问题”解释为所有场景绝对合规。</span><RouterLink :to="`/projects/${projectId}/results/${inspection.result.revision_id}`" class="button button-secondary button-small">查看报告 <ArrowRight :size="14" aria-hidden="true" /></RouterLink></div>
      <div v-if="inspection.selectedCount" class="mobile-plan-bar">
        <span><strong>已选 {{ inspection.selectedCount }} 项</strong></span>
        <button type="button" class="button button-primary" :disabled="repair.creating" @click="createPlan">{{ repair.creating ? '正在生成…' : '生成修复计划' }}<ArrowRight :size="16" aria-hidden="true" /></button>
      </div>
    </template>
    <EmptyState v-if="inspection.loading && !inspection.result" title="正在读取检查结果" />
  </div>
</template>

<style scoped>
.inspection-page { padding: 20px clamp(12px, 2vw, 28px) 28px; }
.inspection-heading { display: flex; align-items: flex-end; justify-content: space-between; gap: 20px; margin-bottom: 18px; }
.inspection-heading h1 { margin: 0; font-size: clamp(1.7rem, 1.4rem + 1vw, 2.25rem); }
.inspection-heading .eyebrow { margin-bottom: 5px; }
.inspection-heading p:not(.eyebrow) { margin: 6px 0 0; color: #737c73; font-size: .8rem; }
.inspection-actions { display: flex; align-items: center; justify-content: flex-end; flex-wrap: wrap; gap: 8px; }
.rules-chip { display: inline-flex; align-items: center; gap: 6px; max-width: 300px; padding: 7px 10px; overflow: hidden; background: #fff; border: 1px solid #dfe3dc; border-radius: 6px; font-size: .75rem; text-decoration: none; text-overflow: ellipsis; white-space: nowrap; }
.rules-chip span { flex-shrink: 0; color: #737c73; }
.revision-select { display: flex; align-items: center; gap: 6px; font-size: .72rem; }
.revision-select .field { width: 130px; min-height: 34px; padding: 4px 7px; }
.job-banner { display: flex; align-items: center; gap: 12px; padding: 14px 18px; margin-bottom: 18px; color: #456653; background: #f0f4ee; border: 1px solid #bdc9dd; border-radius: 8px; }
.job-banner > svg { flex-shrink: 0; }
.job-banner-content { flex: 1; min-width: 0; }
.job-banner-content > strong { display: block; margin-bottom: 7px; }
.job-banner > .button { flex-shrink: 0; }
.job-banner.is-error { color: #9e3636; background: #fff5f5; border-color: #ddb0b0; }
.inspection-metrics { margin-bottom: 14px; }
.inspection-workspace { height: max(640px, calc(100dvh - 300px)); display: grid; grid-template-columns: 280px minmax(0, 1fr) 320px; overflow: hidden; background: #fff; border: 1px solid #d9e0d6; border-radius: 8px; }
.workspace-pane { min-width: 0; min-height: 0; }
.issues-pane { border-right: 1px solid #dfe3dc; }
.document-pane { background: #edf0e9; }
.detail-pane { border-left: 1px solid #dfe3dc; }
.inspection-empty { display: flex; align-items: center; gap: 10px; padding: 16px; margin-top: 16px; color: #1d6c55; background: #f0f8f4; border: 1px solid #a7cec0; border-radius: 8px; }
.inspection-empty > span { flex: 1; }
.mobile-plan-bar { display: none; }
@keyframes pane-enter { from { opacity: 0; translate: 10px 0; } to { opacity: 1; translate: 0 0; } }
@media (max-width: 1100px) { .inspection-heading { align-items: flex-start; flex-direction: column; } .inspection-actions { justify-content: flex-start; } }
@media (max-width: 900px) {
  .inspection-page { padding-inline: 0; }
  .inspection-heading, .inspection-metrics, .inspection-page > .notice, .job-banner { margin-inline: 12px; }
  .inspection-workspace { height: 68dvh; min-height: 520px; grid-template-columns: 1fr; border-inline: 0; border-radius: 0; }
  .workspace-pane { display: none; }
  .workspace-pane.is-active { display: flex; animation: pane-enter var(--motion-base) var(--motion-ease-out) both; }
  .issues-pane, .detail-pane { border: 0; }
  .inspection-page.has-mobile-action { padding-bottom: 112px; }
  .mobile-plan-bar { position: fixed; inset-inline: 12px; inset-block-end: calc(12px + env(safe-area-inset-bottom)); z-index: 45; display: flex; align-items: center; justify-content: space-between; gap: 14px; max-width: 580px; padding: 12px 14px; margin-inline: auto; background: rgba(255, 255, 255, .97); border: 1px solid #cfd7e2; border-radius: 12px; box-shadow: 0 14px 40px rgba(39, 52, 73, .15); backdrop-filter: blur(14px); animation: motion-fade-up var(--motion-base) var(--motion-ease-out) both; }
  .mobile-plan-bar > span { min-width: 0; }
  .mobile-plan-bar strong, .mobile-plan-bar small { display: block; }
  .mobile-plan-bar small { margin-top: 3px; color: #737c73; font-size: .66rem; }
  .mobile-plan-bar .button { flex-shrink: 0; min-height: 46px; }
}
@media (max-width: 600px) { .job-banner { align-items: flex-start; flex-wrap: wrap; } .job-banner > .button { margin-left: 32px; } }
@media (prefers-reduced-motion: reduce) { .workspace-pane.is-active, .mobile-plan-bar { animation: none; } }
</style>
