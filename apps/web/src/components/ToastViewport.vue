<script setup lang="ts">
import { CheckCircle2, CircleAlert, Info, TriangleAlert, X } from 'lucide-vue-next'
import { useToastStore } from '../stores/toast'
import type { ToastKind } from '../stores/toast'

const toast = useToastStore()
const icons: Record<ToastKind, typeof CheckCircle2> = {
  success: CheckCircle2,
  info: Info,
  warning: TriangleAlert,
  error: CircleAlert,
}
</script>

<template>
  <div class="toast-viewport" aria-label="操作通知">
    <TransitionGroup name="toast-list" tag="div" class="toast-list">
      <article v-for="item in toast.items" :key="item.id" class="toast" :class="`toast-${item.kind}`" :role="item.kind === 'error' ? 'alert' : 'status'">
        <component :is="icons[item.kind]" :size="19" aria-hidden="true" />
        <div class="toast-content"><strong>{{ item.title }}</strong><p>{{ item.message }}</p></div>
        <button type="button" class="toast-close" aria-label="关闭通知" @click="toast.dismiss(item.id)"><X :size="15" aria-hidden="true" /></button>
      </article>
    </TransitionGroup>
  </div>
</template>
