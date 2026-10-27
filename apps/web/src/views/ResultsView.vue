<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { AlertOctagon, CheckCircle2, Columns2, Download, FileJson, FileText, LoaderCircle, ShieldCheck } from 'lucide-vue-next'
import { api } from '../lib/api'
import { saveBlob } from '../lib/download'
import { errorMessage, formatDate } from '../lib/format'
import { useProjectStore } from '../stores/project'
import type { Artifact, VerificationReport } from '../types/contracts'
import PdfDocumentViewer from '../components/PdfDocumentViewer.vue'
import StatusBadge from '../components/StatusBadge.vue'
import ErrorNotice from '../components/ErrorNotice.vue'
import EmptyState from '../components/EmptyState.vue'
import DisclosurePanel from '../components/DisclosurePanel.vue'

const route = useRoute()
const project = useProjectStore()
const projectId = String(route.params.id)
const revisionId = computed(() => String(route.params.revisionId))
const report = ref<VerificationReport | null>(null)
const artifacts = ref<Artifact[]>([])
const originalData = ref<ArrayBuffer | null>(null)
const revisedData = ref<ArrayBuffer | null>(null)
const originalPage = ref(1)
const revisedPage = ref(1)
const originalScale = ref(.8)
const revisedScale = ref(.8)
const originalRotation = ref(0)
const revisedRotation = ref(0)
const loading = ref(false)
const reportError = ref<string | null>(null)
const artifactError = ref<string | null>(null)
const downloadError = ref<string | null>(null)
const previewErrors = ref<{ original: string | null; revised: string | null }>({ original: null, revised: null })
const downloading = ref<string | null>(null)
const activeView = ref<'summary' | 'compare' | 'download'>('summary')
const showRenderDetails = ref(false)
const generalWarnings = computed(() => report.value?.warnings.filter((warning) => !warning.startsWith('Render environment:')) ?? [])
const renderDetails = computed(() => report.value?.warnings.filter((warning) => warning.startsWith('Render environment:')) ?? [])
let serial = 0
const originalRevisionId = computed(() => report.value?.base_revision_id ?? project.originalRevisionId)
const hardGateFailure = computed(() => report.value?.status === 'BLOCKED' || Boolean(report.value?.gates.some((gate) => ['G1', 'G2', 'G3', 'G4'].includes(gate.gate) && gate.status === 'FAIL')))
const gateRows = computed(() => {
  const gates = report.value?.gates ?? []
  return ['G1', 'G2', 'G3', 'G4', 'G5'].map((gate) => ({ gate, result: gates.find((item) => item.gate === gate) ?? null }))
})
const gateNames: Record<string, string> = { G0: '输入安全', G1: 'DOCX 结构', G2: '全量文本', G3: '媒体与关系', G4: 'XML 白名单', G5: '规则与视觉复检' }

async function loadPreview(revision: string | null, target: 'original' | 'revised', requestSerial: number): Promise<void> {
  if (!revision) {
    previewErrors.value[target] = '缺少此版本的 revision ID。'
    return
  }
  try {
    const data = await api.getPreview(projectId, revision)
    if (requestSerial !== serial) return
    if (target === 'original') originalData.value = data
    else revisedData.value = data
  } catch (error) {
    if (requestSerial === serial) previewErrors.value[target] = errorMessage(error)
  }
}

async function loadAll(): Promise<void> {
  const requestSerial = ++serial
  const revision = revisionId.value
  loading.value = true
  reportError.value = null
  artifactError.value = null
  previewErrors.value = { original: null, revised: null }
  report.value = null
  artifacts.value = []
  originalData.value = null
  revisedData.value = null
  project.setActiveRevision(revision)
  const original = originalRevisionId.value
  await Promise.all([
    api.getReport(projectId, revision).then((value) => { if (requestSerial === serial) report.value = value }).catch((error: unknown) => { if (requestSerial === serial) reportError.value = errorMessage(error) }),
    api.getArtifacts(projectId, revision).then((value) => { if (requestSerial === serial) artifacts.value = value.data }).catch((error: unknown) => { if (requestSerial === serial) artifactError.value = errorMessage(error) }),
    loadPreview(original, 'original', requestSerial),
    loadPreview(revision, 'revised', requestSerial),
  ])
  if (requestSerial === serial) loading.value = false
}

watch(revisionId, () => { void loadAll() }, { immediate: true })

async function downloadDocx(revision: string, original = false): Promise<void> {
  downloading.value = `docx-${revision}`
  downloadError.value = null
  try {
    const { blob, filename } = await api.downloadRevision(projectId, revision)
    saveBlob(blob, filename ?? `alinea-${original ? 'original' : 'revised'}-${revision}.docx`)
  } catch (error) {
    downloadError.value = errorMessage(error)
  } finally {
    downloading.value = null
  }
}

async function downloadMarkdown(): Promise<void> {
  downloading.value = 'markdown'
  downloadError.value = null
  try {
    const { blob, filename } = await api.downloadReport(projectId, revisionId.value)
    saveBlob(blob, filename ?? `alinea-report-${revisionId.value}.md`)
  } catch (error) {
    downloadError.value = errorMessage(error)
  } finally {
    downloading.value = null
  }
}

function downloadJson(): void {
  if (!report.value) return
  saveBlob(new Blob([JSON.stringify(report.value, null, 2)], { type: 'application/json' }), `alinea-report-${revisionId.value}.json`)
}

async function downloadArtifact(artifact: Artifact): Promise<void> {
  downloading.value = `artifact-${artifact.kind}`
  downloadError.value = null
  try {
    const { blob, filename } = await api.downloadArtifact(projectId, artifact)
    saveBlob(blob, filename ?? `alinea-${revisionId.value}-${artifact.kind}`)
  } catch (error) {
    downloadError.value = errorMessage(error)
  } finally {
    downloading.value = null
  }
}
</script>

<template>
  <div class="page-container results-page motion-page">
    <div class="page-heading">
      <div><p class="eyebrow">04 / Verify & export</p><h1>复检与下载</h1><p>先看质量结论，再对照文档或下载证据。</p></div>
      <StatusBadge v-if="report" :status="report.status" />
    </div>
    <ErrorNotice v-if="reportError || downloadError" :message="downloadError ?? reportError ?? ''" retry-label="重新加载报告" @retry="loadAll" />
    <div v-if="hardGateFailure" class="notice notice-error"><AlertOctagon :size="22" aria-hidden="true" /><div><strong>硬性完整性 Gate 未通过</strong><p>此候选不能被标记为验证通过，也不作为修复完成版推荐。修订版 DOCX 下载已停用；报告仍可导出用于诊断。</p></div></div>

    <nav class="result-view-nav" aria-label="结果视图">
      <button type="button" :aria-pressed="activeView === 'summary'" @click="activeView = 'summary'"><ShieldCheck :size="16" aria-hidden="true" /> 结论</button>
      <button type="button" :aria-pressed="activeView === 'compare'" @click="activeView = 'compare'"><Columns2 :size="16" aria-hidden="true" /> 对照</button>
      <button type="button" :aria-pressed="activeView === 'download'" @click="activeView = 'download'"><Download :size="16" aria-hidden="true" /> 下载</button>
    </nav>

    <EmptyState v-if="loading && !report" title="正在读取验证报告与双版本预览" description="每个请求都直接访问服务端；失败会单独显示。" />
    <Transition v-else name="view-panel" mode="out-in">
      <div :key="activeView" class="result-view">
        <template v-if="activeView === 'summary'">
          <section v-if="report" class="verification-summary" aria-labelledby="verification-title">
            <div class="summary-heading"><div><span class="eyebrow">Verification report</span><h2 id="verification-title">{{ report.status === 'PASS' ? '验证通过' : report.status === 'PARTIAL' ? '部分通过，仍有事项' : report.status === 'BLOCKED' ? '发布已阻断' : '结果无法完全判定' }}</h2></div><ShieldCheck :size="30" aria-hidden="true" /></div>
            <div class="metric-grid motion-stagger">
              <div class="metric"><span class="metric-value">{{ report.selected_count }}</span><span class="metric-label">选中问题</span></div>
              <div class="metric"><span class="metric-value">{{ report.resolved_count }}</span><span class="metric-label">复检已解决</span></div>
              <div class="metric"><span class="metric-value">{{ report.remaining_count }}</span><span class="metric-label">仍需处理</span></div>
              <div class="metric"><span class="metric-value">{{ report.gates.filter((gate) => gate.status === 'PASS').length }}</span><span class="metric-label">通过 Gate</span></div>
            </div>
          </section>

          <section v-if="report" class="panel gates-panel" aria-labelledby="gates-title">
            <div class="panel-header"><h2 id="gates-title">G1–G5 文件级质量 Gate</h2><span class="muted small">G1–G4 失败会阻断发布</span></div>
            <div class="table-scroll">
              <table class="data-table">
                <caption>结构、文本、资源、白名单与复检结果</caption>
                <thead><tr><th scope="col">Gate</th><th scope="col">检查内容</th><th scope="col">状态</th><th scope="col">详情</th></tr></thead>
                <tbody><tr v-for="row in gateRows" :key="row.gate"><th scope="row">{{ row.gate }}</th><td>{{ gateNames[row.gate] }}</td><td><StatusBadge v-if="row.result" :status="row.result.status" /><span v-else class="status status-neutral">报告未提供</span></td><td><pre v-if="row.result" class="gate-details">{{ JSON.stringify(row.result.details, null, 2) }}</pre><span v-else class="muted">不能据此推定通过</span></td></tr></tbody>
              </table>
            </div>
            <div v-if="report.gates.some((gate) => gate.gate === 'G0')" class="panel-body"><strong>G0 · {{ gateNames.G0 }}</strong><StatusBadge class="ml-2" :status="report.gates.find((gate) => gate.gate === 'G0')?.status ?? 'NOT_RUN'" /></div>
          </section>
          <div v-if="report?.warnings.length" class="notice notice-warn">
            <AlertOctagon :size="19" aria-hidden="true" />
            <div>
              <strong>报告警告</strong>
              <p v-for="warning in generalWarnings" :key="warning">{{ warning }}</p>
              <DisclosurePanel v-if="renderDetails.length" title="渲染环境详情" description="LibreOffice、字体与预览指纹" :open="showRenderDetails" @toggle="showRenderDetails = !showRenderDetails">
                <p v-for="warning in renderDetails" :key="warning" class="warning-detail">{{ warning }}</p>
              </DisclosurePanel>
            </div>
          </div>
          <div v-if="report?.status === 'PASS' && !hardGateFailure" class="pass-note"><CheckCircle2 :size="18" aria-hidden="true" /> 当前报告为 PASS；仍建议在你的目标 Word 环境中复核最终分页与字体。</div>
        </template>

        <template v-else-if="activeView === 'compare'">
          <section class="compare-section" aria-labelledby="compare-title">
            <div class="section-title"><div><p class="eyebrow">Side-by-side documents</p><h2 id="compare-title">原版 / 修订版独立预览</h2></div><span class="muted small">PDF 仅用于只读复核</span></div>
            <div class="compare-grid">
              <article class="compare-card">
                <div class="compare-heading"><div><span>ORIGINAL</span><h3>原版</h3><p class="mono">{{ originalRevisionId ?? '未知版本' }}</p></div><button type="button" class="button button-secondary button-small" :disabled="!originalRevisionId || downloading !== null" @click="originalRevisionId && downloadDocx(originalRevisionId, true)"><Download :size="14" aria-hidden="true" /> 下载原版</button></div>
                <ErrorNotice v-if="previewErrors.original" :message="previewErrors.original" />
                <PdfDocumentViewer v-model:page="originalPage" v-model:scale="originalScale" v-model:rotation="originalRotation" compact :data="originalData" :revision-id="originalRevisionId ?? 'original-unavailable'" />
              </article>
              <article class="compare-card">
                <div class="compare-heading"><div><span>REVISED</span><h3>修订版</h3><p class="mono">{{ revisionId }}</p></div><button type="button" class="button button-primary button-small" :disabled="hardGateFailure || downloading !== null" @click="downloadDocx(revisionId)"><Download :size="14" aria-hidden="true" /> {{ hardGateFailure ? '下载已阻断' : '下载修订版' }}</button></div>
                <ErrorNotice v-if="previewErrors.revised" :message="previewErrors.revised" />
                <PdfDocumentViewer v-model:page="revisedPage" v-model:scale="revisedScale" v-model:rotation="revisedRotation" compact :data="revisedData" :revision-id="revisionId" />
              </article>
            </div>
          </section>
        </template>

        <template v-else>
          <section class="download-primary panel" aria-labelledby="download-title">
            <div><span class="eyebrow">Approved artifacts</span><h2 id="download-title">带走你的文件</h2><p>修订版与原版分别保存，下载前可回到对照视图复核。</p></div>
            <div class="download-document-actions">
              <button type="button" class="button button-primary" :disabled="hardGateFailure || downloading !== null" @click="downloadDocx(revisionId)"><Download :size="16" aria-hidden="true" /> {{ hardGateFailure ? '下载已阻断' : '下载修订版' }}</button>
              <button type="button" class="button button-secondary" :disabled="!originalRevisionId || downloading !== null" @click="originalRevisionId && downloadDocx(originalRevisionId, true)"><Download :size="16" aria-hidden="true" /> 下载原版</button>
            </div>
          </section>
          <section class="panel export-panel" aria-labelledby="export-title">
            <div class="panel-header"><h2 id="export-title">证据报告与文件</h2><FileText :size="18" aria-hidden="true" /></div>
            <div class="panel-body export-body">
              <div><strong>验证报告</strong><p>导出实际获取的 JSON 证据或服务端生成的 Markdown。</p></div>
              <div class="button-group"><button type="button" class="button button-secondary" :disabled="!report" @click="downloadJson"><FileJson :size="16" aria-hidden="true" /> JSON 报告</button><button type="button" class="button button-secondary" :disabled="downloading !== null" @click="downloadMarkdown"><Download :size="16" aria-hidden="true" /> Markdown 报告</button></div>
            </div>
            <ErrorNotice v-if="artifactError" :message="artifactError" />
            <div v-if="artifacts.length" class="table-scroll artifact-table"><table class="data-table"><caption>此修订版登记的文件与 SHA-256</caption><thead><tr><th scope="col">类型</th><th scope="col">SHA-256</th><th scope="col">操作</th></tr></thead><tbody><tr v-for="artifact in artifacts" :key="`${artifact.kind}-${artifact.sha256}`"><td>{{ artifact.kind }}</td><td class="mono">{{ artifact.sha256 }}</td><td><button type="button" class="button button-secondary button-small" :disabled="downloading !== null" @click="downloadArtifact(artifact)"><Download :size="14" aria-hidden="true" /> 下载文件</button></td></tr></tbody></table></div>
          </section>
          <section v-if="report" class="panel evidence-meta" aria-labelledby="evidence-meta-title">
            <div class="panel-header"><h2 id="evidence-meta-title">版本与证据指纹</h2><FileText :size="17" aria-hidden="true" /></div>
            <div class="panel-body">
              <dl class="definition-list">
                <dt>原稿 SHA-256</dt><dd class="mono">{{ report.original_sha256 }}</dd>
                <dt>修订 SHA-256</dt><dd class="mono">{{ report.revision_sha256 }}</dd>
                <dt>渲染配置</dt><dd>{{ report.renderer_profile_id ?? '未提供' }}</dd>
                <dt>报告生成</dt><dd>{{ formatDate(report.generated_at) }}</dd>
              </dl>
            </div>
          </section>
        </template>
      </div>
    </Transition>
    <p v-if="downloading" class="loading" role="status"><LoaderCircle class="spinner" :size="16" aria-hidden="true" /> 正在获取真实文件：{{ downloading }}</p>
  </div>
</template>

<style scoped>
.results-page { max-width: 1400px; }
.result-view { min-width: 0; }
.result-view-nav { display: flex; gap: 4px; width: fit-content; padding: 4px; margin-bottom: 22px; background: #e9edf2; border-radius: 8px; }
.result-view-nav button { display: inline-flex; align-items: center; gap: 7px; min-height: 40px; padding: 8px 18px; color: #536174; background: transparent; border: 0; border-radius: 6px; transition: color var(--motion-fast) ease, background-color var(--motion-fast) ease, box-shadow var(--motion-fast) ease, translate var(--motion-fast) var(--motion-ease-out); }
.result-view-nav button:hover { translate: 0 -1px; }
.result-view-nav button[aria-pressed='true'] { color: #273449; background: #fff; box-shadow: 0 1px 4px rgba(39, 52, 73, .12); font-weight: 650; }
.verification-summary { padding: 24px; margin-bottom: 18px; color: #fff; background: #273449; border-radius: 10px; }
.summary-heading { display: flex; align-items: center; justify-content: space-between; margin-bottom: 20px; }
.summary-heading h2 { margin: 0; font-size: 1.7rem; }
.summary-heading .eyebrow { color: #becce2; }
.verification-summary .metric { color: #273449; }
.verification-summary .metric-grid { border-color: #657188; border-radius: 7px; }
.gates-panel { margin-bottom: 18px; }
.gates-panel .table-scroll { max-height: 440px; }
.gate-details { max-width: 520px; max-height: 140px; margin: 0; overflow: auto; font-size: .68rem; white-space: pre-wrap; overflow-wrap: anywhere; }
.result-view .compare-section { margin: 0; }
.section-title { display: flex; align-items: end; justify-content: space-between; gap: 20px; margin-bottom: 16px; }
.section-title h2 { margin: 0; }
.compare-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px; }
.compare-card { min-width: 0; overflow: hidden; background: #fff; border: 1px solid #cfd5de; border-radius: 8px; }
.compare-heading { min-height: 94px; display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 14px 16px; }
.compare-heading > div { min-width: 0; }
.compare-heading span { color: #5675a8; font-size: .65rem; letter-spacing: .12em; }
.compare-heading h3 { margin: 3px 0; font-size: 1.2rem; }
.compare-heading p { margin: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: #6b7482; font-size: .65rem; }
.compare-card :deep(.pdf-viewer) { height: 620px; border-top: 1px solid #d8dde5; }
.download-primary { display: flex; align-items: center; justify-content: space-between; gap: 24px; padding: 24px; margin-bottom: 18px; border-top: 3px solid #273449; }
.download-primary h2 { margin-bottom: 8px; }
.download-primary p { margin-bottom: 0; color: #6b7482; }
.download-document-actions { display: flex; flex-shrink: 0; flex-wrap: wrap; gap: 8px; }
.export-panel { margin-bottom: 16px; }
.export-body { display: flex; align-items: center; justify-content: space-between; gap: 20px; }
.export-body p { margin: 4px 0 0; color: #5e6979; }
.artifact-table { max-height: 320px; border-top: 1px solid #d8dde5; }
.evidence-meta { margin-bottom: 16px; }
.pass-note { display: flex; align-items: center; gap: 8px; padding: 14px; color: #1d6c55; background: #f0f8f4; border: 1px solid #a7cec0; border-radius: 8px; }
@media (max-width: 1000px) { .compare-grid { grid-template-columns: 1fr; } .compare-card :deep(.pdf-viewer) { height: 68dvh; } }
@media (max-width: 700px) {
  .export-body, .section-title, .download-primary { align-items: flex-start; flex-direction: column; }
  .download-document-actions { width: 100%; }
  .download-document-actions .button { flex: 1; }
}
@media (prefers-reduced-motion: reduce) { .result-view-nav button { transition: none; translate: 0 0; } }
</style>
