import { beforeEach, describe, expect, it } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import { nextTick } from 'vue'
import { useProjectStore } from '../stores/project'
import WorkflowRail from './WorkflowRail.vue'

beforeEach(() => {
  setActivePinia(createPinia())
  localStorage.clear()
})

describe('WorkflowRail', () => {
  it('marks the current step and unlocks results only after publication', async () => {
    const project = useProjectStore()
    project.project = { project_id: 'p1', name: 'Demo', revisions: [] }
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [
        { path: '/projects/:id/rules', name: 'rules', component: { template: '<div />' } },
        { path: '/projects/:id/inspection', name: 'inspection', component: { template: '<div />' } },
        { path: '/projects/:id/repairs', name: 'repairs', component: { template: '<div />' } },
        { path: '/projects/:id/results/:revisionId', name: 'results', component: { template: '<div />' } },
      ],
    })
    await router.push('/projects/p1/inspection')
    await router.isReady()
    const wrapper = mount(WorkflowRail, { global: { plugins: [router] } })
    expect(wrapper.get('[aria-current="step"]').attributes('aria-label')).toBe('检查与选择')
    expect(wrapper.get('button[aria-label="报告与下载"]').attributes('disabled')).toBeDefined()

    project.project = { project_id: 'p1', name: 'Demo', revisions: [{ revision_id: 'published-1', kind: 'PUBLISHED' }] }
    await nextTick()
    await wrapper.get('a[aria-label="报告与下载"]').trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.path).toBe('/projects/p1/results/published-1')
  })
})
