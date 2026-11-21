const zh = {
  pageTitle: '互审会话原型 · Roami',
  home: '首页', projects: '项目', tools: '工具', settings: '设置',
  create: '开任务', start: '开干', project: '项目',
  back: '返回', close: '关闭', prototype: '交互原型',
  noSessions: '暂无会话', taskPrompt: '任务描述', workspace: '工作区',
  exampleTask: '修复会话列表的活跃时间\n恢复会话后刷新活跃时间，并验证列表排序。',
  newWorkspace: '新建 worktree', existingWorkspace: '已有', base: '基于',
  terminal: '终端', voice: '语音输入', attach: '添加附件',
  author: '作者', reviewer: '审查者', review: '互审',
  trigger: '交审方式', bySubmit: '主动交审', byIdle: '空闲交审',
  authorPrompt: '作者', reviewerPrompt: '审查者', messages: '会话记录', sessions: '任务会话',
  openReviewer: '打开 review', openAuthor: '打开作者会话',
  context: (role, trigger) => role + ' · ' + trigger,
  waiting: '等待交审', reviewing: '审查中', changes: '待修复', approved: '通过', limit: '达到轮次上限',
  waitingSubmit: '等待作者提交可审版本。', waitingIdle: '等待作者空闲且有新改动。',
  simulateSubmit: '演示主动交审', simulateIdle: '演示空闲交审',
  simulateChanges: '演示发回意见', simulateFix: '演示修复交审', simulateApproval: '演示通过',
  submitted: '提交版本', feedback: '请求修改', revised: '提交修复', passed: '审查通过',
  round: (n) => '第 ' + n + ' 轮',
  taskInput: '用户 · 任务', reviewInput: 'Roami · 互审任务', hostInput: 'Roami · 空闲交审',
  incoming: (name, role) => '来自' + (role === 'reviewer' ? ' review · ' : '作者会话 · ') + name,
  sendTool: (peer) => '查看发送记录 · ' + peer,
  receivedFeedback: '我会先按意见修改并验证，再提交新的版本。',
  submittedMessage: '请审这一版的改动。会话恢复时已刷新活跃时间，列表排序通过了基本验证。请再检查相同时间戳和已有会话数据。',
  idleMessage: '作者已空闲，收到一个新版本。请检查会话恢复后的时间刷新和列表排序。',
  feedbackMessages: [
    '结论：请修复后复审。\n\nsession-list.ts:84  时间戳相同时，列表可能在两次刷新之间跳动。请保持原顺序，并增加两条会话时间相同的回归用例。\n\n证据：对照两次刷新时的列表结果。',
    '排序问题已修复。还需要补一个场景：旧记录没有活动时间时，应按创建时间排序。请加一条旧数据回归用例后再提交。',
    '旧数据回归已补齐。还发现一条边界：无效时间字符串应按缺失值处理。请记录该问题供后续处理。',
  ],
  revisionMessages: [
    '已让时间戳相同的会话保留原顺序，新增回归用例已通过。请用新版本复审。',
    '已为缺失活动时间的记录回退到创建时间，旧数据和排序回归均通过。请用新版本复审。',
  ],
  passedMessage: '结论：通过。已核对本轮版本里的时间刷新、稳定排序以及对应的验证证据。',
  limitMessage: '已到本次审查轮次上限。剩余问题保留在消息中。',
}
const en = {
  pageTitle: 'Peer review prototype · Roami',
  home: 'Home', projects: 'Projects', tools: 'Tools', settings: 'Settings',
  create: 'New task', start: 'Start task', project: 'Project',
  back: 'Back', close: 'Close', prototype: 'Interactive prototype',
  noSessions: 'No sessions yet', taskPrompt: 'Task description', workspace: 'Workspace',
  exampleTask: 'Fix session activity timestamps\nRefresh activity on resume and verify the session list order.',
  newWorkspace: 'New worktree', existingWorkspace: 'Existing', base: 'From',
  terminal: 'Terminal', voice: 'Voice input', attach: 'Attach files',
  author: 'Author', reviewer: 'Reviewer', review: 'Peer review',
  trigger: 'Review trigger', bySubmit: 'Author submits', byIdle: 'When idle',
  authorPrompt: 'Author', reviewerPrompt: 'Reviewer', messages: 'Session transcript', sessions: 'Task sessions',
  openReviewer: 'Open review', openAuthor: 'Open author session',
  context: (role, trigger) => role + ' · ' + trigger,
  waiting: 'Awaiting submission', reviewing: 'Reviewing', changes: 'Changes requested',
  approved: 'Approved', limit: 'Round limit reached',
  waitingSubmit: 'Waiting for the author to submit a version.', waitingIdle: 'Waiting for new changes and idle time.',
  simulateSubmit: 'Simulate author submission', simulateIdle: 'Simulate idle review',
  simulateChanges: 'Simulate sending feedback', simulateFix: 'Simulate resubmission', simulateApproval: 'Simulate approval',
  submitted: 'Review requested', feedback: 'Changes requested', revised: 'Fix submitted', passed: 'Review approved',
  round: (n) => 'Round ' + n,
  taskInput: 'User · Task', reviewInput: 'Roami · Review task', hostInput: 'Roami · Idle review',
  incoming: (name, role) => 'From ' + (role === 'reviewer' ? 'review' : 'author session') + ' · ' + name,
  sendTool: (peer) => 'View send record · ' + peer,
  receivedFeedback: 'I’ll address these findings, verify the fix, and submit a new revision.',
  submittedMessage: 'Please review this revision. Resuming a session now refreshes its activity and the basic sort check passed. Check equal timestamps and older records.',
  idleMessage: 'The author is idle and a new revision is ready. Check activity refresh and list sorting after resume.',
  feedbackMessages: [
    'Changes requested.\n\nsession-list.ts:84 Rows may jump between refreshes when timestamps match. Preserve the previous order and add a regression case with matching timestamps.\n\nEvidence: compare the list order across two refreshes.',
    'The sort fix checks out. Add a case for older records with no activity timestamp, which should sort by creation time.',
    'The older-record check is in place. An invalid timestamp should also fall back to creation time. Record this finding for follow-up.',
  ],
  revisionMessages: [
    'Matching timestamps now preserve the previous order. The new regression case passed. Please review this revision.',
    'Records with missing timestamps now use creation time. The older-record and sorting checks passed. Please review this revision.',
  ],
  passedMessage: 'Approved. I checked activity refresh and stable ordering against this revision and its verification results.',
  limitMessage: 'This review reached its round limit. The remaining findings are in the messages.',

}

const query = new URLSearchParams(location.search)
const language = query.get('lang') || navigator.language
const t = language.startsWith('en') ? en : zh
const root = document.documentElement
root.lang = t === en ? 'en-US' : 'zh-CN'
root.dataset.theme = query.get('theme') === 'light' ? 'light' : 'dark'
root.dataset.pointer = navigator.maxTouchPoints ? 'coarse' : 'fine'
window.addEventListener('pointerdown', (event) => {
  root.dataset.pointer = event.pointerType === 'touch' ? 'coarse' : 'fine'
})
document.title = t.pageTitle

const all = (selector) => [...document.querySelectorAll(selector)]
const byId = (id) => document.getElementById(id)
const agentNames = { claude: 'Claude Code', codex: 'Codex', opencode: 'OpenCode', pi: 'Pi' }
const exampleIds = { author: '2026-1120-1600-a001', reviewer: '2026-1120-1600-r001' }
const revisions = ['b7a18c2', 'e124dc0', 'd80ae91']
const messageKinds = {
  submitted: 'request', revised: 'request', feedback: 'changes_requested', passed: 'approved',
}
const composer = byId('composer')
const triggerInput = byId('review-trigger')
const promptInput = byId('task-prompt')

let authorAgent = 'codex'
let reviewEnabled = false
let explicitReviewer = null
let task = null
let currentRole = null

all('[data-t]').forEach((element) => { element.textContent = t[element.dataset.t] })
all('[data-label]').forEach((element) => { element.setAttribute('aria-label', t[element.dataset.label]) })
promptInput.value = t.exampleTask

function setMark(svg, name) {
  const use = document.createElementNS('http://www.w3.org/2000/svg', 'use')
  const mark = name === 'opencode' && root.dataset.theme === 'light' ? 'opencode-light' : name
  use.setAttribute('href', '#icon-' + mark)
  svg.replaceChildren(use)
}

function populateAgentChoices(group, role) {
  const firstStaticControl = group.querySelector('button')
  for (const [kind, name] of Object.entries(agentNames)) {
    const button = document.createElement('button')
    button.type = 'button'
    button.className = 'icon-button pill'
    button.dataset[role] = kind
    button.title = name
    button.setAttribute('aria-label', name)
    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg')
    svg.setAttribute('aria-hidden', 'true')
    setMark(svg, kind)
    button.append(svg)
    group.insertBefore(button, firstStaticControl)
  }
}

const nav = byId('mobile-nav')
nav.setAttribute('aria-label', t.projects)
for (const [key, icon] of [['home', 'home'], ['projects', 'folder'], ['tools', 'tools'], ['settings', 'settings']]) {
  const button = document.createElement('button')
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg')
  const label = document.createElement('span')
  button.type = 'button'
  svg.setAttribute('aria-hidden', 'true')
  setMark(svg, icon)
  label.textContent = t[key]
  button.append(svg, label)
  if (key === 'projects') {
    button.setAttribute('aria-current', 'page')
    button.addEventListener('click', showProject)
  } else {
    button.disabled = true
  }
  nav.append(button)
}

function suggestedReviewer() {
  return authorAgent === 'codex' ? 'claude' : 'codex'
}

function renderForm() {
  all('[data-author]').forEach((button) => {
    button.setAttribute('aria-pressed', String(button.dataset.author === authorAgent))
  })
  const reviewer = explicitReviewer || suggestedReviewer()
  all('[data-reviewer]').forEach((button) => {
    button.setAttribute('aria-pressed', String(reviewEnabled && button.dataset.reviewer === reviewer))
  })
  byId('review-toggle').setAttribute('aria-expanded', String(reviewEnabled))
  byId('review-options').hidden = !reviewEnabled
}

function showProject() {
  currentRole = null
  byId('project-view').hidden = false
  byId('session-view').hidden = true
  nav.hidden = false
  setCurrentRow()
}

function setCurrentRow() {
  for (const row of all('[data-open-session]')) {
    if (row.dataset.openSession === currentRole) row.setAttribute('aria-current', 'true')
    else row.removeAttribute('aria-current')
  }
}

function showSession(role) {
  currentRole = role
  byId('project-view').hidden = true
  byId('session-view').hidden = false
  nav.hidden = true
  renderSession()
  byId('session-title').focus({ preventScroll: true })
  const scroll = byId('session-scroll')
  scroll.scrollTop = task.messages.length ? scroll.scrollHeight : 0
}

function renderSession() {
  setCurrentRow()
  byId('session-title').textContent = currentRole === 'reviewer' ? 'review' : task.name
  byId('task-message').textContent = task.description
  byId('task-source').textContent = t[currentRole === 'reviewer' ? 'reviewInput' : 'taskInput']
  if (!task.hasReview) {
    byId('waiting-message').hidden = true
    byId('messages').replaceChildren()
    return
  }
  const isAuthor = currentRole === 'author'
  byId('current-agent').textContent = agentNames[task[currentRole]]
  setMark(byId('current-agent-icon'), task[currentRole])
  byId('session-context').textContent = t.context(
    t[isAuthor ? 'authorPrompt' : 'reviewerPrompt'],
    t[task.trigger === 'idle' ? 'byIdle' : 'bySubmit'],
  ) + (task.round ? ' · ' + t.round(task.round) : '')
  byId('open-peer').lastElementChild.textContent = t[isAuthor ? 'openReviewer' : 'openAuthor']
  byId('status').dataset.stage = task.stage
  all('[data-review-status]').forEach((node) => { node.textContent = t[task.stage] })
  const waiting = byId('waiting-message')
  waiting.textContent = task.stage === 'limit' ? t.limitMessage : t[task.trigger === 'idle' ? 'waitingIdle' : 'waitingSubmit']
  waiting.hidden = !['waiting', 'limit'].includes(task.stage)
  byId('messages').replaceChildren(...task.messages.map(renderMessage))
  const next = byId('next-step')
  const actions = {
    waiting: task.trigger === 'idle' ? 'simulateIdle' : 'simulateSubmit',
    reviewing: 'simulateChanges',
    changes: 'simulateFix',
  }
  next.hidden = !actions[task.stage]
  next.textContent = actions[task.stage] ? t[actions[task.stage]] : ''
  byId('approve-step').hidden = task.stage !== 'reviewing'
}

function sendCommand(message, peer) {
  const body = '[review.' + messageKinds[message.action] + '] r' + message.round + ' rev=' + message.version + '\n' + message.body
  return 'roami session send "' + exampleIds[peer] + '" ' + "'" + body.replaceAll("'", "'\\''") + "'"
}

function renderSendStep(message, peer) {
  const details = document.createElement('details')
  details.className = 'prompt-details tool-disclosure'
  const summary = document.createElement('summary')
  const mark = document.createElementNS('http://www.w3.org/2000/svg', 'svg')
  mark.setAttribute('aria-hidden', 'true')
  setMark(mark, 'next')
  const peerLabel = peer === 'reviewer' ? 'review' : agentNames[task.author]
  summary.append(mark, t.sendTool(peerLabel))
  const command = document.createElement('pre')
  command.textContent = sendCommand(message, peer)
  details.append(summary, command)
  return details
}

function renderMessage(message) {
  const row = document.createElement('li')
  const turn = document.createElement('div')
  const outgoing = message.sender === currentRole && !message.fromHost
  if (!outgoing) turn.className = 'inbound'
  const header = document.createElement('header')
  const mark = document.createElementNS('http://www.w3.org/2000/svg', 'svg')
  mark.setAttribute('aria-hidden', 'true')
  setMark(mark, task[message.sender])
  const sender = document.createElement('strong')
  const name = agentNames[task[message.sender]]
  sender.textContent = message.fromHost ? t.hostInput : outgoing ? name : t.incoming(name, message.sender)
  const metadata = document.createElement('span')
  metadata.className = 'badge'
  metadata.textContent = [t[message.action], t.round(message.round), message.version].join(' · ')
  if (!message.fromHost) header.append(mark)
  header.append(sender, metadata)
  const detail = document.createElement('p')
  detail.className = 'turn-body'
  detail.textContent = message.body
  turn.append(header, detail)
  row.append(turn)
  if (outgoing) row.append(renderSendStep(message, currentRole === 'author' ? 'reviewer' : 'author'))
  if (currentRole === 'author' && message.action === 'feedback' && message.round < revisions.length) {
    const response = document.createElement('p')
    response.className = 'turn-response'
    response.textContent = t.receivedFeedback
    row.append(response)
  }
  return row
}

function recordMessage(sender, action, body, fromHost = false) {
  task.messages.push({ sender, action, body, fromHost, round: task.round, version: revisions[task.round - 1] })
}

function advanceReview() {
  if (task.stage === 'waiting' || task.stage === 'changes') {
    const firstRound = task.round === 0
    const fromHost = firstRound && task.trigger === 'idle'
    const body = firstRound ? t[fromHost ? 'idleMessage' : 'submittedMessage'] : t.revisionMessages[task.round - 1]
    task.round += 1
    task.stage = 'reviewing'
    recordMessage('author', firstRound ? 'submitted' : 'revised', body, fromHost)
  } else if (task.stage === 'reviewing') {
    task.stage = task.round === revisions.length ? 'limit' : 'changes'
    recordMessage('reviewer', 'feedback', t.feedbackMessages[task.round - 1])
  }
  displayLatestTurn()
}

function approveReview() {
  if (task.stage !== 'reviewing') return
  task.stage = 'approved'
  recordMessage('reviewer', 'passed', t.passedMessage)
  displayLatestTurn()
}

function displayLatestTurn() {
  renderSession()
  const result = document.querySelector('#messages li:last-child')
  result?.scrollIntoView({ block: 'nearest' })
}

function createTask(event) {
  event.preventDefault()
  const description = promptInput.value.trim()
  if (!description) {
    promptInput.value = ''
    promptInput.reportValidity()
    return
  }
  task = {
    description,
    author: authorAgent,
    reviewer: explicitReviewer || suggestedReviewer(),
    trigger: triggerInput.value,
    name: description.split('\n')[0],
    hasReview: reviewEnabled,
    stage: 'waiting',
    round: 0,
    messages: [],
  }
  all('[data-task-name]').forEach((element) => { element.textContent = task.name })
  all('[data-author-mark]').forEach((element) => setMark(element, task.author))
  all('[data-session-tree]').forEach((element) => { element.hidden = false })
  all('[data-review-only]').forEach((element) => { element.hidden = !task.hasReview })
  all('[data-review-only] [data-reviewer-mark]').forEach((element) => setMark(element, task.reviewer))
  byId('project-empty').hidden = true
  composer.close()
  showSession('author')
}

populateAgentChoices(document.querySelector('.author-choices'), 'author')
populateAgentChoices(document.querySelector('.review-choices'), 'reviewer')
all('[data-author]').forEach((button) => button.addEventListener('click', () => {
  authorAgent = button.dataset.author
  renderForm()
}))
all('[data-reviewer]').forEach((button) => button.addEventListener('click', () => {
  explicitReviewer = button.dataset.reviewer
  reviewEnabled = true
  renderForm()
}))
byId('review-toggle').addEventListener('click', () => {
  reviewEnabled = !reviewEnabled
  renderForm()
})
all('[data-workspace]').forEach((button) => button.addEventListener('click', () => {
  const usingNew = button.dataset.workspace === 'new'
  all('[data-workspace]').forEach((option) => option.setAttribute('aria-pressed', String(option === button)))
  byId('worktree-branch').parentElement.hidden = !usingNew
  byId('existing-branch').hidden = usingNew
}))
all('[data-open-composer]').forEach((button) => button.addEventListener('click', () => composer.showModal()))
all('[data-close-composer]').forEach((button) => button.addEventListener('click', () => composer.close()))
all('[data-open-session]').forEach((button) => button.addEventListener('click', () => showSession(button.dataset.openSession)))
byId('task-form').addEventListener('submit', createTask)
byId('next-step').addEventListener('click', advanceReview)
byId('approve-step').addEventListener('click', approveReview)
byId('session-back').addEventListener('click', () => {
  showProject()
  document.querySelector('#project-view [data-open-composer]').focus({ preventScroll: true })
})
byId('open-peer').addEventListener('click', () => showSession(currentRole === 'author' ? 'reviewer' : 'author'))
renderForm()
composer.showModal()
