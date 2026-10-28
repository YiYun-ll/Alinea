import { beforeEach, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import { api } from '../lib/api'
import { useProjectStore } from '../stores/project'
import type { VerificationReport } from '../types/contracts'
import ResultsView from './ResultsView.vue'

vi.mock('../components/PdfDocumentViewer.vue', () => ({ default: { template: '<div class="pdf-test-stub" />' } }))

beforeEach(() => {
  vi.restoreAllMocks()
  setActivePinia(createPinia())
  vi.spyOn(api, 'getArtifacts').mockResolvedValue({ data: [] })
})

const report: VerificationReport = {
  revision_id: 'revised', base_revision_id: 'previous-revision', inspection_id: null, before_inspection_id: null,
  status: 'PASS', selected_count: 1, resolved_count: 1, remaining_count: 0, operations: [], warnings: [],
  renderer_profile_id: null, original_sha256: 'before', revision_sha256: 'after', generated_at: '',
  gates: ['G1', 'G2', 'G3', 'G4', 'G5'].map((gate) => ({ gate: gate as VerificationReport['gates'][number]['gate'], status: 'PASS', details: {} })),
}

async function openResults() {
  const project = useProjectStore()
  project.originalRevisionId = 'first-original'
  const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/projects/:id/results/:revisionId', component: ResultsView }] })
  await router.push('/projects/project/results/revised')
  return mount(ResultsView, { global: { plugins: [router] } })
}

it('loads comparison PDFs on demand and uses the actual repair base from the report', async () => {
  vi.spyOn(api, 'getReport').mockResolvedValue(report)
  const preview = vi.spyOn(api, 'getPreview').mockResolvedValue(new ArrayBuffer(0))
  const wrapper = await openResults()
  await flushPromises()
  expect(preview).not.toHaveBeenCalled()
  await wrapper.get('.result-view-nav button:nth-child(2)').trigger('click')
  await flushPromises()
  expect(preview.mock.calls).toEqual([['project', 'previous-revision'], ['project', 'revised']])
})

it.each(['missing report', 'missing integrity gate'])('keeps revised downloads disabled for %s', async (scenario) => {
  const load = vi.spyOn(api, 'getReport')
  if (scenario === 'missing report') load.mockRejectedValue(new Error('Report unavailable'))
  else load.mockResolvedValue({ ...report, gates: report.gates.filter((gate) => gate.gate !== 'G2') })
  const download = vi.spyOn(api, 'downloadRevision')
  const wrapper = await openResults()
  await flushPromises()
  await wrapper.get('.result-view-nav button:nth-child(3)').trigger('click')
  await flushPromises()
  const revised = wrapper.findAll('button').find((button) => button.text() === '下载修订版')
  expect(revised?.attributes('disabled')).toBeDefined()
  await revised?.trigger('click')
  expect(download).not.toHaveBeenCalled()
})
