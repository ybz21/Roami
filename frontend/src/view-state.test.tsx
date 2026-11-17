// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { WorkspaceStateStore } from './workspace-state'
import { ViewStateProvider, WorkspaceStateProvider, useViewRef, useViewState } from './view-state'
import ViewBoundary from './app/ViewBoundary'
import { definePage } from './app/page-definition'

afterEach(cleanup)
it('shares one source of truth, synchronously saves batched updates, and subscribes by key', () => {
  const store = new WorkspaceStateStore(), scope = store.scope('node', 'one', 'page', 'future')
  const renders = { other: vi.fn() }
  function Counter({ id }: { id: string }) {
    const [count, setCount] = useViewState('count', 0)
    return <button onClick={() => setCount(value => value + 1)}>{id}:{count}</button>
  }
  function Other() { renders.other(); const [value] = useViewState('other', 'unchanged'); return <span>{value}</span> }
  const rendered = render(<WorkspaceStateProvider store={store}><ViewStateProvider scope={scope}><Counter id="one" /><Counter id="two" /><Other /></ViewStateProvider></WorkspaceStateProvider>)
  fireEvent.click(screen.getByText('one:0')); expect(screen.getByText('two:1')).toBeTruthy()
  expect(renders.other).toHaveBeenCalledOnce()
  act(() => { fireEvent.click(screen.getByText('one:1')); fireEvent.click(screen.getByText('two:1')) })
  expect(scope.get('count')).toBe(3)
  rendered.unmount(); expect(store.stats().subscriptions).toBe(0)
})
it('restores an unfamiliar page through the default boundary without changing a page-name list', () => {
  const store = new WorkspaceStateStore(), scope = store.scope('node', 'one', 'page', 'future')
  function Future() {
    const [draft, setDraft] = useViewState('draft', '')
    const edited = useViewRef('edited', false)
    return <input aria-label="future draft" value={draft} onChange={event => { edited.current = true; setDraft(event.target.value) }} />
  }
  const definition = definePage(<Future />)
  const view = (active: boolean) => <WorkspaceStateProvider store={store}><ViewBoundary page="future" scope={scope} active={active} lifetime={definition.lifetime} mobile={false} hasDock={false}>{definition.content}</ViewBoundary></WorkspaceStateProvider>
  const rendered = render(view(true)), input = screen.getByRole('textbox')
  fireEvent.change(input, { target: { value: 'new component state' } })
  rendered.rerender(view(false)); expect(input.isConnected).toBe(false)
  expect(scope.get('edited')).toBe(true)
  rendered.rerender(view(true)); expect((screen.getByRole('textbox') as HTMLInputElement).value).toBe('new component state')
})
it('switches scopes immediately and preserves explicit null values', () => {
  const store = new WorkspaceStateStore(), one = store.scope('one'), two = store.scope('two')
  function Page() { const [value, setValue] = useViewState<string | null>('value', 'default'); return <button onClick={() => setValue(null)}>{value === null ? 'cleared' : value}</button> }
  const rendered = render(<ViewStateProvider scope={one}><Page /></ViewStateProvider>)
  fireEvent.click(screen.getByRole('button')); expect(one.get('value')).toBeNull()
  rendered.rerender(<ViewStateProvider scope={two}><Page /></ViewStateProvider>); expect(screen.getByText('default')).toBeTruthy()
  rendered.rerender(<ViewStateProvider scope={one}><Page /></ViewStateProvider>); expect(screen.getByText('cleared')).toBeTruthy()
})

it('keeps the reload warning after a dirty controller unmounts and clears it after save', () => {
  const store = new WorkspaceStateStore(), scope = store.scope('node', 'one', 'page', 'form')
  const view = (show: boolean) => <WorkspaceStateProvider store={store}>{show && <div>form</div>}</WorkspaceStateProvider>
  const rendered = render(view(true))
  scope.set('draft', 'unsaved', 'draft'); rendered.rerender(view(false))
  const pending = new Event('beforeunload', { cancelable: true }); window.dispatchEvent(pending)
  expect(pending.defaultPrevented).toBe(true)
  scope.delete('draft')
  const saved = new Event('beforeunload', { cancelable: true }); window.dispatchEvent(saved)
  expect(saved.defaultPrevented).toBe(false)
})
