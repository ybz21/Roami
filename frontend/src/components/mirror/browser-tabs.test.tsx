// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { I18nProvider } from '../../i18n'
import { useState } from 'react'
import { TabSheet, TabStrip } from './browser-tabs'

afterEach(cleanup)

describe('mobile browser tab actions', () => {
  it('pinning from a tab menu leaves the sheet open and does not select the tab', async () => {
    const onSelect = vi.fn()
    const onPin = vi.fn()
    const onClose = vi.fn()
    render(<I18nProvider><TabSheet open tabs={[{ id: 'a', title: 'A', url: 'https://example.com' }]}
      active="a" pinned={new Set()} onClose={onClose} onSelect={onSelect} onCloseTab={vi.fn()}
      onCloseMany={vi.fn()} onPin={onPin} onAdd={vi.fn()} /></I18nProvider>)
    fireEvent.click(screen.getByRole('button', { name: '更多' }))
    fireEvent.click(await screen.findByText('固定标签'))
    expect(onPin).toHaveBeenCalledWith('a')
    expect(onSelect).not.toHaveBeenCalled()
    expect(onClose).not.toHaveBeenCalled()
    expect(screen.getByRole('dialog')).toBeTruthy()
  })
})

it('separates human and Agent pages and exposes source changes and sleeping state', async () => {
  const onOrigin = vi.fn(), onSelect = vi.fn()
  render(<I18nProvider><TabSheet open tabs={[
    { id: 'human', title: 'My page', url: 'https://human.test', origin: 'human' },
    { id: 'agent', title: 'Research', url: 'https://agent.test', origin: 'agent', sleeping: true },
  ]} active="human" pinned={new Set()} onClose={vi.fn()} onSelect={onSelect} onCloseTab={vi.fn()}
    onCloseMany={vi.fn()} onPin={vi.fn()} onOrigin={onOrigin} onAdd={vi.fn()} /></I18nProvider>)
  expect(screen.getByText('Research')).toBeTruthy()
  fireEvent.click(screen.getByText('智能体', { exact: true }))
  expect(onSelect).not.toHaveBeenCalled()
  expect(screen.getByRole('dialog')).toBeTruthy()
  expect(screen.getByText('休眠')).toBeTruthy()
  expect(screen.queryByText('My page')).toBeNull()
  fireEvent.click(screen.getByRole('button', { name: '更多' }))
  fireEvent.click(await screen.findByText('移到人工组'))
  expect(onOrigin).toHaveBeenCalledWith('agent', 'human')
})


it('keeps group navigation at the right end and restores the last page in each group', () => {
  const pages = ['h1', 'h2', 'a1', 'a2'].map(id => ({ id, title: id, url: 'https://' + id + '.test', origin: (id[0] === 'h' ? 'human' : 'agent') as 'human' | 'agent' }))
  const open = vi.fn()
  function View() { const [active, select] = useState('a2'); return <TabStrip tabs={pages} active={active} pinned={new Set()} onSelect={select} onClose={vi.fn()} onCloseMany={vi.fn()} onPin={vi.fn()} onAdd={vi.fn()} onOpenTabs={open} /> }
  const { container } = render(<I18nProvider><View /></I18nProvider>)
  const end = container.querySelector('.mc-tabs-end')!
  expect(within(end as HTMLElement).getByLabelText('页面分组')).toBeTruthy()
  expect(container.querySelector('.mc-tabs-strip .mc-tab-groups')).toBeNull()
  fireEvent.click(screen.getByText('人工 (2)'))
  fireEvent.click(screen.getByRole('button', { name: 'h2' }))
  fireEvent.click(screen.getByText('智能体 (2)'))
  expect(screen.getByRole('button', { name: 'a2' }).closest('.mc-tab')?.classList.contains('is-on')).toBe(true)
  fireEvent.click(screen.getByText('人工 (2)'))
  expect(screen.getByRole('button', { name: 'h2' }).closest('.mc-tab')?.classList.contains('is-on')).toBe(true)
  fireEvent.click(screen.getByRole('button', { name: '全部页面' }))
  expect(open).toHaveBeenCalledOnce()
})

it('shows both groups in the desktop directory and searches without selecting a page', () => {
  const select = vi.fn(), close = vi.fn()
  render(<I18nProvider><TabSheet compact={false} open tabs={[
    { id: 'h', title: 'My docs', url: 'https://docs.test', origin: 'human' },
    { id: 'a', title: 'Result', url: 'https://research.test', origin: 'agent' },
  ]} active="h" pinned={new Set()} onClose={close} onSelect={select} onCloseTab={vi.fn()} onCloseMany={vi.fn()} onPin={vi.fn()} onAdd={vi.fn()} /></I18nProvider>)
  expect(screen.getByRole('complementary', { name: '全部页面' })).toBeTruthy()
  expect(screen.getByText('My docs')).toBeTruthy(); expect(screen.getByText('Result')).toBeTruthy()
  fireEvent.change(screen.getByRole('textbox', { name: '搜索标题或网址' }), { target: { value: 'RESEARCH.TEST' } })
  expect(screen.queryByText('My docs')).toBeNull(); expect(screen.getByText('Result')).toBeTruthy()
  expect(select).not.toHaveBeenCalled()
  fireEvent.keyDown(screen.getByRole('textbox'), { key: 'Escape' })
  expect(close).toHaveBeenCalledOnce()
})

it('limits directory bulk-close actions to the displayed origin group', async () => {
  const close = vi.fn()
  render(<I18nProvider><TabSheet open tabs={[
    { id: 'h', title: 'Human', url: 'https://human.test', origin: 'human' },
    { id: 'a1', title: 'Agent 1', url: 'https://one.test', origin: 'agent' },
    { id: 'a2', title: 'Agent 2', url: 'https://two.test', origin: 'agent' },
  ]} active="h" pinned={new Set()} onClose={vi.fn()} onSelect={vi.fn()} onCloseTab={vi.fn()} onCloseMany={close} onPin={vi.fn()} onAdd={vi.fn()} /></I18nProvider>)
  const row = screen.getByRole('button', { name: 'Agent 1' }).closest('.mc-tabcard')!
  fireEvent.click(within(row as HTMLElement).getByRole('button', { name: '更多' }))
  fireEvent.click(await screen.findByText('关闭其他标签'))
  expect(close).toHaveBeenCalledWith(['a2'])
})


it('keeps an empty chosen group stable as background pages arrive', () => {
  const select = vi.fn(), pause = vi.fn()
  const props = { active: 'a1', pinned: new Set<string>(), onSelect: select, onClose: vi.fn(), onCloseMany: vi.fn(), onPin: vi.fn(), onAdd: vi.fn(), onOpenTabs: vi.fn(), onGroupChange: pause }
  const first = { id: 'a1', title: 'First', url: 'https://first.test', origin: 'agent' as const }
  const { rerender } = render(<I18nProvider><TabStrip {...props} tabs={[first]} /></I18nProvider>)
  fireEvent.click(screen.getByText('人工 (0)'))
  expect(pause).toHaveBeenCalledOnce(); expect(select).not.toHaveBeenCalled()
  expect(screen.getByText('暂无页面')).toBeTruthy()
  rerender(<I18nProvider><TabStrip {...props} tabs={[first, { ...first, id: 'a2', title: 'Second' }]} /></I18nProvider>)
  expect(screen.getByText('暂无页面')).toBeTruthy(); expect(screen.queryByRole('button', { name: 'Second' })).toBeNull()
})
