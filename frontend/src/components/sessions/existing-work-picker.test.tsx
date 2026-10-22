// @vitest-environment jsdom
// 「已有」不只有 worktree：还没开工作区的本地分支也能直接开工。
//
// 三件事得钉住：计数把两组都算上（只数 worktree 的话，一个没有 worktree 的仓库那枚钮永远是灰的）；
// 已经被检出的分支不能当候选（git 不许一条分支同时检出两次）；选了分支去开干，发的是
// existing=true 的建 worktree 请求，简报也得告诉 agent「分支是既有的，别改名」。
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { App as AntApp } from 'antd'
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { TaskComposer } from './TaskComposer'
import { I18nProvider } from '../../i18n'

const DAY = 86400
const now = Math.floor(Date.now() / 1000)

function jsonResponse(body: unknown) {
  return new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } })
}

class ResizeObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
}

const WORKTREES = [
  { path: '/repo', branch: 'main', isMain: true, prunable: false, sessions: [], dirty: 0, untracked: 0 },
  { path: '/repo/.worktrees/a', branch: 'feat/a', isMain: false, prunable: false, sessions: [], dirty: 0, untracked: 0 },
]
const BRANCHES = {
  default: 'main',
  branches: [
    { name: 'main', at: now - DAY, worktree: '/repo' },
    { name: 'feat/a', at: now - 2 * DAY, worktree: '/repo/.worktrees/a' },
    { name: 'feat/old', at: now - 3 * DAY },
  ],
  remotes: [],
}

describe('开任务 · 「已有」选择器', () => {
  let fetchMock: ReturnType<typeof vi.fn>

  beforeEach(() => {
    localStorage.clear()
    localStorage.setItem('ttmux-locale', 'zh-CN')
    vi.stubGlobal('ResizeObserver', ResizeObserverStub)
    vi.stubGlobal('matchMedia', vi.fn().mockReturnValue({
      matches: false, addEventListener: vi.fn(), removeEventListener: vi.fn(),
      addListener: vi.fn(), removeListener: vi.fn(),
    }))
    fetchMock = vi.fn(async (url: string) => {
      const u = String(url)
      if (u.includes('/git/is-repo')) return jsonResponse({ data: { repo: true, hasCommits: true } })
      if (u.includes('/git/worktrees')) return jsonResponse({ data: WORKTREES })
      if (u.includes('/git/branches')) return jsonResponse({ data: BRANCHES })
      if (u.includes('/worktree-sessions')) {
        return jsonResponse({ name: 'sess-1', data: { session: 'sess-1', path: '/repo/.worktrees/sess-1', branch: 'feat/old', base: 'main' } })
      }
      return jsonResponse({ data: {} })
    })
    vi.stubGlobal('fetch', fetchMock)
  })
  afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals() })

  const body = (match: string) => fetchMock.mock.calls
    .filter(([url]) => String(url).includes(match))
    .map(([, init]) => JSON.parse(String((init as RequestInit).body)))

  const renderComposer = () => render(
    <I18nProvider><AntApp>
      <TaskComposer dir="/repo" isGit openTerm={() => {}} />
    </AntApp></I18nProvider>,
  )

  const openPicker = async () => {
    // 「已有 (2)」= 1 个 worktree + 1 条还没有工作区的分支
    const existing = await screen.findByText('已有 (2)')
    fireEvent.click(existing)
    fireEvent.click(await screen.findByLabelText('选一个工作区，或一条分支'))
  }
  /** 单子本体：pill 上也写着选中项的名字，断言得盯着面板问 */
  const list = () => within(document.querySelector('.tt-picklist') as HTMLElement)

  it('分支和 worktree 分两组列出，被检出的分支点不动', async () => {
    renderComposer()
    await openPicker()

    expect(await screen.findByText('分支')).toBeTruthy()
    expect(screen.getByText('工作区')).toBeTruthy()
    // feat/a 有工作区 → 只出现在上面那组，不在分支组里重复列
    expect(list().getAllByText('feat/a')).toHaveLength(1)
    // main 被主仓库检出：留着但禁用，免得搜不到让人以为漏了
    const mainRow = list().getByText('main').closest('button') as HTMLButtonElement
    expect(mainRow.disabled).toBe(true)
    expect(list().getByText('主仓库检出中')).toBeTruthy()
  })

  it('选一条已有分支去开干：请求带 existing=true，简报说清分支是既有的', async () => {
    const { container } = renderComposer()
    const box = container.querySelector('textarea') as HTMLTextAreaElement
    fireEvent.change(box, { target: { value: '接着把 P2P 那条分支收尾' } })
    await openPicker()

    fireEvent.click(list().getByText('feat/old'))
    // pill 上写明代价：开干会为它新开一个工作区
    expect(await screen.findByText('建工作区')).toBeTruthy()

    fireEvent.click(screen.getByRole('button', { name: /开\s*干/ }))
    await waitFor(() => expect(body('/worktree-sessions')).toHaveLength(1))
    expect(body('/worktree-sessions')[0]).toMatchObject({ dir: '/repo', branch: 'feat/old', existing: true })
    await waitFor(() => expect(body('/tasks/_/send')).toHaveLength(1))
    expect(body('/tasks/_/send')[0].activity).toBe('task')
    const msg = body('/tasks/_/send')[0].msg as string
    expect(msg).toContain('/repo/.worktrees/sess-1')
    expect(msg).toContain('feat/old')
    expect(msg).toContain('别改名')
  })

  it('选已有 worktree 仍然只开会话，不建 worktree', async () => {
    const { container } = renderComposer()
    const box = container.querySelector('textarea') as HTMLTextAreaElement
    fireEvent.change(box, { target: { value: '去 feat/a 里接着干' } })
    await openPicker()

    fireEvent.click(list().getByText('feat/a'))
    fireEvent.click(screen.getByRole('button', { name: /开\s*干/ }))
    await waitFor(() => expect(body('/sessions')).toHaveLength(1))
    expect(body('/sessions')[0]).toMatchObject({ dir: '/repo/.worktrees/a' })
    expect(body('/worktree-sessions')).toHaveLength(0)
  })
})
