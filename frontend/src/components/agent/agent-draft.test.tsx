// @vitest-environment jsdom
import { act, renderHook } from '@testing-library/react'
import { expect, it } from 'vitest'
import { useAgentDraft } from './useAgentDraft'

it('restores the selected conversation before typing and retains immediate input', () => {
  localStorage.clear()
  localStorage.setItem('first', 'saved first')
  localStorage.setItem('second', 'saved second')
  const hook = renderHook(({ key }) => useAgentDraft(key), { initialProps: { key: 'first' } })
  expect(hook.result.current[0]).toBe('saved first')
  hook.rerender({ key: 'second' })
  act(() => hook.result.current[1]('immediate typing'))
  expect(hook.result.current[0]).toBe('immediate typing')
  hook.rerender({ key: 'first' })
  expect(hook.result.current[0]).toBe('saved first')
  hook.unmount()
})
