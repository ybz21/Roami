// ── 独立单终端页：新浏览器标签全屏打开单个会话（hash 路由 #/term/name）──
import { nativeSessionId } from '../sessions/session-record'
import { useEffect } from 'react'
import { api } from '../../api'
import TerminalPane from './TerminalPane'
import { OPEN_FILE_INTENT, requestIntent } from '../../intents'
import { sessionDisplay, setSessionLabels, useSessionLabel } from '../sessions/session-label'
import { type PaletteActions } from '../shell/palette'
import { GlobalSearch } from '../shell/palette'
import { useAgentKindInventory } from '../../agent-kind'
import { useLayout } from '../../layout'
import { useTerminalRuntime } from '../../app/useTerminalRuntime'

export default function SoloTerminal({ name }: { name: string }) {
  const inventory = useAgentKindInventory()
  const agentKinds = inventory.value.kinds
  const { phone } = useLayout()
  const runtime = useTerminalRuntime(name, inventory, phone, false)
  const label = useSessionLabel(name)

  // 独立页没有会话列表轮询，自己拉一次拿展示名（标题要显示「名字（id）」）
  useEffect(() => {
    if (nativeSessionId(name)) return
    api('GET', '/sessions').then((list) => {
      setSessionLabels(Object.fromEntries((Array.isArray(list) ? list : []).filter((s: any) => s?.name && s?.label).map((s: any) => [s.name, s.label])))
    }).catch(() => {})
  }, [name])
  useEffect(() => { document.title = `Roami · ${sessionDisplay(name) || name}` }, [name, label])
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
        {...runtime}
        sendKey={(seq) => runtime.termRefs.current[name]?.send(seq)}
        agentKinds={agentKinds}
        onOpenSession={paletteActions.openSession}
        onRename={(_, newName) => { location.hash = '#/term/' + encodeURIComponent(newName) }}
        fileDock="left"
      />
    </div>
  )
}
