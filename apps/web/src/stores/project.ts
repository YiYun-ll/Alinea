import { defineStore } from 'pinia'
import { api } from '../lib/api'
import { getLastProjectId, removeProjectToken, saveProjectToken } from '../lib/auth'
import { errorMessage } from '../lib/format'
import { useToastStore } from './toast'
import type { Project, ProjectCreated, Revision } from '../types/contracts'
import { useInspectionStore } from './inspection'
import { usePreviewStore } from './preview'

interface RecentProject {
  project_id: string
  name: string
  original_revision_id: string | null
  updated_at: string
}

interface ProjectState {
  projectId: string | null
  project: Project | null
  originalRevisionId: string | null
  activeRevisionId: string | null
  recentProjects: RecentProject[]
  loading: boolean
  deleting: boolean
  error: string | null
}

const RECENT_KEY = 'alinea:recent-projects'
let projectLoadSerial = 0

function readRecent(): RecentProject[] {
  try {
    const value: unknown = JSON.parse(localStorage.getItem(RECENT_KEY) ?? '[]')
    if (!Array.isArray(value)) return []
    return value.flatMap((item): RecentProject[] => {
      if (typeof item !== 'object' || item === null) return []
      const record = item as Record<string, unknown>
      if (typeof record.project_id !== 'string' || typeof record.name !== 'string') return []
      return [{
        project_id: record.project_id, name: record.name,
        original_revision_id: typeof record.original_revision_id === 'string' ? record.original_revision_id : null,
        updated_at: typeof record.updated_at === 'string' ? record.updated_at : new Date(0).toISOString(),
      }]
    })
  } catch {
    return []
  }
}

function remember(project: Project, originalRevisionId: string | null): RecentProject[] {
  const next = readRecent().filter((item) => item.project_id !== project.project_id)
  next.unshift({ project_id: project.project_id, name: project.name, original_revision_id: originalRevisionId, updated_at: new Date().toISOString() })
  localStorage.setItem(RECENT_KEY, JSON.stringify(next.slice(0, 8)))
  return next
}

function revisionFrom(project: Project, fallback?: string | null): string | null {
  return project.active_revision_id ?? project.revision_id ?? project.original_revision_id ?? fallback ?? project.revisions?.[0]?.revision_id ?? null
}

export const useProjectStore = defineStore('project', {
  state: (): ProjectState => ({
    projectId: null, project: null, originalRevisionId: null, activeRevisionId: null,
    recentProjects: readRecent(), loading: false, deleting: false, error: null,
  }),
  actions: {
    acceptCreated(created: ProjectCreated, revisionId?: string): void {
      projectLoadSerial += 1
      saveProjectToken(created.project_id, created.token)
      this.projectId = created.project_id
      this.project = created
      this.originalRevisionId = created.original_revision_id ?? created.revision_id ?? revisionId ?? null
      this.activeRevisionId = this.originalRevisionId
      this.recentProjects = remember(created, this.originalRevisionId)
    },
    async create(name: string): Promise<ProjectCreated> {
      this.loading = true
      this.error = null
      try {
        const created = await api.createProject(name)
        this.acceptCreated(created)
        return created
      } catch (error) {
        this.error = errorMessage(error)
        throw error
      } finally {
        this.loading = false
      }
    },
    async createDemo(): Promise<string> {
      this.loading = true
      this.error = null
      try {
        const created = await api.createDemo()
        this.acceptCreated(created, created.revision_id)
        this.originalRevisionId = created.revision_id
        this.activeRevisionId = created.revision_id
        useToastStore().push('success', '演示工作区已就绪', '真实文档与规则已加载，请先审阅规则。')
        return created.project_id
      } catch (error) {
        this.error = errorMessage(error)
        throw error
      } finally {
        this.loading = false
      }
    },
    async upload(file: File): Promise<string> {
      if (!this.projectId) throw new Error('请先创建项目。')
      this.error = null
      try {
        const uploaded = await api.uploadDocument(this.projectId, file)
        this.originalRevisionId = uploaded.revision_id
        this.activeRevisionId = uploaded.revision_id
        if (this.project) {
          this.project.original_revision_id = uploaded.revision_id
          this.project.revision_id = uploaded.revision_id
          this.recentProjects = remember(this.project, uploaded.revision_id)
        }
        useToastStore().push('success', 'DOCX 上传完成', '原稿已安全保存，结构解析已就绪。')
        return uploaded.revision_id
      } catch (error) {
        this.error = errorMessage(error)
        throw error
      }
    },
    async load(projectId: string): Promise<void> {
      const serial = ++projectLoadSerial
      this.loading = true
      this.error = null
      try {
        const project = await api.getProject(projectId)
        if (serial !== projectLoadSerial) return
        const previousRevision = this.projectId === projectId ? this.activeRevisionId : null
        this.projectId = projectId
        this.project = project
        this.originalRevisionId = project.original_revision_id ?? project.revisions?.[0]?.revision_id ?? this.originalRevisionId
        this.activeRevisionId = revisionFrom(project, previousRevision ?? this.originalRevisionId)
        this.recentProjects = remember(project, this.originalRevisionId)
      } catch (error) {
        if (serial !== projectLoadSerial) return
        this.error = errorMessage(error)
        throw error
      } finally {
        if (serial === projectLoadSerial) this.loading = false
      }
    },
    restoreLastProject(): string | null {
      return getLastProjectId()
    },
    setActiveRevision(revisionId: string): void {
      if (this.activeRevisionId === revisionId) return
      this.activeRevisionId = revisionId
      if (this.project) this.project.active_revision_id = revisionId
      const inspection = useInspectionStore()
      inspection.clearForRevisionChange()
      usePreviewStore().clear()
    },
    revisions(): Revision[] {
      return this.project?.revisions ?? []
    },
    async remove(): Promise<void> {
      if (!this.projectId) return
      const projectId = this.projectId
      this.deleting = true
      try {
        await api.deleteProject(projectId)
        removeProjectToken(projectId)
        const recent = readRecent().filter((item) => item.project_id !== projectId)
        localStorage.setItem(RECENT_KEY, JSON.stringify(recent))
        this.recentProjects = recent
        this.projectId = null
        this.project = null
        this.originalRevisionId = null
        this.activeRevisionId = null
      } catch (error) {
        this.error = errorMessage(error)
        throw error
      } finally {
        this.deleting = false
      }
    },
  },
})
