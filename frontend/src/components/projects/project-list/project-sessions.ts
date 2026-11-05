import type { Proj } from './project-model'
import { nativeSessionName, nativeSessionRecord, type NativeSessionRecord } from '../../sessions/session-record'

export function mergeProjectSessions(projects: Proj[], sessions: NativeSessionRecord[]): Proj[] {
  return projects.map(project => {
    const owned = sessions.filter(session => session.projectId === project.key).map(nativeSessionRecord)
    if (!owned.length) return project
    const top = [...(project.top || []), ...owned.map(session => ({ ...session, attached: false }))]
      .sort((a, b) => b.lastActivity - a.lastActivity || a.name.localeCompare(b.name)).slice(0, 3)
    return { ...project, sessions: project.sessions + owned.length, running: (project.running || 0) + owned.filter(session => session.running).length, lastActivity: Math.max(project.lastActivity, ...owned.map(session => session.lastActivity)), top }
  })
}


export function mergeWorktreeSessions<T extends { path: string; sessions?: { session: string }[] | null }>(worktrees: T[], native: NativeSessionRecord[]): T[] {
  return worktrees.map(worktree => {
    const owned = native.filter(session => session.directory === worktree.path)
    if (!owned.length) return worktree
    const sessions = [...worktree.sessions || []]
    for (const record of owned) {
      const name = nativeSessionName(record.nativeSessionId)
      if (!sessions.some(session => session.session === name)) sessions.push({ session: name })
    }
    return { ...worktree, sessions }
  })
}
