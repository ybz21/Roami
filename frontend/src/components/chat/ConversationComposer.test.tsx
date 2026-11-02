// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import ConversationComposer from './ConversationComposer'

const layout = vi.hoisted(() => ({ phone: false, landscape: false }))
vi.mock('../../layout', () => ({ useLayout: () => layout }))
vi.mock('antd', () => ({ Input: { TextArea: ({ autoSize: _auto, variant: _variant, ...props }: any) => <textarea {...props} /> }, Spin: () => <span role="progressbar" /> }))
afterEach(() => { cleanup(); layout.phone = false })
const show = (extra: any = {}) => {
  const send = vi.fn(), stop = vi.fn(), onKeyDown = vi.fn()
  const page = render(<ConversationComposer value="Keep this draft" onChange={vi.fn()} label="Message" placeholder="Message" send={{ label: 'Send', onClick: send }} onKeyDown={onKeyDown} {...extra} />)
  return { ...page, send, stop, onKeyDown }
}

it('submits on desktop Enter, while composition and Shift+Enter preserve the draft', () => {
  const page = show(), input = screen.getByRole('textbox')
  fireEvent.compositionStart(input)
  fireEvent.keyDown(input, { key: 'Enter' })
  expect(page.send).not.toHaveBeenCalled()
  fireEvent.compositionEnd(input)
  fireEvent.keyDown(input, { key: 'Enter', keyCode: 229 })
  fireEvent.keyDown(input, { key: 'Enter', shiftKey: true })
  expect(page.send).not.toHaveBeenCalled()
  fireEvent.keyDown(input, { key: 'Enter' })
  expect(page.send).toHaveBeenCalledTimes(1)
})

it('keeps phone Enter as a newline even when command suggestions are open', () => {
  layout.phone = true
  const page = show()
  fireEvent.keyDown(screen.getByRole('textbox'), { key: 'Enter' })
  expect(page.onKeyDown).not.toHaveBeenCalled()
  expect(page.send).not.toHaveBeenCalled()
  fireEvent.click(screen.getByRole('button', { name: 'Send' }))
  expect(page.send).toHaveBeenCalledTimes(1)
})

it('shows stop in the primary position when empty and retains both actions with a draft', () => {
  const stop = vi.fn(), send = vi.fn()
  const props = { value: '', onChange: vi.fn(), label: 'Message', placeholder: 'Message', send: { label: 'Send', onClick: send }, stop: { label: 'Stop', onClick: stop } }
  const page = render(<ConversationComposer {...props} />)
  expect(screen.queryByRole('button', { name: 'Send' })).toBeNull()
  fireEvent.click(screen.getByRole('button', { name: 'Stop' }))
  expect(stop).toHaveBeenCalledTimes(1)
  page.rerender(<ConversationComposer {...props} value="Continue with this" />)
  fireEvent.click(screen.getByRole('button', { name: 'Send' }))
  expect(send).toHaveBeenCalledTimes(1)
  expect(screen.getByRole('button', { name: 'Stop' })).toBeTruthy()
})

it('allows attachment-only messages and keeps settings independent from form submission', () => {
  const mode = vi.fn()
  const page = show({ value: '', hasAttachments: true, leading: <button type="button" onClick={mode}>Mode</button> })
  fireEvent.click(screen.getByRole('button', { name: 'Mode' }))
  expect(mode).toHaveBeenCalledTimes(1)
  expect(page.send).not.toHaveBeenCalled()
  fireEvent.click(screen.getByRole('button', { name: 'Send' }))
  expect(page.send).toHaveBeenCalledTimes(1)
})
