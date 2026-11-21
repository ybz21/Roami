import { useState } from 'react'
import { hasRenderedChat } from '../../agent-kind'
import { useI18n } from '../../i18n'
import { nodeApi } from '../cluster/node-url'
import Term from '../terminal/Terminal'
import AgentViewToggle from '../terminal/AgentViewToggle'
import ClaudeChat from './ClaudeChat'
import CodexChat from './CodexChat'
import OpenCodeChat from './OpenCodeChat'
import PiChat from './PiChat'
import type { NativeMainTurn } from './types'
import './executor-session-chat.css'

export default function ExecutorSessionChat({ sessionId, sessionIdentity, executor, storageKey, mainTurn, onSend, onCommand, onSession }: {
  sessionId: string; sessionIdentity?: string; executor: string; storageKey?: string; mainTurn?: NativeMainTurn | null
  onSend: (text: string) => Promise<void>; onCommand?: (text: string) => Promise<void>; onSession?: (id: string) => void
}) {
  const { t } = useI18n()
  const viewKey = storageKey || 'roami.executor.view:' + nodeApi('/sessions/' + encodeURIComponent(sessionId))
  const [chat, setChat] = useState(() => { try { return hasRenderedChat(executor) && localStorage.getItem(viewKey) !== 'terminal' } catch { return hasRenderedChat(executor) } })
  const [terminalOpened, setTerminalOpened] = useState(!chat)
  const toggle = () => {
    setChat(!chat); setTerminalOpened(true)
    try { localStorage.setItem(viewKey, chat ? 'terminal' : 'chat') } catch { /* Retain the current view without storage. */ }
  }
  return <div className="executor-session-chat">
    <div className="executor-session-actions">
      {hasRenderedChat(executor) && <AgentViewToggle agent={executor} chat={chat} onToggle={toggle} />}
      {onSession && <button type="button" className="tt-act" onClick={() => onSession(sessionId)}>{t('agent.openSession')}</button>}
    </div>
    <div className="executor-session-view">
      {terminalOpened && <div className="executor-session-terminal" style={{ visibility: chat ? 'hidden' : 'visible', pointerEvents: chat ? 'none' : 'auto' }} aria-hidden={chat}>
        <Term name={sessionId} fontSize={Number.parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--fs-sm'))} active={!chat} restore={false} />
      </div>}
      {chat && (executor === 'codex' ? <CodexChat name={sessionId} sessionIdentity={sessionIdentity} mainTurn={mainTurn} onSend={onSend} onCommand={onCommand} /> : executor === 'claude' ? <ClaudeChat name={sessionId} sessionIdentity={sessionIdentity} mainTurn={mainTurn} onSend={onSend} onCommand={onCommand} /> : executor === 'pi' ? <PiChat name={sessionId} sessionIdentity={sessionIdentity} onSend={onSend} /> : <OpenCodeChat name={sessionId} sessionIdentity={sessionIdentity} onSend={onSend} />)}
    </div>
  </div>
}
