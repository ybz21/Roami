export type ManagedKind = 'skills' | 'cli' | 'mcp'
export type ManagedEntry = { name: string; description?: string; text?: string; argv?: string[]; cwd?: string; schema?: unknown; config?: Record<string, unknown>; argumentMode?: 'json' | 'argv'; files?: Record<string, string>; origin?: { source: string; id: string; version: string; url: string } }
export type ManagedCatalog = Record<ManagedKind, Record<string, ManagedEntry>>
export const MAX_IMPORT_BYTES = 65536

export function parseCapability(kind: ManagedKind, text: string): Record<string, unknown> {
  if (new TextEncoder().encode(text).length > MAX_IMPORT_BYTES) throw new Error('CAPABILITY_IMPORT_TOO_LARGE')
  if (kind !== 'skills') {
    const value: unknown = JSON.parse(text)
    if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error('INVALID_CAPABILITY_IMPORT')
    return value as Record<string, unknown>
  }
  const normalized = text.replace(/^\uFEFF/, '').replace(/\r\n/g, '\n')
  const frontmatter = normalized.match(/^---\n([\s\S]*?)\n---(?:\n|$)/)?.[1] || ''
  const field = (name: string) => {
    const lines = frontmatter.split('\n')
    const index = lines.findIndex(line => line.startsWith(name + ':'))
    if (index < 0) return ''
    const value = lines[index].slice(name.length + 1).trim()
    if (/^[>|][-+]?$/.test(value)) {
      const body: string[] = []
      for (const line of lines.slice(index + 1)) {
        if (line && !/^\s/.test(line)) break
        body.push(line.trim())
      }
      return body.join(value.startsWith('>') ? ' ' : '\n').trim()
    }
    return value.replace(/^(['"])(.*)\1$/, '$2')
  }
  if (!field('name')) throw new Error('SKILL_NAME_REQUIRED')
  return { name: field('name'), description: field('description'), text: normalized }
}
