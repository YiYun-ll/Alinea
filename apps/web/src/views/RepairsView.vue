<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { ArrowLeft, ArrowRight, Check, CircleAlert, FileCheck2, LoaderCircle, LockKeyhole, Play, ShieldCheck } from 'lucide-vue-next'
import { useProjectStore } from '../stores/project'
import { useRepairStore } from '../stores/repair'
import { useJobStore } from '../stores/job'
import { errorMessage, formatDate, formatValue, propertyLabel } from '../lib/format'
import StatusBadge from '../components/StatusBadge.vue'
import ErrorNotice from '../components/ErrorNotice.vue'
import EmptyState from '../components/EmptyState.vue'
import ConfirmDialog from '../components/ConfirmDialog.vue'
import DisclosurePanel from '../components/DisclosurePanel.vue'
import ProgressBar from '../components/ProgressBar.vue'
import { useToastStore } from '../stores/toast'

const route = useRoute()
const projectId = String(route.params.id)
const project = useProjectStore()
const repair = useRepairStore()
const jobs = useJobStore()
const approveDialog = ref<InstanceType<typeof ConfirmDialog> | null>(null)
const executeDialog = ref<InstanceType<typeof ConfirmDialog> | null>(null)
const localError = ref<string | null>(null)
const showTechnical = ref(false)
const showOperations = ref(false)
const plan = computed(() => repair.plan)
const job = computed(() => repair.jobId ? jobs.jobs[repair.jobId] : null)
const resultRevisionId = computed(() => plan.value?.result_revision_id ?? job.value?.result_revision_id ?? job.value?.result?.result_revision_id ?? job.value?.result?.revision_id ?? null)
const canExecute = computed(() => plan.value?.status === 'APPROVED' && Boolean(plan.value.approved_at) && !repair.executing)
const previewOperations = computed(() => plan.value?.operations ?? [])
const visibleError = computed(() => localError.value ?? repair.error ?? (job.value?.error_message ? errorMessage(job.value.error_message, '修复任务未完成，请重试。') : null))
const executionMessage = computed(() => {
  if (job.value?.error_message) return errorMessage(job.value.error_message, '修复任务未完成，请重试。')
  if (job.value?.message) return errorMessage(job.value.message, '修复任务正在处理中。')
  return '正在修复并核验文档…'
})
const needsRebuild = computed(() => ['STALE', 'FAILED'].includes(plan.value?.status ?? '') || job.value?.status === 'FAILED')
const completedJobId = ref<string | null>(null)
onMounted(() => repair.restore(projectId))

watch(() => [job.value?.job_id, job.value?.status] as const, async ([jobId, status]) => {
  if (status !== 'SUCCEEDED' || !jobId || completedJobId.value === jobId) return
  completedJobId.value = jobId
  try {
    if (resultRevisionId.value && plan.value) plan.value.result_revision_id = resultRevisionId.value
    else {
      await project.load(projectId)
      const candidate = project.revisions().find((revision) => revision.parent_revision_id === plan.value?.base_revision_id && revision.revision_id !== plan.value?.base_revision_id)
      if (candidate && plan.value) plan.value.result_revision_id = candidate.revision_id
    }
    if (plan.value) plan.value.status = 'SUCCEEDED'
    if (resultRevisionId.value) useToastStore().push('success', '修复与复检已完成', '可查看报告并下载修订版。')
    else localError.value = '修复任务已完成，但未找到候选修订版，请在任务记录中核对。'
  } catch (error) {
    localError.value = errorMessage(error, '修复已完成，但候选版本信息读取失败，请刷新重试。')
  }
}, { immediate: true })

async function approve(): Promise<void> {
  localError.value = null
  try {
    await repair.approve(projectId)
  } catch (error) {
    localError.value = errorMessage(error, '计划批准失败，请重试。')
  } finally {
    await approveDialog.value?.close()
  }
}

async function execute(): Promise<void> {
  localError.value = null
  try {
    await repair.execute(projectId)
  } catch (error) {
    localError.value = errorMessage(error, '修复执行请求失败，请重试。')
  } finally {
    await executeDialog.value?.close()
  }
}
</script>

<template>
  <div class="page-container repairs-page motion-page">
    <div class="page-heading">
      <div><h1>审阅修改</h1></div>
      <StatusBadge v-if="plan" :status="plan.status" />
    </div>
    <ErrorNotice v-if="visibleError" :message="visibleError" :retry-label="!plan ? '重新加载' : undefined" @retry="repair.restore(projectId)" />

    <EmptyState v-if="repair.restoring" title="正在读取修复计划" />
    <EmptyState v-else-if="!plan" title="先选择要修复的问题" description="返回检查结果，勾选问题并生成修复计划。">
      <RouterLink class="button button-primary" :to="`/projects/${projectId}/inspection`"><ArrowLeft :size="16" aria-hidden="true" /> 返回检查与选择</RouterLink>
    </EmptyState>

    <template v-else>
      <div v-if="needsRebuild" class="notice notice-error">
        <CircleAlert :size="20" aria-hidden="true" />
        <p>{{ plan.status === 'STALE' ? '计划已失效。原文、检查或规则摘要可能已变化，请重新检查并创建计划。' : '本次修复未完成。旧计划不会继续执行，请返回检查核对问题后重建计划。' }}</p>
        <RouterLink class="button button-secondary button-small" :to="`/projects/${projectId}/inspection`"><ArrowLeft :size="15" aria-hidden="true" /> 返回检查并重建计划</RouterLink>
      </div>
      <section class="plan-summary panel" aria-labelledby="plan-summary-title">
        <div class="plan-summary-heading"><h2 id="plan-summary-title">{{ plan.selected_issue_ids.length }} 项格式调整</h2></div>
        <div class="plan-assurances"><span><FileCheck2 :size="14" aria-hidden="true" /> 规范 v{{ plan.rule_set_version }}</span><span>{{ plan.affected_node_count }} 个影响节点</span></div>
        <DisclosurePanel title="版本与审批记录" :open="showTechnical" @toggle="showTechnical = !showTechnical">
          <dl class="definition-list">
            <dt>计划标识</dt><dd class="mono">{{ plan.plan_id }}</dd>
            <dt>原稿版本</dt><dd class="mono">{{ plan.base_revision_id }}</dd>
            <dt>检查标识</dt><dd class="mono">{{ plan.inspection_id }}</dd>
            <dt>规则版本</dt><dd>{{ plan.rule_set_id }} · v{{ plan.rule_set_version }}</dd>
            <dt>计划 digest</dt><dd class="mono">{{ plan.plan_digest }}</dd>
            <dt>批准时间</dt><dd>{{ formatDate(plan.approved_at) }}</dd>
          </dl>
        </DisclosurePanel>
      </section>

      <section class="panel operations-panel" aria-labelledby="operations-title">
        <div class="panel-header"><h2 id="operations-title">将要做出的修改</h2><FileCheck2 :size="18" aria-hidden="true" /></div>
        <ol v-if="previewOperations.length" class="operation-list motion-stagger">
          <li v-for="operation in previewOperations" :key="operation.operation_id">
            <div class="operation-name"><strong>{{ propertyLabel(operation.property) }}</strong><span>第 {{ operation.target.paragraph_ordinal + 1 }} 段</span></div>
            <div class="diff-values"><del>{{ formatValue(operation.expected_before) }}</del><ArrowRight :size="15" aria-hidden="true" /><ins>{{ formatValue(operation.desired_after) }}</ins></div>
            <StatusBadge v-if="operation.risk !== 'low'" :status="operation.risk" :label="operation.risk === 'high' ? '高风险' : '需复核'" />
          </li>
        </ol>
        <p v-if="plan.operations.length > previewOperations.length" class="operations-remaining">另有 {{ plan.operations.length - previewOperations.length }} 项操作，可在完整计划中查看。</p>
        <EmptyState v-if="!plan.operations.length" title="计划没有可执行操作" description="所选问题可能均需人工复核或不支持修复；不会生成空的成功结果。" />
        <DisclosurePanel v-if="plan.operations.length" class="technical-disclosure" title="技术详情" :open="showOperations" @toggle="showOperations = !showOperations">
          <div class="table-scroll">
            <table class="data-table">
              <caption>每个操作绑定目标元素、原值、新值与 OOXML 白名单</caption>
              <thead><tr><th scope="col">操作 / Issue</th><th scope="col">目标与属性</th><th scope="col">Before → After</th><th scope="col">影响与风险</th><th scope="col" class="container-optional">允许变更</th></tr></thead>
              <tbody>
                <tr v-for="operation in plan.operations" :key="operation.operation_id">
                  <td><strong>{{ operation.operation_id }}</strong><span class="mono table-muted">{{ operation.issue_id }}</span></td>
                  <td><span>{{ operation.property }}</span><span class="table-muted">{{ operation.target.part_uri }} · 段 {{ operation.target.paragraph_ordinal + 1 }}</span></td>
                  <td><div class="diff-values"><del>{{ formatValue(operation.expected_before) }}</del><ArrowRight :size="15" aria-hidden="true" /><ins>{{ formatValue(operation.desired_after) }}</ins></div></td>
                  <td><span>{{ operation.impact_scope }}</span><StatusBadge :status="operation.risk" :label="operation.risk === 'high' ? '高风险' : operation.risk === 'medium' ? '需复核' : '低风险'" /></td>
                  <td class="container-optional"><span v-for="change in operation.allowed_xml_changes" :key="change" class="code-value xml-change">{{ change }}</span></td>
                </tr>
              </tbody>
            </table>
          </div>
        </DisclosurePanel>
      </section>

      <section class="approval-flow" aria-labelledby="approval-title">
        <h2 id="approval-title" class="sr-only">计划批准与执行</h2>
        <article class="approval-step" :class="{ complete: Boolean(plan.approved_at) }">
          <span class="step-number">01</span><div><h3>{{ plan.approved_at ? '计划已批准' : '批准计划' }}</h3><p>确认修改内容。</p></div>
          <button type="button" :class="plan.status === 'DRAFT' ? 'button button-primary' : 'button button-secondary'" :disabled="plan.status !== 'DRAFT' || !plan.operations.length || repair.approving" @click="approveDialog?.open()"><ShieldCheck :size="16" aria-hidden="true" /> {{ plan.status === 'DRAFT' ? '批准修复计划' : '计划已批准' }}</button>
        </article>
        <article class="approval-step" :class="{ complete: Boolean(resultRevisionId) }">
          <span class="step-number">02</span><div><h3>执行修复</h3><p>生成修订版并复检。</p></div>
          <button type="button" class="button button-primary" :disabled="!canExecute || !plan.operations.length" @click="executeDialog?.open()"><Play :size="16" aria-hidden="true" /> {{ repair.executing ? '正在提交…' : '执行修复' }}</button>
        </article>
      </section>

      <section v-if="job" class="execution-status panel motion-card" aria-labelledby="execution-title">
        <div class="panel-header"><h2 id="execution-title">修复进度</h2><StatusBadge :status="job.status" /></div>
        <div class="panel-body execution-body">
          <LoaderCircle v-if="!['SUCCEEDED', 'FAILED', 'CANCELLED'].includes(job.status)" class="spinner" :size="24" aria-hidden="true" />
          <Check v-else-if="job.status === 'SUCCEEDED'" :size="24" aria-hidden="true" />
          <CircleAlert v-else :size="24" aria-hidden="true" />
          <div class="execution-progress">
            <ProgressBar :value="job.progress" label="修复进度" :message="executionMessage" />
            <span v-if="job.error_code" class="job-reference">{{ job.error_code }}</span>
          </div>
        </div>
      </section>
      <div v-if="resultRevisionId" class="result-callout"><LockKeyhole :size="22" aria-hidden="true" /><div><strong>候选修订版已生成</strong><p>查看质量结论后，再决定是否下载。</p></div><RouterLink class="button button-primary" :to="`/projects/${projectId}/results/${resultRevisionId}`">查看复检与下载 <ArrowRight :size="16" aria-hidden="true" /></RouterLink></div>
    </template>

    <ConfirmDialog ref="approveDialog" title="批准这份修复计划？" confirm-label="批准计划" :busy="repair.approving" description="确认上述格式调整。批准后，你仍需单独执行修复。" @confirm="approve"></ConfirmDialog>
    <ConfirmDialog ref="executeDialog" title="执行已批准的修复？" confirm-label="提交执行" :busy="repair.executing" description="在副本中应用已批准的修改，并检查文件完整性。原稿将保留。" @confirm="execute" />
  </div>
</template>

<style scoped>
.repairs-page { max-width: 1280px; }
.plan-summary { padding: 22px 24px; margin-bottom: 18px; }
.plan-summary-heading h2 { margin-bottom: 8px; font-size: 1.5rem; }
.plan-summary-heading p { margin-bottom: 0; color: #657184; }
.plan-assurances { display: flex; flex-wrap: wrap; gap: 8px 18px; margin: 18px 0 8px; color: #647186; font-size: .75rem; }
.plan-assurances span { display: inline-flex; align-items: center; gap: 6px; }
.plan-summary .disclosure-panel { margin-top: 12px; border-top: 1px solid #e5eaf1; }
.plan-metrics { margin-bottom: 18px; }
.operations-panel { margin-bottom: 18px; }
.operation-list { padding: 0; margin: 0; list-style: none; }
.operation-list li { display: grid; grid-template-columns: minmax(140px, 1fr) minmax(180px, 1.2fr) auto; align-items: center; gap: 12px; padding: 15px 18px; border-bottom: 1px solid #e5e8ed; }
.operation-name strong, .operation-name span { display: block; }
.operation-name span { margin-top: 4px; color: #748095; font-size: .7rem; }
.operation-list .status { justify-self: end; }
.operations-remaining { padding: 0 18px 10px; color: #748095; font-size: .76rem; }
.technical-disclosure { padding: 0 18px; }
.operations-panel .table-scroll { max-height: 520px; border-top: 1px solid #e5eaf1; }
.table-muted { display: block; margin-top: 5px; color: #748095; font-size: .68rem; overflow-wrap: anywhere; }
.diff-values { display: flex; align-items: center; flex-wrap: wrap; gap: 7px; }
.diff-values del { padding: 3px 6px; color: #8d3d3d; background: #fff1f1; }
.diff-values ins { padding: 3px 6px; color: #1d6c55; background: #edf7f2; text-decoration: none; font-weight: 700; }
.xml-change { margin: 2px; }
.approval-flow { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px; margin-bottom: 18px; }
.approval-step { display: flex; flex-direction: column; align-items: flex-start; gap: 14px; padding: 22px; background: #fff; border: 1px solid #dce2eb;  border-radius: 8px; }
.approval-step.complete { border-color: #bdcce0; }
.approval-step .button { width: 100%; margin-top: auto; }
.step-number { color: #4b6588; font-family: 'Noto Serif SC', serif; font-size: .75rem; }
.approval-step h3 { margin-bottom: 7px; font-size: 1.15rem; }
.approval-step p { color: #657184; font-size: .8rem; }
.execution-status { margin-bottom: 18px; }
.execution-body { display: flex; align-items: center; gap: 14px; }
.execution-body > div { flex: 1; min-width: 0; }
.job-reference { display: block; margin-top: 8px; color: #748095; font-size: .66rem; }
.result-callout { display: flex; align-items: center; gap: 14px; padding: 20px; color: #1d6c55; background: #f0f8f4; border: 1px solid #a7cec0; border-radius: 8px; }
.result-callout > div { flex: 1; }
.result-callout p { margin: 4px 0 0; }
@media (max-width: 800px) {
  .approval-flow { grid-template-columns: 1fr; }
  .operation-list li { grid-template-columns: 1fr; gap: 8px; }
  .operation-list .status { justify-self: start; }
  .result-callout { align-items: flex-start; flex-direction: column; }
}
</style>
