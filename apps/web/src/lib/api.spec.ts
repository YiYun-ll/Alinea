import { beforeEach, describe, expect, it, vi } from 'vitest'
import { saveProjectToken } from './auth'

beforeEach(() => {
  vi.resetModules()
  vi.restoreAllMocks()
  vi.unstubAllEnvs()
  localStorage.clear()
})

describe('artifact downloads', () => {
  it('normalizes an absolute artifact URL without duplicating the API prefix', async () => {
    const { api } = await import('./api')
    saveProjectToken('project-1', 'token-1')
    const response = new Response(new Blob(['%PDF-1.7']), {
      status: 200,
      headers: { 'Content-Disposition': 'attachment; filename="preview.pdf"' },
    })
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(response)

    const result = await api.downloadArtifact('project-1', {
      kind: 'pdf',
      url: 'http://localhost:3000/api/v1/revisions/revision-1/preview?sha256=abc',
      sha256: 'abc',
    })

    expect(fetchMock).toHaveBeenCalledOnce()
    const requested = new URL(String(fetchMock.mock.calls[0][0]), window.location.origin)
    expect(requested.pathname).toBe('/api/v1/revisions/revision-1/preview')
    expect(requested.search).toBe('?sha256=abc')
    expect(requested.pathname).not.toContain('/api/v1/api/v1')
    expect(result.filename).toBe('preview.pdf')
    expect(result.blob.size).toBeGreaterThan(0)
  })
})
