// @vitest-environment jsdom
import { act, cleanup, renderHook } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { useClusterNavigation } from './useClusterNavigation'
import type { MenuItemType } from 'antd/es/menu/interface'

const mock = vi.hoisted(() => ({ node: vi.fn(), hash: vi.fn(), reload: vi.fn() }))
vi.mock('../components/cluster/node-url', () => ({
  useClusterNodes: () => [{ id: 'other', name: 'Other', online: true }],
  useCurrentNodeId: () => 'current', setCurrentNode: mock.node,
}))
vi.mock('../components/cluster/hub-health', () => ({ useHubHealth: () => ({ level: 'ok' }) }))
vi.mock('../components/terminal/term-tabs-store', () => ({ loadTabs: () => ({ terms: ['$2'], active: '$2' }) }))
vi.mock('../route-hash', () => ({ NO_TERMS: 'none', setHashParams: mock.hash }))
vi.mock('../i18n', () => ({ useI18n: () => ({ t: (key: string) => key }) }))

afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.clearAllMocks() })

describe('node switch workspace restoration', () => {
  it.each([true, false])('reads the current clean-page flag at click time (clean=%s)', clean => {
    vi.stubGlobal('location', { reload: mock.reload })
    const noTabs = { current: true }
    const { result } = renderHook(() => useClusterNavigation(noTabs, vi.fn()))
    // Opening a terminal changes this ref in an effect, without another render.
    noTabs.current = clean
    const item = result.current.nodeItems[0] as MenuItemType
    act(() => item.onClick({ key: 'node:other' } as Parameters<NonNullable<MenuItemType['onClick']>>[0]))
    expect(mock.node).toHaveBeenCalledWith('other')
    expect(mock.hash).toHaveBeenCalledWith(clean
      ? { terms: 'none', active: '' }
      : { terms: '%242', active: '%242' })
    expect(mock.reload).toHaveBeenCalledOnce()
  })
})
