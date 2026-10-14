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
  vi.mocked(api).mockImplementation(async (_method, path) => path.startsWith('/activity/day?') ? { data: { projects: [], dialogues: 2, tasks: 1, commits: 0 } } : { data: { usage: [{ at: Date.now() / 1000, dialogues: 2, tasks: 1 }], commits: [], repositories: 0, failed: 0 } })
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
  it('keeps day summaries below the heatmap without opening a dialog', async () => {
    layout.phone = false; layout.coarse = false
    vi.mocked(api).mockImplementation(async (_method, path) => path.startsWith('/activity/day?')
      ? { data: { projects: [{ repo: '/projects/roami', count: 3 }], dialogues: 2, tasks: 1, commits: 3 } }
      : { data: { usage: [], commits: [{ oid: 'abc1234', at: Date.now() / 1000 }], repositories: 1, failed: 0 } })
    const { container } = render(<I18nProvider><DailyActivity /></I18nProvider>)
    await waitFor(() => expect(container.querySelectorAll('.tt-activity-year button.tt-activity-day')).toHaveLength(365))
    expect(screen.queryByRole('region', { name: '当天足迹' })).toBeNull()
    fireEvent.click(container.querySelector<HTMLButtonElement>(`.tt-activity-year [data-day="${dayKey(new Date())}"]`)!)
    const summary = await screen.findByRole('region', { name: '当天足迹' })
    await waitFor(() => expect(summary.textContent).toContain('roami'))
    expect(summary.textContent).toContain('3 次提交')
    expect(summary.textContent).toContain('对话 2 次 · 下任务 1 次 · 提交 3 次')
    expect(screen.queryByRole('dialog')).toBeNull()
    expect(summary.compareDocumentPosition(container.querySelector('.tt-activity-year')!) & Node.DOCUMENT_POSITION_PRECEDING).toBeTruthy()
    fireEvent.click(container.querySelector<HTMLButtonElement>('.tt-activity-year button.tt-activity-day')!)
    expect(screen.queryByRole('dialog')).toBeNull()
  })
})
