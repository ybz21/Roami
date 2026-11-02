import { useEffect, useRef, useState } from 'react'
import { api } from '../../api'
import type { WorkflowArtifact } from './RsiWorkflow'
type ArtifactView = { name: string; text?: string; loading: boolean; failed: boolean; request: WorkflowArtifact }
export function useRsiArtifact(node: string | null, runId: string) {
  const [artifact, setArtifact] = useState<ArtifactView | null>(null)
  const requestId = useRef(0), binding = useRef({ node, runId })
  binding.current = { node, runId }
  const close = () => { requestId.current++; setArtifact(null) }
  useEffect(() => { requestId.current++; setArtifact(null) }, [node, runId])
  useEffect(() => () => { requestId.current++ }, [])
  const open = async (request: WorkflowArtifact) => {
    const id = ++requestId.current
    setArtifact({ ...request, loading: !!request.artifactId, failed: false, request })
    if (!request.artifactId) return
    const current = () => requestId.current === id && binding.current.node === node && binding.current.runId === runId
    try {
      const response = await api('GET', '/agent/improvement/pipeline/runs/' + encodeURIComponent(request.runId || runId) + '/artifacts/' + encodeURIComponent(request.artifactId))
      if (current()) setArtifact({ ...request, ...response.data, request, loading: false, failed: false })
    } catch { if (current()) setArtifact({ ...request, request, loading: false, failed: true }) }
  }
  return { artifact, open, close }
}
