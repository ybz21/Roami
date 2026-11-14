import { useEffect, useState } from 'react'
import { api } from '../../api'
import type { ModelCatalog } from './model-hub-api'

export type SourceModelDetail = { id: string; name?: string; context?: number; output?: number; inputModalities?: string[]; outputModalities?: string[]; tools?: boolean; reasoning?: boolean; inputPrice?: number; outputPrice?: number }
export type SourceDirectory = { models: SourceModelDetail[]; error?: string }
export const advertisedFree = (model: SourceModelDetail) => model.inputPrice === 0 && model.outputPrice === 0

export function useSourceDirectory(catalog: ModelCatalog | null, sourceId: string, active: boolean) {
  const [result, setResult] = useState<{ key: string; value: SourceDirectory } | null>(null)
  const [attempt, setAttempt] = useState(0)
  const source = catalog?.sources.find(row => row.id === sourceId)
  const revision = catalog?.revision || '', key = revision + '/' + sourceId
  const cached = result?.key === key ? result.value : undefined
  useEffect(() => {
    if (!active || !source || cached) return
    const abort = new AbortController()
    void api('POST', '/agent/model-gateway/catalog/discover', { source, revision }, { signal: abort.signal }).then(({ data }) => {
      if (abort.signal.aborted) return
      const details = new Map<string, SourceModelDetail>((data.details || []).map((row: SourceModelDetail) => [row.id, row]))
      setResult({ key, value: { models: (data.models || []).map((id: string) => details.get(id) || { id }) } })
    }).catch(() => { if (!abort.signal.aborted) setResult({ key, value: { models: [], error: 'hub.directory.failed' } }) })
    return () => abort.abort()
  }, [active, source, revision, key, cached, attempt])
  return { value: cached, loading: active && !!source && !cached, retry: () => { setResult(null); setAttempt(value => value + 1) } }
}
