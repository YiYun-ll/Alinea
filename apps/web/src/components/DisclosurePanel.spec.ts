import { describe, expect, it } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import DisclosurePanel from './DisclosurePanel.vue'

describe('DisclosurePanel', () => {
  it('synchronizes accessible state and removes collapsed fields', async () => {
    const wrapper = mount(DisclosurePanel, {
      props: { title: '高级设置', open: false },
      slots: { default: '<input id="advanced-value" required />' },
    })
    const trigger = wrapper.get('button')
    expect(trigger.attributes('aria-expanded')).toBe('false')
    expect(wrapper.find('#advanced-value').exists()).toBe(false)

    await trigger.trigger('click')
    expect(wrapper.emitted('toggle')).toHaveLength(1)
    await wrapper.setProps({ open: true })
    await flushPromises()
    const region = wrapper.get('[role="region"]')
    expect(trigger.attributes('aria-expanded')).toBe('true')
    expect(trigger.attributes('aria-controls')).toBe(region.attributes('id'))
    expect(wrapper.find('#advanced-value').exists()).toBe(true)

    await wrapper.setProps({ open: false })
    await flushPromises()
    expect(trigger.attributes('aria-expanded')).toBe('false')
    expect(wrapper.find('#advanced-value').exists()).toBe(false)
  })
})
