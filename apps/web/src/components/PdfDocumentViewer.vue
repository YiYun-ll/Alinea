<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, shallowRef, watch } from 'vue'
import { getDocument, GlobalWorkerOptions } from 'pdfjs-dist'
import type { PDFDocumentLoadingTask, PDFDocumentProxy } from 'pdfjs-dist'
import workerUrl from 'pdfjs-dist/build/pdf.worker.min.mjs?url'
import { ChevronLeft, ChevronRight, LoaderCircle, RotateCw, ZoomIn, ZoomOut } from 'lucide-vue-next'
import PdfPage from './PdfPage.vue'
import EmptyState from './EmptyState.vue'
import ErrorNotice from './ErrorNotice.vue'
import { overlaysForPage } from '../lib/pdfCoordinates'
import { errorMessage } from '../lib/format'
import type { Issue } from '../types/contracts'

GlobalWorkerOptions.workerSrc = workerUrl

const props = withDefaults(defineProps<{
  data: ArrayBuffer | null
  revisionId: string
  issues?: Issue[]
  previewSha256?: string | null
  focusedIssueId?: string | null
  compact?: boolean
}>(), { issues: () => [], previewSha256: null, focusedIssueId: null, compact: false })
const emit = defineEmits<{ selectIssue: [issueId: string]; loaded: [pageCount: number]; failed: [message: string] }>()
const page = defineModel<number>('page', { default: 1 })
const scale = defineModel<number>('scale', { default: 1 })
const rotation = defineModel<number>('rotation', { default: 0 })
const scrollContainer = ref<HTMLElement | null>(null)
const pdfDocument = shallowRef<PDFDocumentProxy | null>(null)
const pageCount = ref(0)
const loading = ref(false)
const error = ref<string | null>(null)
let loadingTask: PDFDocumentLoadingTask | null = null
let serial = 0
let scrollFrame = 0
const pageNumbers = computed(() => Array.from({ length: pageCount.value }, (_, index) => index + 1))
const issueNumbers = computed<Record<string, number>>(() => Object.fromEntries(props.issues.map((issue, index) => [issue.issue_id, index + 1])))

async function destroyDocument(): Promise<void> {
  const task = loadingTask
  loadingTask = null
  const document = pdfDocument.value
  pdfDocument.value = null
  if (task) await task.destroy()
  else await document?.destroy()
}

async function load(data: ArrayBuffer | null): Promise<void> {
  const generation = ++serial
  error.value = null
  pageCount.value = 0
  if (!data) {
    await destroyDocument()
    loading.value = false
    return
  }
  loading.value = true
  await destroyDocument()
  try {
    const task = getDocument({ data: new Uint8Array(data.slice(0)) })
    loadingTask = task
    const document = await task.promise
    if (generation !== serial) {
      await document.destroy()
      return
    }
    pdfDocument.value = document
    pageCount.value = document.numPages
    page.value = Math.min(Math.max(1, page.value), document.numPages)
    emit('loaded', document.numPages)
  } catch (cause) {
    if (generation !== serial) return
    error.value = errorMessage(cause, 'PDF 无法加载，请重试。')
    emit('failed', error.value)
  } finally {
    if (generation === serial) loading.value = false
  }
}

function overlays(pageIndex: number) {
  return overlaysForPage(props.issues, props.revisionId, pageIndex, props.previewSha256 ?? undefined)
}

function goToPage(value: number): void {
  page.value = Math.min(Math.max(1, value), Math.max(1, pageCount.value))
}

async function scrollToCurrentPage(): Promise<void> {
  await nextTick()
  const target = scrollContainer.value?.querySelector<HTMLElement>(`[data-page-number="${page.value}"]`)
  const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches
  target?.scrollIntoView({ block: 'start', behavior: reduced ? 'auto' : 'smooth' })
}

function updateCurrentPage(): void {
  if (scrollFrame) return
  scrollFrame = requestAnimationFrame(() => {
    scrollFrame = 0
    const container = scrollContainer.value
    if (!container) return
    const containerRect = container.getBoundingClientRect()
    const center = containerRect.top + Math.min(containerRect.height / 3, 240)
    let nearest = page.value
    let distance = Number.POSITIVE_INFINITY
    container.querySelectorAll<HTMLElement>('[data-page-number]').forEach((element) => {
      const rect = element.getBoundingClientRect()
      const nextDistance = Math.abs(rect.top + Math.min(rect.height / 2, 200) - center)
      if (nextDistance < distance) {
        nearest = Number(element.dataset.pageNumber)
        distance = nextDistance
      }
    })
    if (nearest !== page.value) page.value = nearest
  })
}

function zoom(delta: number): void {
  scale.value = Math.min(3, Math.max(.5, Math.round((scale.value + delta) * 100) / 100))
}

watch(() => props.data, (data) => { void load(data) }, { immediate: true })
watch(page, () => { void scrollToCurrentPage() })
watch(() => props.focusedIssueId, (issueId) => {
  if (!issueId) return
  const issue = props.issues.find((item) => item.issue_id === issueId)
  if (!issue || issue.location.status !== 'LOCATED' || issue.revision_id !== props.revisionId) return
  if (props.previewSha256 && issue.location.preview_pdf_sha256 !== props.previewSha256) return
  const fragment = issue.location.fragments[0]
  if (fragment) goToPage(fragment.page_index + 1)
}, { immediate: true })

onBeforeUnmount(() => {
  ++serial
  if (scrollFrame) cancelAnimationFrame(scrollFrame)
  void destroyDocument()
})
</script>

<template>
  <div class="pdf-viewer" :class="{ compact }">
    <div class="pdf-toolbar" aria-label="PDF 阅读工具">
      <div class="button-group">
        <button type="button" class="button button-ghost icon-button" aria-label="上一页" :disabled="page <= 1" @click="goToPage(page - 1)"><ChevronLeft :size="18" aria-hidden="true" /></button>
        <label class="sr-only" :for="`pdf-page-${revisionId}`">页码</label>
        <input :id="`pdf-page-${revisionId}`" class="page-input" type="number" min="1" :max="pageCount || 1" :value="page" :disabled="!pageCount" @change="goToPage(Number(($event.target as HTMLInputElement).value))" />
        <span class="page-count">/ {{ pageCount || '—' }}</span>
        <button type="button" class="button button-ghost icon-button" aria-label="下一页" :disabled="!pageCount || page >= pageCount" @click="goToPage(page + 1)"><ChevronRight :size="18" aria-hidden="true" /></button>
      </div>
      <div class="button-group">
        <button type="button" class="button button-ghost icon-button" aria-label="缩小" :disabled="scale <= .5" @click="zoom(-.25)"><ZoomOut :size="18" aria-hidden="true" /></button>
        <label class="sr-only" :for="`pdf-scale-${revisionId}`">缩放比例</label>
        <select :id="`pdf-scale-${revisionId}`" v-model.number="scale" class="scale-select" :disabled="!pageCount">
          <option :value=".5">50%</option><option :value=".75">75%</option><option :value="1">100%</option><option :value="1.25">125%</option><option :value="1.5">150%</option><option :value="2">200%</option><option :value="3">300%</option>
        </select>
        <button type="button" class="button button-ghost icon-button" aria-label="放大" :disabled="scale >= 3" @click="zoom(.25)"><ZoomIn :size="18" aria-hidden="true" /></button>
        <button type="button" class="button button-ghost icon-button" aria-label="顺时针旋转 90 度" :disabled="!pageCount" @click="rotation = (rotation + 90) % 360"><RotateCw :size="18" aria-hidden="true" /></button>
      </div>
    </div>
    <div class="pdf-render-note">只读 PDF 预览 · 浏览器显示可能与 Microsoft Word 略有差异</div>
    <ErrorNotice v-if="error" :message="error" retry-label="重新加载" @retry="load(data)" />
    <div v-else-if="loading" class="pdf-loading"><LoaderCircle class="spinner" :size="24" aria-hidden="true" /><span>正在解析真实 PDF…</span></div>
    <EmptyState v-else-if="!data" title="没有可用预览" description="预览可能尚未生成，或此版本的 PDF 渲染失败。结构化问题与摘录仍可查看。" />
    <div v-else ref="scrollContainer" class="pdf-scroll" tabindex="0" aria-label="PDF 分页阅读区" @scroll.passive="updateCurrentPage">
      <PdfPage
        v-for="number in pageNumbers" :key="`${revisionId}-${number}`" :pdf-document="pdfDocument" :page-number="number"
        :scale="scale" :rotation="rotation" :overlays="overlays(number - 1)" :issue-numbers="issueNumbers"
        :focused-issue-id="focusedIssueId" @select-issue="emit('selectIssue', $event)"
      />
    </div>
  </div>
</template>

<style scoped>
.pdf-viewer { min-width: 0; height: 100%; display: flex; flex-direction: column; background: #e8ebef; }
.pdf-toolbar { display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 8px; padding: 8px 12px; background: #fff; border-bottom: 1px solid #d8dde5; }
.page-input, .scale-select { min-height: 34px; color: #273449; background: #fff; border: 1px solid #b9c2cf; border-radius: 5px; text-align: center; }
.page-input { width: 56px; }
.scale-select { width: 70px; }
.page-count { min-width: 38px; color: #5e6979; font-size: .8rem; }
.pdf-render-note { padding: 5px 12px; color: #5e6979; background: #f4f5f7; border-bottom: 1px solid #d8dde5; font-size: .68rem; text-align: center; }
.pdf-scroll { min-height: 0; flex: 1; overflow: auto; padding: 30px clamp(12px, 4vw, 48px) 80px; scroll-behavior: smooth; scrollbar-gutter: stable; }
.pdf-loading { min-height: 240px; display: flex; align-items: center; justify-content: center; gap: 10px; color: #5e6979; }
.compact .pdf-render-note { display: none; }
.compact .pdf-scroll { padding: 20px 12px 48px; }
@media (max-width: 600px) { .pdf-toolbar { justify-content: center; } .pdf-scroll { padding-inline: 8px; } }
</style>
