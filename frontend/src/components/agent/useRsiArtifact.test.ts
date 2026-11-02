// @vitest-environment jsdom
import { act, cleanup, renderHook } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { api } from '../../api'
import { useRsiArtifact } from './useRsiArtifact'
vi.mock('../../api', () => ({ api: vi.fn() }))
afterEach(cleanup)
function deferred() { let resolve!: (value: any) => void, reject!: (value: unknown) => void; const promise = new Promise<any>((ok, fail) => { resolve = ok; reject = fail }); return { promise, resolve, reject } }
it('keeps the last chosen artifact when network responses arrive out of order', async () => {
  const a = deferred(), b = deferred()
  vi.mocked(api).mockReset().mockReturnValueOnce(a.promise).mockReturnValueOnce(b.promise)
  const { result } = renderHook(() => useRsiArtifact(null, 'run'))
  act(() => { void result.current.open({ name: 'a.md', artifactId: 'a' }) })
  expect(result.current.artifact?.loading).toBe(true)
  act(() => { void result.current.open({ name: 'b.md', artifactId: 'b' }) })
  await act(async () => { b.resolve({ data: { name: 'b.md', text: 'second' } }) })
  await act(async () => { a.resolve({ data: { name: 'a.md', text: 'first' } }) })
  expect(result.current.artifact?.text).toBe('second')
})
it.each(['close', 'inline', 'run', 'node', 'unmount'])('does not reopen or replace a view after %s', async mode => {
  const a = deferred(); vi.mocked(api).mockReset().mockReturnValue(a.promise)
  const { result, rerender, unmount } = renderHook(({ node, run }) => useRsiArtifact(node, run), { initialProps: { node: null as string | null, run: 'a' } })
  act(() => { void result.current.open({ name: 'old.md', artifactId: 'old' }) })
  act(() => { if (mode === 'close') result.current.close(); else if (mode === 'inline') void result.current.open({ name: 'evidence.json', text: 'selected evidence' }); else if (mode === 'run') rerender({ node: null, run: 'b' }); else if (mode === 'node') rerender({ node: 'remote', run: 'a' }); else unmount() })
  await act(async () => { a.resolve({ data: { name: 'old.md', text: 'stale' } }) })
  if (mode !== 'unmount') expect(result.current.artifact?.text).toBe(mode === 'inline' ? 'selected evidence' : undefined)
})
it('keeps read errors in the selected view and retries the same source run', async () => {
  vi.mocked(api).mockReset().mockRejectedValueOnce(new Error('network')).mockResolvedValueOnce({ data: { name: 'saved.md', text: 'recovered' } })
  const { result } = renderHook(() => useRsiArtifact(null, 'selected'))
  await act(async () => { await result.current.open({ name: 'saved.md', artifactId: 'proof', runId: 'original' }) })
  expect(result.current.artifact?.failed).toBe(true)
  await act(async () => { await result.current.open(result.current.artifact!.request) })
  expect(result.current.artifact?.text).toBe('recovered')
  expect(api).toHaveBeenLastCalledWith('GET', '/agent/improvement/pipeline/runs/original/artifacts/proof')
})
