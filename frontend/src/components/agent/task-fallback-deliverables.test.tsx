// @vitest-environment jsdom
import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { I18nProvider } from '../../i18n'
import zhCN from '../../i18n/locales/zh-CN'
import enUS from '../../i18n/locales/en-US'
import AgentMessageView from './AgentMessageView'
import type { AgentMessage } from './agent-protocol'

vi.mock('../../preferences', () => ({ usePreferences: () => [{}], savePreferences: vi.fn() }))
vi.mock('../../layout', () => ({ useLayout: () => ({ phone: false }) }))
afterEach(() => { cleanup(); localStorage.clear() })

it.each(['zh-CN', 'en-US'].flatMap(locale => ['succeeded', 'failed', 'waiting_user'].map(state => ({ locale, state }))))('keeps the $state result, deliverable and separate summary blocker in $locale', async ({ locale, state }) => {
  localStorage.setItem('ttmux-locale', locale)
  const dict: Record<string, string> = locale === 'zh-CN' ? zhCN : enUS
  const item: AgentMessage = { id: 'fallback', branch_id: 'branch', seq: 1, role: 'assistant', status: 'completed', content: { text: '[report.txt](/api/agent/artifacts/persisted/content)', taskStatus: { taskId: 'internal-task', state, reportError: 'MODEL_PROXY_USAGE_PENDING' } } }
  render(<I18nProvider><AgentMessageView item={item} node={null} focused={false} remember={vi.fn()} readOnly /></I18nProvider>)
  const status = screen.getByRole('status')
  expect(status.querySelector('strong')?.textContent).toContain(dict['agent.state.' + state])
  expect(status.getAttribute('data-state')).toBe(state)
  expect(status.querySelector('small')?.textContent).toContain(dict['agent.proxy.usagePending'])
  expect(status.textContent).not.toMatch(/internal-task|MODEL_PROXY_USAGE_PENDING/)
  const download = await screen.findByRole('link', { name: 'report.txt' })
  expect(download.getAttribute('href')).toBe('/api/agent/artifacts/persisted/content')
})
