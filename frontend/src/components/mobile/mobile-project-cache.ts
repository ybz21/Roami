import { currentNodeId } from '../cluster/node-url'

export type MobileProject = {
  key: string; name: string; dir: string; sessions: number
  unfinished: number; worktrees: number; lastActivity: number
}

const KEY = 'roam.mobile.projects'
const MAX_AGE = 24 * 60 * 60 * 1000
const MAX_NODES = 4
type Snapshot = { at: number; projects: MobileProject[] }

function snapshots(): Record<string, Snapshot> {
  try {
    const value = JSON.parse(localStorage.getItem(KEY) || '{}')
    return value && typeof value === 'object' && !Array.isArray(value) ? value : {}
  } catch { return {} }
}

export function readMobileProjects(node = currentNodeId()): MobileProject[] | null {
  const snapshot = snapshots()[node || '']
  if (!snapshot || !Array.isArray(snapshot.projects) || Date.now() - snapshot.at > MAX_AGE) return null
  return snapshot.projects
}

export function writeMobileProjects(projects: MobileProject[], node = currentNodeId()): MobileProject[] {
  const all = snapshots()
  const slot = node || ''
  all[slot] = { at: Date.now(), projects }
  const old = Object.keys(all).filter((key) => key !== slot).sort((a, b) => (all[b]?.at || 0) - (all[a]?.at || 0))
  for (const key of old.slice(MAX_NODES - 1)) delete all[key]
  try { localStorage.setItem(KEY, JSON.stringify(all)) } catch { /* Storage may be unavailable. */ }
  return projects
}
