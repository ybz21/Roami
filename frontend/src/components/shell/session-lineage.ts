import type { TreeSession, TreeTask } from './task-tree'

export type SessionBranch = {
  session: TreeSession
  task: TreeTask | null
  children: SessionBranch[]
}

/** Parent links organize navigation; each session keeps its own workspace target. */
export function sessionBranches(entries: { session: TreeSession; task: TreeTask | null }[]): SessionBranch[] {
  const nodes = new Map(entries.map(entry => [entry.session.name, { ...entry, children: [] } as SessionBranch]))
  const roots: SessionBranch[] = []
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
