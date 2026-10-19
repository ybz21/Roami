import { useState } from 'react'

export type WorkspaceTab = 'activity' | 'tasks' | 'reminders' | 'memory'
type Workspace = { open: boolean; tab: WorkspaceTab }
const tabs = new Set(['activity', 'tasks', 'reminders', 'memory'])
function storedWorkspace(key: string): Workspace {
  try { const value = JSON.parse(localStorage.getItem(key) || 'null'); if (typeof value?.open === 'boolean' && tabs.has(value.tab)) return value } catch {}
  return { open: true, tab: 'activity' }
}
export function useAgentWorkspace(node: string | null) {
  const key = `roami.agent.workspace.${node || 'local'}`
  const [states, setStates] = useState<Record<string, Workspace>>(() => ({ [key]: storedWorkspace(key) }))
  const value = states[key] || storedWorkspace(key)
  const change = (patch: Partial<Workspace>) => {
    const next = { ...value, ...patch }
    setStates(current => ({ ...current, [key]: next }))
    try { localStorage.setItem(key, JSON.stringify(next)) } catch {}
  }
  return { ...value, change }
}
