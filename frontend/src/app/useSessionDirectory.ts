import { useEffect, useMemo, useRef, useState } from 'react'
import { useNativeSessionList } from '../components/sessions/native-session-list'
import { nativeSessionName, nativeSessionRecord } from '../components/sessions/session-record'
import { isAgentKind, type AgentKind } from '../agent-kind'
import { api } from '../api'
import { isInfraSession } from '../components/sessions/infra-session'
import { setSessionLabels } from '../components/sessions/session-label'

export function useSessionDirectory() {
  const [cliIds, setSessIds] = useState<{ byId: Record<string, string>; byName: Record<string, string> } | null>(null)
  const native = useNativeSessionList()
  const [cliSessions, setSessList] = useState<{ name: string; label?: string; lastActivity?: number; agent?: AgentKind; parent?: string }[]>([])
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
        const names: { name: string; label?: string; lastActivity?: number; agent?: AgentKind; parent?: string }[] = []
        for (const s of Array.isArray(list) ? list : []) {
          if (s?.name && isInfraSession(s.name)) continue
          if (s?.id && s?.name) { byId[s.id] = s.name; byName[s.name] = s.id }
          if (s?.name) names.push({ name: s.name, label: s.label || undefined, lastActivity: s.lastActivity || undefined, agent: isAgentKind(s.agent) ? s.agent : undefined, parent: s.parent || undefined })
        }
        const ids = Object.keys(byId)
        setSessIds(current => current && ids.length === Object.keys(current.byId).length && ids.every(id => current.byId[id] === byId[id]) ? current : { byId, byName })
        setSessListLoaded(true)
        setSessList((cur) => (cur.length === names.length && cur.every((x, i) => x.name === names[i].name && x.label === names[i].label && x.lastActivity === names[i].lastActivity && x.agent === names[i].agent && x.parent === names[i].parent) ? cur : names))
      }).catch(() => { if (!stop) setSessIds((m) => m || { byId: {}, byName: {} }) }) // 拉不到也要放行还原，别把标签卡在空白
    }
    sessReload.current = load
    load()
    const t = setInterval(load, 5000)
    return () => { stop = true; clearInterval(t); sessReload.current = null }
  }, [])

  const nativeNames = native.value.map(record => nativeSessionName(record.nativeSessionId)).sort().join('\n')
  const sessIds = useMemo(() => {
    if (!cliIds) return null
    const byId = { ...cliIds.byId }, byName = { ...cliIds.byName }
    for (const name of nativeNames.split('\n').filter(Boolean)) { byId[name] = name; byName[name] = name }
    return { byId, byName }
  }, [cliIds, nativeNames])
  const sessList = useMemo(() => [...cliSessions, ...native.value.map(nativeSessionRecord)], [cliSessions, native.value])
  useEffect(() => { setSessionLabels(Object.fromEntries(sessList.map(session => [session.name, session.label || session.name]))) }, [sessList])
  const rename = (oldName: string, newName: string) => setSessIds((m) => {
    const id = m?.byName[oldName]
    if (!m || !id) return m
    const { [oldName]: _drop, ...rest } = m.byName
    return { byId: { ...m.byId, [id]: newName }, byName: { ...rest, [newName]: id } }
  })
  return { sessIds, sessList, nativeSessionsLoaded: native.loaded, sessListLoaded, rename, refresh: () => sessReload.current?.() }
}
export type SessionDirectory = ReturnType<typeof useSessionDirectory>
