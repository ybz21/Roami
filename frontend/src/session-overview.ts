import type { SessionAgent } from './components/sessions/session-record'
import type { SessionMem } from './components/sessions/session-memory'
import { createSessionPoll } from './session-poll'
import { useMemo } from 'react'
import { useSessionLifecycle, lifecycleEnded } from './components/sessions/session-lifecycle'

export type OverviewItem = {
  name: string; label: string; lastActivity: number; dormant: boolean; parent?: string; cwd?: string
  projectKey?: string; project?: string; projectDir?: string; worktree?: string; branch?: string
  agent?: SessionAgent | ''; running: boolean; waiting: boolean; tail?: string
  mem?: SessionMem
  lifecycle?: 'preparing' | 'closing' | 'attention'
}

const useOverview = createSessionPoll<OverviewItem[]>('/sessions/overview', 5000, [], response => response?.data?.items || [])
export function useSessionOverview(enabled = true) {
  const snapshot = useOverview(enabled), operations = useSessionLifecycle(enabled)
  const closingNames = useMemo(() => new Set(operations.value.filter(op => op.kind === 'close' && op.state !== 'cancelled').map(op => op.resourceId)), [operations.value])
  const value = useMemo(() => {
    const result = [...snapshot.value]
    for (const op of [...operations.value].reverse()) {
      const index = result.findIndex(item => item.name === op.resourceId)
      if (op.kind === 'close' && op.state !== 'cancelled') { if (index >= 0) result.splice(index, 1); continue }
      if (lifecycleEnded(op)) continue
      const lifecycle = op.state === 'attention' ? 'attention' : op.kind === 'create' ? 'preparing' : 'closing'
      if (index >= 0) result[index] = { ...result[index], lifecycle }
      else result.push({ name: op.resourceId, label: op.intent.name || op.resourceId, parent: op.intent.parent, cwd: op.receipts.workspace?.result?.path || op.intent.path || op.intent.dir, lastActivity: op.acceptedAt / 1000, dormant: false, running: false, waiting: false, lifecycle })
    }
    return operations.value.length ? result : snapshot.value
  }, [snapshot.value, operations.value])
  return { ...snapshot, value, closingNames }
}
