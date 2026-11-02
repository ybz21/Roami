export type MemoryExample = {
  id: string; title: string; body: string; kind: 'preference' | 'decision' | 'fact' | 'summary'
  scope: 'personal' | 'project' | 'conversation' | 'task'; scopeName?: string
  state: 'active' | 'candidate' | 'conflict'; quote: string; conversation: string; updated: string
  current?: string; merged?: boolean; unavailable?: boolean
}

export const examples: MemoryExample[] = [
  { id: 'codex', title: '复杂任务首选 Codex', body: '以后分配复杂任务，首选 Codex。', kind: 'preference', scope: 'personal', state: 'active', quote: '帮我记下，以后分配复杂任务，首选codex', conversation: '任务安排与 OKR 原型', updated: '2026-10-22T20:40:00+08:00', merged: true },
  { id: 'brief', title: '用简洁中文回复', body: '默认用中文回复。先说明结果，再补充必要的依据和下一步；常规进度不要展开执行日志。', kind: 'preference', scope: 'personal', state: 'active', quote: '记住，我希望平时用简洁中文回复，先说结果，过程按需展开。', conversation: '协作习惯', updated: '2026-10-22T18:10:00+08:00' },
  { id: 'phone', title: '手机是正式验收端', body: 'Roami 的界面改动需要在 Android 真机上检查触控、滚动、软键盘和安全区。桌面缩窄视口只能作为补充。', kind: 'decision', scope: 'project', scopeName: 'Roami', state: 'active', quote: '这个项目所有界面都要在手机上验收，不能只测桌面。', conversation: 'Roami 界面验收', updated: '2026-10-22T16:20:00+08:00' },
  { id: 'okr', title: 'OKR 从项目工作台进入', body: '本轮原型的入口为：项目 / 具体项目 / 目标 OKR。创建流程包含 Objective、KR、负责人、指标来源和周期设置。', kind: 'fact', scope: 'conversation', scopeName: '任务安排与 OKR 原型', state: 'active', quote: '这轮先把 OKR 放在具体项目的工作台里，演示从入口到保存确认的完整路径。', conversation: '任务安排与 OKR 原型', updated: '2026-10-22T15:30:00+08:00' },
  { id: 'prototype', title: '这次只交付设计与原型', body: '本次任务只修改设计稿和可点击原型，不修改线上业务。交付时提供可打开的 HTML 和页面清单。', kind: 'decision', scope: 'task', scopeName: '补齐 OKR 设置原型', state: 'active', quote: '这次先做设计和原型，给我能打开看的版本。', conversation: '任务安排与 OKR 原型', updated: '2026-10-21T18:15:00+08:00' },
  { id: 'conflict', title: '复杂任务默认执行器', body: '复杂任务默认交给 Claude Code。', current: '以后分配复杂任务，首选 Codex。', kind: 'preference', scope: 'personal', state: 'conflict', quote: '可以考虑让 Claude Code 处理下一项复杂任务。', conversation: '下一轮任务安排', updated: '2026-10-22T21:00:00+08:00' },
  { id: 'report', title: '周报按目标、进展、风险组织', body: '周报使用目标、进展、风险三个部分。', kind: 'preference', scope: 'conversation', scopeName: '周报整理', state: 'candidate', quote: '这周的报告先列目标，再讲进展，最后列风险。', conversation: '周报整理', updated: '2026-10-22T19:15:00+08:00' },
]

export const activityExamples = [
  { id: 'today-roami', date: '2026-10-22T12:00:00+08:00', project: 'Roami', turns: 12, completed: 3, created: 4, failed: 1 },
  { id: 'today-okr', date: '2026-10-22T12:00:00+08:00', project: 'OKR 工作台', turns: 6, completed: 2, created: 2, failed: 0 },
  { id: 'yesterday-roami', date: '2026-10-21T12:00:00+08:00', project: 'Roami', turns: 9, completed: 2, created: 3, failed: 0 },
]
