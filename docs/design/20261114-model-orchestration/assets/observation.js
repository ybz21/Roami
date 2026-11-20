'use strict'

function mountObservation(root, navigation = {
  query: () => location.search,
  href: (page, query) => page + '.html' + (query ? '?' + query : ''),
  destination: page => page + '.html',
  isCurrent: () => true,
}) {
  const by = id => root.querySelector('#' + id)
  const content = by('trace-content')
  const monitor = root.dataset.view === 'monitor'
  const pools = { coding: '日常编码', okr: 'OKR 工作流', direct: '原生直调', ...navigation.pools }
  const sources = {
    workbuddy: { name: 'WorkBuddy', model: 'DS 代码助手' },
    openrouter: { name: 'OpenRouter', model: 'Qwen 免费' },
    lan: { name: '本机 Qwen', model: '本机 Qwen' },
    ...navigation.sources,
  }
  const labels = {
    success: '直接成功', recovered: '切换后恢复', failed: '最终失败',
    rejected: '准入拒绝', exhausted: '候选用尽', interrupted: '输出中断',
  }
  const failures = ['rejected', 'exhausted', 'interrupted']
  const keys = ['success', 'recovered', ...failures]
  const buckets = [
    [6,0,0,0,0], [8,0,0,1,0], [5,1,0,0,0], [8,0,0,0,0], [7,0,1,0,0], [6,1,0,0,0],
    [7,0,0,0,0], [8,0,1,0,0], [7,1,0,0,0], [9,3,1,2,1], [7,0,0,1,0], [10,1,0,0,1],
  ]
  const time = minute => [Math.floor(minute / 60), minute % 60].map(value => String(value).padStart(2,'0')).join(':')
  const bucketAt = index => 13 * 60 + 30 + index * 5
  const bucketName = index => time(bucketAt(index)) + '–' + time(bucketAt(index) + 5)
  const pairs = Object.entries(sources)
  const pageSize = 8
  const fields = ['window', 'pool', 'source', 'result', 'bucket', 'q', 'page', 'id', 'origin']
  const defaults = { window:30, bucket:null, page:1 }
  const guard = (key, dict) => Object.hasOwn(dict,key) ? key : ''

  function simulate(bucket, position, outcome) {
    const { key: source, model } = outcome === 'success'
      ? [{ key: 'workbuddy', model: sources.workbuddy.model }, { key: 'openrouter', model: sources.openrouter.model }, { key: 'lan', model: sources.lan.model }][(bucket + position) % 3]
      : { key: outcome === 'recovered' ? 'openrouter' : 'workbuddy', model: '' }
    const entry = outcome === 'recovered' || outcome === 'exhausted'
      ? (bucket % 2 ? 'coding' : 'okr')
      : ['coding', 'coding', 'okr', 'direct'][(bucket + position) % 4]
    const when = time(bucketAt(bucket) + Math.floor(position / 4)) + ':' + String(4 + position * 3 % 56).padStart(2,'0')
    const attempts = {
      success: [{ source, code: 200, ms: 576 + 12 * position, note: '流正常结束' }],
      recovered: [
        { source: 'workbuddy', code: 429, ms: 195, note: '限流。按生效顺位尝试下一来源。' },
        { source: 'openrouter', code: 200, ms: 797, note: '接续完成，流正常结束。' },
      ],
      rejected: [],
      exhausted: [
        { source: 'workbuddy', code: 429, ms: 212, note: '上游限流' },
        { source: 'openrouter', code: 503, ms: 734, note: '上游暂不可用，候选已用尽。' },
      ],
      interrupted: [{ source: 'workbuddy', code: 200, ms: 1065, note: '已发送部分输出，随后连接断开。' }],
    }[outcome]
    const matched = outcome === 'success' ? model : outcome === 'recovered' ? sources.openrouter.model : ''
    const code = failures.includes(outcome) && outcome !== 'interrupted' ? 503 : 200
    const ms = attempts.reduce((sum,attempt) => sum + attempt.ms, 0)
    const fee = outcome === 'rejected' ? '未发往上游' : outcome === 'recovered' || (outcome==='success' && source==='openrouter')
      ? '¥0.00' : outcome === 'success' ? '¥0.01' : '费用未知'
    return { id: 'trace-' + bucket + '-' + position, bucket, when, entry, outcome, attempts, matched, code, fee, ms,
      tokens: matched ? 842 : outcome === 'interrupted' ? 180 : 0 }
  }

  const requests = buckets.flatMap((counts,bucket) => {
    let position = 0
    return counts.flatMap((count,index) => Array.from({ length:count }, () => simulate(bucket,position++,keys[index])))
  }).reverse()
  const findRequest = id => requests.find(row => row.id === id)

  function read(query = navigation.query()) {
    const p = new URLSearchParams(query)
    const window = p.get('window') === '60' ? 60 : 30
    const rawBucket = p.get('bucket')
    const bucket = rawBucket !== null && /^\d{1,2}$/.test(rawBucket) && Number(rawBucket) < buckets.length && Number(rawBucket) >= (window === 60 ? 0 : 6) ? Number(rawBucket) : null
    return { window, pool: guard(p.get('pool'),pools), source: guard(p.get('source'),sources), result: guard(p.get('result'),labels), bucket,
      q: (p.get('q') || '').slice(0,120), page: Math.min(1000,Math.max(1,parseInt(p.get('page'),10)||1)),
      id: findRequest(p.get('id'))?.id || '', origin: p.get('origin') || '' }
  }

  function params(state) {
    const p = new URLSearchParams()
    for (const key of fields) {
      const value = state[key]
      if (value !== undefined && value !== '' && value !== defaults[key]) p.set(key,String(value))
    }
    return p.toString()
  }

  function href(page,state) {
    return navigation.href(page,params(state))
  }

  const monitorScope = ({window, pool, source, result, bucket}) => ({window, pool, source, result, bucket})
  const auditHref = (state, changes = {}) => href('audit',{...monitorScope(state),origin:params(monitorScope(state))||'window=30',...changes})
  const recordMatches = (row,result) => !result || row.outcome === result || result === 'failed' && failures.includes(row.outcome)
  const countKind = (rows,result) => rows.filter(row => recordMatches(row,result)).length
  let state = read()

  function visibleRows(state) {
    const needle = state.q?.trim().toLowerCase()
    return requests.filter(row =>
      row.bucket >= (state.window === 60 ? 0 : 6)
      && (state.bucket == null || row.bucket === state.bucket)
      && (!state.pool || row.entry === state.pool)
      && (!state.source || row.attempts.some(attempt => attempt.source === state.source))
      && recordMatches(row,state.result)
      && (!needle || [pools[row.entry], row.matched, ...row.attempts.map(attempt => sources[attempt.source].name)]
        .some(value => value.toLowerCase().includes(needle))))
  }

  const setFields = () => {
    for (const name of ['window','pool','source','result','q']) {
      const field = by(name)
      if (field && field.value !== String(state[name])) field.value = state[name]
    }
  }
  const button = (text,attribute,extra='') => '<button type="button" ' + attribute + (extra ? ' ' + extra : '') + '>' + text + '</button>'
  const sampleStatus = (outcome) => '<span class="trace-result" data-kind="' + outcome + '">' + labels[outcome] + '</span>'
  const pairsMarkup = fields => fields.map(([name,value]) => '<div><dt>' + name + '</dt><dd>' + value + '</dd></div>').join('')

  function metricRow(rows) {
    return pairsMarkup([['请求总数',rows.length],['直接成功',countKind(rows,'success')],['切换后恢复',countKind(rows,'recovered')],['最终失败',countKind(rows,'failed')]])
  }

  function drawPlot(rows) {
    const start = state.window === 60 ? 0 : 6
    const sliced = buckets.map((_,index) => rows.filter(row => row.bucket===index)).slice(start)
    const max = Math.max(1,...sliced.map(group=>group.length))
    by('plot').style.setProperty('--buckets',String(sliced.length))
    by('plot').innerHTML = sliced.map((group,index)=>{
      const bucket = index + start
      const tally = [['success','直接成功'],['recovered','切换后恢复'],['failed','最终失败']]
        .map(([kind,text])=>({ kind,text,count:countKind(group,kind) }))
      const bars = tally.map(({kind,count})=>'<span data-kind="' + kind + '" style="--bar:' + count/max*100 + '%"></span>').join('')
      const alt = bucketName(bucket) + '，' + tally.map(({text,count}) => text + ' ' + count + ' 次').join('，')
      return button('<span class="trace-bars" aria-hidden="true">' + bars + '</span><small aria-hidden="true">' + time(bucketAt(bucket)) + '</small>',
        'class="trace-bucket" data-bucket="' + bucket + '" aria-pressed="' + (state.bucket===bucket) + '" aria-label="' + alt + '"')
    }).join('')
  }

  function drawHealth(rows) {
    const available = state.source ? [[state.source,sources[state.source]]] : pairs
    by('source-health').innerHTML = available.map(([id,source])=>{
      const attempts = rows.flatMap(row=>row.attempts).filter(attempt=>attempt.source===id)
      const latency = attempts.map(attempt=>attempt.ms).sort((a,b)=>a-b)
      const limited = attempts.filter(attempt=>attempt.code===429).length
      const p95 = latency[Math.ceil(latency.length*.95)-1]
      return '<div class="trace-health-row"><div><strong>' + source.name + '</strong><small>' + source.model + '</small></div>' +
        '<span><small>上游尝试</small>' + attempts.length + ' 次</span><span><small>429</small>' + limited + ' 次</span>' +
        '<span><small>P95 耗时</small>' + (p95 ? p95+' ms' : '无样本') + '</span>' +
        button('抽检','data-probe="' + id + '" aria-label="抽检 ' + source.name + '"') + '</div>'
    }).join('')
  }

  function drawMonitor() {
    setFields()
    const windowRows = visibleRows({...state,bucket:null,result:''})
    const selectedRows = visibleRows({...state,result:''})
    const detailRows = visibleRows(state)
    by('metrics').innerHTML = metricRow(detailRows)
    by('metrics').setAttribute('aria-label',state.bucket === null ? '当前时间范围请求统计' : bucketName(state.bucket) + ' 请求统计')
    drawPlot(windowRows)
    const sum = countKind(selectedRows,'failed')
    by('cause-scope').textContent = (state.bucket === null ? '当前时间范围' : bucketName(state.bucket)) + ' · ' + sum + ' 次失败'
    by('causes').innerHTML = sum ? failures.map(key => {
      const count = countKind(selectedRows,key)
      return button('<span>' + labels[key] + '</span><span>' + count + ' 次</span>','data-result="' + key + '" aria-pressed="' + (state.result===key) + '"',count ? '' : 'disabled')
    }).join('') : '<p class="trace-empty">这个范围内没有失败请求。</p>'
    const selected = state.bucket !== null || state.result
    by('selection').hidden = !selected
    by('selection').innerHTML = selected ? '<div class="trace-context">' +
      (state.bucket === null ? '' : '<span>' + bucketName(state.bucket) + '</span>' + button('清除时段','data-clear-monitor="bucket"')) +
      (state.result ? '<span>' + labels[state.result] + '</span>' + button('清除原因','data-clear-monitor="result"') : '') + '</div>' : ''
    const audit = auditHref(state)
    const peer = by('peer')
    if (peer) peer.href = audit
    by('review-audits').href = audit
    by('review-audits').textContent = selected ? '查看所选请求' : '查看请求审计'
    drawHealth(selectedRows)
  }

  function drawRecords(items) {
    if (!items.length) return '<p class="trace-empty">这个范围内没有请求。可以更改时间或筛选条件。</p>'
    return '<div class="trace-row-head" aria-hidden="true"><span>时间</span><span>调用入口</span><span>请求终态</span><span>费用</span></div>' +
      items.map(row => {
        const key = 'record-' + row.id
        const source = row.attempts.at(-1)?.source
        const name = row.matched || (source ? sources[source].name : '无上游尝试')
        const current = row.id === state.id ? ' aria-current="true"' : ''
        return '<a class="trace-record" id="' + key + '" data-record="' + row.id + '" href="' + htmlUrl(href('audit',{...state,id:row.id})) + '"' + current + '>' +
          '<span>' + row.when + '</span><span><strong>' + pools[row.entry] + '</strong><small>' + name + '</small></span>' +
          sampleStatus(row.outcome) + '<span class="trace-fee">' + row.fee + '</span></a>'
      }).join('')
  }

  const htmlUrl = value => value.replaceAll('&','&amp;')
  const eventEntry = (at,title,note) => '<li><time>' + at + '</time><div><strong>' + title + '</strong><small>' + note + '</small></div></li>'

  function drawDetail(row) {
    const intro = {
      success: '所选来源完成请求。', recovered: '首选限流，备选完成请求。', rejected: '费用准入拦截，网关尚未联系上游。',
      exhausted: '实际尝试了所有符合条件的候选。', interrupted: '已发送部分内容，连接随后中断。',
    }[row.outcome]
    const phases = eventEntry(row.when,row.outcome === 'rejected' ? '准入拒绝' : '通过准入',
      row.outcome === 'rejected' ? '请求在发出前结束。' : '使用当时生效的调度策略。') +
      row.attempts.map((attempt,index)=>eventEntry('第 ' + (index+1) + ' 次',sources[attempt.source].name + ' · HTTP ' + attempt.code,attempt.note)).join('')
    const [page, action] = row.outcome === 'rejected' ? ['usage','查看限额']
      : row.entry === 'direct' ? ['sources','查看模型源'] : ['aggregation','查看聚合顺位']
    const target = '<a class="trace-action" href="' + htmlUrl(navigation.destination(page,row)) + '">' + action + '</a>'
    return '<header class="trace-detail-top"><button type="button" class="trace-back trace-icon" data-close aria-label="返回请求列表"><span aria-hidden="true"></span></button>' +
      '<h2 id="detail-title" tabindex="-1">请求详情</h2></header>' +
      '<div class="trace-conclusion"><h3>' + labels[row.outcome] + '</h3><p class="trace-muted">' + intro + '</p><dl class="trace-facts">' +
      pairsMarkup([['调用入口',pools[row.entry]],['最终命中',row.matched || '无'],['上游尝试',row.attempts.length + ' 次'],['最终费用',row.fee]]) + '</dl></div>' +
      '<section><h3>尝试时间线</h3><ol class="trace-timeline">' + phases + '</ol></section>' +
      '<section><h3>响应与记账</h3><dl class="trace-facts">' + pairsMarkup([
        ['HTTP 状态',row.code],['耗时',row.ms ? row.ms + ' ms' : '未发送'],['已记录 Token',row.tokens]
      ]) + '</dl>' + target + '</section>' +
      '<details class="trace-technical"><summary>技术详情</summary><p>网关关联号 <code>req-demo-' + row.id + '</code></p>' +
      button('复制关联号','data-copy="req-demo-' + row.id + '"') + '<p id="copy-feedback" class="trace-muted" role="status"></p></details>'
  }

  function drawAudit() {
    setFields()
    const matched = visibleRows(state)
    const limit = Math.max(1,Math.ceil(matched.length/pageSize))
    const previous = state.page
    state.page = Math.min(state.page,limit)
    if (previous !== state.page) history.replaceState(history.state,'',href('audit',state))
    const start = (state.page-1)*pageSize
    const visible = matched.slice(start,start+pageSize)
    const active = findRequest(state.id)
    by('audit-workspace').classList.toggle('has-detail', Boolean(active))
    root.dataset.detail = Boolean(active)
    by('request-list').innerHTML = drawRecords(visible)
    const nav = by('pagination')
    nav.hidden = limit === 1
    nav.innerHTML = '<p>第 ' + state.page + ' / ' + limit + ' 页 · 共 ' + matched.length + ' 条</p>' +
      button('上一页','data-page="' + (state.page-1) + '"',state.page===1?'disabled':'') +
      button('下一页','data-page="' + (state.page+1) + '"',state.page===limit?'disabled':'')
    const detail = by('request-detail')
    detail.hidden = !active
    detail.innerHTML = active ? drawDetail(active) : ''
    const context = by('audit-context')
    const tags = []
    if (state.bucket !== null) tags.push('<span>所选时段 ' + bucketName(state.bucket) + '</span>' + button('清除时段','data-clear-bucket'))
    if (state.origin && state.result) tags.push('<span>所选结果 ' + labels[state.result] + '</span>')
    context.hidden = !tags.length
    context.innerHTML = tags.join('')
    const scope = state.origin ? monitorScope(read(state.origin)) : monitorScope(state)
    const returnHref = href('monitor',scope)
    const peer = by('peer')
    if (peer) peer.href = returnHref
    by('return-monitor').hidden = !state.origin
    by('return-monitor').href = returnHref
  }

  function render() {
    if (monitor) drawMonitor()
    else drawAudit()
  }

  function replace(patch,resetPage=false) {
    state = {...state,...patch}
    if (resetPage) Object.assign(state,{page:1,id:''})
    history.replaceState(history.state,'',href(monitor ? 'monitor' : 'audit',state))
    render()
  }

  const controller = new AbortController()
  const events = { signal: controller.signal }
  const filters = root.querySelector('form')
  filters.addEventListener('submit',event=>event.preventDefault(),events)
  filters.addEventListener('change',event=>{
    const field = event.target
    if (field.name === 'window') replace({window:Number(field.value),bucket:null,result:monitor?'':state.result},true)
    else if (field.tagName === 'SELECT') replace({[field.name]:field.value},true)
  },events)
  by('q')?.addEventListener('input',event=>replace({q:event.target.value.slice(0,120)},true),events)
  if (root === document.body) {
    document.addEventListener('pointermove',event=>{
      document.documentElement.dataset.pointer = event.pointerType==='mouse'?'fine':'coarse'
    },{...events,passive:true})
  }

  content.addEventListener('click',async event=>{
    const action = event.target.closest('button, a[data-record]')
    if (!action) return
    const data = action.dataset
    if (data.bucket !== undefined) {
      const bucket = Number(data.bucket)
      replace({bucket:state.bucket===bucket?null:bucket})
      content.querySelector('[data-bucket="' + bucket + '"]').focus({preventScroll:true})
    } else if (data.result) {
      replace({result:state.result===data.result?'':data.result})
      content.querySelector('[data-result="' + data.result + '"]').focus({preventScroll:true})
    } else if (data.clearMonitor !== undefined) {
      replace(data.clearMonitor === 'bucket' ? {bucket:null} : {result:''})
      by('review-audits').focus({preventScroll:true})
    } else if (data.probe) {
      const source = sources[data.probe]
      const status = by('probe-result')
      status.hidden = false
      status.textContent = '模拟抽检 · ' + source.name + ' · 可完成一条短文本请求。'
    } else if (data.clearBucket !== undefined) {
      replace({bucket:null},true)
      by('result').focus({preventScroll:true})
    } else if (data.page) {
      replace({page:Number(data.page),id:''})
      content.scrollTop = 0
      by('audit-heading').focus({preventScroll:true})
    } else if (data.record && !event.metaKey && !event.ctrlKey && !event.shiftKey && !event.altKey) {
      event.preventDefault()
      history.replaceState({focusId:data.record,scroll:content.scrollTop},'')
      state = {...state,id:data.record}
      history.pushState({returnToList:true},'',href('audit',state))
      render()
      content.scrollTop = 0
      by('detail-title').focus()
    } else if (data.close !== undefined) {
      if (history.state?.returnToList) history.back()
      else {
        replace({id:''})
        by('audit-heading').focus()
      }
    } else if (data.copy) {
      const feedback = by('copy-feedback')
      try {
        await navigator.clipboard.writeText(data.copy)
        feedback.textContent = '已复制'
      } catch {
        feedback.textContent = '无法自动复制。可选中上面的关联号手动复制。'
      }
    }
  },events)

  window.addEventListener('popstate',()=>{
    if (!navigation.isCurrent()) return
    state = read()
    render()
    if (monitor) return
    if (state.id) {
      content.scrollTop = 0
      by('detail-title').focus()
      return
    }
    const { focusId,scroll } = history.state || {}
    if (focusId) {
      content.scrollTop = scroll
      by('record-' + focusId)?.focus({preventScroll:true})
    }
  },events)

  for (const option of by('pool').options) {
    if (option.value) option.textContent = pools[option.value]
  }
  for (const option of by('source').options) {
    if (option.value) option.textContent = sources[option.value].name
  }
  render()
  return () => controller.abort()
}

globalThis.mountRoamiObservation = mountObservation
if (document.body.dataset.view) mountObservation(document.body)
