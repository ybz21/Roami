import { currentNodeId } from '../cluster/node-url'

export function artifactPreviewHref(id: string): string {
  const params = new URLSearchParams({ from: location.hash || '#/home' })
  const node = currentNodeId()
  if (node) params.set('node', node)
  return '#/artifact/' + encodeURIComponent(id) + '?' + params
}

export function readArtifactPreviewRoute(hash: string) {
  const [path, query] = hash.split('?')
  const match = path.match(/^#\/artifact\/([^/]+)$/)
  if (!match) return null
  try {
    const id = decodeURIComponent(match[1]), params = new URLSearchParams(query)
    if (!id) return null
    const from = params.get('from') || '#/home'
    return { id, node: params.get('node'), from: /^#\/(home|projects)(?:[/?]|$)/.test(from) ? from : '#/home' }
  } catch { return null }
}
