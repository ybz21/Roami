import type { AgentKind } from './agent-kind'
import { createSessionPoll } from './session-poll'

export type OverviewItem = {
  name: string; label: string; lastActivity: number; dormant: boolean
  projectKey?: string; project?: string; projectDir?: string; worktree?: string; branch?: string
  agent?: AgentKind | ''; running: boolean; waiting: boolean; tail?: string
}

export const useSessionOverview = createSessionPoll<OverviewItem[]>('/sessions/overview', 5000, [], response => response?.data?.items || [])
