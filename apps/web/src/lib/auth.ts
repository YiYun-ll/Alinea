const TOKEN_PREFIX = 'alinea:project-token:'
const LAST_PROJECT_KEY = 'alinea:last-project'

export function saveProjectToken(projectId: string, token: string): void {
  localStorage.setItem(`${TOKEN_PREFIX}${projectId}`, token)
  localStorage.setItem(LAST_PROJECT_KEY, projectId)
}

export function getProjectToken(projectId: string): string | null {
  return localStorage.getItem(`${TOKEN_PREFIX}${projectId}`)
}

export function removeProjectToken(projectId: string): void {
  localStorage.removeItem(`${TOKEN_PREFIX}${projectId}`)
  if (localStorage.getItem(LAST_PROJECT_KEY) === projectId) {
    localStorage.removeItem(LAST_PROJECT_KEY)
  }
}

export function getLastProjectId(): string | null {
  return localStorage.getItem(LAST_PROJECT_KEY)
}
