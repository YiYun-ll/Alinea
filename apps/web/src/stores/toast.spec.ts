import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useToastStore } from './toast'

beforeEach(() => {
  setActivePinia(createPinia())
  vi.useFakeTimers()
})

describe('toast notifications', () => {
  it('dismisses automatically and supports manual close', () => {
    const toast = useToastStore()
    toast.push('success', '已完成', '操作成功', 1000)
    toast.push('info', '提示', '仍然可见', 5000)
    expect(toast.items).toHaveLength(2)
    vi.advanceTimersByTime(1000)
    expect(toast.items).toHaveLength(1)
    toast.dismiss(toast.items[0].id)
    expect(toast.items).toHaveLength(0)
  })

  it('clears timers and all messages', () => {
    const toast = useToastStore()
    toast.push('warning', '注意', '请检查')
    toast.clear()
    expect(toast.items).toHaveLength(0)
    expect(vi.getTimerCount()).toBe(0)
  })
})
