import { defineStore } from 'pinia'
import { ref } from 'vue'

export type ToastKind = 'success' | 'info' | 'warning' | 'error'
export interface ToastItem {
  id: number
  kind: ToastKind
  title: string
  message: string
}

let sequence = 0

export const useToastStore = defineStore('toast', () => {
  const items = ref<ToastItem[]>([])
  const timers = new Map<number, number>()

  function dismiss(id: number): void {
    const timer = timers.get(id)
    if (timer !== undefined) window.clearTimeout(timer)
    timers.delete(id)
    items.value = items.value.filter((item) => item.id !== id)
  }

  function push(kind: ToastKind, title: string, message: string, duration = 4800): number {
    const id = ++sequence
    items.value.push({ id, kind, title, message })
    timers.set(id, window.setTimeout(() => dismiss(id), duration))
    return id
  }

  function clear(): void {
    timers.forEach((timer) => window.clearTimeout(timer))
    timers.clear()
    items.value = []
  }

  return { items, push, dismiss, clear }
})
