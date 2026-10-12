import type { AgentKind } from './agent-kind'

export type OverviewItem = {
  name: string; label: string; lastActivity: number; dormant: boolean
  projectKey?: string; project?: string; projectDir?: string; worktree?: string; branch?: string
  agent?: AgentKind | ''; running: boolean; waiting: boolean; tail?: string
}
