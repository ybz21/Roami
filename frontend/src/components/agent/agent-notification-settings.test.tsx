// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import AgentNotificationSettings from './AgentNotificationSettings'
import { api } from '../../api'

vi.mock('../../api', () => ({ api: vi.fn() }))
vi.mock('../../i18n', () => ({ useI18n: () => ({ t: (key: string) => key }) }))
vi.mock('antd', () => ({
  Button: ({ children, loading: _loading, ...props }: any) => <button {...props}>{children}</button>,
  Input: (props: any) => <input {...props} />,
  InputNumber: ({ onChange, precision: _precision, ...props }: any) => <input type="number" {...props} onChange={(event) => onChange(Number(event.target.value))} />,
  Switch: ({ checked, onChange, ...props }: any) => <button role="switch" aria-checked={checked} {...props} onClick={() => onChange(!checked)} />,
  Spin: () => <span role="progressbar" />,
}))
afterEach(() => { cleanup(); vi.resetAllMocks() })
const stored = { timezone: 'Asia/Shanghai', enabled: { task_result: true, decision: true, reminder: true, suggestion: false }, quietHours: { start: '23:00', end: '07:00' }, hidePreview: false, attentionBypassesQuiet: false, maxSuggestionsPerHour: 2 }

it('waits for stored preferences before exposing changes and saves the edited complete record', async () => {
  let resolve!: (value: any) => void
  const pending = new Promise((done) => { resolve = done })
  vi.mocked(api).mockImplementation(async (method) => method === 'GET' ? pending : { data: {} })
  render(<AgentNotificationSettings />)
  expect(screen.queryByRole('button', { name: 'agent.save' })).toBeNull()
  await act(async () => { resolve({ data: stored }); await pending })
  const preview = await screen.findByRole('switch', { name: 'agent.notification.hidePreview' })
  expect(preview.getAttribute('aria-checked')).toBe('false')
  expect((screen.getByLabelText('agent.notification.timezone') as HTMLInputElement).value).toBe('Asia/Shanghai')
  fireEvent.click(preview)
  fireEvent.click(screen.getByRole('button', { name: 'agent.save' }))
  await waitFor(() => expect(api).toHaveBeenCalledWith('PUT', '/agent/notification-preferences', { settings: { ...stored, hidePreview: true } }))
  await screen.findByText('agent.notification.settingsSaved')
})

it('does not populate a replacement node form from a late response for the previous node', async () => {
  let finishOld!: (value: any) => void
  const previous = new Promise((done) => { finishOld = done })
  let count = 0, previousSignal: AbortSignal | undefined
  vi.mocked(api).mockImplementation(async (_method, _path, _body, options) => {
    if (++count === 1) { previousSignal = options?.signal; return previous }
    return { data: { ...stored, timezone: 'UTC' } }
  })
  const view = render(<AgentNotificationSettings key="first-node" />)
  view.rerender(<AgentNotificationSettings key="second-node" />)
  await screen.findByLabelText('agent.notification.timezone')
  expect(previousSignal?.aborted).toBe(true)
  await act(async () => { finishOld({ data: stored }); await previous })
  expect((screen.getByLabelText('agent.notification.timezone') as HTMLInputElement).value).toBe('UTC')
})
