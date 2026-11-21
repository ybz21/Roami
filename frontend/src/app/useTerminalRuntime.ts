import { useEffect, useMemo, useRef, useState } from 'react'
import { useNativeSessionList } from '../components/sessions/native-session-list'
import { nativeSessionRecord, nativeSessionId } from '../components/sessions/session-record'
import { api } from '../api'
import type { useAgentKindInventory } from '../agent-kind'
import { currentNodeId, useCurrentNodeId } from '../components/cluster/node-url'
import { usePageEffect } from '../page-activity'
import { pollWhileVisible } from '../visible-poll'
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

const EMPTY_DETAILS: Record<string, ClaudeInfo> = {}

export function useTerminalRuntime(visible: string | null, inventory: ReturnType<typeof useAgentKindInventory>, isMobile: boolean, desktopClaude = true) {
  const node = useCurrentNodeId()
  const [detailNode, setDetailNode] = useState(node)
  const [fontSize, setFontSize] = useState(13)
  const [statusMap, setStatusMap] = useState<Record<string, TermStatus>>({})
  const sessionOverview = useSessionOverview()
  const native = useNativeSessionList()
  const activityMap = useMemo(() => Object.fromEntries([...sessionOverview.value, ...native.value.map(nativeSessionRecord)].map(item =>
    [item.name, { running: item.running, waiting: item.waiting, identity: 'identity' in item ? item.identity as string | undefined : undefined }])), [sessionOverview.value, native.value])
  const termRefs = useRef<Record<string, TermHandle | null>>({})
  const [claudeMap, setClaudeMap] = useState<Record<string, ClaudeInfo>>({})
  const [claudeView, setClaudeView] = useState<Record<string, boolean>>({})
  const [codexMap, setCodexMap] = useState<Record<string, ClaudeInfo>>({})
  const [codexView, setCodexView] = useState<Record<string, boolean>>({})
  const [openCodeMap, setOpenCodeMap] = useState<Record<string, ClaudeInfo>>({})
  const [openCodeView, setOpenCodeView] = useState<Record<string, boolean>>({})

  if (detailNode !== node) {
    setDetailNode(node)
    setClaudeMap(EMPTY_DETAILS); setCodexMap(EMPTY_DETAILS); setOpenCodeMap(EMPTY_DETAILS)
    setClaudeView({}); setCodexView({}); setOpenCodeView({})
  }

  const details = {
    claude: { setMap: setClaudeMap, setView: setClaudeView, defaultRendered: isMobile || desktopClaude },
    codex: { setMap: setCodexMap, setView: setCodexView, defaultRendered: isMobile },
    opencode: { setMap: setOpenCodeMap, setView: setOpenCodeView, defaultRendered: isMobile },
  }
  const detailRefs = useRef(details)
  detailRefs.current = details
  const session = visible ? sessionOverview.value.find(item => item.name === visible) : undefined
  const primary = visible ? inventory.value.kinds[visible] || (!inventory.loaded || inventory.failed ? session?.agent : undefined) : undefined
  const providers = visible && primary ? [primary, ...(inventory.value.alternatives[visible] || [])].join(' ') : ''
  const identity = session?.identity
  const confirmed = inventory.loaded && !inventory.failed
  const remembered = useRef(new Map<string, string>())
  useEffect(() => {
    if (!visible || nativeSessionId(visible)) return
    const names = new Set(providers.split(' '))
    const previous = remembered.current.get(visible)
    const replaced = !!identity && !!previous && previous !== identity
    if (identity) remembered.current.set(visible, identity)
    for (const [kind, detail] of Object.entries(detailRefs.current)) {
      if (replaced || (confirmed && !names.has(kind))) detail.setMap(map => {
        if (!(visible in map)) return map
        const next = { ...map }; delete next[visible]
        return next
      })
    }
  }, [visible, identity, providers, confirmed])

  usePageEffect(() => {
    if (!visible || nativeSessionId(visible) || !providers) return
    const names = providers.split(' ').filter((kind): kind is keyof typeof details =>
      kind === 'claude' || kind === 'codex' || kind === 'opencode')
    if (!names.length) return
    const load = pollWhileVisible(async signal => {
      for (const kind of names) {
        if (signal.aborted || currentNodeId() !== node) return
        const { setMap, setView, defaultRendered } = detailRefs.current[kind]
        const { data } = await api('GET', `/sessions/${encodeURIComponent(visible)}/${kind}`, undefined, { signal })
        if (signal.aborted || currentNodeId() !== node || !data) return
        setMap(m => sameProbe(m[visible], data) ? m : { ...m, [visible]: data })
        if (data.running && defaultRendered) setView(v => visible in v ? v : { ...v, [visible]: true })
      }
    }, 5000)
    return load.stop
  }, [visible, providers, node, identity, isMobile, desktopClaude])

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
  return { fontSize, setFontSize, statusMap, setStatus, activityMap, termRefs, claudeMap, claudeView, setClaudeView, codexMap, codexView, setCodexView, openCodeMap, openCodeView, setOpenCodeView, rename }
}
