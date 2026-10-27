<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { TextLayer } from 'pdfjs-dist'
import type { PDFDocumentProxy, PDFPageProxy, RenderTask } from 'pdfjs-dist'
import { CircleAlert } from 'lucide-vue-next'
import { PageCoordinateAdapter, type IssueOverlay, type ViewportRect } from '../lib/pdfCoordinates'
import { errorMessage, propertyLabel } from '../lib/format'

const props = defineProps<{
  pdfDocument: PDFDocumentProxy | null
  pageNumber: number
  scale: number
  rotation: number
  overlays: IssueOverlay[]
  issueNumbers: Record<string, number>
  focusedIssueId: string | null
}>()
const emit = defineEmits<{ selectIssue: [issueId: string] }>()
const root = ref<HTMLElement | null>(null)
const canvas = ref<HTMLCanvasElement | null>(null)
const textContainer = ref<HTMLDivElement | null>(null)
const rendered = ref(false)
const rendering = ref(false)
const renderError = ref<string | null>(null)
const pageStyle = ref<Record<string, string>>({ aspectRatio: '210 / 297' })
const overlayBoxes = ref<Array<{ overlay: IssueOverlay; box: ViewportRect }>>([])
let observer: IntersectionObserver | null = null
let visible = false
let serial = 0
let page: PDFPageProxy | null = null
let renderTask: RenderTask | null = null
let textLayer: TextLayer | null = null

function issueLabel(issueId: string): string {
  return `I-${String(props.issueNumbers[issueId] ?? 0).padStart(2, '0')}`
}

async function cancelRender(): Promise<void> {
  textLayer?.cancel()
  textLayer = null
  const task = renderTask
  renderTask = null
  task?.cancel()
  await task?.promise.catch(() => undefined)
}

async function release(): Promise<void> {
  ++serial
  await cancelRender()
  rendered.value = false
  rendering.value = false
  overlayBoxes.value = []
  textContainer.value?.replaceChildren()
  if (canvas.value) {
    canvas.value.width = 0
    canvas.value.height = 0
  }
  page?.cleanup()
  page = null
}

async function renderPage(): Promise<void> {
  if (!visible || !props.pdfDocument) return
  const generation = ++serial
  rendering.value = true
  renderError.value = null
  await cancelRender()
  if (generation !== serial) return
  try {
    const pdfPage = await props.pdfDocument.getPage(props.pageNumber)
    if (generation !== serial) {
      pdfPage.cleanup()
      return
    }
    page = pdfPage
    const viewport = pdfPage.getViewport({ scale: props.scale, rotation: pdfPage.rotate + props.rotation })
    const targetCanvas = canvas.value
    const targetText = textContainer.value
    const targetRoot = root.value
    if (!targetCanvas || !targetText || !targetRoot) return
    const context = targetCanvas.getContext('2d', { alpha: false })
    if (!context) throw new Error('浏览器无法创建 PDF canvas 上下文。')
    const ratio = Math.min(window.devicePixelRatio || 1, 2)
    targetCanvas.width = Math.max(1, Math.floor(viewport.width * ratio))
    targetCanvas.height = Math.max(1, Math.floor(viewport.height * ratio))
    targetCanvas.style.width = `${Math.floor(viewport.width)}px`
    targetCanvas.style.height = `${Math.floor(viewport.height)}px`
    targetRoot.style.setProperty('--scale-factor', String(viewport.scale))
    targetRoot.style.setProperty('--user-unit', String(pdfPage.userUnit))
    pageStyle.value = { width: `${Math.floor(viewport.width)}px`, height: `${Math.floor(viewport.height)}px`, aspectRatio: 'auto' }
    targetText.replaceChildren()
    const adapter = new PageCoordinateAdapter(pdfPage.view, viewport)
    overlayBoxes.value = props.overlays.flatMap((overlay) => {
      const box = adapter.toViewportRect(overlay.rect, overlay.fragment.page_size_pt)
      return box ? [{ overlay, box }] : []
    })
    const task = pdfPage.render({
      canvasContext: context, canvas: targetCanvas, viewport,
      transform: ratio === 1 ? undefined : [ratio, 0, 0, ratio, 0, 0], background: '#ffffff',
    })
    renderTask = task
    await task.promise
    if (generation !== serial) return
    const layer = new TextLayer({ textContentSource: await pdfPage.getTextContent(), container: targetText, viewport })
    textLayer = layer
    await layer.render()
    if (generation !== serial) return
    rendered.value = true
  } catch (cause) {
    if (generation !== serial || (cause instanceof Error && cause.name === 'RenderingCancelledException')) return
    renderError.value = errorMessage(cause, 'PDF 页面渲染失败，请重试。')
  } finally {
    if (generation === serial) rendering.value = false
  }
}

onMounted(async () => {
  await nextTick()
  observer = new IntersectionObserver((entries) => {
    const entry = entries[0]
    if (!entry) return
    visible = entry.isIntersecting
    if (visible) void renderPage()
    else void release()
  }, { rootMargin: '500px 0px', threshold: 0.01 })
  if (root.value) observer.observe(root.value)
})

watch(() => [props.pdfDocument, props.scale, props.rotation], () => {
  if (visible) void renderPage()
  else void release()
})
watch(() => props.overlays, () => {
  if (visible && rendered.value) void renderPage()
}, { deep: false })

onBeforeUnmount(() => {
  observer?.disconnect()
  visible = false
  void release()
})
</script>

<template>
  <section
    ref="root" class="pdf-page" :class="{ 'deferred-page': pageNumber > 1, 'is-rendering': rendering }"
    :style="pageStyle" :data-page-number="pageNumber" :aria-label="`第 ${pageNumber} 页`"
  >
    <canvas ref="canvas" class="pdf-canvas" :aria-label="`第 ${pageNumber} 页 PDF 渲染`" />
    <div ref="textContainer" class="textLayer pdf-text-layer" role="document" :aria-label="`第 ${pageNumber} 页可选文本`" />
    <div v-if="overlayBoxes.length" class="issue-overlay-layer" :aria-label="`第 ${pageNumber} 页问题高亮`">
      <button
        v-for="{ overlay, box } in overlayBoxes" :key="`${overlay.issue.issue_id}-${overlay.rectIndex}`"
        type="button" class="issue-overlay" :class="{ focused: focusedIssueId === overlay.issue.issue_id }"
        :style="{ left: `${box.left}px`, top: `${box.top}px`, width: `${Math.max(box.width, 8)}px`, height: `${Math.max(box.height, 8)}px` }"
        :aria-label="`${issueLabel(overlay.issue.issue_id)} ${propertyLabel(overlay.issue.property)}，第 ${pageNumber} 页`"
        @click.stop="emit('selectIssue', overlay.issue.issue_id)"
      >
        <span>{{ issueLabel(overlay.issue.issue_id) }}</span>
      </button>
    </div>
    <div v-if="!rendered && !renderError" class="page-placeholder" aria-hidden="true">{{ rendering ? '正在渲染页面…' : `第 ${pageNumber} 页` }}</div>
    <div v-if="renderError" class="page-error" role="alert"><CircleAlert :size="20" aria-hidden="true" /><span>第 {{ pageNumber }} 页无法渲染：{{ renderError }}</span><button type="button" class="button button-secondary button-small" @click="renderPage">重试</button></div>
  </section>
</template>

<style scoped>
.pdf-page { position: relative; flex: none; margin: 0 auto 28px; overflow: hidden; background: #fff; box-shadow: 0 2px 12px rgba(39, 52, 73, .14); container-type: inline-size; }
.deferred-page { content-visibility: auto; contain-intrinsic-size: auto none auto 800px; }
.pdf-canvas { position: absolute; inset: 0; z-index: 1; display: block; }
.pdf-text-layer { position: absolute; inset: 0; z-index: 2; overflow: hidden; }
.issue-overlay-layer { position: absolute; inset: 0; z-index: 3; pointer-events: none; }
.issue-overlay { position: absolute; min-width: 8px; min-height: 8px; padding: 0; pointer-events: auto; background: rgba(217, 139, 39, .16); border: 2px solid #b56c10; border-radius: 2px; }
.issue-overlay:hover, .issue-overlay.focused { background: rgba(217, 139, 39, .25); border-style: dashed; outline: 2px solid #273449; outline-offset: 2px; }
.issue-overlay > span { position: absolute; top: -23px; left: -2px; min-width: 30px; padding: 1px 4px; color: #fff; background: #273449; border: 1px solid #fff; border-radius: 3px; font-family: 'Noto Sans SC', 'Microsoft YaHei', sans-serif; font-size: .65rem; font-weight: 700; line-height: 17px; }
.page-placeholder { position: absolute; inset: 0; display: grid; place-items: center; color: #8793a4; background: #fdfdfe; font-size: .8rem; }
.page-error { position: absolute; inset: 0; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 12px; padding: 24px; color: #9e3636; background: #fff5f5; text-align: center; }
@media print { .issue-overlay { display: none; } }
</style>
