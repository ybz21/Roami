import { nodePath } from '../cluster/node-url'

export function agentResourceUrl(href: string, originNode: string | null): string {
  if (!/^\/api\/(?:agent\/artifacts\/|file(?:[/?#]|$))/.test(href)) return href
  return nodePath(href, originNode)
}
