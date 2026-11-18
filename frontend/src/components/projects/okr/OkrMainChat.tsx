import { useCallback, useEffect, useRef, useState } from 'react'
import { App, Button, Spin } from 'antd'
import { api } from '../../../api'
import { useI18n } from '../../../i18n'
import { useLayout } from '../../../layout'
import { CloseIcon } from '../../../icons'
import { currentNodeId, useCurrentNodeId } from '../../cluster/node-url'
import type { OkrMessageReference } from '../../agent/notification-destination'
import AgentConversation from '../../agent/AgentConversation'
import { agentFailure } from '../../agent/agent-request-failure'
import ExecutorSessionChat from '../../chat/ExecutorSessionChat'
import { useSessionOverview } from '../../../session-overview'
import { nativeMainRequest, transferMainDraft, type NativeMainRequest } from './okr-main-native-draft'
import MobileSubPage from '../../MobileSubPage'
import type { SwarmSnapshot } from '../../swarm/swarm-protocol'
import type { Configuration, Workspace } from './okr-workspace'
import { displayOkrMessage, prepareOkrContext } from './okr-conversation-context'

type Props = {
  embedded?: boolean; expectedConversationId?: string
  reference?: OkrMessageReference; onClearReference?: () => void; onSession?: (id: string) => void
  projectId: string; projectDir?: string; draft: Configuration; workspace: Workspace | null; onClose: () => void; onUpdated?: () => void
}
export default function OkrMainChat(props: Props) {
  const node = useCurrentNodeId()
  return <OkrMainInstance key={`${node}:${props.projectId}:${props.workspace?.swarm || ''}:${props.reference?.conversationId || ''}:${props.expectedConversationId || ''}`} {...props} />
}
function OkrMainInstance({ embedded = false, expectedConversationId, reference: sourceReference, onClearReference, projectId, draft, workspace, onClose, onUpdated, onSession }: Props) {
  const { t } = useI18n()
  const { message } = App.useApp()
  const [execution, setExecution] = useState<{ executor: 'claude' | 'codex'; model: string; sessionId: string; generation: number } | null>()
  const sessions = useSessionOverview(!!execution)
  const nativePending = useRef<Record<string, NativeMainRequest>>({})
  const { phone, size } = useLayout()
  const secondaryPage = !embedded && (phone || size !== 'large')
  const node = useCurrentNodeId()
  const [cid, setCID] = useState('')
  const [localReference, setLocalReference] = useState<OkrMessageReference>()
  const reference = localReference || sourceReference
  const draftKey = `roami.okr.main.draft:${node || 'local'}:${projectId}`
  const [failed, setFailed] = useState(false)
  const [upgradeRequired, setUpgradeRequired] = useState(false)
  const [restoring, setRestoring] = useState(true)
  const identity = JSON.stringify([node, projectId, workspace?.swarm, expectedConversationId, reference?.conversationId, reference?.branchId])
  const latest = useRef(identity); latest.current = identity
  const current = () => alive.current && latest.current === identity && currentNodeId() === node
  const create = useRef({ requestKey: crypto.randomUUID(), title: t('okr.chatTitle'), projectId })
  const contextSupported = useRef(false)
  const conversation = useRef('')
  const acquiring = useRef<Promise<string> | null>(null)
  const alive = useRef(true)
  const acquire = useCallback(() => {
    if (conversation.current) return Promise.resolve(conversation.current)
    if (acquiring.current) return acquiring.current
    acquiring.current = (async () => {
      const status = await api('GET', '/agent/status')
      if (!current()) throw new Error('Conversation changed')
      contextSupported.current = status.data?.okrMessageContext === true
      let id: string
      if (reference && status.data?.conversationIdentity === true) {
        const response = await api('GET', '/agent/conversations/' + encodeURIComponent(reference.conversationId) + '/identity')
        const identity = response.data
        if (identity?.kind !== 'project_main' || identity.projectId !== projectId || identity.conversationId !== reference.conversationId) throw new Error('Referenced conversation changed')
        id = identity.conversationId
      } else if (status.data?.projectOkrMain === true && !reference) {
        const response = await api('POST', '/agent/conversations', create.current)
        id = response.data?.id
      } else if (workspace?.swarm.startsWith('sw-')) {
        const [team, home, directory] = await Promise.all([
          api('GET', '/agent/swarms/' + encodeURIComponent(workspace.swarm)),
          api('POST', '/agent/main-conversation'),
          api('GET', '/agent/swarms'),
        ])
        id = team.data?.mainConversationId
        if (reference && id !== reference.conversationId) throw new Error('Referenced conversation changed')
        if (!id || team.data.archived || team.data.target?.projectId !== projectId || id === home.data?.id
          || !Array.isArray(directory.data) || (directory.data as SwarmSnapshot[]).some(item => item.mainConversationId === id && item.target?.projectId !== projectId)) throw new Error('Project Main unavailable')
      } else {
        if (alive.current) setUpgradeRequired(true)
        throw new Error('Project Main upgrade required')
      }
      if (!id || !current() || expectedConversationId && id !== expectedConversationId) throw new Error('Project Main unavailable')
      if (status.data?.projectMainExecution === true) {
        const response = await api('GET', '/agent/conversations/' + encodeURIComponent(id) + '/execution')
        if (!current() || response.data?.conversationId !== id) throw new Error('Project Main changed')
        const value = response.data
        if (value.executor === 'roami') setExecution(null)
        else {
          if (!['claude', 'codex'].includes(value.executor) || value.projectId !== projectId || typeof value.sessionId !== 'string' || !value.sessionId || typeof value.model !== 'string' || !value.model || !Number.isInteger(value.generation) || value.generation < 1) throw new Error('Project Main unavailable')
          transferMainDraft(draftKey, value.sessionId)
          setExecution(value)
        }
      } else setExecution(null)
      conversation.current = id; setCID(id)
      return id
    })().finally(() => { acquiring.current = null })
    return acquiring.current
  }, [projectId, workspace?.swarm, reference?.conversationId, expectedConversationId, identity])
  useEffect(() => {
    alive.current = true
    void acquire().catch(() => { if (alive.current) setFailed(true) }).finally(() => { if (alive.current) setRestoring(false) })
    return () => { alive.current = false }
  }, [acquire])
  const sendNative = async (text: string, command = false) => {
    const id = await acquire()
    if (!current() || !execution) throw new Error(t('agent.requestFailed'))
    const scope = command ? draftKey + ':command:' + text : draftKey
    let request = nativePending.current[scope]
    try {
      if (!request || request.cid !== id || request.text !== text) request = nativeMainRequest(scope, id, text, command ? undefined : prepareOkrContext(text, draft, workspace, contextSupported.current))
      nativePending.current[scope] = request
    } catch (error) { throw new Error(agentFailure(error, t)) }
    try { localStorage.setItem(scope + ':native-pending', JSON.stringify(request)) } catch { /* Keep the retry identity in memory. */ }
    let data: any
    try {
      const response = await api('POST', '/agent/conversations/' + encodeURIComponent(id) + '/messages', { requestKey: request.key, text, ...(request.okrContext ? { okrContext: request.okrContext } : {}) })
      data = response.data
    } catch (error) { throw new Error(agentFailure(error, t)) }
    if (!current()) return
    if (data.kind === 'model' || data.kind === 'status') message.info(data.model)
    delete nativePending.current[scope]
    try {
      localStorage.removeItem(scope + ':native-pending')
      if (!command && localStorage.getItem(draftKey) === text) localStorage.removeItem(draftKey)
      const old = JSON.parse(localStorage.getItem(scope + ':pending') || 'null')
      if (old?.key === request.key) localStorage.removeItem(scope + ':pending')
    } catch { /* The successful host request remains idempotent. */ }
    onUpdated?.()
  }
  const nativeSession = execution && sessions.value.filter(session => session.name === execution.sessionId && session.agent === execution.executor && session.projectKey === projectId && !session.dormant && !session.lifecycle)
  const nativeReady = !!nativeSession && nativeSession.length === 1 && !sessions.failed
  const content = <aside className="okr-main-chat" data-embedded={embedded} data-conversation-id={cid}>
    {!secondaryPage && !embedded && <header className="okr-chat-head"><strong>{t('okr.chatTitle')}</strong><button type="button" className="tt-act" aria-label={t('okr.endChat')} onClick={onClose}><CloseIcon /></button></header>}
    {restoring && <Spin />}
    {(failed || upgradeRequired) && <div className="okr-error" role="alert"><p>{t(upgradeRequired ? 'okr.agentUpgradeRequired' : 'agent.requestFailed')}</p><Button onClick={() => { setFailed(false); setUpgradeRequired(false); void acquire().catch(() => setFailed(true)) }}>{t('inbox.retry')}</Button></div>}
    {execution && !reference?.messageId ? nativeReady ? <ExecutorSessionChat key={execution.sessionId} sessionId={execution.sessionId} executor={execution.executor} onSend={sendNative} onCommand={async command => {
      if (!['/model', '/status', '/stop', '/help', '/tasks', '/memory'].includes(command)) throw new Error(t('okr.nativeCommand'))
      await sendNative(command, true)
    }} onSession={onSession} /> : !sessions.loaded ? <Spin /> : <p role="status">{t('swarm.member.sessionUnavailable')}</p> : <AgentConversation cid={cid} branch={reference?.branchId || ''} focusMessage={reference?.messageId || ''} node={node} onSession={onSession} select={(conversationId, branchId = '', messageId = '') => { if (conversationId === cid) setLocalReference({ conversationId, branchId, messageId }) }} project={{
      nativeModel: execution?.model, modelControlsDisabled: execution === undefined,
      draftKey, ensureConversation: acquire, isCurrent: current,
      prepareContext: text => prepareOkrContext(text, draft, workspace, contextSupported.current), displayText: displayOkrMessage,
      onUpdated, onCurrentBranch: () => { setLocalReference(undefined); onClearReference?.() }, inputLabel: t('okr.chatInput'), sendLabel: t('okr.send'),
      placeholder: t('chat.sendTo', { name: t('swarm.conversation.main') }),
    }} />}
  </aside>
  return secondaryPage ? <MobileSubPage title={t('okr.chatTitle')} onBack={onClose}>{content}</MobileSubPage> : content
}
