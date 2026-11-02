import React from 'react'
import { CycleState, watchQuality } from './okr-execution-cycle'

const show = (value:number|null,unit:string) => value === null ? '待采集' : `${Number(value.toFixed(2))}${unit}`
const change = (value:number|null,before:number|null,unit:string) => value === null || before === null ? '待比较' : `${value-before > 0 ? '+' : ''}${Number((value-before).toFixed(2))}${unit}`
export default function WatchQuality({state,date}:{state:CycleState;date:string}) {
  const current = watchQuality(state.observations.find(row=>row.date===date))
  const previous = new Date(Date.parse(`${date}T12:00:00Z`)-86400000).toISOString().slice(0,10)
  const before = watchQuality(state.observations.find(row=>row.date===previous))
  return <section className="book-section watch-quality" aria-label="观看质量 KR">
    <h3>观看质量 KR</h3><p className="meta">账号当日同口径数据 · {date} · 与粉丝增长独立衡量</p>
    <div className="book-board-stats"><article data-quality="completion"><small>完播率 / 建议目标 30%</small><strong>{show(current.completion,'%')}</strong><small>较前日 {change(current.completion,before.completion,' 个百分点')}</small></article><article data-quality="average"><small>平均观看时长 / 建议目标 18 秒</small><strong>{show(current.average,' 秒')}</strong><small>较前日 {change(current.average,before.average,' 秒')}</small></article></div>
    <p className="meta">目标需结合真实基线和片长确认。单条视频按 T+24h 另作对比；单日达到参考线不等于整个周期达标。</p>
    <details><summary>观看质量按日记录与原始数</summary><div className="history-table"><table><thead><tr><th>日期</th><th>完播率</th><th>平均观看</th><th>完整 / 有效播放</th><th>总观看秒数</th><th>来源 / 更新时间</th></tr></thead><tbody>{state.observations.filter(row=>row.date<=date).map(row=>{const quality=watchQuality(row);return <tr key={row.date}><td>{row.date}</td><td>{show(quality.completion,'%')}</td><td>{show(quality.average,' 秒')}</td><td>{row.completed ?? '未知'} / {row.plays ?? '未知'}</td><td>{row.watchSeconds ?? '未知'}</td><td>{row.source}<br/>{row.dataReadyAt}</td></tr>})}</tbody></table></div><p className="meta">完播率 = 完整播放 / 有效播放；平均观看 = 总观看秒数 / 对应播放量。窗口统计先汇总原始数；缺字段或零播放保持未知。平均观看时长与视频片长分别保存。</p></details>
  </section>
}
