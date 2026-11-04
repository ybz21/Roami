import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { nodeApi } from '../cluster/node-url'
import { App, Button, Input, Select, Spin } from 'antd'
import { api } from '../../api'
import { useLayout } from '../../layout'
import { useI18n } from '../../i18n'
import { ChevronLeft, CloseIcon, ArrowUp } from '../../icons'
import MobileSubPage from '../MobileSubPage'
import Markdown from '../markdown/Markdown'
import type { TaskDetail } from '../agent/agent-task-protocol'
import { openAgentPage } from '../agent/agent-page-route'
import { useSwarmSnapshot } from './useSwarmSnapshot'
import SwarmStudio from './SwarmStudio'
import SwarmRelations from './SwarmRelations'
import TeamMemory from './TeamMemory'
import LegacySwarmHistory from './LegacySwarmHistory'
import ExternalAcceptance from './ExternalAcceptance'
import { artifactPreviewHref } from '../agent/artifact-preview-route'
import { swarmColumn, swarmStateToken, type SwarmSnapshot, type SwarmWork } from './swarm-protocol'
import './swarm.css'

function State({ state }: { state: string }) {
  const { t } = useI18n()
  return <span className="swarm-state" style={{ color: `var(${swarmStateToken(state)})` }}>{t(`swarm.managed.state.${state}`)}</span>
}
export default function ManagedSwarm({ id, onBack, openTerm, embedded = false, projectId, onManage }: { id: string; onBack: () => void; openTerm: (id: string) => void; embedded?: boolean; projectId?: string; onManage?: () => void }) {
  const { data, error, missing, refresh } = useSwarmSnapshot(id), { t, locale } = useI18n(), { phone } = useLayout(), { message, modal } = App.useApp()
  const panelKey = 'roami.swarm.panel:' + nodeApi('/agent/swarms/' + id)
  const [selected, setSelected] = useState('main'), [tab, setTab] = useState(() => localStorage.getItem(panelKey) === 'board' ? 'board' : 'studio'), [detail, setDetail] = useState<string | null>(null), [busy, setBusy] = useState(false)
  const [chatRecipientRequest, setChatRecipientRequest] = useState<{ id: string; nonce: number }>()
  const recipientNonce = useRef(0)
  const [memoryOpen, setMemoryOpen] = useState(false), [teamOpen, setTeamOpen] = useState(false)
  const controlKey = useRef<{ action: string; revision: number; key: string } | null>(null)
  useEffect(() => { localStorage.setItem(panelKey, tab) }, [tab, panelKey])
  const positions = useRef<Record<string, number>>({})
  const switchTab = (next: string) => {
    const panel = document.querySelector<HTMLElement>(tab === 'chat' ? '.swarm-chat-log' : '.swarm-main-area')
    positions.current[tab] = panel?.scrollTop || 0; setTab(next)
  }
  useLayoutEffect(() => {
    const panel = document.querySelector<HTMLElement>(tab === 'chat' ? '.swarm-chat-log' : '.swarm-main-area')
    if (panel) panel.scrollTop = positions.current[tab] || 0
  }, [tab])
  const blockedCount = data?.work.filter(item => swarmColumn(item.state) === 'blocked').length || 0
  const nodes = useMemo(() => data ? [{ id: 'main', name: 'Roami Main', executor: 'roami', main: true, state: data.mainState === 'failed' ? 'failed' : data.paused ? 'idle' : data.mainState === 'queued' ? 'preparing' : data.mainState === 'running' ? 'running' : 'idle' }, ...data.work.map(w => ({ id: w.id, name: w.member_name, executor: w.executor, state: w.state }))] : [], [data?.work, data?.paused, data?.mainState])
  const control = async (action: string) => {
    if (!data) return
    if (!controlKey.current || controlKey.current.action !== action || controlKey.current.revision !== data.revision) controlKey.current = { action, revision: data.revision, key: crypto.randomUUID() }
    setBusy(true)
    try { await api('POST', `/agent/swarms/${encodeURIComponent(id)}/control`, { action, expectedRevision: data.revision, commandKey: controlKey.current.key }); controlKey.current = null; await refresh() }
    catch { message.error(t('swarm.managed.actionFailed')) } finally { setBusy(false) }
  }
  useEffect(() => {
    if (!phone && detail && tab === 'board') document.querySelector('.swarm-work-detail')?.scrollIntoView?.({ block: 'nearest' })
  }, [detail, tab, phone])
  if (!data && missing && projectId) return <LegacySwarmHistory projectId={projectId} onManage={onManage || onBack} />
  if (!data) return <div className="swarm-loading">{missing ? <><p role="alert">{t('swarm.managed.relinkTeam')}</p><button type="button" className="tt-act" onClick={onBack}>{t('swarm.managed.selectTeam')}</button></> : error ? <><p role="alert">{t('swarm.managed.unavailable')}</p><button type="button" className="tt-act" onClick={() => void refresh()}>{t('agent.retry')}</button></> : <Spin />}</div>
  const work = data.work.find(item => item.id === detail)
  const openWork = (item: SwarmWork) => { setSelected(item.id); setDetail(item.id); if (!phone) switchTab('board') }
  const openChat = (recipient: string) => { setSelected(recipient); setDetail(null); setChatRecipientRequest({ id: recipient, nonce: ++recipientNonce.current }); switchTab('studio'); if (phone) setTeamOpen(false) }
  const view = <div className="swarm-work-detail">
    {work && <>{!phone && <div className="swarm-panel-head"><h3>{work.title}</h3><button type="button" className="tt-act" aria-label={t('common.close')} onClick={() => setDetail(null)}><CloseIcon /></button></div>}<State state={work.state} />
      {work.evidence?.verification?.state === 'missing' && <p role="status">{t('swarm.managed.evidenceMissing')}</p>}
      {Boolean(work.evidence?.artifacts.length) && <section><h4>{t('swarm.managed.outputs')}</h4>{work.evidence!.artifacts.map(item => <p key={item.id}><a href={artifactPreviewHref(item.id)} target={phone ? undefined : '_blank'} rel="noopener noreferrer">{item.name}</a></p>)}</section>}
      {work.attempt?.summary && <details><summary>{t('swarm.managed.report')}</summary><Markdown>{work.attempt.summary}</Markdown></details>}
      {work.state === 'waiting_user' && work.deliverables?.some(item => item.kind === 'external_action') && <ExternalAcceptance key={work.id + ':' + work.revision} work={work} onAccepted={refresh} />}
      <details className="swarm-description"><summary>{t('swarm.managed.instructions')}</summary><Markdown>{work.goal}</Markdown><h4>{t('swarm.managed.acceptance')}</h4><Markdown>{work.acceptance}</Markdown></details>
      {work.dispatch_error && <p role="alert">{t(work.dispatch_error === 'SWARM_DEPENDENCY_NOT_VERIFIED' ? 'swarm.managed.dependencyBlocked' : 'swarm.managed.dispatchFailed')}</p>}
      {work.dependencies.length > 0 && <section><h4>{t('swarm.managed.dependencies')}</h4>{work.dependencies.map(dep => <p key={dep.upstreamId}>{data.work.find(item => item.id === dep.upstreamId)?.title}</p>)}</section>}
      <div className="swarm-detail-actions">{work.task_id && <button type="button" className="tt-act" onClick={() => openAgentPage('tasks', work.task_id!)}>{t('swarm.managed.openTask')}</button>}{work.attempt?.sessionId && <button type="button" className="tt-act" onClick={() => openTerm(work.attempt!.sessionId!)}>{t('swarm.managed.openSession')}</button>}</div>
    </>}
  </div>
  return <div className="swarm-managed" data-tab={tab} data-team-open={teamOpen}>
    <header className="tt-pagehead"><div className="swarm-page-identity">{!phone && !embedded && <button type="button" className="tt-act" onClick={onBack} aria-label={t('common.back')}><ChevronLeft /></button>}<h2>{data.name}</h2><State state={data.state} />{data.paused && <span className="swarm-note">{t('swarm.managed.paused')}</span>}</div><div className="acts"><Button size="small" loading={busy} disabled={data.archived} onClick={() => void control(data.paused ? 'resume' : 'pause')}>{t(data.paused ? 'swarm.managed.resume' : 'swarm.managed.pause')}</Button><details className="swarm-controls"><summary>{t('common.more')}</summary><button type="button" className="tt-act" onClick={() => { void refresh().then(() => setMemoryOpen(true)) }}>{t('swarm.managed.memory')}</button><button type="button" className="tt-act danger" disabled={busy || data.archived} onClick={() => modal.confirm({ title: t('swarm.managed.stopTitle'), content: t('swarm.managed.stopHint'), onOk: () => control('stop') })}>{t('swarm.managed.stop')}</button><button type="button" className="tt-act" disabled={busy || data.archived} onClick={() => void control('archive')}>{t('swarm.archive')}</button></details></div></header>
    {error && <div className="swarm-stream-error" role="status">{t('swarm.managed.reconnecting')}</div>}
    {data.mainState === 'failed' && <p role="alert" className="swarm-stream-error">{t('swarm.managed.mainFailed')}</p>}
    {data.archived && <p className="swarm-note">{t('swarm.managed.archived')}</p>}
    {!memoryOpen && <nav className="swarm-tabs" aria-label={t('swarm.managed.workspace')}>{['studio', 'board'].map(key => <button type="button" key={key} aria-pressed={tab === key} onClick={() => switchTab(key)}>{t(`swarm.managed.tab.${key}`)}{(key === 'board' ? blockedCount : 0) > 0 && <span className="swarm-tab-count">{new Intl.NumberFormat(locale).format(blockedCount)}</span>}</button>)}{phone && tab === 'studio' && <button type="button" aria-expanded={teamOpen} onClick={() => setTeamOpen(value => !value)}>{t('swarm.chat.team')}</button>}</nav>}
    <div className="swarm-managed-grid" hidden={memoryOpen && !phone}>
      <div className="swarm-main-area">
        <div className="swarm-studio-area"><SwarmRelations data={data} selected={selected} onSelect={id => { const item = data.work.find(w => w.id === id); item?.task_id ? openChat(id) : item ? openWork(item) : openChat('main') }} onMain={() => openChat('main')} onWork={item => item.task_id ? openAgentPage('tasks', item.task_id) : openWork(item)} onChat={item => openChat(item.task_id ? item.id : 'main')} /><SwarmStudio active={tab === 'studio' && !memoryOpen && (!phone || teamOpen)} nodes={nodes} selected={selected} onSelect={id => { const item = data.work.find(w => w.id === id); item?.task_id ? openChat(id) : item ? openWork(item) : openChat('main') }} /></div>
        <section className="swarm-board" aria-label={t('swarm.board')}>{!data.work.length ? <p className="swarm-note">{t('swarm.managed.planning')}</p> : <div className="swarm-board-columns">{['backlog', 'doing', 'blocked', 'review', 'done'].map(column => <section key={column}><h3>{t(`swarm.board.col.${column}`)}</h3>{data.work.filter(item => swarmColumn(item.state) === column).map(item => <button type="button" className="swarm-work-card" key={item.id} aria-pressed={selected === item.id} onClick={() => openWork(item)}><strong>{item.title}</strong><small>{item.member_name} · {item.executor === 'native' ? 'Roami' : item.executor}</small><State state={item.state} /></button>)}</section>)}</div>}</section>
        {!phone && work && view}
      </div>
      <SwarmChat key={data.id} data={data} recipientRequest={chatRecipientRequest} selected={selected} onSelect={setSelected} onWork={openWork} onSession={openTerm} onSent={refresh} />
    </div>
    {memoryOpen && (phone ? <MobileSubPage title={t('swarm.managed.memory')} onBack={() => setMemoryOpen(false)}><TeamMemory data={data} onReload={refresh} onSaved={async () => { await refresh(); setMemoryOpen(false) }} /></MobileSubPage> : <><div className="swarm-panel-head"><strong>{t('swarm.managed.memory')}</strong><button type="button" className="tt-act" aria-label={t('common.close')} onClick={() => setMemoryOpen(false)}><CloseIcon /></button></div><TeamMemory data={data} onReload={refresh} onSaved={async () => { await refresh(); setMemoryOpen(false) }} /></>)}
    {phone && work && <MobileSubPage title={work.title} onBack={() => setDetail(null)}>{view}</MobileSubPage>}
  </div>
}

function SwarmChat({ data, recipientRequest, selected, onSelect, onWork, onSession, onSent }: { data: SwarmSnapshot; recipientRequest?: { id: string; nonce: number }; selected: string; onSelect: (id: string) => void; onWork: (item: SwarmWork) => void; onSession: (id: string) => void; onSent: () => Promise<void> }) {
  const { t, locale } = useI18n(), { message } = App.useApp()
  const storageKey = 'roami.swarm.draft:' + nodeApi('/agent/swarms/' + data.id)
  const [saved] = useState(() => { try { return JSON.parse(localStorage.getItem(storageKey) || '{}') } catch { return {} } })
  const [scope, setScope] = useState<string>(saved.scope || 'group'), [opening, setOpening] = useState(false)
  const alive = useRef(true), openingRef = useRef(false), latestScope = useRef(scope); latestScope.current = scope
  useEffect(() => { alive.current = true; return () => { alive.current = false } }, [])
  const [draft, setDraft] = useState<string>(saved.draft || ''), [recipient, setRecipient] = useState<string>(saved.recipient || 'main'), [sending, setSending] = useState(false)
  const sendKey = useRef<{ key: string; payload: string; body?: { text: string; workId?: string; taskRevision?: number | null } }>(saved.pending || { key: crypto.randomUUID(), payload: '' })
  useEffect(() => { localStorage.setItem(storageKey, JSON.stringify({ draft, recipient, scope, pending: sendKey.current })) }, [draft, recipient, scope, sending, storageKey])
  const editDraft = (text: string) => {
    setDraft(text)
    const mention = /^\s*@([^\s]+)(?:\s+|$)/.exec(text)?.[1]
    const id = ['leader', 'main'].includes(mention?.toLowerCase() || '') ? 'main' : data.work.find(item => item.task_id && item.member_name === mention)?.id
    if (id) { setRecipient(id); setScope(id); onSelect(id) }
  }
  const chooseRecipient = (id: string) => {
    const member = data.work.find(item => item.id === id && item.task_id)
    if (id !== 'main' && !member) return
    setRecipient(id); setScope(id); onSelect(id)
    setDraft(text => text.replace(/^(\s*)@[^\s]+(?=\s|$)/, (_match, space: string) => space + '@' + (id === 'main' ? 'leader' : member!.member_name)))
  }
  useEffect(() => {
    if (!recipientRequest) return
    chooseRecipient(recipientRequest.id)
    document.querySelector<HTMLTextAreaElement>('.swarm-chat textarea')?.focus()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [recipientRequest?.id, recipientRequest?.nonce])
  const messages = useMemo(() => [
    ...data.posts.map(post => ({ id: 'post:' + post.id, taskId: post.taskId, author: post.author === 'human' ? t('swarm.chat.you') : post.author === 'main' ? 'Roami Main' : post.author, text: post.text, time: post.createdMs, pending: post.deliveryState === 'pending', work: post.taskId ? data.work.find(item => item.task_id === post.taskId) : undefined })),
    ...data.mainMessages.filter(item => item.text).map(item => ({ id: item.id, taskId: undefined as string | null | undefined, author: 'Roami Main', text: item.text, time: item.createdMs, pending: false, work: undefined as SwarmWork | undefined })),
    ...data.work.filter(item => item.attempt?.summary).map(item => ({ id: 'result:' + item.id, taskId: item.task_id, author: item.member_name, text: item.attempt!.summary!, time: item.attempt?.finishedMs || 0, pending: false, work: item })),
  ].sort((a, b) => a.time - b.time), [data.posts, data.mainMessages, data.work, t])
  const currentWork = data.work.find(item => item.id === scope && item.task_id)
  const latestWork = useRef(currentWork); latestWork.current = currentWork
  const thread = scope === 'main' || currentWork ? scope : 'group'
  const visibleMessages = messages.filter(item => thread === 'group' || thread === 'main' && !item.taskId || item.work?.id === thread)
  const enterConversation = async () => {
    if (!currentWork?.task_id || openingRef.current) return
    openingRef.current = true; setOpening(true)
    const taskId = currentWork.task_id, requestedScope = scope, requestedRevision = currentWork.revision, requestedRun = currentWork.attempt?.runId
    const fallback = () => openAgentPage('tasks', taskId)
    try {
      const response = await api('GET', '/agent/tasks/' + encodeURIComponent(taskId))
      const detail: TaskDetail = response.data
      if (!alive.current || latestScope.current !== requestedScope) return
      const observed = latestWork.current
      if (!observed) return
      if (observed.task_id !== taskId || observed.revision !== requestedRevision || observed.attempt?.runId !== requestedRun) { if (observed.task_id) openAgentPage('tasks', observed.task_id); return }
      const attempt = detail.attempts[0]
      if (detail.task.id !== taskId || detail.task.revision !== currentWork.revision || !attempt || attempt.revision !== detail.task.revision || attempt.id !== currentWork.attempt?.runId || ['closing', 'closed'].includes(detail.sessionClosure?.state || '')) { fallback(); return }
      if (detail.task.nativeSession) openAgentPage('session', detail.task.nativeSession.id)
      else if (attempt.sessionId) onSession(attempt.sessionId)
      else fallback()
    } catch { if (alive.current && latestScope.current === requestedScope) fallback() }
    finally { openingRef.current = false; if (alive.current) setOpening(false) }
  }
  const send = async () => {
    if (!draft.trim() || sending) return
    const mention = /^\s*@([^\s]+)(?:\s+|$)/.exec(draft)?.[1]
    const destination = mention?.toLowerCase() === 'leader' || mention?.toLowerCase() === 'main' ? 'main' : mention ? data.work.find(item => item.member_name === mention)?.id ?? recipient : recipient
    const work = data.work.find(item => item.id === destination)
    if (destination !== 'main' && (!work?.task_id || !work.revision)) { message.error(t('swarm.managed.sendFailed')); return }
    let body = { text: draft.trim(), ...(work ? { workId: work.id, taskRevision: work.revision } : {}) }
    const payload = JSON.stringify({ text: body.text, workId: body.workId })
    if (sendKey.current.payload && payload !== sendKey.current.payload) sendKey.current = { key: crypto.randomUUID(), payload: '' }
    if (sendKey.current.payload === payload && sendKey.current.body) body = sendKey.current.body
    else sendKey.current.body = body
    sendKey.current.payload = payload; setSending(true)
    try { await api('POST', `/agent/swarms/${data.id}/messages`, { ...body, commandKey: sendKey.current.key }); setDraft(''); sendKey.current = { key: crypto.randomUUID(), payload: '' }; await onSent() }
    catch { message.error(t('swarm.managed.sendFailed')) } finally { setSending(false) }
  }
  return <section className="swarm-chat" aria-label={t('swarm.managed.tab.chat')}>
    <nav className="swarm-chat-threads" aria-label={t('swarm.chat.conversations')}>
      <button type="button" className="tt-act" aria-pressed={thread === 'group'} onClick={() => { chooseRecipient('main'); setScope('group') }}>{t('swarm.managed.tab.chat')}</button>
      {data.mainConversationId && <button type="button" className="tt-act" aria-pressed={thread === 'main'} aria-label={t('swarm.chat.withMain')} onClick={() => chooseRecipient('main')}>Roami Main</button>}
      {data.work.map(item => <button type="button" className="tt-act" key={item.id} aria-pressed={thread === item.id} aria-label={t(item.task_id ? 'swarm.chat.withMember' : 'swarm.chat.memberPlan', { name: item.member_name })} onClick={() => item.task_id ? chooseRecipient(item.id) : onWork(item)}>{item.member_name}{!item.task_id && <small>{t('swarm.chat.notStarted')}</small>}</button>)}
    </nav>
    <div className="swarm-chat-context"><span>{t('swarm.chat.teamVisible')}</span>{currentWork && <div className="swarm-detail-actions"><button type="button" className="tt-act" onClick={() => openAgentPage('tasks', currentWork.task_id!)}>{t('swarm.relations.openWork')}</button><button type="button" className="tt-act" disabled={opening} onClick={() => void enterConversation()}>{t('swarm.managed.openSession')}</button></div>}</div>
    <div className="swarm-chat-log" role="log" aria-label={t('swarm.managed.messages')}>
    {!visibleMessages.length && <p className="swarm-note">{t('swarm.managed.chatEmpty')}</p>}
    {visibleMessages.map(item => <article className="swarm-chat-message" key={item.id} data-selected={item.work?.id === selected}><header><button type="button" className="tt-act" onClick={() => chooseRecipient(item.work?.id || 'main')}>{item.author}</button>{item.time > 0 && <time>{new Intl.DateTimeFormat(locale, { hour: 'numeric', minute: '2-digit' }).format(item.time)}</time>}</header>{item.pending && <span className="swarm-note">{t('swarm.managed.deliveryPending')}</span>}{item.id.startsWith('result:') ? <details><summary>{t('swarm.managed.report')}</summary><Markdown>{item.text}</Markdown></details> : <Markdown>{item.text}</Markdown>}{item.work && <div className="swarm-chat-task-actions"><State state={item.work.state} /><button type="button" className="tt-act" onClick={() => onWork(item.work!)}>{t('swarm.managed.openTask')}</button><button type="button" className="tt-act" onClick={() => { chooseRecipient(item.work!.id); document.querySelector<HTMLTextAreaElement>('.swarm-chat textarea')?.focus() }}>{t('swarm.managed.replyMember')}</button></div>}</article>)}
  </div><div className="tt-composer swarm-chat-composer"><Input.TextArea variant="borderless" aria-label={t('swarm.managed.messages')} value={draft} onChange={e => editDraft(e.target.value)} rows={3} disabled={data.archived || sending} placeholder={t('swarm.managed.chatPlaceholder')} />{/^\s*@[^\s]*$/.test(draft) && <div className="swarm-detail-actions">{[{ name: 'leader', id: 'main' }, ...data.work.filter(item => item.task_id).map(item => ({ name: item.member_name, id: item.id }))].filter(item => item.name.toLowerCase().startsWith(draft.trim().slice(1).toLowerCase())).map(item => <button type="button" key={item.id} className="tt-act" onClick={() => { setRecipient(item.id); setDraft('@' + item.name + ' '); document.querySelector<HTMLTextAreaElement>('.swarm-chat textarea')?.focus() }}>{'@' + item.name}</button>)}</div>}<div className="tt-cbar"><div className="tt-cgrp"><label htmlFor="swarm-chat-recipient">{t('swarm.managed.recipient')}</label><Select id="swarm-chat-recipient" value={recipient} onChange={chooseRecipient} disabled={data.archived || sending} options={[{ value: 'main', label: '@leader · ' + t('swarm.managed.leader') }, ...data.work.filter(item => item.task_id).map(item => ({ value: item.id, label: '@' + item.member_name }))]} /></div><div className="tt-cend"><button type="button" className="tt-send" aria-label={t('common.send')} disabled={sending || data.archived || !draft.trim()} onClick={() => void send()}>{sending ? <Spin size="small" /> : <ArrowUp size={18} />}</button></div></div><p className="swarm-note">{t('swarm.managed.chatHint')}</p></div></section>
}
