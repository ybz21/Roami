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
  ['MODEL_GATEWAY_UNAVAILABLE', '模型服务暂不可用', 'Model service is unavailable'],
  ['MODEL_GATEWAY_KEY_DISABLED', '模型连接已停用', 'disabled'],
  ['MODEL_GATEWAY_UNAUTHORIZED', '鉴权', 'authentication'],
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

it.each(['zh-CN', 'en-US'] as const)('preserves readiness and authentication recovery hints in RSI and activity in %s', locale => {
  localStorage.setItem('ttmux-locale', locale)
  const dict: Record<string, string> = locale === 'zh-CN' ? zhCN : enUS
  for (const [code, zh, en] of cases) {
    const view = render(<I18nProvider><AgentActivity items={[{ id: 'turn', anchorMessageId: 'message', kind: 'turn', name: 'main', state: 'failed', errorCode: code, startedMs: 1, updatedMs: 2 }]} onSession={vi.fn()} /></I18nProvider>)
    const hint = locale === 'zh-CN' ? zh : en
    expect(screen.getByRole('status').textContent).toContain(hint)
    expect(rsiErrorMessage(code, key => dict[key] || key)).toContain(hint)
    expect(dict['agent.pipeline.signal.' + code]).toBeTruthy()
    expect(screen.getByRole('status').textContent).not.toContain(code)
    view.unmount()
  }
})
