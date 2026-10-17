// @vitest-environment jsdom
import { cleanup, fireEvent, render } from '@testing-library/react'
import { useRef } from 'react'
import { afterEach, expect, it, vi } from 'vitest'
import { useAgentMessageFocus } from './useAgentMessageFocus'

afterEach(() => { cleanup(); vi.restoreAllMocks() })

it('waits for the target message and scrolls once inside the chat instead of the document', () => {
  let stick: { current: boolean }
  vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockImplementation(function (this: HTMLElement) {
    return { top: this.dataset.messageId ? 1000 : 100, height: this.dataset.messageId ? 100 : 400 } as DOMRect
  })
  function Fixture({ ids, target }: { ids: string[]; target: string }) {
    const root = useRef<HTMLDivElement>(null)
    stick = useRef(true)
    useAgentMessageFocus(root, 'conversation', 'branch', target, ids.join(','), stick)
    return <div data-testid="scroll" ref={root}>{ids.map((id) => <article key={id} data-message-id={id} />)}</div>
  }
  const view = render(<Fixture ids={['earlier']} target="later" />)
  const root = view.getByTestId('scroll')
  expect(root.scrollTop).toBe(0)
  view.rerender(<Fixture ids={['earlier', 'later']} target="later" />)
  expect(root.scrollTop).toBe(750)
  expect(stick!.current).toBe(false)
  fireEvent.wheel(root)
  root.scrollTop = 10
  view.rerender(<Fixture ids={['earlier', 'later', 'new']} target="later" />)
  expect(root.scrollTop).toBe(10)
  expect(document.documentElement.scrollTop).toBe(0)
})
