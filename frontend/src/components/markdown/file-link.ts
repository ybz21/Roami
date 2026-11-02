export type FileLink = { url: string; name: string; path?: string; resolvePath: boolean; metadataUrl?: string }

export function fileLink(href: string, origin: string, rawEndpoint: string): FileLink | null {
  try {
    const url = new URL(href, origin)
    if (url.origin !== origin || url.searchParams.get('dl')) return null
    const artifact = url.pathname.match(/^(\/(?:n\/[^/]+\/)?api\/agent\/artifacts\/[^/]+)\/content$/)
    if (artifact) return { url: url.href, name: 'Roami', resolvePath: false, metadataUrl: url.origin + artifact[1] }
    const match = url.pathname.match(/^\/(?:n\/[^/]+\/)?api\/file(?:\/(?:raw|serve))?(\/.*)?$/)
    if (!match) return null
    const path = url.searchParams.get('path')
    const name = (path || decodeURIComponent(match[1] || '')).split('/').filter(Boolean).pop() || 'Roami'
    // FileView addresses the current node; other-node links must keep their original URL.
    const currentFile = url.pathname === rawEndpoint || url.pathname === rawEndpoint.replace(/\/raw$/, '')
    const base = rawEndpoint.replace(/\/raw$/, '')
    return { url: url.href, name, path: currentFile && path?.startsWith('/') ? path : undefined, resolvePath: url.pathname.startsWith(base + '/') && !currentFile }
  } catch {
    return null
  }
}
