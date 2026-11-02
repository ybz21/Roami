// @vitest-environment jsdom
import { act, cleanup, renderHook } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { useClusterNavigation } from './useClusterNavigation'
import type { MenuItemType } from 'antd/es/menu/interface'

const mock = vi.hoisted(() => ({ node: vi.fn(), hash: vi.fn(), reload: vi.fn() }))
vi.mock('../components/cluster/node-url', () => ({
  useClusterNodes: () => [{ id: 'other', name: 'Other', online: true }],
  useCurrentNodeId: () => 'current', setCurrentNode: mock.node,
}))
vi.mock('../components/cluster/hub-health', () => ({ useHubHealth: () => ({ level: 'ok' }) }))
vi.mock('../route-hash', () => ({ getHashParams: () => new URLSearchParams('terms=old&active=old&node=current&memoryView=activity'), setHashParams: mock.hash }))
vi.mock('../i18n', () => ({ useI18n: () => ({ t: (key: string) => key }) }))
afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.clearAllMocks() })

it('switches nodes without carrying local session lists and preserves page filters', () => {
  vi.stubGlobal('location', { reload: mock.reload })
  const { result } = renderHook(() => useClusterNavigation(vi.fn()))
  const item = result.current.nodeItems[0] as MenuItemType
  act(() => item.onClick({ key: 'node:other' } as Parameters<NonNullable<MenuItemType['onClick']>>[0]))
  expect(mock.node).toHaveBeenCalledWith('other')
  expect(mock.hash).toHaveBeenCalledWith({ node: 'other', memoryView: 'activity' })
  expect(mock.reload).toHaveBeenCalledOnce()
})
