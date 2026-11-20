const zh = {
  pageTitle: '互审会话原型 · Roami',
  home: '首页', projects: '项目', tools: '工具', settings: '设置',
  create: '开任务', start: '开工', project: '项目',
  back: '返回', close: '关闭', prototype: '交互原型',
  noSessions: '暂无会话', taskPrompt: '任务描述', workspace: '新建工作区 · 基于 main',
  exampleTask: '修复会话列表的活跃时间\n恢复会话后刷新活跃时间，并验证列表排序。',
  author: '作者', reviewer: '审查 Agent', review: '互审',
  reviewChild: '开工时创建 review 子会话',
  autoOption: (name) => '自动配对（' + name + '）',
  trigger: '交审方式', bySubmit: '主动交审', byIdle: '空闲交审', maxRounds: '最多轮次',
  submitHint: '作者有可审版本时，主动通知审查 Agent。',
  idleHint: '作者空闲且有新改动时，自动开始首轮审查。',
  promptTitle: '查看双方 Prompt', currentPrompt: '查看启动 Prompt',
  authorPrompt: '作者', reviewerPrompt: '审查者', messages: '互审消息',
  openReviewer: '打开 review', openAuthor: '打开作者会话',
  context: (role, trigger, rounds) => role + ' · ' + trigger + ' · 最多 ' + rounds + ' 轮',
  waiting: '等待交审', reviewing: '审查中', changes: '待修复', approved: '通过', limit: '达到轮次上限',
  waitingSubmit: '等待作者提交可审版本。', waitingIdle: '等待作者空闲且有新改动。',
  simulateSubmit: '演示主动交审', simulateIdle: '演示空闲交审',
  simulateChanges: '演示审查意见', simulateFix: '演示修复交审', simulateApproval: '演示审查通过',
  submitted: '提交版本', feedback: '请求修改', revised: '提交修复', passed: '审查通过',
  round: (n) => '第 ' + n + ' 轮',
  submittedMessage: '恢复会话后会刷新活跃时间，请核对列表排序。',
  idleMessage: '作者已空闲，首次交审已提交。请检查恢复会话后的列表排序。',
  feedbackMessage: 'session-list.ts:84 时间相同时排序会跳动。建议保留稳定排序并补充回归验证。',
  revisedMessage: '已为相同时间戳加入稳定排序，并验证恢复会话后的列表顺序，请复审。',
  passedMessage: '已核对时间刷新、稳定排序及验证结果。',
  limitMessage: '已到本次审查轮次上限。剩余问题保留在消息中。',
  authorIntro: (agent, peer) => '你是作者。审查者为 ' + agent + '，对端会话 ID 为 ' + peer + '。',
  reviewerIntro: (agent, peer) => '你负责审查。作者为 ' + agent + '，对端会话 ID 为 ' + peer + '。',
  reviewerScope: (description) => '审查任务\n' + description,
  authorSubmit: '有可审版本时，将轮次、版本和验证摘要发给审查者。',
  authorIdle: '等待宿主在作者空闲且有新改动时发送首次交审。后续修复完成后按下方命令提交复审。',
  authorIdleSingle: '等待宿主在作者空闲且有新改动时发送交审。收到意见后记录剩余问题，本次只审一轮。',
  authorFollowup: '收到修改意见后逐项响应，验证后提交新版本。达到轮次上限后保留剩余问题并结束。',
  reviewerRule: '等待交审，核对消息中的轮次与只读版本快照。将文件位置、问题和建议发回作者，或明确给出通过结论。',
  reviewerFollowup: '仅评价收到的版本。经过验证才能标记通过。',
  cmdRequest: '验证摘要', cmdFeedback: '文件:行、问题、建议', cmdApproval: '验证结论',
}
const en = {
  pageTitle: 'Peer review prototype · Roami',
  home: 'Home', projects: 'Projects', tools: 'Tools', settings: 'Settings',
  create: 'New task', start: 'Start task', project: 'Project',
  back: 'Back', close: 'Close', prototype: 'Interactive prototype',
  noSessions: 'No sessions yet', taskPrompt: 'Task description', workspace: 'New worktree · from main',
  exampleTask: 'Fix session activity timestamps\nRefresh activity on resume and verify the session list order.',
  author: 'Author', reviewer: 'Review agent', review: 'Peer review',
  reviewChild: 'Creates a review child session at startup',
  autoOption: (name) => 'Automatic pairing (' + name + ')',
  trigger: 'Review trigger', bySubmit: 'Author submits', byIdle: 'When author is idle', maxRounds: 'Max rounds',
  submitHint: 'The author contacts the reviewer when a version is ready.',
  idleHint: 'The first review starts when the author is idle and has new changes.',
  promptTitle: 'Preview both prompts', currentPrompt: 'View startup prompt',
  authorPrompt: 'Author', reviewerPrompt: 'Reviewer', messages: 'Review messages',
  openReviewer: 'Open review', openAuthor: 'Open author session',
  context: (role, trigger, rounds) => role + ' · ' + trigger + ' · Up to ' + rounds + ' rounds',
  waiting: 'Awaiting submission', reviewing: 'Reviewing', changes: 'Changes requested',
  approved: 'Approved', limit: 'Round limit reached',
  waitingSubmit: 'Waiting for the author to submit a version.', waitingIdle: 'Waiting for new changes and idle time.',
  simulateSubmit: 'Simulate author submission', simulateIdle: 'Simulate idle review',
  simulateChanges: 'Simulate review feedback', simulateFix: 'Simulate resubmission', simulateApproval: 'Simulate approval',
  submitted: 'Review requested', feedback: 'Changes requested', revised: 'Fix submitted', passed: 'Review approved',
  round: (n) => 'Round ' + n,
  submittedMessage: 'Resuming a session now refreshes activity. Please verify the list order.',
  idleMessage: 'The author is idle and the first review is queued. Please check the list order after resume.',
  feedbackMessage: 'session-list.ts:84 Rows can jump when timestamps match. Preserve stable order and add a regression check.',
  revisedMessage: 'Equal timestamps now have stable ordering. I verified the list after resume. Please review again.',
  passedMessage: 'I verified the activity refresh, stable order, and validation results.',
  limitMessage: 'This review reached its round limit. The remaining findings are in the messages.',
  authorIntro: (agent, peer) => 'You are the author. Your reviewer is ' + agent + ', session ID ' + peer + '.',
  reviewerIntro: (agent, peer) => 'You are the reviewer. The author is ' + agent + ', session ID ' + peer + '.',
  reviewerScope: (description) => 'Task to review\n' + description,
  authorSubmit: 'When a version is ready, send its round, revision, and validation summary to the reviewer.',
  authorIdle: 'The host submits the first review when the author is idle and has new changes. Use the command below to submit fixes for review.',
  authorIdleSingle: 'The host requests review when the author is idle and has new changes. Record open findings after the first round.',
  authorFollowup: 'Address the findings and verify your changes before submitting a new version. At the round limit, report any open findings and stop.',
  reviewerRule: 'Wait for the request. Check the round and its read-only snapshot. Send findings with file locations and suggestions, or report approval.',
  reviewerFollowup: 'Review the submitted revision. Report approval when verification is complete.',
  cmdRequest: 'Validation summary', cmdFeedback: 'File:line, finding, suggestion', cmdApproval: 'Validation result',
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
const agentNames = { codex: 'Codex', claude: 'Claude Code' }
const exampleIds = { author: '2026-1120-1600-a001', reviewer: '2026-1120-1600-r001' }
const composer = byId('composer')
const authorInput = byId('author-agent')
const reviewerInput = byId('reviewer-agent')
const triggerInput = byId('review-trigger')
const roundsInput = byId('review-rounds')
const enabledInput = byId('enable-review')
const promptInput = byId('task-prompt')

let draftRole = 'author'
let task = null
let currentRole = null

all('[data-t]').forEach((element) => { element.textContent = t[element.dataset.t] })
all('[data-label]').forEach((element) => { element.setAttribute('aria-label', t[element.dataset.label]) })
promptInput.value = t.exampleTask

function setMark(svg, name) {
  const use = document.createElementNS('http://www.w3.org/2000/svg', 'use')
  use.setAttribute('href', '#icon-' + name)
  svg.replaceChildren(use)
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

function selectedReview() {
  const other = authorInput.value === 'codex' ? 'claude' : 'codex'
  return {
    description: promptInput.value.trim(),
    author: authorInput.value,
    reviewer: reviewerInput.value === 'auto' ? other : reviewerInput.value,
    trigger: triggerInput.value,
    rounds: Number(roundsInput.value),
  }
}

function reviewPrompt(role, settings, preview) {
  const peer = role === 'author' ? 'reviewer' : 'author'
  const peerId = preview ? (peer === 'reviewer' ? '$REVIEW_SESSION_ID' : '$AUTHOR_SESSION_ID') : exampleIds[peer]
  const send = 'roami session send "' + peerId + '" '
  if (role === 'author') {
    const idle = settings.trigger === 'idle'
    const intro = [
      t.authorIntro(agentNames[settings.reviewer], peerId),
      t.context(t.authorPrompt, t[idle ? 'byIdle' : 'bySubmit'], settings.rounds),
    ]
    if (idle && settings.rounds === 1) return [...intro, t.authorIdleSingle].join('\n\n')
    const example = "'[review.request] " + (idle ? 'r2 rev=e124dc0 ' : 'r1 rev=b7a18c2 ') + t.cmdRequest + "'"
    return [
      ...intro,
      t[idle ? 'authorIdle' : 'authorSubmit'], send + example, t.authorFollowup,
    ].join('\n\n')
  }
  return [
    t.reviewerIntro(agentNames[settings.author], peerId),
    t.reviewerScope(settings.description),
    t.context(t.reviewerPrompt, t[settings.trigger === 'idle' ? 'byIdle' : 'bySubmit'], settings.rounds),
    t.reviewerRule,
    send + "'[review.changes_requested] r1 rev=b7a18c2 " + t.cmdFeedback + "'",
    send + "'[review.approved] r1 rev=b7a18c2 " + t.cmdApproval + "'",
    t.reviewerFollowup,
  ].join('\n\n')
}

function renderForm() {
  const settings = selectedReview()
  byId('review-fields').hidden = !enabledInput.checked
  byId('review-child-hint').hidden = !enabledInput.checked
  const suggested = authorInput.value === 'codex' ? 'claude' : 'codex'
  reviewerInput.options[0].textContent = t.autoOption(agentNames[suggested])
  setMark(reviewerInput.previousElementSibling, settings.reviewer)
  byId('trigger-hint').textContent = t[settings.trigger === 'idle' ? 'idleHint' : 'submitHint']
  byId('prompt-preview').textContent = reviewPrompt(draftRole, settings, true)
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
  byId('session-scroll').scrollTop = 0
  byId('session-title').focus({ preventScroll: true })
}

function renderSession() {
  setCurrentRow()
  byId('session-title').textContent = currentRole === 'reviewer' ? 'review' : task.name
  byId('task-message').textContent = task.description
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
    task.rounds,
  )
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
    reviewing: task.round === 1 ? 'simulateChanges' : 'simulateApproval',
    changes: 'simulateFix',
  }
  next.hidden = !actions[task.stage]
  next.textContent = actions[task.stage] ? t[actions[task.stage]] : ''
  byId('runtime-prompt').textContent = reviewPrompt(currentRole, task, false)
}

function renderMessage(message) {
  const row = document.createElement('li')
  const header = document.createElement('header')
  const mark = document.createElementNS('http://www.w3.org/2000/svg', 'svg')
  mark.setAttribute('aria-hidden', 'true')
  setMark(mark, task[message.sender])
  const sender = document.createElement('strong')
  sender.textContent = agentNames[task[message.sender]]
  const metadata = document.createElement('span')
  metadata.className = 'badge'
  metadata.textContent = [t[message.action], t.round(message.round), message.version].join(' · ')
  header.append(mark, sender, metadata)
  const detail = document.createElement('p')
  detail.textContent = t[message.body]
  row.append(header, detail)
  return row
}

function advanceReview() {
  if (task.stage === 'waiting') {
    task.round = 1
    task.stage = 'reviewing'
    task.messages.push({ sender: 'author', action: 'submitted', round: 1, version: 'b7a18c2',
      body: task.trigger === 'idle' ? 'idleMessage' : 'submittedMessage' })
  } else if (task.stage === 'reviewing' && task.round === 1) {
    task.stage = task.rounds === 1 ? 'limit' : 'changes'
    task.messages.push({ sender: 'reviewer', action: 'feedback', round: 1, version: 'b7a18c2', body: 'feedbackMessage' })
  } else if (task.stage === 'changes') {
    task.round = 2
    task.stage = 'reviewing'
    task.messages.push({ sender: 'author', action: 'revised', round: 2, version: 'e124dc0', body: 'revisedMessage' })
  } else if (task.stage === 'reviewing') {
    task.stage = 'approved'
    task.messages.push({ sender: 'reviewer', action: 'passed', round: 2, version: 'e124dc0', body: 'passedMessage' })
  }
  renderSession()
  byId('session-scroll').scrollTop = byId('session-scroll').scrollHeight
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
    ...selectedReview(),
    name: description.split('\n')[0],
    hasReview: enabledInput.checked,
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

for (const input of [authorInput, reviewerInput, triggerInput, roundsInput, enabledInput]) {
  input.addEventListener('change', renderForm)
}
promptInput.addEventListener('input', () => {
  if (draftRole === 'reviewer') byId('prompt-preview').textContent = reviewPrompt(draftRole, selectedReview(), true)
})
all('[data-open-composer]').forEach((button) => button.addEventListener('click', () => composer.showModal()))
all('[data-close-composer]').forEach((button) => button.addEventListener('click', () => composer.close()))
all('[data-open-session]').forEach((button) => button.addEventListener('click', () => showSession(button.dataset.openSession)))
all('[data-prompt-role]').forEach((button) => button.addEventListener('click', () => {
  draftRole = button.dataset.promptRole
  all('[data-prompt-role]').forEach((control) => control.setAttribute('aria-pressed', String(control === button)))
  renderForm()
}))
byId('task-form').addEventListener('submit', createTask)
byId('next-step').addEventListener('click', advanceReview)
byId('session-back').addEventListener('click', () => {
  showProject()
  document.querySelector('#project-view [data-open-composer]').focus({ preventScroll: true })
})
byId('open-peer').addEventListener('click', () => showSession(currentRole === 'author' ? 'reviewer' : 'author'))
document.querySelector('.runtime-prompts summary span').textContent = t.currentPrompt
renderForm()
composer.showModal()
