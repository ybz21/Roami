import { useEffect, useState } from 'react'
import { Button, Spin } from 'antd'
import { api } from '../../api'
import { useI18n } from '../../i18n'
import { nodeApi } from '../cluster/node-url'
import Markdown from '../markdown/Markdown'
import './swarm.css'

type LegacyHistory = {
  id: string; name: string; goal: string; source: 'legacy'; historical: true; verified: false; status: string
  members: { name: string; type?: string; task?: string; status?: string; done?: boolean | number; kind?: string; role?: string; duty?: string }[]
  tasks: { id: string; title: string; description?: string; assignee?: string; status: string }[]
  posts: { id: number; createdAt?: string; author: string; kind?: string; text: string }[]
  truncated: { members: boolean; tasks: boolean; posts: boolean }; unavailableSources?: string[]
}

export default function LegacySwarmHistory({ projectId, onManage }: { projectId: string; onManage: () => void }) {
  const { t } = useI18n(), path = `/projects/${encodeURIComponent(projectId)}/okr/legacy-swarm`, scope = nodeApi(path)
  const [data, setData] = useState<LegacyHistory | null>(null), [loading, setLoading] = useState(true), [error, setError] = useState(false), [retry, setRetry] = useState(0)
  useEffect(() => {
    const controller = new AbortController()
    setLoading(true); setError(false); setData(null)
    void api('GET', path, undefined, { signal: controller.signal }).then(value => {
      const history = value.data
      if (history && (history.source !== 'legacy' || history.historical !== true || history.verified !== false || !Array.isArray(history.members) || !Array.isArray(history.tasks) || !Array.isArray(history.posts))) throw new Error('INVALID_LEGACY_HISTORY')
      if (!controller.signal.aborted) setData(history || null)
    }).catch(() => { if (!controller.signal.aborted) setError(true) }).finally(() => { if (!controller.signal.aborted) setLoading(false) })
    return () => controller.abort()
  }, [scope, retry])
  if (loading) return <div className="swarm-loading"><Spin /></div>
  return <section className="swarm-legacy" aria-label={t('swarm.legacy.title')}>
    <header className="swarm-panel-head"><strong>{data?.name || t('swarm.legacy.title')}</strong><Button onClick={onManage}>{t('swarm.legacy.connect')}</Button></header>
    <div className="swarm-legacy-content">
      {error ? <><p role="alert">{t('swarm.managed.unavailable')}</p><button type="button" className="tt-act" onClick={() => setRetry(value => value + 1)}>{t('agent.retry')}</button></> : !data ? <p className="swarm-note">{t('swarm.legacy.missing')}</p> : <>
        <p role="status" className="swarm-note">{t('swarm.legacy.hint')}</p>
        {Boolean(data.unavailableSources?.length) && <p role="status" className="swarm-note">{t('swarm.legacy.partial')}</p>}
        {data.goal && <details><summary>{t('swarm.goal')}</summary><Markdown>{data.goal}</Markdown></details>}
        {data.members.length > 0 && <section><h3>{t('swarm.managed.members')}</h3>{data.members.map(member => <details key={member.name}><summary><strong>{member.name}</strong>{member.kind && <small>{member.kind}</small>}{member.status && <span className="swarm-note">{t('swarm.legacy.recordedStatus', { status: member.status })}</span>}</summary>{member.duty && <p>{member.duty}</p>}{member.task && <Markdown>{member.task}</Markdown>}</details>)}</section>}
        {data.tasks.length > 0 && <section><h3>{t('swarm.board')}</h3>{data.tasks.map(task => <details key={task.id}><summary><strong>{task.title}</strong>{task.assignee && <small>{task.assignee}</small>}<span className="swarm-note">{t('swarm.legacy.recordedStatus', { status: task.status })}</span></summary>{task.description && <Markdown>{task.description}</Markdown>}</details>)}</section>}
        {data.posts.length > 0 && <section><h3>{t('swarm.legacy.messages')}</h3>{data.posts.map(post => <details key={post.id}><summary><strong>{post.author}</strong>{post.createdAt && <time>{post.createdAt}</time>}</summary><Markdown>{post.text}</Markdown></details>)}</section>}
        {Object.values(data.truncated).some(Boolean) && <p className="swarm-note">{t('swarm.legacy.truncated')}</p>}
      </>}
    </div>
  </section>
}
