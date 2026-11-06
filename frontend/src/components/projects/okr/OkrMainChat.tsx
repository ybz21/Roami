import { useCallback, useEffect, useRef, useState } from 'react'
import { Button, Spin } from 'antd'
import { api } from '../../../api'
import { useI18n } from '../../../i18n'
import { useLayout } from '../../../layout'
import { CloseIcon } from '../../../icons'
import { currentNodeId, useCurrentNodeId } from '../../cluster/node-url'
import type { OkrMessageReference } from '../../agent/notification-destination'
import AgentConversation from '../../agent/AgentConversation'
import MobileSubPage from '../../MobileSubPage'
import type { SwarmSnapshot } from '../../swarm/swarm-protocol'
import type { Configuration, Workspace } from './okr-workspace'
import { displayOkrMessage, prepareOkrMessage } from './okr-conversation-context'

type Props = {
  embedded?: boolean; expectedConversationId?: string
  reference?: OkrMessageReference; onClearReference?: () => void; onSession?: (id: string) => void
  projectId: string; projectDir?: string; draft: Configuration; workspace: Workspace | null; onClose: () => void; onUpdated?: () => void
}
export default function OkrMainChat(props: Props) {
  const node = useCurrentNodeId()
  return <OkrMainInstance key={`${node}:${props.projectId}:${props.workspace?.swarm || ''}:${props.reference?.conversationId || ''}:${props.expectedConversationId || ''}`} {...props} />
}
function OkrMainInstance({ embedded = false, expectedConversationId, reference: sourceReference, onClearReference, projectId, projectDir, draft, workspace, onClose, onUpdated, onSession }: Props) {
  const { t } = useI18n()
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
  const conversation = useRef('')
  const acquiring = useRef<Promise<string> | null>(null)
  const alive = useRef(true)
  const acquire = useCallback(() => {
    if (conversation.current) return Promise.resolve(conversation.current)
    if (acquiring.current) return acquiring.current
    acquiring.current = (async () => {
      const status = await api('GET', '/agent/status')
      if (!current()) throw new Error('Conversation changed')
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
  const content = <aside className="okr-main-chat" data-embedded={embedded} data-conversation-id={cid}>
    {!secondaryPage && !embedded && <header className="okr-chat-head"><strong>{t('okr.chatTitle')}</strong><button type="button" className="tt-act" aria-label={t('okr.endChat')} onClick={onClose}><CloseIcon /></button></header>}
    {restoring && <Spin />}
    {(failed || upgradeRequired) && <div className="okr-error" role="alert"><p>{t(upgradeRequired ? 'okr.agentUpgradeRequired' : 'agent.requestFailed')}</p><Button onClick={() => { setFailed(false); setUpgradeRequired(false); void acquire().catch(() => setFailed(true)) }}>{t('inbox.retry')}</Button></div>}
    <AgentConversation cid={cid} branch={reference?.branchId || ''} focusMessage={reference?.messageId || ''} node={node} onSession={onSession} select={(conversationId, branchId = '', messageId = '') => { if (conversationId === cid) setLocalReference({ conversationId, branchId, messageId }) }} project={{
      draftKey, ensureConversation: acquire, isCurrent: current,
      prepareMessage: text => prepareOkrMessage(text, projectId, projectDir, draft, workspace), displayText: displayOkrMessage,
      onUpdated, onCurrentBranch: () => { setLocalReference(undefined); onClearReference?.() }, inputLabel: t('okr.chatInput'), sendLabel: t('okr.send'),
      placeholder: t('chat.sendTo', { name: t('swarm.conversation.main') }),
    }} />
  </aside>
  return secondaryPage ? <MobileSubPage title={t('okr.chatTitle')} onBack={onClose}>{content}</MobileSubPage> : content
}
