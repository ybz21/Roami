export type MemoryRecord = {
  id: string; title: string; body: string; state: 'active' | 'candidate' | 'conflict' | 'superseded'
  kind?: string; project_id?: string; conversation_id?: string; conversation_title?: string
  task_id?: string; task_title?: string; day_key?: string; timezone?: string; updated_ms?: number
  created_ms?: number; revision?: number; source_count?: number; relation?: 'revision' | 'merged'
}
export type MemoryEvidence = {
  sourceKey: string; text?: string; unchanged?: boolean; available?: boolean; truncated?: boolean
  conversationId?: string; conversationTitle?: string; branchId?: string; messageId?: string
  role?: string; kind?: string; createdMs?: number
}
export type MemoryDetail = { record: MemoryRecord; current: MemoryRecord | null; currentVersionId?: string; evidence: MemoryEvidence[]; canConfirm: boolean }
export type MemoryCatalog = { items: MemoryRecord[]; total: number; limit: number; offset: number }
export type MemoryFacets = Record<'project' | 'conversation' | 'task', { id: string; name: string | null }[]> & { reviewCount?: number }
export type MemoryScope = 'all' | 'personal' | 'project' | 'conversation' | 'task'
export type MemoryView = 'saved' | 'review' | 'activity'
export function memoryScope(item: MemoryRecord): Exclude<MemoryScope, 'all'> {
  return item.task_id ? 'task' : item.project_id ? 'project' : item.conversation_id ? 'conversation' : 'personal'
}
export function dailyMemory(item: MemoryRecord): { counts: Record<string, number>; scopeKey?: string } | null {
  if (!item.day_key) return null
  try { const value = JSON.parse(item.body); return value && typeof value.counts === 'object' && value.counts !== null ? value : { counts: {} } } catch { return { counts: {} } }
}
