import { useEffect, useRef, useState } from 'react'
import { isAgentKind, type AgentKind } from '../agent-kind'
import { api } from '../api'
import { isInfraSession } from '../components/sessions/infra-session'
import { setSessionLabels } from '../components/sessions/session-label'

export function useSessionDirectory() {
  const [sessIds, setSessIds] = useState<{ byId: Record<string, string>; byName: Record<string, string> } | null>(null)
  const [sessList, setSessList] = useState<{ name: string; label?: string; lastActivity?: number; agent?: AgentKind }[]>([])
  const [sessListLoaded, setSessListLoaded] = useState(false)
  const sessReload = useRef<(() => void) | null>(null)
  useEffect(() => {
    let stop = false
    const load = () => {
      if (stop || document.hidden) return Promise.resolve()
      return api('GET', '/sessions').then((list) => {
        if (stop) return
        const byId: Record<string, string> = {}
        const byName: Record<string, string> = {}
        const labels: Record<string, string> = {}
        const names: { name: string; label?: string; lastActivity?: number; agent?: AgentKind }[] = []
        for (const s of Array.isArray(list) ? list : []) {
          if (s?.name && isInfraSession(s.name)) continue
          if (s?.id && s?.name) { byId[s.id] = s.name; byName[s.name] = s.id }
          if (s?.name && s?.label) labels[s.name] = s.label
          if (s?.name) names.push({ name: s.name, label: s.label || undefined, lastActivity: s.lastActivity || undefined, agent: isAgentKind(s.agent) ? s.agent : undefined })
        }
        setSessIds({ byId, byName })
        setSessListLoaded(true)
        setSessList((cur) => (cur.length === names.length && cur.every((x, i) => x.name === names[i].name && x.label === names[i].label && x.lastActivity === names[i].lastActivity && x.agent === names[i].agent) ? cur : names))
        setSessionLabels(labels) // 展示名（@roam_name）：界面显示「名字（id）」，handle 仍是会话名
      }).catch(() => { if (!stop) setSessIds((m) => m || { byId: {}, byName: {} }) }) // 拉不到也要放行还原，别把标签卡在空白
    }
    sessReload.current = load
    load()
    const t = setInterval(load, 5000)
    return () => { stop = true; clearInterval(t); sessReload.current = null }
  }, [])

  const rename = (oldName: string, newName: string) => setSessIds((m) => {
    const id = m?.byName[oldName]
    if (!m || !id) return m
    const { [oldName]: _drop, ...rest } = m.byName
    return { byId: { ...m.byId, [id]: newName }, byName: { ...rest, [newName]: id } }
  })
  return { sessIds, sessList, sessListLoaded, rename, refresh: () => sessReload.current?.() }
}
export type SessionDirectory = ReturnType<typeof useSessionDirectory>
