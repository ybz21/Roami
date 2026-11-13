// @vitest-environment jsdom
import { act, renderHook } from '@testing-library/react'
import { expect, it } from 'vitest'
import { FilePageMemoryProvider, useFilePageMemory, useFilePageState } from './file-page-memory'

it('keeps separate file workspaces for each node and discards them with the app shell', () => {
  const shell = renderHook(({ node }) => useFilePageMemory(node), { initialProps: { node: 'first' } })
  const first = shell.result.current
  const wrapper = ({ children }: { children: React.ReactNode }) => <FilePageMemoryProvider memory={first}>{children}</FilePageMemoryProvider>
  const page = renderHook(() => useFilePageState('tabs', ['one']), { wrapper })
  act(() => page.result.current[1](tabs => [...tabs, 'two']))
  page.unmount()
  shell.rerender({ node: 'second' })
  expect(shell.result.current).not.toBe(first)
  expect(shell.result.current.size).toBe(0)
  shell.rerender({ node: 'first' })
  expect(shell.result.current).toBe(first)
  const restored = renderHook(() => useFilePageState('tabs', []), { wrapper })
  expect(restored.result.current[0]).toEqual(['one', 'two'])
  restored.unmount()
  shell.unmount()
  const nextShell = renderHook(() => useFilePageMemory('first'))
  expect(nextShell.result.current.size).toBe(0)
  nextShell.unmount()
})
