import type { AgentKind } from '../../agent-kind'

export type OverviewItem = {
  name: string; label: string; lastActivity: number; dormant: boolean
  projectKey?: string; project?: string; projectDir?: string; worktree?: string; branch?: string
  agent?: AgentKind | ''; running: boolean; waiting: boolean; tail?: string
}

let overview: OverviewItem[] | null = null

export function readMobileOverview(): OverviewItem[] | null {
  return overview
}

export function writeMobileOverview(items: OverviewItem[]): OverviewItem[] {
  overview = items
  return items
}
