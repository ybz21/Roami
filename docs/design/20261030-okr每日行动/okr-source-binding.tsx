import React from 'react'
import { Binding, bindMetrics, entryFor, hasField, requiredFacts, SetupDraft } from './okr-setup-model'
import { Snapshot } from './prototype-data'

export default function SourceBinding({ draft, onChange }: { draft: SetupDraft; onChange: (draft: SetupDraft) => void }) {
  const binding = draft.binding
  const setBinding = (change: Partial<Binding>) => onChange({ ...draft, binding: { ...binding, ...change } })
  const invalidate = (change: Partial<Binding>) => setBinding({ ...change, status: 'idle', sample: undefined, checkedAt: undefined, accountId: undefined, evidence: undefined })
  function inspect() {
    if (binding.scenario === 'login') return setBinding({ status: 'login', sample: undefined })
    if (binding.method === 'api' && binding.platform === '抖音') return setBinding({ status:'failed',sample:undefined,evidence:'需核对现有连接器的应用权限、账号门槛与可取日期；本例先用后台读取。' })
    if (binding.scenario === 'failed') return setBinding({ status: 'failed', sample: undefined })
    const account = binding.account.trim() || (draft.kind === 'creator' ? 'AI 创作实验室（示例）' : 'PocketBoard 本机项目（示例）')
    const sample: Snapshot = draft.kind === 'creator'
      ? { date: '2026-11-11', followers: 328, likes: 10, plays: 636, completed: binding.scenario === 'partial' ? undefined : 160, author: '取样智能体', received: '2026-11-12 08:30', source: `${binding.platform} / ${account} / ${binding.method === 'browser' ? '后台页面取样' : binding.method === 'api' ? '授权接口样本' : '导入文件样本'}（示例）` }
      : { date: '2026-11-11', journeys: 4, p95: 720, retained: 0, author: '取样智能体', received: '2026-11-12 08:30', source: 'PocketBoard 发布版与基准取样（示例）' }
    const required = requiredFacts(draft.metrics)
    for (const key of ['followers','likes','plays','completed','journeys','p95','retained']) if (!required.includes(key)) delete (sample as unknown as Record<string,unknown>)[key]
    setBinding({ status: 'sample', account, accountId: `${binding.platform}-demo-${Array.from(account).reduce((hash,char) => (hash * 31 + char.charCodeAt(0)) >>> 0,7).toString(16)}`, sample, checkedAt: '2026-11-12 08:30', evidence: `${binding.entry || entryFor(binding.platform)} · 样本字段与日期已读取（示例）` })
  }
  const previewBinding = { ...binding, status: 'bound' as const }
  return <section className="source-binding">
    <p className="lead">指标已确认。接下来找到能持续更新的数据。</p>
    <p className="meta">只检查已确认指标所需字段；账号与样本核对后才绑定。下方检查和登录为原型演示，不访问真实后台。</p>
    <div className="form-grid"><label className="field">平台<select value={binding.platform} onChange={e => { const platform = e.target.value; onChange({ ...draft, binding: { ...binding, platform, entry: entryFor(platform), status: 'idle', sample: undefined, checkedAt: undefined, accountId: undefined, evidence: undefined }, metrics: draft.metrics.map(m => ({ ...m, channel: platform })) }) }}>{(draft.kind === 'creator' ? ['视频号','抖音','公众号'] : ['本机项目']).map(platform => <option key={platform}>{platform}</option>)}</select></label><label className="field">接入方式<select value={binding.method} onChange={e => invalidate({ method: e.target.value as Binding['method'] })}><option value="browser">读取后台页面</option><option value="api">使用已有授权接口</option><option value="import">导入导出文件</option></select></label></div>
    <label className="field">要绑定的账号<input value={binding.account} placeholder="不知道也可以先让智能体查找" onChange={e => invalidate({ account: e.target.value })} /></label>
    <details><summary>我知道后台入口或文件位置</summary><label className="field">入口 / 文件位置<input value={binding.entry} onChange={e => invalidate({ entry: e.target.value })} /></label></details>
    <label className="field demo-control">演示接入情况<select value={binding.scenario} onChange={e => invalidate({ scenario: e.target.value as Binding['scenario'] })}><option value="ready">能够读取</option><option value="login">需要登录</option><option value="failed">暂时读不到</option><option value="partial">缺少部分字段</option></select></label>
    <div className="choice-row"><button type="button" className="button primary" onClick={inspect}>{binding.status === 'failed' ? '重新查找与取样' : '让智能体查找并取样（演示）'}</button></div>
    {binding.status === 'login' && <section className="source-state"><h3>需要你登录账号</h3><p>找到后台入口，但尚未读取到指标。请在对应浏览器完成登录，再继续检查。</p><p className="meta">{binding.entry} · 不在 Roami 对话中收集密码。</p><button type="button" className="button" onClick={() => setBinding({ status: 'idle', scenario: 'ready' })}>演示已完成登录</button></section>}
    {binding.status === 'failed' && <section className="source-state"><h3>暂时没有取到有效数据</h3><p>可补充后台入口、换用导出文件，或先保留待接入指标。既有目标和指标选择仍然保留。</p>{binding.evidence && <p className="meta">{binding.evidence}</p>}<p className="meta">填入一个网址不代表已经绑定，也不会用任务完成情况代填数据。</p></section>}
    {(binding.status === 'sample' || binding.status === 'bound') && binding.sample && <section className="source-sample">
      <div className="section-head"><h3>{binding.status === 'bound' ? '已绑定的来源（示例）' : '取到一条样本，请核对'}</h3><span className={binding.status === 'bound' ? 'ok-text meta' : 'meta'}>{binding.status === 'bound' ? '已核对' : '待核对'}</span></div>
      <p>{binding.platform} / {binding.account}</p><p className="meta">示例账号标识 {binding.accountId} · 观测日期 {binding.sample.date} · 取样时间 {binding.checkedAt}</p>
      <div className="sample-grid">{Object.entries(binding.sample).filter(([key]) => ['followers','likes','plays','completed','journeys','p95','retained'].includes(key)).map(([key,value]) => <div key={key}><small>{({ followers:'粉丝总量', likes:'当日点赞量', plays:'当日有效播放量', completed:'当日完整播放量', journeys:'通过旅程',p95:'发布版 p95',retained:'四周使用' } as Record<string,string>)[key]}</small><strong>{value ?? '未读取到'}</strong></div>)}</div>
      <p className="meta">{binding.evidence}</p>
      <p className="meta">先核对账号、字段、观测日期与周期起点。若样本无法建立周期基线，粉丝总量可读，周期净增仍待补起点数据。</p><h3>哪些指标能接上</h3>{draft.metrics.map(metric => <div className="binding-metric" key={metric.id}><span>{metric.name}</span><span className={hasField(previewBinding,metric) ? 'ok-text' : 'warn-text'}>{hasField(previewBinding,metric) ? metric.id === 'netFollowers' ? '可由已读字段计算' : '所需字段已读到' : '缺少字段，待接入'}</span></div>)}
      <label className="check-row"><input type="checkbox" checked={binding.importSample} onChange={e => setBinding({ importSample:e.target.checked })} /><span>将核对后的样本作为首条记录<small>粉丝起点使用本次有效取样；不生成未读取的历史曲线。</small></span></label>
      {binding.status !== 'bound' && <button type="button" className="button primary" onClick={() => { const next = { ...draft, binding: { ...binding, status: 'bound' as const } }; onChange({ ...next, metrics: bindMetrics(next) }) }}>确认账号与样本，绑定可用字段</button>}
    </section>}
  </section>
}
