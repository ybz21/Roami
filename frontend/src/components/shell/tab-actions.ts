export type TabCloseScope = 'others' | 'left' | 'right'

export function tabCloseTargets(order: string[], pinned: ReadonlySet<string>, target: string, scope: TabCloseScope): string[] {
  const at = order.indexOf(target)
  if (at < 0) return []
  return order.filter((id, i) => id !== target && !pinned.has(id) && (
    scope === 'others' || (scope === 'left' ? i < at : i > at)
  ))
}
