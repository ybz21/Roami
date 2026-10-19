export async function waitForClusterRecovery(timeoutMs = 30000, intervalMs = 1500) {
  const abort = new AbortController()
  const timeout = setTimeout(() => abort.abort(), timeoutMs)
  try {
    while (!abort.signal.aborted) {
      await new Promise<void>(resolve => {
        const timer = setTimeout(done, intervalMs)
        function done() { clearTimeout(timer); abort.signal.removeEventListener('abort', done); resolve() }
        abort.signal.addEventListener('abort', done, { once: true })
      })
      if (abort.signal.aborted) break
      try {
        const response = await fetch('/api/version', { cache: 'no-store', signal: abort.signal })
        if (response.ok) return
      } catch { /* Recovery can include refused connections. */ }
    }
    throw new Error('CLUSTER_RECOVERY_TIMEOUT')
  } finally { clearTimeout(timeout) }
}

export async function hubConfiguration(method = 'GET', body?: unknown) {
  const response = await fetch('/api/cluster/config', {
    method, cache: 'no-store',
    ...(body === undefined ? {} : { headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }),
  })
  const result = await response.json()
  if (!response.ok) throw new Error(result?.error?.message || result?.error?.code || `HTTP ${response.status}`)
  return result
}
