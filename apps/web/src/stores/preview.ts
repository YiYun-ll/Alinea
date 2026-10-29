import { defineStore } from 'pinia'
import { api } from '../lib/api'
import { errorMessage } from '../lib/format'

interface PreviewState {
  revisionId: string | null
  pdfSha256: string | null
  pdfData: ArrayBuffer | null
  page: number
  scale: number
  rotation: number
  loading: boolean
  error: string | null
  requestSerial: number
}

export const usePreviewStore = defineStore('preview', {
  state: (): PreviewState => ({ revisionId: null, pdfSha256: null, pdfData: null, page: 1, scale: 1, rotation: 0, loading: false, error: null, requestSerial: 0 }),
  actions: {
    async load(projectId: string, revisionId: string, sha256?: string | null): Promise<void> {
      const serial = ++this.requestSerial
      this.loading = true
      this.error = null
      this.revisionId = revisionId
      this.pdfSha256 = sha256 ?? null
      this.pdfData = null
      try {
        const data = await api.getPreview(projectId, revisionId, sha256)
        if (serial !== this.requestSerial) return
        this.pdfData = data
        this.page = 1
        this.scale = 1
        this.rotation = 0
      } catch (error) {
        if (serial === this.requestSerial) this.error = errorMessage(error)
      } finally {
        if (serial === this.requestSerial) this.loading = false
      }
    },
    clear(): void {
      this.requestSerial += 1
      this.revisionId = null
      this.pdfSha256 = null
      this.pdfData = null
      this.error = null
      this.page = 1
    },
  },
})
