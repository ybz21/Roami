import { useState } from 'react'

export type WorkspaceTab = 'tasks' | 'messages' | 'memory'
type Workspace = { open: boolean; tab: WorkspaceTab }
const tabs = new Set(['tasks', 'messages', 'memory'])
function storedWorkspace(key: string): Workspace {
  try { const value = JSON.parse(localStorage.getItem(key) || 'null'); if (typeof value?.open === 'boolean') { const tab = value.tab === 'activity' ? 'tasks' : value.tab === 'reminders' ? 'messages' : value.tab; if (tabs.has(tab)) return { open: value.open, tab } } } catch {}
  return { open: true, tab: 'tasks' }
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
