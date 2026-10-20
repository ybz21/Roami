// @vitest-environment jsdom
import { useRef } from 'react'
import { act, cleanup, fireEvent, render, renderHook, screen } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { useAgentHistory } from './useAgentHistory'
import type { AgentTimelineGroup } from './agent-timeline'

const entries = (count: number): AgentTimelineGroup[] => Array.from({ length: count }, (_, index) => ({ id: 'm' + index, message: { id: 'm' + index, role: 'assistant', branch_id: 'branch', status: 'completed', seq: index, content: { text: 'History ' + index } } }))
afterEach(() => { cleanup(); vi.restoreAllMocks() })

it('starts with recent messages, expands upward, and keeps the reading boundary when new messages arrive', () => {
  const root = { current: document.createElement('div') }
  const hook = renderHook(({ items }) => useAgentHistory('one', items, '', root), { initialProps: { items: entries(80) } })
  expect(hook.result.current.entries).toHaveLength(24)
  expect(hook.result.current.entries[0].id).toBe('m56')
  act(() => hook.result.current.expand())
  expect(hook.result.current.entries[0].id).toBe('m32')
  hook.rerender({ items: entries(81) })
  expect(hook.result.current.entries[0].id).toBe('m32')
  expect(hook.result.current.entries[hook.result.current.entries.length - 1]?.id).toBe('m80')
  act(() => hook.result.current.expand())
  act(() => hook.result.current.expand())
  expect(hook.result.current.entries).toHaveLength(81)
})

it('includes an old notification target immediately and resets the window for another conversation', () => {
  const root = { current: null }, items = entries(80)
  const hook = renderHook(({ scope, focus }) => useAgentHistory(scope, items, focus, root), { initialProps: { scope: 'one', focus: 'm3' } })
  expect(hook.result.current.entries.some(entry => entry.id === 'm3')).toBe(true)
  hook.rerender({ scope: 'two', focus: '' })
  expect(hook.result.current.entries).toHaveLength(24)
  expect(hook.result.current.entries[0].id).toBe('m56')
})

it('preserves the existing message position when older history is prepended', () => {
  vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockImplementation(function (this: HTMLElement) {
    const index = this.parentElement ? Array.from(this.parentElement.children).indexOf(this) : 0
    return { top: index * 100 + 10 } as DOMRect
  })
  const items = entries(80)
  function History() {
    const root = useRef<HTMLDivElement | null>(null)
    const history = useAgentHistory('one', items, '', root)
    return <><button onClick={history.expand}>Earlier</button><div data-testid="pane" ref={root}><div className="agent-thread">{history.entries.map(entry => <article key={entry.id} data-key={entry.id}>{entry.id}</article>)}</div></div></>
  }
  render(<History />)
  const pane = screen.getByTestId('pane')
  pane.scrollTop = 10
  fireEvent.click(screen.getByText('Earlier'))
  expect(pane.scrollTop).toBe(2410)
  expect(pane.querySelector('.agent-thread')?.children).toHaveLength(48)
})
