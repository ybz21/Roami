// @vitest-environment jsdom
import { App as AntApp } from 'antd'
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { I18nProvider } from '../../i18n'
import { LifecycleOperationView, SessionLifecycleInbox } from './SessionLifecyclePanel'
import { lifecycleAction, type LifecycleOperation } from './session-lifecycle'
import { sendSessionPrompt } from './session-actions'

const state = vi.hoisted(() => ({ operations: [] as any[] }))
vi.mock('../../layout', () => ({ useLayout: () => ({ phone: true }) }))
vi.mock('./native-session-list', () => ({ useNativeSessionList: () => ({ value: [] }) }))
vi.mock('./session-lifecycle', () => ({ lifecycleAction: vi.fn(), useSessionLifecycle: () => ({ value: state.operations, loaded: true }), blockingLifecycle: () => undefined, lifecycleEnded: (op: LifecycleOperation) => ['succeeded', 'cancelled'].includes(op.state) }))
vi.mock('../../preferences', () => { const prefs = { locale: 'en-US' }; return { usePreferences: () => [prefs], savePreferences: vi.fn() } })
vi.mock('./session-actions', () => ({ sendSessionPrompt: vi.fn() }))
const op: LifecycleOperation = { operationId: 'operation', resourceId: 'session', requestKey: 'key', kind: 'create', intent: { name: 'My task', launch: { command: 'codex', agent: 'codex', task: 'Original request', preamble: '', taskHeading: '', setupHeading: '', fileBase: '/api/file', autoReview: false } }, state: 'queued', stage: 'workspace', revision: 7, cancelRequested: false, receipts: {}, acceptedAt: 100, updatedAt: 100 }
const content = (value: LifecycleOperation) => <I18nProvider><AntApp><LifecycleOperationView op={value} /></AntApp></I18nProvider>
beforeEach(() => { state.operations = []; localStorage.clear(); localStorage.setItem('ttmux-locale', 'en-US'); vi.mocked(lifecycleAction).mockReset(); vi.mocked(sendSessionPrompt).mockReset(); vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} }); vi.stubGlobal('matchMedia', () => ({ matches: false, addListener() {}, removeListener() {}, addEventListener() {}, removeEventListener() {} })) })
afterEach(() => { cleanup(); vi.unstubAllGlobals() })

it('saves drafts across navigation and never sends while preparing', async () => {
  const view = render(content(op))
  fireEvent.change(screen.getByRole('textbox'), { target: { value: 'Follow-up draft' } })
  expect(screen.queryByRole('button', { name: 'Send follow-up' })).toBeNull()
  expect(sendSessionPrompt).not.toHaveBeenCalled()
  view.unmount()
  const restored = render(content(op))
  expect((screen.getByRole('textbox') as HTMLTextAreaElement).value).toBe('Follow-up draft')
  restored.rerender(content({ ...op, state: 'succeeded' }))
  fireEvent.click(screen.getByRole('button', { name: 'Send follow-up' }))
  await waitFor(() => expect(sendSessionPrompt).toHaveBeenCalledWith('session', 'Follow-up draft'))
  await waitFor(() => expect((screen.getByRole('textbox') as HTMLTextAreaElement).value).toBe(''))
})

it('retries the original operation revision without reopening the session', async () => {
  const failure = { ...op, kind: 'close' as const, state: 'attention' as const, stage: 'remove', intent: { mode: 'discard' as const }, receipts: { stop: { result: true, durationMs: 2 } }, errorCode: 'LIFECYCLE_STEP_FAILED' }
  render(content(failure))
  expect(screen.getByRole('status').textContent).toContain('Session closed')
  fireEvent.click(screen.getByRole('button', { name: 'Retry this step' }))
  await waitFor(() => expect(lifecycleAction).toHaveBeenCalledWith(failure, 'retry'))
  expect(sendSessionPrompt).not.toHaveBeenCalled()
})

it('offers branch retention rather than claiming a removed workspace can be kept', () => {
  render(content({ ...op, kind: 'close', state: 'attention', intent: { mode: 'discard' }, receipts: { stop: { result: true, durationMs: 2 }, remove: { result: true, durationMs: 2 } } }))
  expect(screen.queryByRole('button', { name: 'Keep workspace' })).toBeNull()
  expect(screen.getByRole('button', { name: 'Keep branch' })).toBeTruthy()
})

it('keeps the original request visible when no agent was selected', () => {
  render(content({ ...op, intent: { task: 'Saved without an agent' } }))
  expect(screen.getByText('Saved without an agent')).toBeTruthy()
})

it('rearms phone Back after returning from an operation to the list', async () => {
  const { handlePop, stackSize, resetStack } = await import('../shell/useBackDismiss')
  resetStack(); state.operations = [op]
  render(<I18nProvider><AntApp><SessionLifecycleInbox onOpen={() => {}} /></AntApp></I18nProvider>)
  fireEvent.click(screen.getByRole('button', { name: /Background work/ }))
  fireEvent.click(screen.getByRole('button', { name: /My task/ }))
  expect(stackSize()).toBe(1)
  await act(async () => { handlePop() })
  expect(screen.getByRole('button', { name: /My task/ })).toBeTruthy()
  expect(stackSize()).toBe(1)
  await act(async () => { handlePop() })
  expect(stackSize()).toBe(0)
  expect(document.querySelector('.tt-mobile-subpage-head')).toBeNull()
})

it('keeps simultaneous pending and inspector drafts synchronized without duplicate field IDs', () => {
 render(<I18nProvider><AntApp><LifecycleOperationView op={op} /><LifecycleOperationView op={op} /></AntApp></I18nProvider>)
 const fields = screen.getAllByRole('textbox') as HTMLTextAreaElement[]
 expect(fields[0].id).not.toBe(fields[1].id)
 fireEvent.change(fields[0], { target: { value: 'Shared draft' } })
 expect(fields[1].value).toBe('Shared draft')
 fireEvent.change(fields[1], { target: { value: 'Updated from inspector' } })
 expect(fields[0].value).toBe('Updated from inspector')
})
