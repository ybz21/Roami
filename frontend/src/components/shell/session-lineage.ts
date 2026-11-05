import type { TreeSession, TreeTask } from './task-tree'

export type SessionBranch<S extends { name: string; parent?: string } = TreeSession> = {
  session: S
  task: TreeTask | null
  children: SessionBranch<S>[]
}

/** Parent links organize navigation; each session keeps its own workspace target. */
export function sessionBranches<S extends { name: string; parent?: string }>(entries: { session: S; task: TreeTask | null }[]): SessionBranch<S>[] {
  const nodes = new Map(entries.map(entry => [entry.session.name, { ...entry, children: [] } as SessionBranch<S>]))
  const roots: SessionBranch<S>[] = []
  for (const node of nodes.values()) {
    const parent = nodes.get(node.session.parent || '')
    const seen = new Set([node.session.name])
    let ancestor = parent
    while (ancestor && !seen.has(ancestor.session.name)) {
      seen.add(ancestor.session.name)
      ancestor = nodes.get(ancestor.session.parent || '')
    }
    // Incomplete or cyclic records stay reachable as roots.
    if (!parent || ancestor) roots.push(node)
    else parent.children.push(node)
  }
  return roots
}

/** Visit parents before descendants, retaining the input order of active families. */
export function sessionLineage<S extends { name: string; parent?: string }>(sessions: S[]) {
  const order = new Map(sessions.map((session, index) => [session.name, index]))
  const rank = (branch: SessionBranch<S>): number => Math.min(order.get(branch.session.name)!, ...branch.children.map(rank))
  const rows: { session: S; depth: number }[] = []
  const visit = (branches: SessionBranch<S>[], depth: number) => {
    for (const branch of branches.sort((a, b) => rank(a) - rank(b))) {
      rows.push({ session: branch.session, depth })
      visit(branch.children, depth + 1)
    }
  }
  visit(sessionBranches(sessions.map(session => ({ session, task: null }))), 0)
  return rows
}
