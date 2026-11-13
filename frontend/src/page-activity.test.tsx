// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { useState } from 'react'
import { afterEach, expect, it, vi } from 'vitest'
import { App as AntApp } from 'antd'
import ViewBoundary from './app/ViewBoundary'
import { useViewState, useViewRef, useViewRetention } from './view-state'
import { usePageEffect } from './page-activity'

afterEach(() => { cleanup(); vi.useRealTimers(); vi.restoreAllMocks() })

it('preserves page input and scroll while suspending and resuming recurring work', () => {
  vi.useFakeTimers()
  const start = vi.fn(), stop = vi.fn(), tick = vi.fn()
  function Page() {
    const [draft, setDraft] = useState('')
    usePageEffect(() => { start(); const timer = setInterval(tick, 1000); return () => { clearInterval(timer); stop() } }, [])
    return <input aria-label="draft" value={draft} onChange={event => setDraft(event.target.value)} />
  }
  const view = (active: boolean) => <ViewBoundary page="settings" lifetime="retain" active={active} mobile={false} hasDock={false}><Page /></ViewBoundary>
  const rendered = render(view(true))
  const input = screen.getByRole('textbox') as HTMLInputElement
  const pane = rendered.container.querySelector<HTMLElement>('[data-page]')!
  fireEvent.change(input, { target: { value: 'keep this' } })
  pane.scrollTop = 120
  act(() => vi.advanceTimersByTime(2000))
  expect(tick).toHaveBeenCalledTimes(2)
  rendered.rerender(view(false))
  expect(stop).toHaveBeenCalledTimes(1)
  act(() => vi.advanceTimersByTime(5000))
  expect(tick).toHaveBeenCalledTimes(2)
  expect(screen.queryByRole('textbox')).toBeNull()
  rendered.rerender(view(true))
  expect(screen.getByRole('textbox')).toBe(input)
  expect(input.value).toBe('keep this')
  expect(pane.scrollTop).toBe(120)
  expect(start).toHaveBeenCalledTimes(2)
  act(() => vi.advanceTimersByTime(1000))
  expect(tick).toHaveBeenCalledTimes(3)
  rendered.unmount()
  expect(stop).toHaveBeenCalledTimes(2)
})

it('pauses page work while the browser document is hidden', () => {
  let hidden = false
  vi.spyOn(document, 'hidden', 'get').mockImplementation(() => hidden)
  const start = vi.fn(), stop = vi.fn()
  function Page() { usePageEffect(() => { start(); return stop }, []); return null }
  render(<ViewBoundary page="browser" active mobile={false} hasDock={false}><Page /></ViewBoundary>)
  expect(start).toHaveBeenCalledTimes(1)
  hidden = true; fireEvent(document, new Event('visibilitychange'))
  expect(stop).toHaveBeenCalledTimes(1)
  hidden = false; fireEvent(document, new Event('visibilitychange'))
  expect(start).toHaveBeenCalledTimes(2)
})

it('hides page-owned modal portals with the page and restores the same dialog', async () => {
  function Page() {
    const { modal } = AntApp.useApp()
    return <button onClick={() => modal.confirm({ title: 'Confirm draft' })}>open</button>
  }
  const view = (active: boolean) => <ViewBoundary page="settings" lifetime="retain" active={active} mobile={false} hasDock={false}><Page /></ViewBoundary>
  const rendered = render(view(true))
  fireEvent.click(screen.getByRole('button', { name: 'open' }))
  const dialog = await screen.findByRole('dialog')
  rendered.rerender(view(false))
  expect(screen.queryByRole('dialog')).toBeNull()
  expect(document.body.contains(dialog)).toBe(true)
  rendered.rerender(view(true))
  expect(screen.getByRole('dialog')).toBe(dialog)
})

it('unloads heavy page DOM, restores lightweight state and scroll, and waits for mutations', async () => {
  let release!: () => void
  function Page() {
    const [draft, setDraft] = useViewState('draft', '')
    const edited = useViewRef('edited', false)
    const retain = useViewRetention()
    return <div data-testid="list"><input aria-label="draft" value={draft} onChange={event => { edited.current = true; setDraft(event.target.value) }} />
      <button onClick={() => { release = retain() }}>save</button><span>{String(edited.current)}</span></div>
  }
  const view = (active: boolean) => <ViewBoundary page="browser" active={active} mobile={false} hasDock={false}><Page /></ViewBoundary>
  const rendered = render(view(true))
  const list = screen.getByTestId('list')
  Object.defineProperty(list, 'scrollHeight', { value: 1000 })
  list.scrollTop = 200; fireEvent.scroll(list)
  fireEvent.change(screen.getByRole('textbox'), { target: { value: 'keep' } })
  rendered.rerender(view(false))
  expect(list.isConnected).toBe(false)
  rendered.rerender(view(true))
  const restored = screen.getByTestId('list')
  Object.defineProperty(restored, 'scrollHeight', { value: 1000 })
  await act(async () => { restored.appendChild(document.createElement('i')) })
  expect(restored.scrollTop).toBe(200)
  expect((screen.getByRole('textbox') as HTMLInputElement).value).toBe('keep')
  expect(screen.getByText('true')).toBeTruthy()
  fireEvent.click(screen.getByRole('button', { name: 'save' }))
  rendered.rerender(view(false))
  expect(restored.isConnected).toBe(true)
  act(() => release())
  expect(restored.isConnected).toBe(false)
})
