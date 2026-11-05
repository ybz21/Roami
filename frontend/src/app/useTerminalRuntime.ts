import { useEffect, useMemo, useRef, useState } from 'react'
import { useNativeSessionList } from '../components/sessions/native-session-list'
import { nativeSessionRecord, nativeSessionId } from '../components/sessions/session-record'
import { api } from '../api'
import type { ClaudeInfo } from '../components/terminal/claude-info'
import { TermHandle, TermStatus } from '../components/terminal/Terminal'
import { useSessionOverview } from '../session-overview'

function sameProbe(a: ClaudeInfo | undefined, b: ClaudeInfo | undefined): boolean {
  if (a === b) return true
  if (!a || !b) return false
  const ks = new Set([...Object.keys(a), ...Object.keys(b)])
  for (const k of ks) if (a[k] !== b[k]) return false
  return true
}

export function useTerminalRuntime(terms: string[], isMobile: boolean) {
  const [fontSize, setFontSize] = useState(13)
  const [statusMap, setStatusMap] = useState<Record<string, TermStatus>>({})
  const sessionOverview = useSessionOverview(terms.length > 0)
  const native = useNativeSessionList(terms.length > 0)
  const activityMap = useMemo(() => Object.fromEntries([...sessionOverview.value, ...native.value.map(nativeSessionRecord)].map(item =>
    [item.name, { running: item.running, waiting: item.waiting }])), [sessionOverview.value, native.value])
  const termRefs = useRef<Record<string, TermHandle | null>>({})
  const [claudeMap, setClaudeMap] = useState<Record<string, ClaudeInfo>>({})
  const [claudeView, setClaudeView] = useState<Record<string, boolean>>({})
  const [codexMap, setCodexMap] = useState<Record<string, ClaudeInfo>>({})
  const [codexView, setCodexView] = useState<Record<string, boolean>>({})
  const [openCodeMap, setOpenCodeMap] = useState<Record<string, ClaudeInfo>>({})
  const [openCodeView, setOpenCodeView] = useState<Record<string, boolean>>({})

  const [mobileWaiting, setMobileWaiting] = useState<Record<string, boolean>>({})
  useEffect(() => {
    if (terms.length === 0) return
    let stop = false
    const check = () => {
      if (document.hidden) return
      terms.filter(name => !nativeSessionId(name)).forEach(async (n) => {
        try {
          const r = await api('GET', `/sessions/${encodeURIComponent(n)}/claude`)
          if (stop) return
          setClaudeMap((m) => (sameProbe(m[n], r.data) ? m : { ...m, [n]: r.data }))
          if (r.data?.running) setClaudeView((v) => (n in v ? v : { ...v, [n]: true }))
        } catch { }
        try {
          const r = await api('GET', `/sessions/${encodeURIComponent(n)}/codex`)
          if (stop) return
          setCodexMap((m) => (sameProbe(m[n], r.data) ? m : { ...m, [n]: r.data }))
          if (isMobile && r.data?.running) setCodexView((v) => (n in v ? v : { ...v, [n]: true }))
        } catch { }
        try {
          const r = await api('GET', `/sessions/${encodeURIComponent(n)}/opencode`)
          if (stop) return
          setOpenCodeMap((m) => (sameProbe(m[n], r.data) ? m : { ...m, [n]: r.data }))
          if (isMobile && r.data?.running) setOpenCodeView((v) => (n in v ? v : { ...v, [n]: true }))
        } catch { }
      })
    }
    check()
    const t = setInterval(check, 5000)
    return () => { stop = true; clearInterval(t) }
  }, [terms, isMobile])

  const rename = (oldName: string, newName: string) => {
    setStatusMap((m) => {
      if (!(oldName in m)) return m
      const { [oldName]: oldValue, ...rest } = m
      return { ...rest, [newName]: oldValue }
    })
    setClaudeMap((m) => {
      if (!(oldName in m)) return m
      const { [oldName]: oldValue, ...rest } = m
      return { ...rest, [newName]: oldValue }
    })
    setClaudeView((m) => {
      if (!(oldName in m)) return m
      const { [oldName]: oldValue, ...rest } = m
      return { ...rest, [newName]: oldValue }
    })
    setCodexMap((m) => {
      if (!(oldName in m)) return m
      const { [oldName]: oldValue, ...rest } = m
      return { ...rest, [newName]: oldValue }
    })
    setCodexView((m) => {
      if (!(oldName in m)) return m
      const { [oldName]: oldValue, ...rest } = m
      return { ...rest, [newName]: oldValue }
    })
    setOpenCodeMap((m) => {
      if (!(oldName in m)) return m
      const { [oldName]: oldValue, ...rest } = m
      return { ...rest, [newName]: oldValue }
    })
    setOpenCodeView((m) => {
      if (!(oldName in m)) return m
      const { [oldName]: oldValue, ...rest } = m
      return { ...rest, [newName]: oldValue }
    })
    if (termRefs.current[oldName]) {
      termRefs.current[newName] = termRefs.current[oldName]
      delete termRefs.current[oldName]
    }
  }
  const setStatus = (name: string, status: TermStatus) => setStatusMap((m) => ({ ...m, [name]: status }))
  return { fontSize, setFontSize, statusMap, setStatus, activityMap, termRefs, claudeMap, claudeView, setClaudeView, codexMap, codexView, setCodexView, openCodeMap, openCodeView, setOpenCodeView, mobileWaiting, setMobileWaiting, rename }
}
