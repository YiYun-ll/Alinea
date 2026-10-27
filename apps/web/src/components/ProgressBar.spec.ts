import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import ProgressBar from './ProgressBar.vue'

describe('ProgressBar', () => {
  it('uses semantic determinate progress', () => {
    const wrapper = mount(ProgressBar, { props: { value: 42, label: '检查任务', message: '正在处理' } })
    const progress = wrapper.get('progress')
    expect(progress.attributes('value')).toBe('42')
    expect(progress.attributes('max')).toBe('100')
    expect(progress.attributes('aria-label')).toBe('检查任务')
    expect(wrapper.text()).toContain('42%')
    expect(wrapper.get('[role="status"]').text()).toBe('正在处理')
  })

  it('uses indeterminate semantics without a value or fake percentage', () => {
    const wrapper = mount(ProgressBar, { props: { value: null, label: '准备任务' } })
    expect(wrapper.get('progress').attributes('value')).toBeUndefined()
    expect(wrapper.text()).not.toContain('%')
  })
})
