import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '../../api'
import { nodeApi } from '../cluster/node-url'

export type AgentAttachment = { id: string; name: string; sizeBytes: number; mimeType: string; previewState?: string }
export type DraftAttachment = { key: string; name: string; sizeBytes: number; state: 'uploading' | 'ready' | 'failed'; reference?: AgentAttachment; file?: File }
const LIMIT = 6, MAX_BYTES = 10 * 1024 * 1024
export function useAgentAttachments(scope: string) {
  const [drafts, setDrafts] = useState<Record<string, DraftAttachment[]>>({})
  const draftsRef = useRef(drafts); draftsRef.current = drafts
  const mounted = useRef(true)
  useEffect(() => { mounted.current = true; return () => { mounted.current = false } }, [])
  const key = 'roami.agent.attachments.' + scope
  const update = useCallback((scopeKey: string, apply: (old: DraftAttachment[]) => DraftAttachment[]) => {
    if (!mounted.current) return
    const old = draftsRef.current
    const items = apply(old[scopeKey] || [])
    try { const saved = items.filter(x => x.state === 'ready'); if (saved.length) localStorage.setItem('roami.agent.attachments.' + scopeKey, JSON.stringify(saved)); else localStorage.removeItem('roami.agent.attachments.' + scopeKey) } catch {}
    const next = { ...old, [scopeKey]: items }; draftsRef.current = next; setDrafts(next)
  }, [])
  useEffect(() => {
    if (draftsRef.current[scope]) return
    try {
      const saved = JSON.parse(localStorage.getItem(key) || '[]')
      if (Array.isArray(saved)) update(scope, () => saved.filter(x => x?.state === 'ready' && typeof x.reference?.id === 'string' && typeof x.name === 'string').slice(0, LIMIT))
    } catch {}
  }, [key, scope, update])
  const upload = async (item: DraftAttachment, ownerScope: string) => {
    if (!item.file) return
    update(ownerScope, list => list.map(x => x.key === item.key ? { ...x, state: 'uploading' } : x))
    try {
      const query = new URLSearchParams({ filename: item.file.name, requestKey: item.key })
      const result = await fetch(nodeApi('/agent/attachments?' + query), { method: 'POST', body: item.file, headers: { 'Content-Type': 'application/octet-stream' } })
      if (!result.ok) throw Error('ATTACHMENT_UPLOAD_FAILED')
      const { data } = await result.json()
      const reference = { id: data.id, name: data.name, sizeBytes: data.sizeBytes, mimeType: data.mimeType, previewState: data.metadata?.preview?.state }
      const destination = Object.keys(draftsRef.current).find(key => draftsRef.current[key].some(x => x.key === item.key)) || ownerScope
      update(destination, list => list.map(x => x.key === item.key ? { ...x, reference, state: 'ready', file: undefined } : x))
    } catch {
      const destination = Object.keys(draftsRef.current).find(key => draftsRef.current[key].some(x => x.key === item.key)) || ownerScope
      update(destination, list => list.map(x => x.key === item.key ? { ...x, state: 'failed' } : x))
    }
  }
  const add = async (files: File[]) => {
    const old = draftsRef.current[scope] || []
    if (files.some(f => f.size > MAX_BYTES || !f.name || f.name.length > 180) || old.length + files.length > LIMIT) return false
    const items: DraftAttachment[] = files.map(file => ({ key: crypto.randomUUID(), name: file.name, sizeBytes: file.size, state: 'uploading', file }))
    update(scope, list => [...list, ...items]); await Promise.all(items.map(item => upload(item, scope))); return true
  }
  const remove = async (item: DraftAttachment) => {
    if (item.state === 'uploading') return
    if (item.reference) await api('DELETE', '/agent/attachments/' + encodeURIComponent(item.reference.id))
    update(scope, list => list.filter(x => x.key !== item.key))
  }
  const clear = (ownerScope = scope) => update(ownerScope, () => [])
  const transfer = (destination: string) => {
    const items = draftsRef.current[scope] || []
    update(scope, () => [])
    update(destination, () => items)
  }
  const items = drafts[scope] || []
  return { items, add, remove, transfer, retry: (item: DraftAttachment) => upload(item, scope), clear, blocked: items.some(x => x.state !== 'ready'), ids: items.flatMap(x => x.reference ? [x.reference.id] : []) }
}
