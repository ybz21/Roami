import { bindOrderDrag } from './order-drag.js'
import { mountSourceCreation } from './source-creation.js'

export function mountWorkspaceSamples(root) {
  const controller = new AbortController()
  const bind = (target, name, handler) => target.addEventListener(name, handler, { signal: controller.signal })
  const byId = id => root.querySelector('#' + id)
  mountSourceCreation(byId, bind, root)
  const fmt = new Intl.NumberFormat('zh-CN')
  bind(byId('free-candidates'), 'change', event => {
    byId('metered-candidate').hidden = event.target.checked
  })
  const members = [
    { name:'ERNIE 5.5 Flash', source:'OpenRouter 免费模型', handled:116, note:'账号额度可用。近 1 小时 116 次最终成功。' },
    { name:'Hy4 Flash', source:'WorkBuddy', handled:80, note:'账号 B 可用。账号 A 额度已用尽，18:00 重置。' },
    { name:'Gemma 4 26B', source:'OpenRouter 免费模型', handled:0, note:'此聚合要求工具调用，目前跳过该成员。' },
  ]
  let savedOrder = members.map((_, index) => index)
  let draftOrder = savedOrder
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
    byId('route-ready').parentElement.dataset.state = mode
    const ready = savedOrder.filter(index => view.state[index] === '可调度')
    const positions = [...ready, ...savedOrder.filter(index => !ready.includes(index))]
    const first = members[ready[0]]?.name
    byId('route-flow').hidden = !first
    byId('route-unavailable').hidden = !!first
    byId('route-unavailable').textContent = view.first
    byId('route-flow-first').textContent = first || ''
    byId('route-flow-first-source').textContent = members[ready[0]]?.source || ''
    byId('route-flow-next-source').textContent = members[ready[1]]?.source || ''
    byId('route-flow-next').textContent = members[ready[1]]?.name || ''
    byId('route-flow-next-node').hidden = ready.length < 2
    byId('route-path-action').hidden = mode === 'unknown'
    byId('route-path-action').href = '#/troubleshoot?case=' + (mode === 'blocked' ? 'blocked' : 'fallback')
    byId('route-failure').textContent = empty ? '暂无样本' : '2.0%'
    byId('route-failure-note').hidden = empty
    byId('route-fallback').textContent = empty ? '0 次' : '3 次'
    byId('route-sources-ready').textContent = mode === 'unknown' ? '待检测' : mode === 'blocked' ? '0 / 2' : '2 / 2'
    byId('route-cooling').textContent = mode === 'unknown' ? '待检测' : mode === 'blocked' ? '1' : '0'
    byId('route-switch-scope').textContent = empty ? '近 1 小时暂无切换。' : '近 1 小时同源换模型 1 次，跨源切换 2 次。'
    const sourceHealth = mode === 'unknown'
      ? ['OpenRouter · 状态未检测', 'WorkBuddy · 状态未检测']
      : mode === 'blocked'
        ? ['OpenRouter · 0 / 2 个成员可调度 · 限流冷却、能力不符', 'WorkBuddy · 0 / 1 个成员可调度 · 额度耗尽']
        : ['OpenRouter · 1 / 2 个成员可调度', 'WorkBuddy · 1 / 1 个成员可调度']
    byId('route-source-health').replaceChildren(...sourceHealth.map(text => {
      const item = document.createElement('li')
      item.textContent = text
      return item
    }))
    byId('route-latest').textContent = empty ? '暂无调用。' : '最近命中 16:39 · ERNIE 5.5 Flash · 成功'
    byId('route-events').hidden = empty
    byId('route-no-events').hidden = !empty
    const message = byId('route-message')
    message.hidden = !view.message
    message.textContent = view.message
    byId('route-members').innerHTML = positions.map(index => {
      const row = members[index]
      const share = Math.round(row.handled / 196 * 100)
      const state = view.state[index]
      const tone = state === '可调度' ? 'ready' : mode === 'blocked' ? 'problem' : ''
      const note = mode === 'unknown' ? '暂未取得当前渠道状态。' : mode !== 'blocked' || index === 2 ? row.note : ['冷却至 16:45。','额度将在 18:00 重置。'][index]
      const load = empty ? '<small>暂无承载样本</small>' : `<small>承载 ${row.handled} 次 · ${share}%</small><div class="meter" aria-hidden="true"><span style="width:${share}%"></span></div>`
      return `<li><details class="member"><summary><div><strong>${row.name}</strong><small>${row.source}</small></div><span class="position">${ready.includes(index) ? '第 ' + (ready.indexOf(index) + 1) + ' 位' : view.positions[index]}</span><span class="status ${tone}">${state}</span><div>${load}</div></summary><p class="member-info muted">${empty && index === 0 ? '账号额度可用。' : note}</p></details></li>`
    }).join('')
  }
  const counts = {
    0: [],
    1: [[34,7,1,3],[43,12,2,4],[58,9,1,4],[51,15,3,4],[48,20,2,5],[43,8,1,3]],
    6: [[216,38,4,12],[283,46,7,14],[264,53,4,22],[299,61,4,33],[379,78,6,18],[277,71,10,23]],
    24: [[818,84,27,64],[721,58,31,24],[963,102,20,55],[949,113,36,87],[1216,220,38,95],[1024,183,26,77]],
  }
  const recoveryCounts = {
    0: [], 1: [2, 4, 2, 3, 5, 4], 6: [6, 9, 15, 12, 18, 19], 24: [25, 71, 32, 47, 65, 39],
  }
  const failureTypes = ['限流 429','鉴权失败','其他失败','切换后恢复']
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
    const recovered = total(recoveryCounts[hours])
    const localRecovered = selectedBucket < 0 ? recovered : recoveryCounts[hours][selectedBucket]
    byId('monitor-failed').textContent = fmt.format(total(full.slice(1)))
    byId('monitor-recovered').textContent = fmt.format(recovered)
    byId('monitor-selection').textContent = requests ? window + ' · ' + fmt.format(total(local)) + ' 个请求' : '该时段暂无调用'
    byId('failure-scope').textContent = requests ? window : '暂无样本'
    byId('monitor-chart').hidden = !requests
    const audit = byId('monitor-audit')
    audit.hidden = !failed && !localRecovered
    audit.textContent = selectedFailure < 0 ? '查看请求' : '查看所选请求'
    const query = new URLSearchParams({ demo:'monitor', range:window, reason:failureTypes[selectedFailure] || '全部结果' })
    audit.href = '#/audit?' + query
    byId('monitor-chart').innerHTML = buckets.map((row,index) => {
      const errors = total(row.slice(1))
      const switched = recoveryCounts[hours][index]
      const label = interval(hours,index) + '，成功 ' + row[0] + '，切换后恢复 ' + switched + '，失败 ' + errors
      return `<button type="button" data-bucket="${index}" aria-label="${label}" aria-pressed="${selectedBucket===index}"><span class="stack" aria-hidden="true"><span class="succeeded" style="height:${(row[0] - switched) / peak * 100}%"></span><span class="recovered" style="height:${switched / peak * 100}%"></span><span class="failed" style="height:${errors / peak * 100}%"></span></span><time>${interval(hours,index).slice(0,5)}</time></button>`
    }).join('')
    const outcomes = [...local.slice(1), localRecovered]
    const maximum = Math.max(1,...outcomes)
    byId('failure-list').innerHTML = (failed || localRecovered) ? failureTypes.map((label,index) => {
      const count = outcomes[index]
      return `<li><button type="button" data-failure="${index}" aria-pressed="${selectedFailure===index}"><span>${label}</span><small>${fmt.format(count)}</small><span class="meter" aria-hidden="true"><span class="${index === 3 ? 'recovered' : ''}" style="width:${count / maximum * 100}%"></span></span></button></li>`
    }).join('') : ''
  }

  const orderList = byId('draft-order')
  function renderDraftOrder() {
    orderList.innerHTML = draftOrder.map((index, position) => {
      const row = members[index]
      return `<li><button type="button" class="order-grip" data-order-index="${position}" aria-label="调整 ${row.name} 的顺序" aria-keyshortcuts="ArrowUp ArrowDown Home End"></button><small>第 ${position + 1} 位</small><strong>${row.name}</strong></li>`
    }).join('')
    byId('apply-order').disabled = draftOrder.every((index, position) => index === savedOrder[position])
  }
  function moveDraftMember(from, to) {
    if (from === to || to < 0 || to >= draftOrder.length) return
    draftOrder = [...draftOrder]
    const [moved] = draftOrder.splice(from, 1)
    draftOrder.splice(to, 0, moved)
    renderDraftOrder()
    orderList.children[to].querySelector('button').focus({preventScroll:true})
    byId('order-status').textContent = members[moved].name + ' 已移到第 ' + (to + 1) + ' 位，待应用。'
  }
  const cancelDrag = bindOrderDrag(orderList, root.closest('.scroll'), bind, moveDraftMember)
  bind(byId('route-order'), 'toggle', event => { if (!event.target.open) cancelDrag() })
  bind(window, 'hashchange', cancelDrag)
  bind(byId('apply-order'), 'click', () => {
    savedOrder = draftOrder
    renderDraftOrder()
    renderRoute()
    byId('order-status').textContent = '已应用。上方顺位使用新的成员顺序。'
  })
  renderDraftOrder()
  bind(byId('route-scenario'), 'change', renderRoute)
  renderRoute()
    bind(byId('monitor-range'), 'change', () => {
      selectedBucket = -1
      selectedFailure = -1
      renderMonitor()
    })
    bind(byId('monitor-chart'), 'click', event => {
      const button = event.target.closest('[data-bucket]')
      if (!button) return
      const index = Number(button.dataset.bucket)
      selectedBucket = selectedBucket === index ? -1 : index
      selectedFailure = -1
      renderMonitor()
      byId('monitor-chart').querySelector('[data-bucket="'+index+'"]').focus({preventScroll:true})
    })
    bind(byId('failure-list'), 'click', event => {
      const button = event.target.closest('[data-failure]')
      if (!button) return
      const index = Number(button.dataset.failure)
      selectedFailure = selectedFailure === index ? -1 : index
      renderMonitor()
      byId('failure-list').querySelector('[data-failure="'+index+'"]').focus({preventScroll:true})
    })
  renderMonitor()
  const gatewayCases = new Map([
    ['blocked', {
      caller: 'OKR · Claude Code · free',
      outcome: '请求失败 · 503',
      explanation: '网关在发送前找不到可用成员。',
      response: '503 MODEL_ROUTE_NO_AVAILABLE_MEMBER',
      attempts: 0,
      timeline: [
        ['接收请求', '解析到网关模型 free。'],
        ['选路未通过', '示例：一个成员处于冷却，另一个成员的上游额度已耗尽。'],
        ['返回失败', '上游尝试 0 次。'],
      ],
    }],
    ['exhausted', {
      caller: '聚合调用 · free',
      outcome: '切换后仍失败 · 503',
      explanation: '首选限流，备选额度耗尽，候选用完。',
      response: '503 MODEL_ROUTE_NO_AVAILABLE_MEMBER',
      attempts: 2,
      timeline: [
        ['第 1 次尝试 · 429', 'OpenRouter 免费模型 · 上游限流。'],
        ['第 2 次尝试 · 402', 'WorkBuddy · 上游额度耗尽。'],
        ['返回失败', '候选耗尽，计入 1 次最终失败。'],
      ],
    }],
    ['fallback', {
      caller: '聚合调用 · free',
      outcome: '切换后恢复',
      explanation: '首选受到上游限流，备选成员完成请求。',
      response: '200 · 响应完成',
      attempts: 2,
      timeline: [
        ['第 1 次尝试 · 429', 'OpenRouter 免费模型 · 上游限流。'],
        ['第 2 次尝试 · 成功', 'WorkBuddy · 返回完整响应。'],
        ['计入 1 次请求成功', '1 次切换恢复，来源侧仍保留第 1 次失败。'],
      ],
    }],
    ['stream', {
      caller: '聚合调用 · free',
      outcome: '输出中断',
      explanation: '输出已开始，客户端收到部分内容。',
      response: 'HTTP 200 · 流在完成前中断',
      attempts: 1,
      timeline: [
        ['第 1 次尝试 · 开始输出', '网关已向客户端发送首段输出。'],
        ['上游流中断', '上游尝试 1 次，后续发送 0 次。'],
        ['计入 1 次请求失败', '保留已发送状态与已知用量。'],
      ],
    }],
  ])
  function renderGatewayTimeline(element, rows) {
    element.replaceChildren(...rows.map(([title, evidence]) => {
      const item = document.createElement('li')
      const heading = document.createElement('strong')
      const detail = document.createElement('span')
      heading.textContent = title
      detail.textContent = evidence
      item.append(heading, detail)
      return item
    }))
  }
  const gatewayScenario = byId('gateway-scenario')
  {
    const updateScenario = () => {
      const requested = new URLSearchParams(location.hash.split('?')[1]).get('case')
      if (gatewayCases.has(requested)) gatewayScenario.value = requested
      render()
    }
    const render = () => {
      const name = gatewayScenario.value
      const entry = gatewayCases.get(name)
      for (const field of ['caller', 'outcome', 'explanation', 'response']) {
        byId('gateway-' + field).textContent = entry[field]
      }
      byId('gateway-attempts').textContent = entry.attempts + ' 次'
      byId('gateway-audit-link').href = '#/audit?demo=gateway&case=' + name
      byId('gateway-outcome').dataset.result = name
      renderGatewayTimeline(byId('gateway-timeline'), entry.timeline)
    }
    bind(gatewayScenario, 'change', () => {
      history.replaceState(null, '', '#/troubleshoot?case=' + gatewayScenario.value)
      render()
    })
    bind(window, 'hashchange', updateScenario)
    updateScenario()
  }
  function renderAudit() {
    const query = new URLSearchParams(location.hash.split('?')[1])
    const audit = byId('audit-example')
    audit.open = true
    byId('audit-record').hidden = true
    byId('gateway-audit-record').hidden = true
    byId('audit-return').hidden = true
    byId('audit-context').textContent = '从监控或调度选择一次调用。'
    const demo = query.get('demo')
    if (demo === 'route' || demo === 'monitor' || demo === 'usage') {
      const routes = { route: '#/aggregate', monitor: '#/monitoring', usage: '#/overview' }
      byId('audit-return').hidden = false
      byId('audit-return').href = routes[demo]
      byId('audit-record').hidden = demo !== 'route'
      const range = query.get('range')?.slice(0, 40) || '默认时段'
      const reason = query.get('reason')?.slice(0, 30) || '全部失败'
      byId('audit-context').textContent = demo === 'route'
        ? '聚合调用 · 16:35 · 已记录故障切换 · 演示'
        : demo === 'usage' ? '今日用量 · Asia/Shanghai · 演示'
        : range + ' · 全部来源 · 全部模型 · ' + reason + ' · 演示'
    }
    const name = query.get('case')
    const entry = demo === 'gateway' && gatewayCases.get(name)
    if (entry) {
      byId('audit-example').open = true
      byId('gateway-audit-record').hidden = false
      byId('audit-context').textContent = entry.caller + ' · 演示'
      byId('gateway-audit-outcome').textContent = entry.outcome
      byId('gateway-audit-outcome').dataset.result = name
      byId('gateway-audit-response').textContent = entry.response
      byId('gateway-audit-return').href = '#/troubleshoot?case=' + name
      renderGatewayTimeline(byId('gateway-audit-timeline'), entry.timeline)
    }
  }
  bind(window, 'hashchange', renderAudit)
  renderAudit()
  bind(byId('speech-test'), 'click', () => {
    byId('speech-status').textContent = '识别成功 · 演示'
  })
  bind(byId('plugin-import'), 'submit', event => {
    event.preventDefault()
    const path = byId('plugin-path').value.trim().replace(/\/$/, '')
    const workBuddy = path === 'packages/workbuddy' ||
      path === 'https://github.com/magpie-community/plugins/tree/main/packages/workbuddy'
    byId('plugin-preview').textContent = workBuddy
      ? '找到 WorkBuddy · Magpie 社区 · 兼容版 0.2.27（演示）'
      : '演示目录仅包含 packages/workbuddy。'
  })
  for (const [action, version] of [['update', '0.2.27'], ['rollback', '0.2.26']]) {
    bind(byId('plugin-' + action), 'click', () => {
      const updated = action === 'update'
      byId('plugin-version').textContent = version
      byId('plugin-available').textContent = updated ? '已是兼容版' : '0.2.27'
      byId('plugin-update').hidden = updated
      byId('plugin-rollback').hidden = !updated
      byId('plugin-update-status').textContent = (updated ? '已更新至 ' : '已回退至 ') + version
    })
  }
  bind(byId('claim'), 'click', () => {
    byId('claim').disabled = true
    byId('claim-status').textContent = '已领取 10 积分 · 演示回执'
    byId('bonus').textContent = '50'
  })
  return () => { cancelDrag(); controller.abort() }
}
