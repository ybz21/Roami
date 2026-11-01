// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { App as AntApp } from 'antd'
import { act, cleanup, fireEvent, render, renderHook, screen, waitFor, within } from '@testing-library/react'
import { TaskComposer } from './TaskComposer'
import { useRepositorySetup } from './RepositorySetup'
import { I18nProvider } from '../../i18n'

const layout = vi.hoisted(() => ({ phone: false }))
vi.mock('../../layout', () => ({ useLayout: () => layout }))

const json = (data: unknown, status = 200) => new Response(JSON.stringify(data), { status, headers: { 'Content-Type': 'application/json' } })
class ResizeObserverStub { observe() {} unobserve() {} disconnect() {} }

describe('task repository setup', () => {
 let state: { repo: boolean; hasCommits?: boolean } = { repo: false, hasCommits: false }
 let failProbe = false, failInit = false
 let fetchMock: ReturnType<typeof vi.fn>
 beforeEach(() => {
  localStorage.clear()
  localStorage.setItem('ttmux-locale', 'zh-CN')
  vi.stubGlobal('ResizeObserver', ResizeObserverStub)
  vi.stubGlobal('matchMedia', vi.fn().mockReturnValue({ matches: false, addEventListener: vi.fn(), removeEventListener: vi.fn(), addListener: vi.fn(), removeListener: vi.fn() }))
  layout.phone = false
  state = { repo: false, hasCommits: false }; failProbe = false; failInit = false
  fetchMock = vi.fn(async (url: string) => {
   if (url.includes('/git/is-repo')) return failProbe ? json({ error: { code: 'GIT_PROBE_FAILED' } }, 500) : json({ data: state })
   if (url.includes('/git/initialize')) {
    if (failInit) return json({ error: { code: 'GIT_INIT_FAILED' } }, 409)
    state = { repo: true, hasCommits: true }
    return json({ data: state })
   }
   if (url.includes('/git/branches')) return json({ data: { default: 'main', branches: [{ name: 'main', worktree: '/project' }], remotes: [] } })
   if (url.includes('/git/worktrees')) return json({ data: [{ path: '/project', branch: 'main', isMain: true }] })
   if (url.endsWith('/worktree-sessions')) return json({ name: 'task', data: { path: '/project/.worktrees/task', branch: 'task', base: 'main' } })
   if (url.endsWith('/sessions')) return json({ name: 'task' })
   return json({ data: {} })
  })
  vi.stubGlobal('fetch', fetchMock)
 })
 afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals() })
 const requests = (suffix: string) => fetchMock.mock.calls.filter(([url]) => String(url).endsWith(suffix))
 const show = () => render(<I18nProvider><AntApp><TaskComposer dir="/project" isGit openTerm={() => {}} /></AntApp></I18nProvider>)
 const prompt = () => screen.getByRole('textbox') as HTMLTextAreaElement
 const start = () => screen.getByRole('button', { name: /开\s*干/ })
 const confirm = () => within(screen.getByRole('dialog')).getByRole('button', { name: '创建首次提交' })


 it('keeps Enter as a newline on phones and submits with the visible button', async () => {
  layout.phone = true
  show()
  await screen.findByText(/项目尚未初始化 Git/)
  fireEvent.change(prompt(), { target: { value: '手机任务草稿' } })
  fireEvent.keyDown(prompt(), { key: 'Enter' })
  expect(requests('/sessions')).toHaveLength(0)
  expect(prompt().value).toBe('手机任务草稿')
  fireEvent.click(start())
  await waitFor(() => expect(requests('/sessions')).toHaveLength(1))
 })

 it('preserves all executor choices when adding the first-task guidance', async () => {
  render(<I18nProvider><AntApp><TaskComposer dir="/project" isGit={false} openTerm={() => {}} draftKey="first-task" initialAgent="codex" /></AntApp></I18nProvider>)
  await screen.findByText(/项目尚未初始化 Git/)
  fireEvent.change(prompt(), { target: { value: '保留首个任务草稿' } })
  expect(screen.getByRole('button', { name: 'Codex' }).getAttribute('aria-pressed')).toBe('true')
  for (const name of ['Claude', 'Codex', 'Pi', 'OpenCode', '不启动']) expect((screen.getByRole('button', { name }) as HTMLButtonElement).disabled).toBe(false)
  fireEvent.click(screen.getByRole('button', { name: 'Claude' }))
  await waitFor(() => expect(screen.getByRole('button', { name: 'Claude' }).getAttribute('aria-pressed')).toBe('true'))
  expect(prompt().value).toBe('保留首个任务草稿')
  expect(requests('/sessions')).toHaveLength(0)
  fireEvent.change(prompt(), { target: { value: '' } })
 })

 it('checks despite a stale Git hint and works directly without Git', async () => {
  show()
  await screen.findByText(/项目尚未初始化 Git/)
  expect(screen.queryByText('新建 worktree')).toBeNull()
  fireEvent.change(prompt(), { target: { value: '保留任务内容' } })
  fireEvent.click(screen.getByRole('button', { name: '不启动' }))
  fireEvent.click(start())
  await waitFor(() => expect(requests('/sessions')).toHaveLength(1))
  expect(requests('/worktree-sessions')).toHaveLength(0)
  expect(JSON.parse(requests('/sessions')[0][1].body)).toMatchObject({ dir: '/project' })
 })

 it('confirms initialization, preserves the draft and creates a worktree', async () => {
  show()
  fireEvent.change(prompt(), { target: { value: '已有项目继续开发' } })
  fireEvent.click(await screen.findByRole('button', { name: '初始化 Git' }))
  expect(requests('/git/initialize')).toHaveLength(0)
  fireEvent.click(screen.getByRole('button', { name: /取\s*消/ }))
  await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
  expect(prompt().value).toBe('已有项目继续开发')
  fireEvent.click(screen.getByRole('button', { name: '初始化 Git' }))
  fireEvent.click(confirm())
  await screen.findByText('新建 worktree')
  expect(prompt().value).toBe('已有项目继续开发')
  fireEvent.click(screen.getByRole('button', { name: '不启动' }))
  fireEvent.click(start())
  await waitFor(() => expect(requests('/worktree-sessions')).toHaveLength(1))
  expect(requests('/sessions')).toHaveLength(0)
 })

 it('repairs an unborn repository and keeps input after failure', async () => {
  state = { repo: true, hasCommits: false }; failInit = true
  show()
  fireEvent.change(prompt(), { target: { value: '任务草稿' } })
  await screen.findByText(/项目还没有提交/)
  fireEvent.click(screen.getByRole('button', { name: '创建首次提交' }))
  fireEvent.click(confirm())
  await screen.findByText('初始化失败，请检查目录权限或 Git 配置后重试。')
  expect(prompt().value).toBe('任务草稿')
  expect(screen.queryByText('新建 worktree')).toBeNull()
  failInit = false
  fireEvent.click(confirm())
  await screen.findByText('新建 worktree')
  expect(prompt().value).toBe('任务草稿')
 })

 it('accepts a non-repository response without commit metadata', async () => {
  state = { repo: false }
  show()
  await screen.findByText(/项目尚未初始化 Git/)
  fireEvent.change(prompt(), { target: { value: '普通目录任务' } })
  fireEvent.click(screen.getByRole('button', { name: '不启动' }))
  fireEvent.click(start())
  await waitFor(() => expect(requests('/sessions')).toHaveLength(1))
  expect(JSON.parse(requests('/sessions')[0][1].body)).toMatchObject({ dir: '/project' })
  expect(requests('/worktree-sessions')).toHaveLength(0)
  expect(requests('/git/initialize')).toHaveLength(0)
 })

 it.each(['button', 'Enter'])('creates in the current directory after a failed check via %s', async (submit) => {
  failProbe = true
  show()
  fireEvent.change(prompt(), { target: { value: '继续普通目录任务' } })
  await screen.findByText('无法检查 Git，将在当前目录开工。')
  expect((start() as HTMLButtonElement).disabled).toBe(false)
  expect(screen.queryByText('新建 worktree')).toBeNull()
  if (submit === 'Enter') fireEvent.keyDown(prompt(), { key: 'Enter' })
  else fireEvent.click(start())
  await waitFor(() => expect(requests('/tasks/_/send')).toHaveLength(1))
  expect(JSON.parse(requests('/sessions')[0][1].body)).toMatchObject({ dir: '/project' })
  const message = JSON.parse(requests('/tasks/_/send')[0][1].body).msg
  expect(message).toContain('继续普通目录任务')
  expect(message).toContain('/project')
  expect(message).not.toContain('git branch -m')
  expect(requests('/worktree-sessions')).toHaveLength(0)
  expect(requests('/git/initialize')).toHaveLength(0)
 })

 it('retries a failed check without losing input and restores worktree creation', async () => {
  failProbe = true
  show()
  fireEvent.change(prompt(), { target: { value: '重试检查' } })
  await screen.findByText('无法检查 Git，将在当前目录开工。')
  failProbe = false
  state = { repo: true, hasCommits: true }
  fireEvent.click(screen.getByRole('button', { name: /重\s*试/ }))
  await screen.findByText('新建 worktree')
  expect(prompt().value).toBe('重试检查')
  fireEvent.click(screen.getByRole('button', { name: '不启动' }))
  fireEvent.click(start())
  await waitFor(() => expect(requests('/worktree-sessions')).toHaveLength(1))
  expect(requests('/sessions')).toHaveLength(0)
 })

 it('ignores a late response from a previously selected directory', async () => {
  let finishFirst!: (response: Response) => void
  fetchMock.mockImplementation((url: string) => url.includes('first')
   ? new Promise<Response>((resolve) => { finishFirst = resolve })
   : Promise.resolve(json({ data: { repo: false, hasCommits: false } })))
  const hook = renderHook(({ dir }) => useRepositorySetup(dir), { initialProps: { dir: '/first' } })
  hook.rerender({ dir: '/second' })
  await waitFor(() => expect(hook.result.current.checking).toBe(false))
  await act(async () => finishFirst(json({ data: { repo: true, hasCommits: true } })))
  expect(hook.result.current.ready).toBe(false)
  expect(hook.result.current.repo).toBe(false)
 })

})
