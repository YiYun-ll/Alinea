<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ArrowRight, CheckCircle2, FileCheck2, UploadCloud } from 'lucide-vue-next'
import ErrorNotice from '../components/ErrorNotice.vue'
import DisclosurePanel from '../components/DisclosurePanel.vue'
import ProgressBar from '../components/ProgressBar.vue'
import { api } from '../lib/api'
import { errorMessage } from '../lib/format'
import { useProjectStore } from '../stores/project'
import { useRulesStore } from '../stores/rules'
import { useJobStore } from '../stores/job'

const router = useRouter()
const project = useProjectStore()
const rules = useRulesStore()
const jobs = useJobStore()
const name = ref('')
const nameManuallyEdited = ref(false)
const documentFile = ref<File | null>(null)
const guidelineKind = ref<'preset' | 'text' | 'pdf'>('preset')
const presetId = ref('general_report')
const guidelineName = ref('')
const guidelineText = ref('')
const guidelineFile = ref<File | null>(null)
const createdProjectId = ref<string | null>(null)
const revisionId = ref<string | null>(null)
const guidelineId = ref<string | null>(null)
const stage = ref<'idle' | 'creating' | 'uploading' | 'guideline' | 'extracting'>('idle')
const localError = ref<string | null>(null)
const dragging = ref(false)
const showAdvanced = ref(false)
const presetOptions = [
  { id: 'general_report', name: '通用报告', description: '正文、标题与页面设置' },
  { id: 'thesis_demo', name: '学位论文', description: '字体、行距与段落缩进' },
]

const busy = computed(() => stage.value !== 'idle')
const stageLabel = computed(() => ({ idle: '', creating: '正在创建项目…', uploading: '正在上传并验证 DOCX…', guideline: '正在提交规范来源…', extracting: '正在申请规则提取…' })[stage.value])
const fileSummary = computed(() => documentFile.value ? `${(documentFile.value.size / 1024 / 1024).toFixed(2)} MiB` : '')

function selectDocument(file: File | null): void {
  if (busy.value) return
  documentFile.value = file
  if (file) {
    if (createdProjectId.value) {
      revisionId.value = null
      guidelineId.value = null
    }
    if (!nameManuallyEdited.value && !createdProjectId.value) name.value = file.name.replace(/\.docx$/i, '').slice(0, 120)
  }
  localError.value = null
}

function chooseDocument(event: Event): void {
  selectDocument((event.target as HTMLInputElement).files?.[0] ?? null)
}

function dropDocument(event: DragEvent): void {
  dragging.value = false
  selectDocument(event.dataTransfer?.files[0] ?? null)
}

function selectPreset(id: string): void {
  if (busy.value) return
  presetId.value = id
  guidelineId.value = null
}

function chooseGuideline(event: Event): void {
  guidelineFile.value = (event.target as HTMLInputElement).files?.[0] ?? null
  guidelineId.value = null
  localError.value = null
}

function validate(): string | null {
  const file = documentFile.value
  if (!name.value.trim()) return '请填写项目名称。'
  if (!file) return '请选择原稿 DOCX。'
  if (!file.name.toLocaleLowerCase().endsWith('.docx')) return '仅支持 .docx；不支持 .doc、.docm 或其他格式。'
  if (file.size === 0) return 'DOCX 是空文件，请选择有效文档。'
  if (file.size > 15 * 1024 * 1024) return 'DOCX 超过 15 MiB 上限。'
  if (guidelineKind.value === 'preset' && !presetId.value.trim()) return '请填写服务端预设 ID。'
  if (guidelineKind.value === 'text' && !guidelineText.value.trim()) return '请粘贴格式规范文本。'
  if (guidelineKind.value === 'pdf') {
    if (!guidelineFile.value) return '请选择文本型 PDF 规范。'
    if (!guidelineFile.value.name.toLocaleLowerCase().endsWith('.pdf')) return '规范文件必须是 PDF。'
    if (guidelineFile.value.size === 0 || guidelineFile.value.size > 10 * 1024 * 1024) return '规范 PDF 必须非空且不超过 10 MiB。'
  }
  return null
}

watch([guidelineKind, guidelineName, guidelineText, guidelineFile, presetId], () => { guidelineId.value = null })

async function submit(): Promise<void> {
  localError.value = validate()
  if (localError.value || busy.value) return
  try {
    let projectId = createdProjectId.value
    if (!projectId) {
      stage.value = 'creating'
      const created = await project.create(name.value.trim())
      projectId = created.project_id
      createdProjectId.value = projectId
    }
    if (!revisionId.value && documentFile.value) {
      stage.value = 'uploading'
      revisionId.value = await project.upload(documentFile.value)
    }
    if (!guidelineId.value) {
      stage.value = 'guideline'
      const input = guidelineKind.value === 'pdf'
        ? { kind: 'pdf' as const, file: guidelineFile.value as File, name: guidelineName.value || undefined }
        : guidelineKind.value === 'text'
          ? { kind: 'text' as const, text: guidelineText.value, name: guidelineName.value || undefined }
          : { kind: 'preset' as const, preset_id: presetId.value.trim(), name: guidelineName.value || undefined }
      const guideline = await api.createGuideline(projectId, input)
      guidelineId.value = guideline.guideline_id
    }
    stage.value = 'extracting'
    const jobId = await rules.extract(projectId, guidelineId.value, guidelineKind.value === 'preset' ? presetId.value.trim() : undefined)
    jobs.track(projectId, jobId)
    await router.push(`/projects/${projectId}/inspection?setup=1`)
  } catch (error) {
    localError.value = errorMessage(error, '创建流程未完成，请检查后重试。')
  } finally {
    stage.value = 'idle'
  }
}
</script>

<template>
  <div class="page-container new-page motion-page">
    <div class="page-heading">
      <div><h1>新建检查</h1></div>
    </div>

    <ErrorNotice v-if="localError" :message="localError" />
    <form class="wizard-grid" @submit.prevent="submit">
      <section class="panel document-card" aria-labelledby="document-title">
        <div class="panel-header"><h2 id="document-title">文档</h2></div>
        <div class="panel-body">
          <div class="form-field">
            <label class="field-label" for="project-name">项目名称</label>
            <input id="project-name" v-model="name" name="project_name" class="field" required maxlength="120" autocomplete="off" enterkeyhint="next" placeholder="选择 DOCX 后自动命名" :disabled="busy || Boolean(createdProjectId)" @input="nameManuallyEdited = true" />
          </div>
          <label
            class="dropzone" :class="{ dragging, 'has-file': documentFile, 'is-disabled': busy }"
            @dragenter.prevent="dragging = true" @dragover.prevent="dragging = true"
            @dragleave.prevent="dragging = false" @drop.prevent="dropDocument"
          >
            <CheckCircle2 v-if="documentFile" :size="32" aria-hidden="true" />
            <UploadCloud v-else :size="32" aria-hidden="true" />
            <strong>{{ documentFile?.name ?? '选择或拖入 DOCX' }}</strong>
            <span>{{ fileSummary || 'DOCX · 最大 15 MiB' }}</span>
            <input id="docx-input" class="file-input" type="file" name="document" accept=".docx,application/vnd.openxmlformats-officedocument.wordprocessingml.document" aria-label="原稿 DOCX 文件" aria-describedby="docx-hint" :disabled="busy" @change="chooseDocument" />
          </label>
          <p id="docx-hint" class="field-hint">支持 .docx，最大 15 MiB。原稿将单独保留。</p>
          <div v-if="revisionId" class="notice notice-pass mb-0"><FileCheck2 :size="18" aria-hidden="true" /><span>原稿已安全保存，可以继续准备规范。</span></div>
        </div>
      </section>

      <section class="panel guideline-card" aria-labelledby="guideline-title">
        <div class="panel-header"><h2 id="guideline-title">格式规范</h2></div>
        <div class="panel-body">
          <fieldset class="source-picker" :disabled="busy">
            <legend class="sr-only">规范来源</legend>
            <label class="checkbox-label"><input v-model="guidelineKind" class="checkbox" type="radio" name="guideline_kind" value="preset" @change="guidelineId = null" /> 预设规范</label>
            <label class="checkbox-label"><input v-model="guidelineKind" class="checkbox" type="radio" name="guideline_kind" value="text" @change="guidelineId = null" /> 粘贴文本</label>
            <label class="checkbox-label"><input v-model="guidelineKind" class="checkbox" type="radio" name="guideline_kind" value="pdf" @change="guidelineId = null" /> 上传 PDF</label>
          </fieldset>
          <div v-if="guidelineKind === 'preset'" class="form-field">
            <div class="preset-options">
              <label v-for="option in presetOptions" :key="option.id" class="preset-option">
                <input v-model="presetId" type="radio" name="preset_choice" :value="option.id" :disabled="busy" @change="selectPreset(option.id)" />
                <span><strong>{{ option.name }}</strong><small>{{ option.description }}</small></span>
              </label>
            </div>
            <span class="field-hint">演示预设不属于任何学校或机构的官方标准。</span>
          </div>
          <div v-else-if="guidelineKind === 'text'" class="form-field">
            <label class="field-label" for="guideline-text">规范原句</label>
            <textarea id="guideline-text" v-model="guidelineText" name="guideline_text" class="field guideline-text" required placeholder="例如：正文使用宋体，小四号，1.5 倍行距；一级标题黑体三号并居中。" :disabled="busy" />
            <span class="field-hint">模型只协助形成候选规则，所有规则均需你复核与批准。</span>
          </div>
          <div v-else class="form-field">
            <label class="field-label" for="pdf-input">文本型 PDF 规范</label>
            <input id="pdf-input" class="field pdf-input" type="file" name="guideline_pdf" accept=".pdf,application/pdf" :disabled="busy" @change="chooseGuideline" />
            <span class="field-hint">最大 10 MiB。扫描件或无文本层 PDF 不可用时，请改用文本或预设。</span>
          </div>

          <DisclosurePanel class="advanced-settings" title="更多选项" :open="showAdvanced" @toggle="showAdvanced = !showAdvanced">
            <div class="form-field">
              <label class="field-label" for="guideline-name">规范名称（可选）</label>
              <input id="guideline-name" v-model="guidelineName" name="guideline_name" class="field" maxlength="120" placeholder="例如：学院 2026 版要求" :disabled="busy" />
            </div>
            <div v-if="guidelineKind === 'preset'" class="form-field">
              <label class="field-label" for="preset-id">服务端预设 ID</label>
              <input id="preset-id" v-model="presetId" name="custom_preset_id" class="field" :required="guidelineKind === 'preset' && showAdvanced" autocomplete="off" aria-describedby="preset-hint" :disabled="busy" @input="guidelineId = null" />
              <span id="preset-hint" class="field-hint">可用值：general_report、thesis_demo。无效值会返回真实错误。</span>
            </div>
          </DisclosurePanel>
        </div>
      </section>

      <div class="wizard-submit">
        <div class="submit-context">
          <span class="muted small">下一步，确认检查规则</span>
          <ProgressBar v-if="busy" :value="null" label="上传与规范准备" :message="stageLabel" />
        </div>
        <button type="submit" class="button button-primary submit-button" :disabled="busy" enterkeyhint="next">
          {{ busy ? stageLabel : '上传并继续' }}
          <ArrowRight v-if="!busy" :size="18" aria-hidden="true" />
        </button>
      </div>
    </form>
  </div>
</template>

<style scoped>
.new-page { max-width: 1180px; }
.wizard-grid { display: grid; grid-template-columns: minmax(0, 1.08fr) minmax(0, .92fr); gap: 20px; }
.document-card { align-self: start; }
.guideline-card { min-height: 370px; }
.dropzone { position: relative; display: flex; flex-direction: column; align-items: center; gap: 8px; min-height: 184px; justify-content: center; padding: 24px; color: #667467; background: #f7f8fa; border: 1px dashed #8f9bad; border-radius: 8px; text-align: center; cursor: pointer; transition: color var(--motion-fast) ease, background-color var(--motion-fast) ease, border-color var(--motion-fast) ease; }
.dropzone:hover, .dropzone.dragging { color: #34513f; background: #eef3ec; border-color: #456653; }
.dropzone:focus-within { outline: 3px solid #d98b27; outline-offset: 3px; }
.dropzone.has-file { color: #1d6c55; background: #f0f8f4; border-style: solid; }
.dropzone.is-disabled { cursor: wait; opacity: .65; }
.dropzone strong { max-width: 100%; overflow-wrap: anywhere; }
.dropzone span { font-size: .78rem; }
.file-input { position: absolute; width: 1px; height: 1px; overflow: hidden; clip-path: inset(50%); }
.source-picker { display: flex; flex-wrap: wrap; gap: 8px 16px; padding: 0; margin: 0 0 20px; border: 0; }
.source-picker { min-width: 0; }
.preset-options { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; }
.preset-option { display: flex; align-items: flex-start; gap: 9px; min-height: 82px; padding: 14px; background: #f8fafc; border: 1px solid #dfe3dc; border-radius: 7px; cursor: pointer; transition: border-color var(--motion-fast) ease, background-color var(--motion-fast) ease, translate var(--motion-fast) var(--motion-ease-out); }
.preset-option:has(input:checked) { background: #eef3ec; border-color: #456653; }
.preset-option:hover { translate: 0 -1px; border-color: #8fa2bf; }
.preset-option:focus-within { outline: 3px solid #d98b27; outline-offset: 2px; }
.preset-option input { flex-shrink: 0; margin-top: 3px; accent-color: #456653; }
.preset-option strong, .preset-option small { display: block; }
.preset-option strong { font-size: .875rem; }
.preset-option small { margin-top: 5px; color: #737c73; font-size: .72rem; line-height: 1.55; }
.guideline-text { min-height: 170px; }
.pdf-input { padding: 7px; }
.support-box { margin-block: 14px; padding: 12px 14px; color: #465268; background: #f7f8f5; border-left: 3px solid #456653; font-size: .8rem; }
.support-box p { margin: 4px 0 0; }
.advanced-settings { border-top: 1px solid #e7ebe3; }
.wizard-submit { grid-column: 1 / -1; display: flex; align-items: center; justify-content: space-between; gap: 20px; padding: 20px 24px; background: #fff; border: 1px solid #dfe3dc; border-top: 1px solid var(--line); border-radius: 8px; }
.submit-context { flex: 1; }
.submit-context > p { margin: 5px 0 0; color: #737c73; font-size: .78rem; }
.submit-context .job-progress { max-width: 400px; margin-top: 14px; }
.submit-button { min-height: 48px; }
@media (max-width: 800px) {
  .wizard-grid { grid-template-columns: 1fr; }
  .wizard-submit { align-items: stretch; flex-direction: column; }
  .submit-button { width: 100%; }
}
@media (max-width: 480px) { .preset-options { grid-template-columns: 1fr; } }
</style>
