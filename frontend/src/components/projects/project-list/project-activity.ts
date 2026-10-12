import type { OverviewItem } from '../../../session-overview'
import type { Proj, ProjSession } from './project-model'

export function mergeProjectActivity(projects: Proj[], items: OverviewItem[] | null): Proj[] {
  if (!items) return projects
  const byProject = new Map<string, OverviewItem[]>()
  const byName = new Map(items.map((item) => [item.name, item]))
  for (const item of items) {
    if (!item.projectKey) continue
    const group = byProject.get(item.projectKey) || []
    group.push(item)
    byProject.set(item.projectKey, group)
  }
  return projects.map((project) => {
    const sessions = byProject.get(project.key) || []
    const waiting = sessions.filter((item) => item.waiting)
    const needs: ProjSession[] = waiting.map((item) => ({
      name: item.name, label: item.label, attached: false,
      running: false, waiting: true, agent: item.agent || undefined,
      lastActivity: item.lastActivity, branch: item.branch, tail: item.tail,
    }))
    return {
      ...project,
      running: sessions.filter((item) => item.running).length,
      waiting: waiting.length,
      needs,
      top: project.top?.map((session) => {
        const item = byName.get(session.name)
        return item ? { ...session, running: item.running, waiting: item.waiting, agent: item.agent || undefined } : session
      }) || project.top,
    }
  })
}
