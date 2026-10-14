// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { I18nProvider } from '../../i18n'
import { api } from '../../api'
import { resetStack } from '../shell/useBackDismiss'
import DailyActivity from './DailyActivity'
import { dayKey } from './activity-calendar'

vi.mock('../../api', () => ({ api: vi.fn() }))
const layout = vi.hoisted(() => ({ phone: true, coarse: true }))
vi.mock('../../layout', () => ({ useLayout: () => layout }))

beforeEach(() => {
  layout.phone = true; layout.coarse = true
  vi.stubGlobal('matchMedia', vi.fn(() => ({ matches: false, addListener: vi.fn(), removeListener: vi.fn(), addEventListener: vi.fn(), removeEventListener: vi.fn() })))
  localStorage.clear()
  localStorage.setItem('ttmux-locale', 'zh-CN')
  vi.mocked(api).mockResolvedValue({ data: { usage: [{ at: Date.now() / 1000, dialogues: 2, tasks: 1 }], commits: [], repositories: 0, failed: 0 } })
})
afterEach(() => { cleanup(); resetStack(); vi.resetAllMocks(); vi.unstubAllGlobals() })

describe('mobile AI footprints', () => {
  it('keeps daily touch targets out of the preview and opens details on demand', async () => {
    const { container } = render(<I18nProvider><DailyActivity /></I18nProvider>)
    const preview = await screen.findByRole('button', { name: '查看 AI 足迹详情' })
    expect(screen.queryByRole('dialog')).toBeNull()
    expect(container.querySelectorAll('button.tt-activity-day')).toHaveLength(0)
    expect(screen.getByText('对话 2 次 · 下任务 1 次 · 提交 0 次')).toBeTruthy()
    fireEvent.click(preview)
    expect(screen.getByRole('dialog', { name: 'AI 足迹' })).toBeTruthy()
    const picker = screen.getByLabelText('选择日期') as HTMLInputElement
    const yesterday = new Date(); yesterday.setDate(yesterday.getDate() - 1)
    fireEvent.change(picker, { target: { value: dayKey(yesterday) } })
    expect(picker.value).toBe(dayKey(yesterday))
    fireEvent.click(screen.getByRole('button', { name: '后一天' }))
    expect(picker.value).toBe(dayKey(new Date()))
    expect((screen.getByRole('button', { name: '后一天' }) as HTMLButtonElement).disabled).toBe(true)
    fireEvent.keyDown(window, { key: 'Escape' })
    expect(screen.queryByRole('dialog')).toBeNull()
    expect(screen.getByRole('button', { name: '查看 AI 足迹详情' })).toBeTruthy()
  })
  it('refreshes after a submission and preserves the last counts on failure', async () => {
    render(<I18nProvider><DailyActivity /></I18nProvider>)
    await screen.findByRole('button', { name: '查看 AI 足迹详情' })
    vi.mocked(api).mockRejectedValueOnce(new Error('offline'))
    fireEvent(window, new Event('roam:footprints-updated'))
    await waitFor(() => expect(screen.getByRole('alert')).toBeTruthy())
    expect(screen.getByText('对话 2 次 · 下任务 1 次 · 提交 0 次')).toBeTruthy()
  })
})

describe('desktop AI footprints', () => {
  it('shows the full year on desktop and opens additional details in a dialog', async () => {
    layout.phone = false; layout.coarse = false
    render(<I18nProvider><DailyActivity /></I18nProvider>)
    const preview = await screen.findByRole('button', { name: '查看 AI 足迹详情' })
    expect(document.querySelectorAll('.tt-activity-year button.tt-activity-day')).toHaveLength(365)
    expect(screen.queryByRole('dialog')).toBeNull()
    fireEvent.click(preview)
    expect(await screen.findByRole('dialog')).toBeTruthy()
    expect(screen.getByRole('dialog').querySelectorAll('button.tt-activity-day')).toHaveLength(365)
    const yesterday = new Date(); yesterday.setDate(yesterday.getDate() - 1)
    fireEvent.click(screen.getByRole('dialog').querySelector<HTMLButtonElement>(`[data-day="${dayKey(yesterday)}"]`)!)
    expect((screen.getByLabelText('选择日期') as HTMLInputElement).value).toBe(dayKey(yesterday))
    fireEvent.click(screen.getByRole('button', { name: 'Close' }))
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
  })
})

it('opens the clicked day and shows its project and commit description', async () => {
  layout.phone = false; layout.coarse = false
  vi.mocked(api).mockImplementation(async (_method, path) => path.startsWith('/activity/day?')
    ? { data: { commits: [{ oid: 'abc1234', at: Date.now() / 1000, repo: '/projects/roami', subject: 'Fix activity density' }], usage: [] } }
    : { data: { usage: [], commits: [{ oid: 'abc1234', at: Date.now() / 1000 }], repositories: 1, failed: 0 } })
  render(<I18nProvider><DailyActivity /></I18nProvider>)
  await screen.findByRole('button', { name: '查看 AI 足迹详情' })
  fireEvent.click(document.querySelector<HTMLButtonElement>(`.tt-activity-year [data-day="${dayKey(new Date())}"]`)!)
  const dialog = await screen.findByRole('dialog', { name: 'AI 足迹' })
  await waitFor(() => expect(dialog.textContent).toContain('Fix activity density'))
  expect(dialog.textContent).toContain('roami · abc1234')
  expect(vi.mocked(api).mock.calls.some(([, path]) => path.startsWith('/activity/day?from='))).toBe(true)
})
