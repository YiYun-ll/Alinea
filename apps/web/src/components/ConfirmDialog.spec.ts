import { beforeEach, describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import ConfirmDialog from './ConfirmDialog.vue'

beforeEach(() => {
  Object.defineProperty(window, 'matchMedia', {
    configurable: true,
    value: vi.fn().mockReturnValue({ matches: false }),
  })
  HTMLDialogElement.prototype.showModal = vi.fn(function (this: HTMLDialogElement) {
    this.open = true
  })
  HTMLDialogElement.prototype.close = vi.fn(function (this: HTMLDialogElement) {
    this.open = false
  })
})

describe('ConfirmDialog', () => {
  it('closes through the same animated path without a native form fallback', async () => {
    const wrapper = mount(ConfirmDialog, { props: { title: '批准规则', description: '确认操作' } })
    const component = wrapper.vm as unknown as { open: () => void; close: () => Promise<void> }
    component.open()
    const dialog = wrapper.get('dialog')
    expect(dialog.element.open).toBe(true)
    await wrapper.get('button[aria-label="关闭对话框"]').trigger('click')
    expect(dialog.element.open).toBe(false)
    expect(dialog.attributes('data-closing')).toBeUndefined()
  })

  it('clears an interrupted closing state when reduced motion is enabled', async () => {
    const wrapper = mount(ConfirmDialog, { props: { title: '批准规则', description: '确认操作' } })
    const component = wrapper.vm as unknown as { open: () => void; close: () => Promise<void> }
    component.open()
    const dialog = wrapper.get('dialog')
    dialog.element.setAttribute('data-closing', '')
    vi.mocked(window.matchMedia).mockReturnValue({ matches: true } as MediaQueryList)
    await component.close()
    expect(dialog.element.open).toBe(false)
    expect(dialog.attributes('data-closing')).toBeUndefined()
  })

  it('does not let Escape dismiss a confirmation while its request is pending', async () => {
    const wrapper = mount(ConfirmDialog, { props: { title: '批准规则', description: '确认操作', busy: true } })
    const component = wrapper.vm as unknown as { open: () => void }
    component.open()
    await wrapper.get('dialog').trigger('cancel')
    expect(wrapper.get('dialog').element.open).toBe(true)
    expect(wrapper.get('button[aria-label="关闭对话框"]').attributes('disabled')).toBeDefined()
  })
})
