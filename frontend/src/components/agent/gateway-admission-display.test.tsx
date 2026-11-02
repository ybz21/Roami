// @vitest-environment jsdom
import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { I18nProvider } from '../../i18n'
import zhCN from '../../i18n/locales/zh-CN'
import enUS from '../../i18n/locales/en-US'
import AgentMessageView from './AgentMessageView'
import AgentActivity from './AgentActivity'
import { rsiErrorMessage } from './rsi-error-message'
import type { AgentMessage } from './agent-protocol'

vi.mock('../../preferences', () => ({ usePreferences: () => [{}], savePreferences: vi.fn() }))
vi.mock('../../layout', () => ({ useLayout: () => ({ phone: false }) }))
afterEach(() => { cleanup(); localStorage.clear() })

const cases = [
  ['MODEL_PROXY_USAGE_PENDING', '请稍后重试', 'settling'],
  ['MODEL_PROXY_USAGE_UNKNOWN', '未结算', 'unknown'],
  ['MODEL_HTTP_401', '鉴权', 'authentication'],
] as const

it.each(['zh-CN', 'en-US'] as const)('shows each report-generation cause without changing the task result in %s', locale => {
  localStorage.setItem('ttmux-locale', locale)
  const dict: Record<string, string> = locale === 'zh-CN' ? zhCN : enUS
  for (const [code, zh, en] of cases) {
    const item: AgentMessage = { id: 'fallback', branch_id: 'branch', seq: 1, role: 'assistant', status: 'completed', content: { taskStatus: { taskId: 'actual-task', state: 'failed', errorCode: 'SESSION_NOT_IDLE', reportError: code } } }
    const view = render(<I18nProvider><AgentMessageView item={item} node={null} focused={false} remember={vi.fn()} readOnly /></I18nProvider>)
    const status = screen.getByRole('status')
    expect(status.querySelector('small')?.textContent).toContain(locale === 'zh-CN' ? zh : en)
    expect(status.querySelector('strong')?.textContent).toContain(dict['agent.state.failed'])
    expect(status.textContent).not.toContain(code)
    expect(status.textContent).not.toContain('actual-task')
    view.unmount()
  }
})

it.each(['zh-CN', 'en-US'] as const)('retains a completed task when only its report was blocked in %s', locale => {
  localStorage.setItem('ttmux-locale', locale)
  const item: AgentMessage = { id: 'fallback', branch_id: 'branch', seq: 1, role: 'assistant', status: 'completed', content: { taskStatus: { taskId: 'actual-task', state: 'succeeded', reportError: 'MODEL_PROXY_USAGE_PENDING' } } }
  render(<I18nProvider><AgentMessageView item={item} node={null} focused={false} remember={vi.fn()} readOnly /></I18nProvider>)
  const status = screen.getByRole('status')
  expect(status.querySelector('strong')?.textContent).toContain(locale === 'zh-CN' ? '已完成' : 'Completed')
  expect(status.querySelector('small')?.textContent).toContain(locale === 'zh-CN' ? '请稍后重试' : 'settling')
})

it.each(['zh-CN', 'en-US'] as const)('shows a settling hint in activity and RSI without exposing an enum in %s', locale => {
  localStorage.setItem('ttmux-locale', locale)
  const dict: Record<string, string> = locale === 'zh-CN' ? zhCN : enUS
  render(<I18nProvider><AgentActivity items={[{ id: 'turn', anchorMessageId: 'message', kind: 'turn', name: 'main', state: 'failed', errorCode: 'MODEL_PROXY_USAGE_PENDING', startedMs: 1, updatedMs: 2 }]} onSession={vi.fn()} /></I18nProvider>)
  expect(screen.getByRole('status').textContent).toContain(locale === 'zh-CN' ? '请稍后重试' : 'settling')
  const text = rsiErrorMessage('MODEL_PROXY_USAGE_PENDING', key => dict[key] || key)
  expect(text).toContain(locale === 'zh-CN' ? '请稍后重试' : 'settling')
  expect(text).not.toContain('MODEL_PROXY_USAGE_PENDING')
})

it.each(['zh-CN', 'en-US'] as const)('keeps the existing fallback when an older record has no report error in %s', locale => {
  localStorage.setItem('ttmux-locale', locale)
  const item: AgentMessage = { id: 'old', branch_id: 'branch', seq: 1, role: 'assistant', status: 'completed', content: { taskStatus: { taskId: 'old-task', state: 'failed' } } }
  render(<I18nProvider><AgentMessageView item={item} node={null} focused={false} remember={vi.fn()} readOnly /></I18nProvider>)
  expect(screen.getByRole('status').querySelector('small')?.textContent).toBe((locale === 'zh-CN' ? zhCN : enUS)['agent.activity.reportUnavailable'])
})
