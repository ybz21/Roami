// @vitest-environment jsdom
import { act, renderHook } from '@testing-library/react'
import { expect, it } from 'vitest'
import { WorkspaceStateStore } from '../../workspace-state'
import { FileWorkspaceStateProvider, useFileWorkspaceState } from './file-workspace-state'

it('uses node scopes in the same store to restore file workspaces', () => {
  const store = new WorkspaceStateStore(), first = store.scope('node', 'first', 'files'), second = store.scope('node', 'second', 'files')
  const wrapper = ({ children }: { children: React.ReactNode }) => <FileWorkspaceStateProvider scope={first}>{children}</FileWorkspaceStateProvider>
  const page = renderHook(() => useFileWorkspaceState('tabs', ['one']), { wrapper })
  act(() => page.result.current[1](tabs => [...tabs, 'two']))
  page.unmount()
  expect(second.get('tabs')).toBeUndefined()
  const restored = renderHook(() => useFileWorkspaceState('tabs', []), { wrapper })
  expect(restored.result.current[0]).toEqual(['one', 'two'])
  restored.unmount()
  expect(new WorkspaceStateStore().scope('node', 'first', 'files').get('tabs')).toBeUndefined()
})
