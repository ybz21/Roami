// @vitest-environment jsdom
import { useLayoutEffect } from 'react'
import { act, cleanup, render, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { api, openEventStream } from '../../api'
import { setCurrentNode, useCurrentNodeId } from '../cluster/node-url'
import { useSwarmSnapshot } from './useSwarmSnapshot'

vi.mock('../../api', () => ({ api: vi.fn(), openEventStream: vi.fn() }))
const id = 'sw-' + 'a'.repeat(32)
type Seen = { node: string | null; name?: string; error: boolean; missing: boolean }

function Probe({ seen, capture }: { seen: Seen[]; capture?: (refresh: () => Promise<void>) => void }) {
  const node = useCurrentNodeId()
  const { data, error, missing, refresh } = useSwarmSnapshot(id)
  // Layout effects observe committed children before passive scope cleanup.
  useLayoutEffect(() => { seen.push({ node, name: data?.name, error, missing }); capture?.(refresh) })
  return <span>{data?.name}</span>
}

beforeEach(() => {
  vi.resetAllMocks()
  setCurrentNode('old-node')
  vi.mocked(openEventStream).mockImplementation(async (_path, signal) => new Response(new ReadableStream({
    start(controller) {
      if (signal.aborted) controller.close()
      else signal.addEventListener('abort', () => controller.close(), { once: true })
    },
  })))
})
afterEach(() => { cleanup(); setCurrentNode(null) })

it.each(['snapshot', 'missing', 'error'] as const)('does not commit old-node %s under the new node while its GET is pending', async previous => {
  const seen: Seen[] = []
  const oldNode = 'old-' + previous, newNode = 'new-' + previous
  setCurrentNode(oldNode)
  if (previous === 'snapshot') vi.mocked(api).mockResolvedValueOnce({ data: { id, sequence: 1, name: 'Old team' } })
  else vi.mocked(api).mockRejectedValueOnce(Object.assign(new Error(previous), { status: previous === 'missing' ? 404 : 503 }))
  vi.mocked(api).mockImplementationOnce(() => new Promise(() => {}))
  render(<Probe seen={seen} />)
  await waitFor(() => expect(seen.some(s => previous === 'snapshot' ? s.name === 'Old team' : previous === 'missing' ? s.missing : s.error)).toBe(true))
  act(() => setCurrentNode(newNode))
  const next = seen.filter(s => s.node === newNode)
  expect(next.length).toBeGreaterThan(0)
  expect(next.every(s => !s.name && !s.error && !s.missing)).toBe(true)
})


it('renders the new node snapshot when its pending GET resolves', async () => {
  const seen: Seen[] = []
  setCurrentNode('old-completion')
  vi.mocked(api).mockResolvedValueOnce({ data: { id, sequence: 1, name: 'Old team' } })
  let finish!: (value: unknown) => void
  vi.mocked(api).mockImplementationOnce(() => new Promise(resolve => { finish = resolve }))
  render(<Probe seen={seen} />)
  await waitFor(() => expect(seen[seen.length - 1]?.name).toBe('Old team'))
  act(() => setCurrentNode('new-completion'))
  await waitFor(() => expect(finish).toBeTypeOf('function'))
  await act(async () => { finish({ data: { id, sequence: 2, name: 'New team' } }) })
  await waitFor(() => expect(seen[seen.length - 1]).toMatchObject({ node: 'new-completion', name: 'New team', error: false, missing: false }))
})

it('ignores a previous node GET that finishes after the new node loaded', async () => {
  const seen: Seen[] = []
  setCurrentNode('old-late')
  let finish!: (value: unknown) => void
  vi.mocked(api).mockImplementationOnce(() => new Promise(resolve => { finish = resolve }))
  vi.mocked(api).mockResolvedValueOnce({ data: { id, sequence: 1, name: 'New team' } })
  render(<Probe seen={seen} />)
  act(() => setCurrentNode('new-late'))
  await waitFor(() => expect(seen[seen.length - 1]?.name).toBe('New team'))
  await act(async () => { finish({ data: { id, sequence: 2, name: 'Old team' } }) })
  expect(seen.filter(s => s.node === 'new-late').some(s => s.name === 'Old team')).toBe(false)
  expect(seen[seen.length - 1]?.name).toBe('New team')
})

it('retains confirmed data after a same-node refresh failure', async () => {
  const seen: Seen[] = []
  setCurrentNode('same-node-refresh')
  vi.mocked(api).mockResolvedValueOnce({ data: { id, sequence: 1, name: 'Confirmed team' } })
  let refresh!: () => Promise<void>
  render(<Probe seen={seen} capture={value => { refresh = value }} />)
  await waitFor(() => expect(seen[seen.length - 1]?.name).toBe('Confirmed team'))
  vi.mocked(api).mockRejectedValueOnce(Object.assign(new Error('offline'), { status: 503 }))
  await act(async () => { await refresh() })
  expect(seen[seen.length - 1]).toMatchObject({ node: 'same-node-refresh', name: 'Confirmed team', error: true, missing: false })
})
