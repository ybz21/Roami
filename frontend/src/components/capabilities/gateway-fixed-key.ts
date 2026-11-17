import { useEffect, useRef, useState } from 'react'
import { api } from '../../api'
import { catalogFailure } from './model-hub-api'

export type FixedGatewayKey = { revision: string; hasKey: boolean; suffix: string; id?: string }
const path = '/agent/model-gateway/access-key'
const failure = (cause: any) => cause?.apiError?.code === 'MODEL_GATEWAY_KEY_RESERVED' ? 'hub.gateway.reservedKey' : cause?.apiError?.code === 'INVALID_MODEL_GATEWAY_KEY' ? 'hub.gateway.invalidKey' : catalogFailure(cause)
export function useGatewayFixedKey(active = true) {
  const [view, setView] = useState<FixedGatewayKey | null>(null), [error, setError] = useState(''), [busy, setBusy] = useState(false), [loading, setLoading] = useState(active), [version, setVersion] = useState(0)
  const current = useRef(view), writing = useRef(false)
  current.current = view
  useEffect(() => {
    if (!active) return
    const abort = new AbortController()
    setLoading(true); setError('')
    void api('GET', path, undefined, { signal: abort.signal }).then(({ data }) => { if (!abort.signal.aborted) setView(data) }).catch(cause => { if (!abort.signal.aborted) setError(failure(cause)) }).finally(() => { if (!abort.signal.aborted) setLoading(false) })
    return () => abort.abort()
  }, [active, version])
  const save = async (key?: string) => {
    if (!current.current || writing.current || loading) return false
    writing.current = true; setBusy(true); setError('')
    try {
      const { data } = await api(key === undefined ? 'DELETE' : 'PUT', path, { revision: current.current.revision, ...(key === undefined ? {} : { apiKey: key }) })
      current.current = data; setView(data); return true
    } catch (cause) { setError(failure(cause)); return false }
    finally { writing.current = false; setBusy(false) }
  }
  return { view, error, busy, loading, save, retry: () => { setLoading(true); setVersion(previous => previous + 1) } }
}
export type GatewayFixedKeyController = ReturnType<typeof useGatewayFixedKey>
