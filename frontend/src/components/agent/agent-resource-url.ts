import { nodePath } from '../cluster/node-url'

export function agentResourceUrl(href: string, originNode: string | null): string {
  // Older reports used filesystem paths; navigating to those paths loads the app shell.
  if (/^\/(?:home|root|Users|tmp|private|var|opt|srv|mnt|media|workspace|workspaces)\//.test(href)) {
    return nodePath('/api/file' + href, originNode)
  }
  if (!/^\/api\/(?:agent\/artifacts\/|file(?:[/?#]|$))/.test(href)) return href
  return nodePath(href, originNode)
}
