import type { ReactNode } from 'react'
import type { ViewLifetime } from './ViewBoundary'

type PageOptions = { lifetime?: ViewLifetime; scroll?: 'page' | 'content'; resource?: string }

// New pages restore snapshots by default; legacy local controllers opt into retention.
export function definePage(content: ReactNode, options: PageOptions = {}) {
  return { content, lifetime: options.lifetime || 'unmount', scroll: options.scroll || 'page', resource: options.resource }
}
