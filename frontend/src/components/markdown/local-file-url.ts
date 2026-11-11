// Normalize legacy file URIs before Markdown removes unsupported protocols.
export function localFileUrlPath(href: string): string | undefined {
  if (!/^file:/i.test(href) || /[\\\u0000-\u0020]/.test(href)) return undefined
  try {
    const url = new URL(href)
    if (url.protocol !== 'file:' || url.host || url.search || /%(?:00|2f|5c)/i.test(url.pathname)) return undefined
    const path = decodeURIComponent(url.pathname)
    if (!/^\/(?:home|root|Users|tmp|private|var|opt|srv|mnt|media|workspace|workspaces)\//.test(path)) return undefined
    return path.split('/').map(encodeURIComponent).join('/') + url.hash
  } catch {
    return undefined
  }
}
