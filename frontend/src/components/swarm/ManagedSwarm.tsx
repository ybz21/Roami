import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { nodeApi } from '../cluster/node-url'
import { App, Button, Input, Select, Spin } from 'antd'
import { api } from '../../api'
import { useLayout } from '../../layout'
import { useI18n } from '../../i18n'
import { ChevronLeft, CloseIcon, ArrowUp } from '../../icons'
import MobileSubPage from '../MobileSubPage'
import Markdown from '../markdown/Markdown'
import { openAgentPage } from '../agent/agent-page-route'
import { useSwarmSnapshot } from './useSwarmSnapshot'
import SwarmStudio from './SwarmStudio'
import { swarmColumn, swarmStateToken, type SwarmSnapshot, type SwarmWork } from './swarm-protocol'
import './swarm.css'

function State({ state }: { state: string }) {
  const { t } = useI18n()
  return <span className="swarm-state" style={{ color: `var(${swarmStateToken(state)})` }}>{t(`swarm.managed.state.${state}`)}</span>
}
export default function ManagedSwarm({ id, onBack, openTerm }: { id: string; onBack: () => void; openTerm: (id: string) => void }) {
  const { data, error, refresh } = useSwarmSnapshot(id), { t, locale } = useI18n(), { phone } = useLayout(), { message, modal } = App.useApp()
  const panelKey = 'roami.swarm.panel:' + nodeApi('/agent/swarms/' + id)
  const [selected, setSelected] = useState('main'), [tab, setTab] = useState(() => localStorage.getItem(panelKey) || 'studio'), [detail, setDetail] = useState<string | null>(null), [busy, setBusy] = useState(false)
  const controlKey = useRef<{ action: string; revision: number; key: string } | null>(null)
  const [readCount, setReadCount] = useState(() => Number(localStorage.getItem(panelKey + ':read') || 0))
  const chatCount = (data?.posts.length || 0) + (data?.mainMessages.filter(item => item.text).length || 0) + (data?.work.filter(item => item.attempt?.summary).length || 0)
  useEffect(() => { localStorage.setItem(panelKey, tab); if (tab === 'chat') { setReadCount(chatCount); localStorage.setItem(panelKey + ':read', String(chatCount)) } }, [phone, tab, chatCount, panelKey])
  const positions = useRef<Record<string, number>>({})
  const switchTab = (next: string) => {
    const panel = document.querySelector<HTMLElement>(tab === 'chat' ? '.swarm-chat-log' : '.swarm-main-area')
    positions.current[tab] = panel?.scrollTop || 0; setTab(next)
  }
  useLayoutEffect(() => {
    const panel = document.querySelector<HTMLElement>(tab === 'chat' ? '.swarm-chat-log' : '.swarm-main-area')
    if (panel) panel.scrollTop = positions.current[tab] || 0
  }, [tab])
  const unread = Math.max(0, chatCount - readCount)
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
  if (!data) return <div className="swarm-loading">{error ? <><p role="alert">{t('swarm.managed.unavailable')}</p><button type="button" className="tt-act" onClick={() => void refresh()}>{t('agent.retry')}</button></> : <Spin />}</div>
  const work = data.work.find(item => item.id === detail)
  const openWork = (item: SwarmWork) => { setSelected(item.id); setDetail(item.id); if (!phone) switchTab('board') }
  const view = <div className="swarm-work-detail">
    {work && <>{!phone && <div className="swarm-panel-head"><h3>{work.title}</h3><button type="button" className="tt-act" aria-label={t('common.close')} onClick={() => setDetail(null)}><CloseIcon /></button></div>}<State state={work.state} />
      {work.attempt?.summary && <section><h4>{t('swarm.managed.result')}</h4><Markdown>{work.attempt.summary}</Markdown></section>}
      <details className="swarm-description"><summary>{t('swarm.managed.instructions')}</summary><Markdown>{work.goal}</Markdown><h4>{t('swarm.managed.acceptance')}</h4><Markdown>{work.acceptance}</Markdown></details>
      {work.dispatch_error && <p role="alert">{t(work.dispatch_error === 'SWARM_DEPENDENCY_NOT_VERIFIED' ? 'swarm.managed.dependencyBlocked' : 'swarm.managed.dispatchFailed')}</p>}
      {work.dependencies.length > 0 && <section><h4>{t('swarm.managed.dependencies')}</h4>{work.dependencies.map(dep => <p key={dep.upstreamId}>{data.work.find(item => item.id === dep.upstreamId)?.title}</p>)}</section>}
      <div className="swarm-detail-actions">{work.task_id && <button type="button" className="tt-act" onClick={() => openAgentPage('tasks', work.task_id!)}>{t('swarm.managed.openTask')}</button>}{work.attempt?.sessionId && <button type="button" className="tt-act" onClick={() => openTerm(work.attempt!.sessionId!)}>{t('swarm.managed.openSession')}</button>}</div>
    </>}
  </div>
  return <div className="swarm-managed" data-tab={tab}>
    <header className="tt-pagehead"><div className="swarm-page-identity">{!phone && <button type="button" className="tt-act" onClick={onBack} aria-label={t('common.back')}><ChevronLeft /></button>}<h2>{data.name}</h2><State state={data.state} />{data.paused && <span className="swarm-note">{t('swarm.managed.paused')}</span>}</div><div className="acts"><Button size="small" loading={busy} disabled={data.archived} onClick={() => void control(data.paused ? 'resume' : 'pause')}>{t(data.paused ? 'swarm.managed.resume' : 'swarm.managed.pause')}</Button><details className="swarm-controls"><summary>{t('common.more')}</summary><button type="button" className="tt-act danger" disabled={busy || data.archived} onClick={() => modal.confirm({ title: t('swarm.managed.stopTitle'), content: t('swarm.managed.stopHint'), onOk: () => control('stop') })}>{t('swarm.managed.stop')}</button><button type="button" className="tt-act" disabled={busy || data.archived} onClick={() => void control('archive')}>{t('swarm.archive')}</button></details></div></header>
    {error && <div className="swarm-stream-error" role="status">{t('swarm.managed.reconnecting')}</div>}
    {data.mainState === 'failed' && <p role="alert" className="swarm-stream-error">{t('swarm.managed.mainFailed')}</p>}
    {data.archived && <p className="swarm-note">{t('swarm.managed.archived')}</p>}
    {<nav className="swarm-tabs" aria-label={t('swarm.managed.workspace')}>{['studio', 'chat', 'board'].map(key => <button type="button" key={key} aria-pressed={tab === key} onClick={() => switchTab(key)}>{t(`swarm.managed.tab.${key}`)}{(key === 'chat' ? unread : key === 'board' ? blockedCount : 0) > 0 && <span className="swarm-tab-count">{new Intl.NumberFormat(locale).format(key === 'chat' ? unread : blockedCount)}</span>}</button>)}</nav>}
    <div className="swarm-managed-grid">
      <div className="swarm-main-area">
        <div className="swarm-studio-area"><SwarmStudio nodes={nodes} selected={selected} onSelect={setSelected} /><div className="swarm-member-list" aria-label={t('swarm.managed.members')}>{data.work.map(item => <button type="button" className="swarm-member" key={item.id} aria-pressed={selected === item.id} onClick={() => setSelected(item.id)}><span>{item.member_name}</span><small>{item.executor === 'native' ? 'Roami' : item.executor}</small><State state={item.state} /></button>)}</div></div>
        <section className="swarm-board" aria-label={t('swarm.board')}>{!data.work.length ? <p className="swarm-note">{t('swarm.managed.planning')}</p> : <div className="swarm-board-columns">{['backlog', 'doing', 'blocked', 'review', 'done'].map(column => <section key={column}><h3>{t(`swarm.board.col.${column}`)}</h3>{data.work.filter(item => swarmColumn(item.state) === column).map(item => <button type="button" className="swarm-work-card" key={item.id} aria-pressed={selected === item.id} onClick={() => openWork(item)}><strong>{item.title}</strong><small>{item.member_name} · {item.executor === 'native' ? 'Roami' : item.executor}</small><State state={item.state} /></button>)}</section>)}</div>}</section>
        {!phone && work && view}
      </div>
      <SwarmChat key={data.id} data={data} selected={selected} onSelect={setSelected} onWork={openWork} onSent={refresh} />
    </div>
    {phone && work && <MobileSubPage title={work.title} onBack={() => setDetail(null)}>{view}</MobileSubPage>}
  </div>
}

function SwarmChat({ data, selected, onSelect, onWork, onSent }: { data: SwarmSnapshot; selected: string; onSelect: (id: string) => void; onWork: (item: SwarmWork) => void; onSent: () => Promise<void> }) {
  const { t, locale } = useI18n(), { message } = App.useApp()
  const storageKey = 'roami.swarm.draft:' + nodeApi('/agent/swarms/' + data.id)
  const [saved] = useState(() => { try { return JSON.parse(localStorage.getItem(storageKey) || '{}') } catch { return {} } })
  const [draft, setDraft] = useState<string>(saved.draft || ''), [recipient, setRecipient] = useState<string>(saved.recipient || 'main'), [sending, setSending] = useState(false)
  const sendKey = useRef<{ key: string; payload: string; body?: { text: string; workId?: string; taskRevision?: number | null } }>(saved.pending || { key: crypto.randomUUID(), payload: '' })
  useEffect(() => { localStorage.setItem(storageKey, JSON.stringify({ draft, recipient, pending: sendKey.current })) }, [draft, recipient, sending, storageKey])
  const messages = useMemo(() => [
    ...data.posts.map(post => ({ id: 'post:' + post.id, author: post.author === 'human' ? t('swarm.chat.you') : post.author === 'main' ? 'Roami Main' : post.author, text: post.text, time: post.createdMs, pending: post.deliveryState === 'pending', work: data.work.find(item => item.task_id === post.taskId) })),
    ...data.mainMessages.filter(item => item.text).map(item => ({ id: item.id, author: 'Roami Main', text: item.text, time: item.createdMs, pending: false, work: undefined as SwarmWork | undefined })),
    ...data.work.filter(item => item.attempt?.summary).map(item => ({ id: 'result:' + item.id, author: item.member_name, text: item.attempt!.summary!, time: item.attempt?.finishedMs || 0, pending: false, work: item })),
  ].sort((a, b) => a.time - b.time), [data.posts, data.mainMessages, data.work, t])
  const send = async () => {
    if (!draft.trim() || sending) return
    const work = data.work.find(item => item.id === recipient)
    if (recipient !== 'main' && (!work?.task_id || !work.revision)) { message.error(t('swarm.managed.sendFailed')); return }
    let body = { text: draft.trim(), ...(work ? { workId: work.id, taskRevision: work.revision } : {}) }
    const payload = JSON.stringify({ text: body.text, workId: body.workId })
    if (sendKey.current.payload && payload !== sendKey.current.payload) sendKey.current = { key: crypto.randomUUID(), payload: '' }
    if (sendKey.current.payload === payload && sendKey.current.body) body = sendKey.current.body
    else sendKey.current.body = body
    sendKey.current.payload = payload; setSending(true)
    try { await api('POST', `/agent/swarms/${data.id}/messages`, { ...body, commandKey: sendKey.current.key }); setDraft(''); sendKey.current = { key: crypto.randomUUID(), payload: '' }; await onSent() }
    catch { message.error(t('swarm.managed.sendFailed')) } finally { setSending(false) }
  }
  return <section className="swarm-chat" aria-label={t('swarm.managed.tab.chat')}><div className="swarm-chat-log" role="log" aria-label={t('swarm.managed.messages')}>
    {!messages.length && <p className="swarm-note">{t('swarm.managed.chatEmpty')}</p>}
    {messages.map(item => <article className="swarm-chat-message" key={item.id} data-selected={item.work?.id === selected}><header><button type="button" className="tt-act" onClick={() => onSelect(item.work?.id || 'main')}>{item.author}</button>{item.time > 0 && <time>{new Intl.DateTimeFormat(locale, { hour: 'numeric', minute: '2-digit' }).format(item.time)}</time>}</header>{item.pending && <span className="swarm-note">{t('swarm.managed.deliveryPending')}</span>}<Markdown>{item.text}</Markdown>{item.work && <div className="swarm-chat-task-actions"><State state={item.work.state} /><button type="button" className="tt-act" onClick={() => onWork(item.work!)}>{t('swarm.managed.openTask')}</button><button type="button" className="tt-act" onClick={() => { setRecipient(item.work!.id); document.querySelector<HTMLTextAreaElement>('.swarm-chat textarea')?.focus() }}>{t('swarm.managed.replyMember')}</button></div>}</article>)}
  </div><div className="tt-composer swarm-chat-composer"><Input.TextArea variant="borderless" value={draft} onChange={e => setDraft(e.target.value)} rows={3} disabled={data.archived || sending} placeholder={t('swarm.managed.chatPlaceholder')} /><div className="tt-cbar"><div className="tt-cgrp"><label htmlFor="swarm-chat-recipient">{t('swarm.managed.recipient')}</label><Select id="swarm-chat-recipient" value={recipient} onChange={setRecipient} disabled={data.archived || sending} options={[{ value: 'main', label: 'Roami Main' }, ...data.work.filter(item => item.task_id).map(item => ({ value: item.id, label: '@' + item.member_name }))]} /></div><div className="tt-cend"><button type="button" className="tt-send" aria-label={t('common.send')} disabled={sending || data.archived || !draft.trim()} onClick={() => void send()}>{sending ? <Spin size="small" /> : <ArrowUp size={18} />}</button></div></div><p className="swarm-note">{t('swarm.managed.chatHint')}</p></div></section>
}
