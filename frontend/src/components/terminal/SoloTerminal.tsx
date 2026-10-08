// ── 独立单终端页：新浏览器标签全屏打开单个会话（hash 路由 #/term/name）──
import { useEffect, useRef, useState } from 'react'
import { TermHandle, TermStatus } from './Terminal'
import { api } from '../../api'
import TerminalPane from './TerminalPane'
import { type ClaudeInfo } from './claude-info'
import { OPEN_FILE_INTENT, requestIntent } from '../../intents'
import { sessionDisplay, setSessionLabels, useSessionLabel } from '../sessions/session-label'
import { type PaletteActions } from '../shell/palette'
import { GlobalSearch } from '../shell/palette'
import { useAgentKinds } from '../../agent-kind'

export default function SoloTerminal({ name }: { name: string }) {
  const agentKinds = useAgentKinds()
  const [fontSize, setFontSize] = useState(13)
  const [statusMap, setStatusMap] = useState<Record<string, TermStatus>>({})
  const [claudeMap, setClaudeMap] = useState<Record<string, ClaudeInfo>>({})
  const [claudeView, setClaudeView] = useState<Record<string, boolean>>({})
  const [codexMap, setCodexMap] = useState<Record<string, ClaudeInfo>>({})
  const [codexView, setCodexView] = useState<Record<string, boolean>>({})
  const termRefs = useRef<Record<string, TermHandle | null>>({})
  const label = useSessionLabel(name)

  // 独立页没有会话列表轮询，自己拉一次拿展示名（标题要显示「名字（id）」）
  useEffect(() => {
    api('GET', '/sessions').then((list) => {
      setSessionLabels(Object.fromEntries((Array.isArray(list) ? list : []).filter((s: any) => s?.name && s?.label).map((s: any) => [s.name, s.label])))
    }).catch(() => {})
  }, [])
  useEffect(() => { document.title = `Roami · ${sessionDisplay(name) || name}` }, [name, label])
  useEffect(() => {
    let stop = false
    const check = async () => {
      try { const r = await api('GET', `/sessions/${encodeURIComponent(name)}/claude`); if (!stop) setClaudeMap((m) => ({ ...m, [name]: r.data })) } catch {}
      try { const r = await api('GET', `/sessions/${encodeURIComponent(name)}/codex`); if (!stop) setCodexMap((m) => ({ ...m, [name]: r.data })) } catch {}
    }
    check()
    const t = setInterval(check, 5000)
    return () => { stop = true; clearInterval(t) }
  }, [name])

  // 独立页也要能搜（⌘K）。这页没有侧栏也没有顶栏，本地条目就只有「当前这个会话」；
  // 结果照样从后端来。打开方式换成同一个标签内换 hash——独立页本身就是同一个 SPA，
  // 所以「打开文件」的意图（intents）也照常能被文件页接住。
  const paletteActions: PaletteActions = {
    openRoute: (hash: string) => { location.hash = hash },
    openSession: (n: string) => { location.hash = '#/term/' + encodeURIComponent(n) },
    openFile: (path: string) => { location.hash = '#/files'; requestIntent(OPEN_FILE_INTENT, { path }) },
  }

  return (
    <div style={{ position: 'fixed', inset: 0, background: 'var(--bg-term)', display: 'flex', flexDirection: 'column' }}>
      <GlobalSearch items={[]} actions={paletteActions} />
      <TerminalPane
        terms={[name]} active={name} setActive={() => {}} closeTerm={() => window.close()}
        fontSize={fontSize} setFontSize={setFontSize}
        statusMap={statusMap} setStatus={(n, s) => setStatusMap((m) => ({ ...m, [n]: s }))}
        termRefs={termRefs} sendKey={(seq) => termRefs.current[name]?.send(seq)}
        claudeMap={claudeMap} claudeView={claudeView} setClaudeView={setClaudeView}
        codexMap={codexMap} codexView={codexView} setCodexView={setCodexView}
        agentKinds={agentKinds}
        onRename={(_, newName) => { location.hash = '#/term/' + encodeURIComponent(newName) }}
        fileDock="left"
      />
    </div>
  )
}
