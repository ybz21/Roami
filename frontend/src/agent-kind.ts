import { useEffect, useState } from 'react'
import { api } from './api'

export type AgentKind = 'claude' | 'codex' | 'opencode' | 'pi'

export const isAgentKind = (value: unknown): value is AgentKind =>
  value === 'claude' || value === 'codex' || value === 'opencode' || value === 'pi'

export const agentName = (kind: AgentKind): string =>
  ({ claude: 'Claude', codex: 'Codex', opencode: 'OpenCode', pi: 'Pi' })[kind]

export function useAgentKinds(): Record<string, AgentKind> {
  const [kinds, setKinds] = useState<Record<string, AgentKind>>({})
  useEffect(() => {
    let stopped = false
    const load = () => api('GET', '/sessions/agents').then((response) => {
      if (stopped) return
      const next: Record<string, AgentKind> = {}
      for (const [name, kind] of Object.entries(response?.data || {})) {
        if (isAgentKind(kind)) next[name] = kind
      }
      setKinds((current) => {
        const names = Object.keys(next)
        return names.length === Object.keys(current).length && names.every((name) => current[name] === next[name])
          ? current : next
      })
    }).catch(() => {})
    load()
    const timer = setInterval(load, 6000)
    return () => { stopped = true; clearInterval(timer) }
  }, [])
  return kinds
}
