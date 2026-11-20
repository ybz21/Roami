import { useEffect, useRef, useState } from 'react'
import { useI18n } from '../../../../frontend/src/i18n'
import { ChevronRight } from '../../../../frontend/src/icons'
import { candidateIdentity, previewRounds } from '../../../../frontend/src/components/capabilities/routing-preview'
import { poolMemberMetrics } from './activity-fixture'
import type { readWorkbench } from './fixture'

type Workbench = ReturnType<typeof readWorkbench>
const policies = ['order', 'rotate', 'weight'] as const
type Policy = typeof policies[number]

export function PoolStrategyObservation({ data, focus, hours }: { data: Workbench; focus: boolean; hours: number }) {
  const { t, locale } = useI18n()
  const { pool, poolRoute, traces, requests, sources } = data
  const zh = locale === 'zh-CN'
  const [policy, setPolicy] = useState<Policy | ''>('')
  const [held, setHeld] = useState('')
  const heading = useRef<HTMLHeadingElement>(null)
  useEffect(() => {
    if (focus) {
      heading.current?.scrollIntoView({ block: 'start' })
      heading.current?.focus({ preventScroll: true })
    }
  }, [focus])

  if (!pool || !poolRoute) return null
  const ready = poolRoute.channels.filter(channel => channel.ready)
  const rank = new Map(ready.map((member, index) => [candidateIdentity(member), index + 1]))
  const members = [...pool.candidates].sort((a, b) => (rank.get(candidateIdentity(a)) || Infinity) - (rank.get(candidateIdentity(b)) || Infinity))
  const observedIds = new Set(traces.map(row => row.request.requestId))
  const sourceName = (id: string) => sources.find(source => source.id === id)?.name || t('gatewayTrace.sourceRemoved')
  const memberName = (id: string) => members.find(member => candidateIdentity(member) === id)?.model
  const routes = [...new Set(members.map(member => member.sourceId))]
  const readySources = new Set(ready.map(row => row.sourceId))
  const format = new Intl.NumberFormat(locale, { maximumFractionDigits: 1 })
  const metric = (value: number | null, unit: string) => value === null ? t('monitor.pending') : format.format(value) + ' ' + unit
  const chosenPolicy = policy || (policies.includes(pool.strategy as Policy) ? pool.strategy as Policy : '')
  const excluded = rank.has(held) ? held : ''
  const eligible = ready.filter(member => candidateIdentity(member) !== excluded)
  const rounds = chosenPolicy ? previewRounds({ ...pool, strategy: chosenPolicy, candidates: eligible }, '') : null
  const leads = [...new Set(rounds || [])]
  const totals = requests?.totals
  const labels = {
    member: zh ? '成员' : 'Member',
    rank: zh ? '生效顺位' : 'Live order',
    state: zh ? '状态' : 'Status',
    served: zh ? '最终承载' : 'Requests served',
    attempts: zh ? '尝试成功 / 总数' : 'Successful / total attempts',
  }

  return <section className="pool-strategy-observation" aria-labelledby="pool-strategy-observation-title">
    <div className="routing-workbench-section-head">
      <h2 id="pool-strategy-observation-title" ref={heading} tabIndex={-1}>{zh ? '策略与承载观测' : 'Strategy & member activity'}</h2>
      <small>{pool.name} · {t('monitor.hours', { hours })}</small>
    </div>

    <div className="pool-strategy-preview">
      <div className="pool-strategy-controls">
        <div>
          <h3>{zh ? '策略预览' : 'Strategy preview'}</h3>
          <div className="pool-strategy-buttons" role="group" aria-label={zh ? '预览策略' : 'Preview strategy'}>
            {policies.map(key => <button key={key} type="button" aria-pressed={chosenPolicy === key} onClick={() => setPolicy(key)}>{t('pool.strategy.' + key)}</button>)}
          </div>
        </div>
        {!!ready.length && <label className="routing-workbench-field">{t('pool.simulateRest')}
          <select value={excluded} onChange={event => setHeld(event.target.value)}>
            <option value="">{zh ? '不额外排除' : 'No additional exclusions'}</option>
            {ready.map(row => <option key={candidateIdentity(row)} value={candidateIdentity(row)}>{row.model} · {sourceName(row.sourceId)}</option>)}
          </select>
        </label>}
      </div>

      {!eligible.length ? <p className="routing-workbench-empty">{t('pool.noneAvailable')}</p>
        : !rounds ? <p className="routing-workbench-empty">{t('orchestration.dynamicHint')}</p>
        : !!rounds.length && <div className="pool-strategy-preview-chart">
          <div><small>{zh ? '模拟首选 · 前 12 轮' : 'Simulated first choice · 12 rounds'}</small>
            <ol className="pool-strategy-rounds">
              {rounds.map((id, index) => <li key={index} data-tone={leads.indexOf(id) % 3} aria-label={memberName(id)}>{rank.get(id)}</li>)}
            </ol>
          </div>
          <div className="pool-strategy-key">
            {leads.map((id, index) => <span key={id}><i data-tone={index % 3} aria-hidden="true" />{rank.get(id)} · {memberName(id)}{chosenPolicy === 'weight' && <small>{zh ? '权重 ' : 'Weight '}{pool.weights?.[id] ?? 1}</small>}</span>)}
          </div>
        </div>}
      {chosenPolicy && <small>{zh ? '预览仅使用当前可调度成员。保存策略与拖动顺序请在聚合编辑页操作。' : 'Preview uses currently eligible members. Edit the pool to save strategy or order.'}</small>}
    </div>

    <div className="pool-strategy-history">
      <div>
        <h3>{zh ? '成员承载' : 'Member activity'}</h3>
        <div className="pool-strategy-table" role="table" aria-label={zh ? '成员顺位和历史承载' : 'Member order and activity'}>
          <div className="pool-strategy-row pool-strategy-columns" role="row">
            {[labels.rank, labels.member, labels.state, labels.served, labels.attempts, t('monitor.firstTokenP95'), t('monitor.outputP50')].map(label =>
              <span role="columnheader" key={label}>{label}</span>)}
          </div>
          {members.map(member => {
            const id = candidateIdentity(member)
            const position = rank.get(id)
            const channel = poolRoute.channels.find(row => candidateIdentity(row) === id)
            const state = position ? t('pool.ready') : pool.enabled === false ? t('pool.disabled') : channel?.restUntil ? (zh ? '冷却中' : 'Cooling down') : t('pool.unchecked')
            const stats = poolMemberMetrics(observedIds, member.sourceId, member.model)
            const served = traces.filter(({ request }) =>
              ['success', 'recovered'].includes(request.outcome) && request.sourceId === member.sourceId && request.upstreamModel === member.model).length
            const values = [
              [labels.state, state],
              [labels.served, format.format(served)],
              [labels.attempts, format.format(stats.successes) + ' / ' + format.format(stats.attempts)],
              [t('monitor.firstTokenP95'), metric(stats.firstTokenP95, 'ms')],
              [t('monitor.outputP50'), metric(stats.outputP50, 'Token/s')],
            ]
            return <div className="pool-strategy-row" role="row" key={id}>
              <span className="pool-strategy-rank" role="cell">{position ?? t('pool.runtimeSkipped')}</span>
              <div className="pool-strategy-member" role="cell"><strong translate="no">{member.model}</strong><small>{sourceName(member.sourceId)}</small></div>
              {values.map(([label, value]) => <span role="cell" key={label}><small className="pool-strategy-compact-label" aria-hidden="true">{label}</small>{value}</span>)}
            </div>
          })}
        </div>
      </div>
      <aside className="pool-strategy-resilience" aria-labelledby="pool-strategy-resilience-title">
        <h3 id="pool-strategy-resilience-title">{zh ? '故障切换与来源' : 'Fallback and sources'}</h3>
        <dl>
          <div><dt>{zh ? '同源换模型' : 'Same-source switches'}</dt><dd>{format.format(totals?.sameSource || 0)}</dd></div>
          <div><dt>{zh ? '跨源切换' : 'Cross-source switches'}</dt><dd>{format.format(totals?.crossSource || 0)}</dd></div>
        </dl>
        {readySources.size === 1 && routes.length > 0 && <p>{zh ? '暂无跨源备用' : 'No cross-source backup'}</p>}
        <ul>{routes.map(id => <li key={id}><span>{sourceName(id)}</span><small>{t('pool.runtimeAvailable', {
          count: format.format(ready.filter(row => row.sourceId === id).length),
          total: format.format(members.filter(row => row.sourceId === id).length),
        })}</small></li>)}</ul>
        <a className="routing-workbench-more" href="#/monitor/sources">{zh ? '查看来源监控' : 'Open source monitoring'}<ChevronRight /></a>
      </aside>
    </div>
  </section>
}
