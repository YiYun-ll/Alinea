<script setup lang="ts">
import { ref, useId } from 'vue'
import { TriangleAlert, X } from 'lucide-vue-next'

withDefaults(defineProps<{ title: string; description: string; confirmLabel?: string; busy?: boolean }>(), { confirmLabel: '确认', busy: false })
const emit = defineEmits<{ confirm: [] }>()
const dialog = ref<HTMLDialogElement | null>(null)
const titleId = useId()
const descriptionId = useId()
let displayTransitionSupported: boolean | undefined

function canTransitionDisplay(): boolean {
  if (displayTransitionSupported !== undefined) return displayTransitionSupported
  if (!window.CSS?.supports?.('transition-behavior', 'allow-discrete') || !document.body) return false
  const probe = document.createElement('div')
  probe.style.cssText = 'transition: display 1s allow-discrete !important; display: block;'
  document.body.appendChild(probe)
  const initialDisplay = getComputedStyle(probe).display
  probe.style.display = 'none'
  displayTransitionSupported = initialDisplay === 'block' && getComputedStyle(probe).display === 'block'
  probe.remove()
  return displayTransitionSupported
}

function open(): void {
  const element = dialog.value
  if (!element || element.open) return
  element.removeAttribute('data-closing')
  element.showModal()
}

async function close(): Promise<void> {
  const element = dialog.value
  if (!element?.open) return
  const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches
  if (reduced) {
    element.removeAttribute('data-closing')
    element.close()
    return
  }
  const nativeExit = canTransitionDisplay()
  element.setAttribute('data-closing', '')
  const animations = typeof element.getAnimations === 'function' ? element.getAnimations({ subtree: true }) : []
  if (animations.length > 0) {
    await Promise.race([
      Promise.allSettled(animations.map((animation) => animation.finished)),
      new Promise((resolve) => window.setTimeout(resolve, 350)),
    ])
  }
  if (!element.open || !element.hasAttribute('data-closing')) return
  if (!nativeExit) element.removeAttribute('data-closing')
  element.close()
  element.removeAttribute('data-closing')
}

function cancel(event: Event): void {
  event.preventDefault()
  void close()
}

defineExpose({ open, close })
</script>

<template>
  <dialog ref="dialog" class="native-dialog" :aria-labelledby="titleId" :aria-describedby="descriptionId" @cancel="cancel">
    <div class="dialog-header">
      <h2 :id="titleId">{{ title }}</h2>
      <button type="button" class="button button-ghost icon-button" aria-label="关闭对话框" @click="close"><X :size="18" aria-hidden="true" /></button>
    </div>
    <div class="dialog-body">
      <div class="notice notice-warn mb-0"><TriangleAlert :size="20" class="shrink-0" aria-hidden="true" /><p :id="descriptionId">{{ description }}</p></div>
      <slot />
    </div>
    <div class="dialog-actions">
      <button type="button" class="button button-secondary" :disabled="busy" @click="close">取消</button>
      <button type="button" class="button button-danger" :disabled="busy" @click="emit('confirm')">{{ busy ? '正在处理…' : confirmLabel }}</button>
    </div>
  </dialog>
</template>
