// @vitest-environment jsdom
import { cleanup, renderHook, waitFor } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { agentDefinition, useRegisteredAgents } from './agent-registry'
import { agentLaunch } from './agent-command'
import type { Preferences } from './preferences'

const state = vi.hoisted(() => ({ node: 'first', api: vi.fn() }))
vi.mock('./api', () => ({ api: (...args: unknown[]) => state.api(...args) }))
vi.mock('./components/cluster/node-url', () => ({
  currentNodeId: () => state.node, useCurrentNodeId: () => state.node,
  nodeApi: (path: string) => state.node + path,
}))
afterEach(() => { cleanup(); vi.clearAllMocks() })

it('shares host registration, launches a future harness, and isolates node metadata', async () => {
  const definitions = [{ kind: 'future-harness', displayName: 'Future Harness', command: 'future-cli --task', interactive: false, models: false, canInstall: false }]
  state.api.mockResolvedValue({ agents: definitions })
  const first = renderHook(() => useRegisteredAgents()), second = renderHook(() => useRegisteredAgents())
  await waitFor(() => expect(first.result.current).toHaveLength(1))
  expect(first.result.current).toBe(second.result.current)
  expect(state.api).toHaveBeenCalledTimes(1)
  expect(state.api.mock.calls[0][1]).toBe('/agent/registry')
  expect(agentDefinition('future-harness')?.displayName).toBe('Future Harness')
  expect(agentLaunch('future-harness', {} as Preferences, "Read John's file")).toBe("future-cli --task 'Read John'\\''s file'")
  state.node = 'second'
  state.api.mockResolvedValue({ agents: [] })
  first.rerender(); second.rerender()
  expect(agentDefinition('future-harness')).toBeUndefined()
  await waitFor(() => expect(state.api).toHaveBeenCalledTimes(2))
  expect(first.result.current).toEqual([])
})
