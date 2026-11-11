import { parseCapability } from './capability-format'

export function skillDocument(text: string, description?: string) {
  const normalized = text.replace(/^\uFEFF/, '').replace(/\r\n/g, '\n')
  const body = normalized.replace(/^---\n[\s\S]*?\n---(?:\n|$)/, '').trim()
  let summary = description || ''
  if (!summary) {
    try { summary = String(parseCapability('skills', normalized).description || '') } catch { /* A document without metadata still has a readable body. */ }
  }
  return { body, summary }
}

export function skillFileText(encoded: string) {
  try {
    const bytes = Uint8Array.from(atob(encoded), char => char.charCodeAt(0))
    if (bytes.includes(0)) return null
    return new TextDecoder('utf-8', { fatal: true }).decode(bytes)
  } catch { return null }
}
