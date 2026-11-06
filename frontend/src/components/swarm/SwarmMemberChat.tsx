import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { Spin } from 'antd'
import { api } from '../../api'
import { useI18n } from '../../i18n'
import { useSessionOverview } from '../../session-overview'
import { nodeApi, useCurrentNodeId } from '../cluster/node-url'
import { openAgentPage } from '../agent/agent-page-route'
import type { TaskDetail } from '../agent/agent-task-protocol'
import NativeSession from '../agent/NativeSession'
import CodexChat from '../chat/CodexChat'
import ClaudeChat from '../chat/ClaudeChat'
import OpenCodeChat from '../chat/OpenCodeChat'
import PiChat from '../chat/PiChat'
import Term from '../terminal/Terminal'
import AgentViewToggle from '../terminal/AgentViewToggle'
import { isAgentKind } from '../../agent-kind'
import type { SwarmTeamMember } from './swarm-members'
import type { SwarmSnapshot } from './swarm-protocol'
import { memberDraft, transferMemberDraft } from './swarm-member-draft'
import { memberSession, memberSessionIdentity } from './swarm-member-session'

export default function SwarmMemberChat({ data, member, onMain, onSession, onChanged }: { data: SwarmSnapshot; member: SwarmTeamMember; onMain: () => void; onSession: (id: string) => void; onChanged: () => void }) {
  const { t } = useI18n(), node = useCurrentNodeId(), sessions = useSessionOverview(!data.archived)
  const identity = nodeApi('/agent/swarms/' + data.id) + ':' + memberSessionIdentity(data, member)
  const [loaded, setLoaded] = useState<{ identity: string; detail?: TaskDetail }>({ identity: '' })
  const [retry, setRetry] = useState(0)
  const taskId = member.work?.task_id
  const pendingKey = 'roami.swarm.member.pending:' + nodeApi('/agent/swarms/' + data.id) + ':' + member.id
  const pending = useRef<{ text: string; revision: number; key: string; workId: string } | null>((() => { try { const legacy = memberDraft(data.id, member); const old = legacy && localStorage.getItem(pendingKey + ':migration') !== legacy.raw ? legacy.saved?.pending : null; const saved = JSON.parse(localStorage.getItem(pendingKey) || 'null') || (old?.body?.workId === member.work?.id ? { text: old.body.text, revision: old.body.taskRevision, key: old.key, workId: old.body.workId } : null); return saved && typeof saved.text === 'string' && Number.isInteger(saved.revision) && typeof saved.key === 'string' && typeof saved.workId === 'string' ? saved : null } catch { return null } })())
  useEffect(() => {
    const legacy = memberDraft(data.id, member)
    if (legacy?.saved?.pending?.key !== pending.current?.key || !pending.current) return
    try { localStorage.setItem(pendingKey, JSON.stringify(pending.current)); localStorage.setItem(pendingKey + ':migration', legacy.raw) } catch { /* Retain the original pending command. */ }
  }, [pendingKey])
  const send = async (text: string) => {
    if (!member.work?.task_id || !member.work.revision || !target || data.archived) throw new Error(t('swarm.member.sessionUnavailable'))
    if (!pending.current || pending.current.text !== text || pending.current.workId !== member.work.id) pending.current = { text, revision: member.work.revision, workId: member.work.id, key: crypto.randomUUID() }
    const request = pending.current
    try { localStorage.setItem(pendingKey, JSON.stringify(request)) } catch { /* Keep the in-memory retry key. */ }
    await api('POST', '/agent/swarms/' + encodeURIComponent(data.id) + '/messages', { text: request.text, workId: request.workId, taskRevision: request.revision, commandKey: request.key })
    pending.current = null
    try { localStorage.removeItem(pendingKey) } catch { /* The successful command remains idempotent. */ }
    onChanged()
  }
  useEffect(() => {
    if (!taskId || member.registered?.instance && member.registered.instance.state !== 'assigned' || data.archived) { setLoaded({ identity }); return }
    const controller = new AbortController()
    void api('GET', '/agent/tasks/' + encodeURIComponent(taskId), undefined, { signal: controller.signal }).then(response => {
      if (!controller.signal.aborted) setLoaded({ identity, detail: response.data })
    }).catch(() => { if (!controller.signal.aborted) setLoaded({ identity }) })
    return () => controller.abort()
  }, [identity, retry, data.archived])
  const target = loaded.identity === identity && loaded.detail ? memberSession(data, member, loaded.detail, sessions.failed ? [] : sessions.value) : null
  const loading = loaded.identity !== identity
  return <section className="swarm-member-chat" aria-label={member.name}>
    {loading ? <Spin /> : !target ? <div className="swarm-note" role="status"><p>{t(taskId ? 'swarm.member.sessionUnavailable' : 'swarm.member.unassigned')}</p><div className="swarm-detail-actions">{taskId && <><button type="button" className="tt-act" onClick={() => setRetry(value => value + 1)}>{t('agent.retry')}</button><button type="button" className="tt-act" onClick={() => openAgentPage('tasks', taskId)}>{t('swarm.managed.openTask')}</button></>}<button type="button" className="tt-act" onClick={onMain}>{t('swarm.relations.adjustMain')}</button></div></div> : <>
      {target.kind === 'native' ? <><div className="swarm-member-session-actions"><button type="button" className="tt-act" onClick={() => openAgentPage('session', target.id)}>{t('swarm.managed.openSession')}</button></div><NativeSession key={target.id} id={target.id} node={node} projects={[]} embedded expectedTask={{ id: target.taskId, projectId: target.projectId, conversationId: member.registered!.instance!.conversationId, branchId: member.registered!.instance!.branchId, revision: member.work!.revision! }} onChanged={onChanged} onSession={onSession} /></> : <MemberCLIChat key={identity} swarmId={data.id} member={member} sessionId={target.id} executor={target.kind} onSend={send} onSession={onSession} />}
    </>}
  </section>
}

function MemberCLIChat({ swarmId, member, sessionId, executor, onSend, onSession }: { swarmId: string; member: SwarmTeamMember; sessionId: string; executor: string; onSend: (text: string) => Promise<void>; onSession: (id: string) => void }) {
  const { t } = useI18n()
  const viewKey = 'roami.swarm.member.view:' + nodeApi('/sessions/' + encodeURIComponent(sessionId))
  const [chat, setChat] = useState(() => { try { return isAgentKind(executor) && localStorage.getItem(viewKey) !== 'terminal' } catch { return isAgentKind(executor) } })
  const [terminalOpened, setTerminalOpened] = useState(!chat)
  const [ready, setReady] = useState(false)
  useLayoutEffect(() => { transferMemberDraft(swarmId, member, sessionId); setReady(true) }, [swarmId, member.id, sessionId])
  if (!ready) return <Spin />
  const toggle = () => {
    setChat(!chat); setTerminalOpened(true)
    try { localStorage.setItem(viewKey, chat ? 'terminal' : 'chat') } catch { /* Retain the current view without storage. */ }
  }
  return <>
    <div className="swarm-member-session-actions">
      {isAgentKind(executor) && <AgentViewToggle agent={executor} chat={chat} onToggle={toggle} />}
      <button type="button" className="tt-act" onClick={() => onSession(sessionId)}>{t('swarm.managed.openSession')}</button>
    </div>
    <div className="swarm-member-session-view">
      {terminalOpened && <div className="swarm-member-terminal" style={{ visibility: chat ? 'hidden' : 'visible', pointerEvents: chat ? 'none' : 'auto' }} aria-hidden={chat}>
        <Term name={sessionId} fontSize={Number.parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--fs-sm'))} active={!chat} restore={false} />
      </div>}
      {chat && (executor === 'codex' ? <CodexChat name={sessionId} onSend={onSend} /> : executor === 'claude' ? <ClaudeChat name={sessionId} onSend={onSend} /> : executor === 'pi' ? <PiChat name={sessionId} onSend={onSend} /> : <OpenCodeChat name={sessionId} onSend={onSend} />)}
    </div>
  </>
}
