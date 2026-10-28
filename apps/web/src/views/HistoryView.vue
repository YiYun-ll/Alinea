<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { Activity, ArrowRight, FileClock, Files, History, LoaderCircle, RefreshCw, RotateCcw, X } from 'lucide-vue-next'
import { api } from '../lib/api'
import { errorMessage, formatDate } from '../lib/format'
import { useJobStore } from '../stores/job'
import { useToastStore } from '../stores/toast'
import { useProjectStore } from '../stores/project'
import type { AuditEvent, Job, Revision } from '../types/contracts'
import StatusBadge from '../components/StatusBadge.vue'
import ErrorNotice from '../components/ErrorNotice.vue'
import EmptyState from '../components/EmptyState.vue'
import ProgressBar from '../components/ProgressBar.vue'

const route = useRoute()
const projectId = String(route.params.id)
const jobs = useJobStore()
const project = useProjectStore()
const jobNames: Record<string, string> = { inspection: '文档检查', repair: '格式修复', rule_extraction: '规范提取' }
const activeTab = ref<'jobs' | 'revisions' | 'audit'>('jobs')
const revisions = ref<Revision[]>([])
const auditEvents = ref<AuditEvent[]>([])
const loading = ref(false)
const pendingJobId = ref<string | null>(null)
const jobsError = ref<string | null>(null)
const revisionsError = ref<string | null>(null)
const auditError = ref<string | null>(null)
const jobList = computed(() => Object.values(jobs.jobs).filter((job) => !job.project_id || job.project_id === projectId).sort((a, b) => (b.created_at ?? '').localeCompare(a.created_at ?? '')))

function jobProgressMessage(job: Job): string {
  return job.message ? errorMessage(job.message, '任务正在处理中。') : ''
}

function jobErrorMessage(job: Job): string {
  return errorMessage(job.error_message, '任务未完成，请查看状态后重试。')
}

async function loadHistory(): Promise<void> {
  loading.value = true
  jobsError.value = null
  revisionsError.value = null
  auditError.value = null
  await Promise.all([
    jobs.loadProjectJobs(projectId).catch((error: unknown) => { jobsError.value = errorMessage(error); return [] }),
    api.getProjectRevisions(projectId).then((response) => { revisions.value = response.data }).catch((error: unknown) => { revisionsError.value = errorMessage(error) }),
    api.getProjectAudit(projectId).then((response) => { auditEvents.value = response.data }).catch((error: unknown) => { auditError.value = errorMessage(error) }),
  ])
  loading.value = false
}

async function updateJob(job: Job, action: 'retry' | 'cancel'): Promise<void> {
  if (pendingJobId.value) return
  pendingJobId.value = job.job_id
  jobsError.value = null
  try {
    const updated = action === 'retry' ? await api.retryJob(projectId, job.job_id) : await api.cancelJob(projectId, job.job_id)
    jobs.jobs[updated.job_id] = updated
    if (!['SUCCEEDED', 'FAILED', 'CANCELLED'].includes(updated.status)) jobs.track(projectId, updated.job_id)
    useToastStore().push(action === 'retry' ? 'info' : 'success', action === 'retry' ? '已提交安全重试' : '任务已取消', action === 'retry' ? '沿用原始请求与批准约束，正在跟踪新任务。' : '排队任务已在执行前取消。')
    await loadHistory()
  } catch (error) {
    jobsError.value = errorMessage(error)
  } finally {
    pendingJobId.value = null
  }
}

onMounted(loadHistory)
</script>

<template>
  <div class="page-container history-page motion-page">
    <div class="page-heading">
      <div><h1>任务记录</h1></div>
      <button type="button" class="button button-secondary" :disabled="loading" @click="loadHistory"><RefreshCw :class="{ spinner: loading }" :size="16" aria-hidden="true" /> 刷新记录</button>
    </div>
    <nav class="history-tabs" aria-label="历史记录类别">
      <button type="button" :aria-pressed="activeTab === 'jobs'" @click="activeTab = 'jobs'"><Activity :size="16" aria-hidden="true" /> 任务 <span>{{ jobList.length }}</span></button>
      <button type="button" :aria-pressed="activeTab === 'revisions'" @click="activeTab = 'revisions'"><Files :size="16" aria-hidden="true" /> 版本 <span>{{ revisions.length }}</span></button>
      <button type="button" :aria-pressed="activeTab === 'audit'" @click="activeTab = 'audit'"><History :size="16" aria-hidden="true" /> 审计 <span>{{ auditEvents.length }}</span></button>
    </nav>

    <section v-if="activeTab === 'jobs'" class="panel history-panel" aria-labelledby="jobs-title">
      <div class="panel-header"><h2 id="jobs-title">后台任务</h2><FileClock :size="18" aria-hidden="true" /></div>
      <ErrorNotice v-if="jobsError" :message="jobsError" retry-label="重试" @retry="loadHistory" />
      <div v-if="jobList.length" class="table-scroll">
        <table class="data-table">
          <caption class="sr-only">任务进度与操作</caption>
          <thead><tr><th scope="col">任务 / 类型</th><th scope="col">阶段</th><th scope="col">状态 / 进度</th><th scope="col">时间</th><th scope="col">错误 / 结果 / 操作</th></tr></thead>
          <tbody>
            <tr v-for="job in jobList" :key="job.job_id">
              <td><strong>{{ jobNames[job.job_type ?? ''] ?? '后台任务' }}</strong><span class="history-subline mono" :title="job.job_id">{{ job.job_id.slice(0, 8) }}</span></td>
              <td>{{ job.stage ?? '未提供' }}<span class="history-subline">{{ jobProgressMessage(job) }}</span></td>
              <td><StatusBadge :status="job.status" /><ProgressBar class="history-progress" :value="job.progress ?? null" :label="`任务 ${job.job_id} 进度`" compact /></td>
              <td><span>{{ formatDate(job.created_at) }}</span><span class="history-subline">更新 {{ formatDate(job.updated_at ?? job.completed_at) }}</span></td>
              <td>
                <span v-if="job.error_code" class="error-code">{{ job.error_code }}</span>
                <span v-if="job.error_message" class="history-subline">{{ jobErrorMessage(job) }}</span>
                <span v-if="job.result_revision_id" class="mono history-subline">{{ job.result_revision_id }}</span>
                <div v-if="job.retryable || job.status === 'QUEUED'" class="job-actions">
                  <button v-if="job.retryable" type="button" class="button button-secondary button-small" :disabled="pendingJobId !== null" :aria-label="`重试任务 ${job.job_id}`" @click="updateJob(job, 'retry')"><RotateCcw :size="13" aria-hidden="true" /> 重试</button>
                  <button v-if="job.status === 'QUEUED'" type="button" class="button button-ghost button-small" :disabled="pendingJobId !== null" :aria-label="`取消任务 ${job.job_id}`" @click="updateJob(job, 'cancel')"><X :size="13" aria-hidden="true" /> 取消</button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <EmptyState v-else-if="!jobsError && !loading" title="没有任务记录" description="上传、规则提取、检查与修复任务出现后，会在这里显示真实状态。" />
    </section>

    <section v-else-if="activeTab === 'revisions'" class="panel history-panel" aria-labelledby="revisions-title">
      <div class="panel-header"><h2 id="revisions-title">文档修订版本</h2><Files :size="18" aria-hidden="true" /></div>
      <ErrorNotice v-if="revisionsError" :message="revisionsError" retry-label="重试" @retry="loadHistory" />
      <div v-if="revisions.length" class="table-scroll">
        <table class="data-table">
          <caption>原稿不可变，每个候选版本都有独立 ID 与父版本</caption>
          <thead><tr><th scope="col">Revision</th><th scope="col">父版本</th><th scope="col">状态</th><th scope="col">SHA-256</th><th scope="col">创建时间</th><th scope="col">操作</th></tr></thead>
          <tbody>
            <tr v-for="revision in revisions" :key="revision.revision_id">
              <td><strong class="mono">{{ revision.revision_id }}</strong><span class="history-subline">{{ revision.kind ?? revision.original_filename }}</span></td>
              <td class="mono">{{ revision.parent_revision_id ?? '原始版本' }}</td>
              <td><StatusBadge :status="revision.status ?? 'UNKNOWN'" /></td>
              <td class="mono">{{ revision.sha256 ?? '未提供' }}</td>
              <td>{{ formatDate(revision.created_at) }}</td>
              <td><RouterLink class="button button-secondary button-small" :to="revision.kind === 'ORIGINAL' ? `/projects/${projectId}/inspection` : `/projects/${projectId}/results/${revision.revision_id}`" @click="project.setActiveRevision(revision.revision_id)">查看 <ArrowRight :size="13" aria-hidden="true" /></RouterLink></td>
            </tr>
          </tbody>
        </table>
      </div>
      <EmptyState v-else-if="!revisionsError && !loading" title="没有版本记录" />
    </section>

    <section v-else class="panel history-panel" aria-labelledby="audit-title">
      <div class="panel-header"><h2 id="audit-title">审计事件</h2><History :size="18" aria-hidden="true" /></div>
      <ErrorNotice v-if="auditError" :message="auditError" retry-label="重试" @retry="loadHistory" />
      <div v-if="auditEvents.length" class="table-scroll">
        <table class="data-table">
          <caption>用户批准、任务执行与文件变更的审计记录</caption>
          <thead><tr><th scope="col">时间</th><th scope="col">事件</th><th scope="col">操作者</th><th scope="col">实体 / Job</th><th scope="col">详情</th></tr></thead>
          <tbody>
            <tr v-for="(event, index) in auditEvents" :key="event.id ?? event.audit_id ?? `${event.created_at}-${index}`">
              <td>{{ formatDate(event.created_at) }}</td>
              <td><strong>{{ event.action ?? event.event_type ?? '未命名事件' }}</strong></td>
              <td>{{ event.actor_type ?? event.actor ?? '未提供' }}</td>
              <td><span class="mono">{{ event.entity_id ?? '—' }}</span><span class="history-subline mono">{{ event.job_id }}</span></td>
              <td><details><summary class="text-link">详情</summary><pre class="audit-details">{{ JSON.stringify(event.details ?? event.details_json ?? {}, null, 2) }}</pre></details></td>
            </tr>
          </tbody>
        </table>
      </div>
      <EmptyState v-else-if="!auditError && !loading" title="没有审计事件" />
    </section>

    <p v-if="loading" class="loading"><LoaderCircle class="spinner" :size="17" aria-hidden="true" /> 正在刷新服务端记录…</p>
  </div>
</template>

<style scoped>
.history-page { max-width: 1360px; }
.history-tabs { display: flex; gap: 4px; margin-bottom: 16px; padding: 4px; background: #e9edf2; border-radius: 8px; width: fit-content; }
.history-tabs button { display: inline-flex; align-items: center; gap: 7px; min-height: 40px; padding: 8px 16px; color: #667467; background: transparent; border: 0; border-radius: 6px; }
.history-tabs button[aria-pressed='true'] { color: #25352e; background: #fff; box-shadow: 0 1px 3px rgba(39, 52, 73, .14); font-weight: 700; }
.history-tabs button span { padding: 1px 6px; background: #e5e9ef; border-radius: 999px; font-size: .68rem; }
.history-panel { min-height: 360px; }
.history-panel > .notice { margin: 16px; }
.history-panel .table-scroll { max-height: 64dvh; }
.history-subline { display: block; margin-top: 4px; color: #737c73; font-size: .68rem; overflow-wrap: anywhere; }
.history-progress { min-width: 120px; margin-top: 10px; }
.job-actions { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 10px; }
.error-code { display: inline-block; padding: 2px 5px; color: #9e3636; background: #fff1f1; border: 1px solid #ddb0b0; border-radius: 3px; font-family: ui-monospace, monospace; font-size: .68rem; }
.audit-details { max-width: 400px; max-height: 150px; margin: 0; overflow: auto; font-size: .68rem; white-space: pre-wrap; }
.history-note { color: #737c73; font-size: .72rem; }
@media (max-width: 600px) { .history-tabs { width: 100%; } .history-tabs button { flex: 1; justify-content: center; padding-inline: 7px; } }
</style>
