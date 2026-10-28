import { defineStore } from 'pinia'
import { api, ApiError } from '../lib/api'
import { errorMessage } from '../lib/format'
import type { Job } from '../types/contracts'

const ACTIVE_PREFIX = 'alinea:active-jobs:'
const TERMINAL_STATUSES = new Set(['SUCCEEDED', 'FAILED', 'CANCELLED'])

interface JobState {
  jobs: Record<string, Job>
  timers: Map<string, number>
  connectionStatus: 'idle' | 'polling' | 'ready' | 'error'
  lastError: string | null
  generation: number
}

function readActive(projectId: string): string[] {
  try {
    const parsed: unknown = JSON.parse(localStorage.getItem(`${ACTIVE_PREFIX}${projectId}`) ?? '[]')
    return Array.isArray(parsed) ? parsed.filter((value): value is string => typeof value === 'string') : []
  } catch {
    return []
  }
}

function writeActive(projectId: string, ids: Set<string>): void {
  localStorage.setItem(`${ACTIVE_PREFIX}${projectId}`, JSON.stringify([...ids]))
}

export const useJobStore = defineStore('job', {
  state: (): JobState => ({ jobs: {}, timers: new Map<string, number>(), connectionStatus: 'idle', lastError: null, generation: 0 }),
  getters: {
    activeJobs: (state) => Object.values(state.jobs).filter((job) => !TERMINAL_STATUSES.has(job.status)),
  },
  actions: {
    async loadProjectJobs(projectId: string): Promise<Job[]> {
      const generation = this.generation
      const response = await api.getProjectJobs(projectId)
      if (generation !== this.generation) return []
      response.data.forEach((job) => { this.jobs[job.job_id] = job })
      return response.data
    },
    track(projectId: string, jobId: string): void {
      const active = new Set(readActive(projectId))
      active.add(jobId)
      writeActive(projectId, active)
      const timerKey = `${projectId}:${jobId}`
      if (this.timers.has(timerKey)) return
      this.timers.set(timerKey, -1)
      this.connectionStatus = 'polling'
      void this.poll(projectId, jobId, 0)
    },
    restore(projectId: string): void {
      readActive(projectId).forEach((jobId) => this.track(projectId, jobId))
    },
    async poll(projectId: string, jobId: string, failures: number): Promise<void> {
      const timerKey = `${projectId}:${jobId}`
      const generation = this.generation
      try {
        const job = await api.getJob(projectId, jobId)
        if (generation !== this.generation) return
        this.jobs[jobId] = job
        this.lastError = null
        this.connectionStatus = 'ready'
        if (TERMINAL_STATUSES.has(job.status)) {
          const active = new Set(readActive(projectId))
          active.delete(jobId)
          writeActive(projectId, active)
          this.timers.delete(timerKey)
          return
        }
        failures = 0
      } catch (error) {
        if (generation !== this.generation) return
        failures += 1
        this.lastError = errorMessage(error)
        this.connectionStatus = 'error'
        if (error instanceof ApiError && (error.status === 401 || error.status === 403 || error.status === 404)) {
          const active = new Set(readActive(projectId))
          active.delete(jobId)
          writeActive(projectId, active)
          this.timers.delete(timerKey)
          return
        }
      }
      const delay = failures > 0 ? Math.min(30_000, 2_000 * 2 ** Math.min(failures, 4)) : document.hidden ? 5_000 : 1_200
      const timer = window.setTimeout(() => {
        void this.poll(projectId, jobId, failures)
      }, delay)
      this.timers.set(timerKey, timer)
    },
    stopAll(): void {
      this.generation += 1
      this.timers.forEach((timer) => window.clearTimeout(timer))
      this.timers.clear()
      this.connectionStatus = 'idle'
    },
  },
})

export interface JobStoreInternals {
  timers: Map<string, number>
}

export const jobTimers = new Map<string, number>()

export function isTerminalJob(job: Job | undefined): boolean {
  return job ? TERMINAL_STATUSES.has(job.status) : false
}
