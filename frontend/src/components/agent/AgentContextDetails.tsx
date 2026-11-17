import { useEffect, useRef, useState, type ReactNode } from 'react'
import { Button, Spin } from 'antd'
import { api } from '../../api'
import { useI18n } from '../../i18n'
import Markdown from '../markdown/Markdown'
import type { AgentContext } from './useAgentContext'
import type { AgentSnapshot } from './agent-protocol'

export default function AgentContextDetails({ cid, node, branch, compaction, running, readOnly, onCompact, onCancel, children }: {
  cid: string; node: string | null; branch: string; compaction: AgentSnapshot['compaction']; running: boolean; readOnly: boolean
  onCompact: () => void; onCancel: () => void; children?: ReactNode
}) {
  const { t, locale } = useI18n()
  const [context, setContext] = useState<AgentContext | null>(null)
  const [loading, setLoading] = useState(true), [failed, setFailed] = useState(false), [attempt, setAttempt] = useState(0)
  const [summary, setSummary] = useState<{ id: string; text: string } | null>(null)
  const snapshot = useRef<typeof summary>(null)
  const compacting = !!compaction && ['queued', 'running', 'started'].includes(compaction.state)
  const settled = compaction && !compacting ? compaction.operationId + ':' + compaction.state : ''
  useEffect(() => {
    if (!cid) { setLoading(false); return }
    const abort = new AbortController()
    setFailed(false)
    const path = '/agent/conversations/' + encodeURIComponent(cid) + '/context'
    void (async () => {
      try {
        const { data } = await api('GET', path + (branch ? '?branch=' + encodeURIComponent(branch) : ''), undefined, { signal: abort.signal })
        if (abort.signal.aborted) return
        setContext(data)
        if (!data.snapshotId) { snapshot.current = null; setSummary(null) }
        else if (snapshot.current?.id !== data.snapshotId) {
          const result = await api('GET', path + '/snapshots/' + encodeURIComponent(data.snapshotId), undefined, { signal: abort.signal })
          if (abort.signal.aborted) return
          snapshot.current = { id: data.snapshotId, text: result.data.summary.text || '' }
          setSummary(snapshot.current)
        }
      } catch { if (!abort.signal.aborted) setFailed(true) }
      finally { if (!abort.signal.aborted) setLoading(false) }
    })()
    return () => abort.abort()
  }, [cid, node, branch, settled, attempt])
  const text = summary?.id === context?.snapshotId ? summary?.text : ''
  return <div className="agent-context">
    {loading && <Spin size="small" />}
    {context?.model && <p>{context.model}</p>}
    {context && <p>{t(context.contextWindow ? 'agent.contextUsage' : 'agent.contextUnknown', { used: context.estimatedTokens?.toLocaleString(locale), budget: context.contextWindow?.toLocaleString(locale) })}</p>}
    {!!context?.contextWindow && <p>{t('agent.contextMeter.threshold', { percent: new Intl.NumberFormat(locale, { maximumFractionDigits: 0 }).format((context.compactionRatio ?? 0.75) * 100) })}</p>}
    {compaction && <p>{t('agent.compaction.' + compaction.state)}</p>}
    {failed && <p role="alert">{t('agent.requestFailed')} <button type="button" className="tt-act" onClick={() => { if (!context) setLoading(true); setAttempt(value => value + 1) }}>{t('agent.retry')}</button></p>}
    {text && <Markdown>{text}</Markdown>}
    {!loading && !failed && !text && <p className="agent-muted">{t('agent.context.noSummary')}</p>}
    <Button disabled={!cid || readOnly || compacting || running} onClick={onCompact}>{t('agent.compactNow')}</Button>
    {compacting && <Button onClick={onCancel}>{t('agent.cancelCompact')}</Button>}
    {children}
  </div>
}
