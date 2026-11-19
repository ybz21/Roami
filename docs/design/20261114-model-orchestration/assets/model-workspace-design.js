const byId = id => document.getElementById(id)
const fmt = new Intl.NumberFormat('zh-CN')
byId('free-candidates')?.addEventListener('change', event => {
  byId('metered-candidate').hidden = event.target.checked
})
const members = [
  { name:'ERNIE 5.5 Flash', source:'OpenRouter 免费模型', handled:116, note:'账号额度可用。近 1 小时 116 次最终成功。' },
  { name:'Hy4 Flash', source:'WorkBuddy', handled:80, note:'账号 B 可用。账号 A 额度已用尽，18:00 重置。' },
  { name:'Gemma 4 26B', source:'OpenRouter 免费模型', handled:0, note:'此聚合要求工具调用，目前跳过该成员。' },
]
const routeCases = {
  ready: { count:'2 / 3', first:'首选 ERNIE 5.5 Flash', state:['可调度','可调度','工具能力不符'], positions:['第 1 位','第 2 位','跳过'], message:'' },
  blocked: { count:'0 / 3', first:'暂无首选', state:['限流冷却','额度耗尽','工具能力不符'], positions:['跳过','跳过','跳过'], message:'预计 16:45 可尝试。以最新渠道状态为准。' },
  unknown: { count:'待检测', first:'等待渠道状态', state:['未检测','未检测','未检测'], positions:['待定','待定','待定'], message:'历史承载仍可查看。' },
}
function renderRoute() {
  const mode = byId('route-scenario').value
  const empty = mode === 'empty'
  const view = empty ? routeCases.ready : routeCases[mode]
  byId('route-ready').textContent = view.count
  byId('route-first').textContent = view.first
  byId('route-total').textContent = empty ? '0' : '200'
  byId('route-failure').textContent = empty ? '暂无样本' : '2.0%'
  byId('route-failure-note').hidden = empty
  byId('route-fallback').textContent = empty ? '0 次' : '3 次'
  byId('route-latest').textContent = empty ? '暂无调用。' : '最近命中 16:39 · ERNIE 5.5 Flash · 成功'
  byId('route-events').hidden = empty
  byId('route-no-events').hidden = !empty
  const message = byId('route-message')
  message.hidden = !view.message
  message.textContent = view.message
  byId('route-members').innerHTML = members.map((row, index) => {
    const share = Math.round(row.handled / 196 * 100)
    const state = view.state[index]
    const tone = state === '可调度' ? 'ready' : mode === 'blocked' ? 'problem' : ''
    const note = mode === 'unknown' ? '暂未取得当前渠道状态。' : mode !== 'blocked' || index === 2 ? row.note : ['冷却至 16:45。','额度将在 18:00 重置。'][index]
    const load = empty ? '<small>暂无承载样本</small>' : `<small>承载 ${row.handled} 次 · ${share}%</small><div class="meter" aria-hidden="true"><span style="width:${share}%"></span></div>`
    return `<li><details class="member"><summary><div><strong>${row.name}</strong><small>${row.source}</small></div><span class="position">${view.positions[index]}</span><span class="status ${tone}">${state}</span><div>${load}</div></summary><p class="member-info muted">${empty && index === 0 ? '账号额度可用。' : note}</p></details></li>`
  }).join('')
}
const counts = {
  0: [],
  1: [[34,7,1,3],[43,12,2,4],[58,9,1,4],[51,15,3,4],[48,20,2,5],[43,8,1,3]],
  6: [[216,38,4,12],[283,46,7,14],[264,53,4,22],[299,61,4,33],[379,78,6,18],[277,71,10,23]],
  24: [[818,84,27,64],[721,58,31,24],[963,102,20,55],[949,113,36,87],[1216,220,38,95],[1024,183,26,77]],
}
const metricValues = {
  1: { p95:'5.38 s', speed:'82' },
  6: { p95:'7.12 s', speed:'74' },
  24: { p95:'8.10 s', speed:'71' },
}
const failureTypes = ['限流 429','鉴权失败','其他']
let selectedBucket = -1
let selectedFailure = -1
const total = row => row.reduce((sum,n) => sum + n,0)
function clock(minutes) {
  const h = (Math.floor(minutes / 60) + 24) % 24
  const m = (minutes % 60 + 60) % 60
  return String(h).padStart(2,'0') + ':' + String(m).padStart(2,'0')
}
function interval(hours, index) {
  if (index < 0) return '最近 ' + hours + ' 小时'
  const end = 16 * 60 + 40
  const minutes = hours * 60 / 6
  const start = end - minutes * (6 - index)
  return clock(start) + ' 至 ' + clock(start + minutes) + (start < 0 ? (start + minutes < 0 ? ' · 昨日' : ' · 跨日') : '')
}
function renderMonitor() {
  const hours = Number(byId('monitor-range').value)
  const buckets = counts[hours]
  const rows = selectedBucket < 0 ? buckets : [buckets[selectedBucket]]
  const sums = cols => cols.reduce((a,row) => a.map((n,index) => n + row[index]),[0,0,0,0])
  const full = sums(buckets), local = sums(rows)
  const requests = total(full)
  const failed = total(local.slice(1))
  const peak = Math.max(1,...buckets.map(total))
  const window = interval(hours,selectedBucket)
  byId('monitor-total').textContent = fmt.format(requests)
  byId('monitor-success').textContent = requests ? (full[0] / requests * 100).toFixed(1) + '%' : '暂无样本'
  byId('monitor-count').textContent = fmt.format(requests) + ' 个完成样本'
  byId('monitor-first').textContent = metricValues[hours]?.p95 || '样本不足'
  byId('monitor-speed').textContent = metricValues[hours]?.speed || '样本不足'
  byId('monitor-selection').textContent = requests ? window + ' · 成功 ' + fmt.format(local[0]) + ' · 失败 ' + fmt.format(failed) : '该时段暂无调用'
  byId('failure-scope').textContent = requests ? window + ' · 共 ' + fmt.format(failed) + ' 次失败' : '暂无失败样本'
  byId('monitor-chart').hidden = !requests
  const audit = byId('monitor-audit')
  audit.hidden = !failed
  const query = new URLSearchParams({ demo:'monitor', range:window, reason:failureTypes[selectedFailure] || '全部失败' })
  audit.href = './model-audit.html?' + query + '#audit-example'
  byId('monitor-chart').innerHTML = buckets.map((row,index) => {
    const errors = total(row.slice(1))
    const label = interval(hours,index) + '，成功 ' + row[0] + '，失败 ' + errors
    return `<button type="button" data-bucket="${index}" aria-label="${label}" aria-pressed="${selectedBucket===index}"><span class="stack" aria-hidden="true"><span class="succeeded" style="height:${row[0] / peak * 100}%"></span><span class="failed" style="height:${errors / peak * 100}%"></span></span><time>${interval(hours,index).slice(0,5)}</time></button>`
  }).join('')
  byId('failure-list').innerHTML = failed ? failureTypes.map((label,index) => {
    const count = local[index + 1]
    const percent = failed ? (count / failed * 100) : 0
    return `<li><button type="button" data-failure="${index}" aria-pressed="${selectedFailure===index}"><span>${label}</span><small>${fmt.format(count)} 次 · ${percent.toFixed(1)}%</small><span class="meter" aria-hidden="true"><span style="width:${percent}%"></span></span></button></li>`
  }).join('') : ''
}

if (byId('route-scenario')) {
  byId('route-scenario').addEventListener('change', renderRoute)
  renderRoute()
}
if (byId('monitor-range')) {
  byId('monitor-range').addEventListener('change', () => {
    selectedBucket = -1
    selectedFailure = -1
    renderMonitor()
  })
  byId('monitor-chart').addEventListener('click', event => {
    const button = event.target.closest('[data-bucket]')
    if (!button) return
    const index = Number(button.dataset.bucket)
    selectedBucket = selectedBucket === index ? -1 : index
    selectedFailure = -1
    renderMonitor()
    byId('monitor-chart').querySelector('[data-bucket="'+index+'"]').focus({preventScroll:true})
  })
  byId('failure-list').addEventListener('click', event => {
    const button = event.target.closest('[data-failure]')
    if (!button) return
    const index = Number(button.dataset.failure)
    selectedFailure = selectedFailure === index ? -1 : index
    renderMonitor()
    byId('failure-list').querySelector('[data-failure="'+index+'"]').focus({preventScroll:true})
  })
  renderMonitor()
}
if (byId('audit-example')) {
  const query = new URLSearchParams(location.search)
  const demo = query.get('demo')
  if (demo === 'route' || demo === 'monitor') {
    byId('audit-example').open = true
    byId('audit-record').hidden = demo !== 'route'
    const range = query.get('range')?.slice(0, 40) || '默认时段'
    const reason = query.get('reason')?.slice(0, 30) || '全部失败'
    byId('audit-context').textContent = demo === 'route'
      ? '聚合调用 · 16:35 · 已记录故障切换 · 演示'
      : range + ' · 全部来源 · 全部模型 · ' + reason + ' · 演示'
  }
}
byId('claim')?.addEventListener('click', () => {
  byId('claim').disabled = true
  byId('claim-status').textContent = '已领取 10 积分 · 演示回执'
  byId('bonus').textContent = '50'
})
