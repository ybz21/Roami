// @vitest-environment jsdom
import { act, cleanup, renderHook, waitFor } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { api } from '../../api'
import { useRoutingStatus } from './model-routing-api'
import { useModelMonitor } from './model-monitor-api'
import { useModelMemberFacts } from './model-member-facts'
import type { ModelCatalog, CatalogModel } from './model-hub-api'
vi.mock('../../api', () => ({ api: vi.fn() }))
vi.mock('./model-routing-api', () => ({ useRoutingStatus: vi.fn(() => ({ data: { channels: [{ sourceId: 'a', model: 'first', ready: true }, { sourceId: 'b', model: 'second', ready: false }] }, failed: false })) }))
vi.mock('./model-monitor-api', () => ({ useModelMonitor: vi.fn(() => ({ data: { sources: [{ sourceId: 'a', totals: { firstTokenP95: 152 } }] }, failed: false })) }))
const model: CatalogModel = { id: 'draft-id', name: 'Pool', aggregate: true, protocol: 'openai-completions', strategy: 'smart', candidates: [{ sourceId: 'a', model: 'first' }, { sourceId: 'a', model: 'other' }, { sourceId: 'b', model: 'second' }, { sourceId: 'c', model: 'third' }, { sourceId: 'd', model: 'fourth' }] }
const catalog: ModelCatalog = { revision: 'one', sources: ['a', 'b', 'c', 'd'].map(id => ({ id, name: id, baseUrl: 'https://example.com', protocol: 'openai-completions', authMode: 'bearer' })), models: [], drafts: [], baseUrl: '', uses: {} }
afterEach(() => { cleanup(); vi.clearAllMocks() })
it('loads each distinct source once with bounded concurrency and preserves unknown facts', async () => {
 let running = 0, peak = 0
 vi.mocked(api).mockImplementation(async () => { running++; peak = Math.max(peak, running); await new Promise(resolve => setTimeout(resolve, 1)); running--; return { data: { details: [{ id: 'first', context: 131072 }] } } })
 const { result, rerender } = renderHook(({ value }) => useModelMemberFacts(value, { ...model, id: 'saved-id' }, catalog, true), { initialProps: { value: model } })
 await waitFor(() => expect(result.current.facts['a/first'].context).toBe(131072))
 expect(api).toHaveBeenCalledTimes(4)
 expect(peak).toBe(3)
 expect(result.current.facts['a/first']).toEqual({ ready: true, context: 131072, sourceLatencyMs: 152 })
 expect(result.current.facts['b/second'].ready).toBe(false)
 expect(result.current.facts['a/other'].ready).toBeUndefined()
 expect(result.current.facts['d/fourth'].context).toBeUndefined()
 expect(useRoutingStatus).toHaveBeenCalledWith('saved-id', true, 'one')
 rerender({ value: { ...model, candidates: [...model.candidates].reverse() } })
 expect(api).toHaveBeenCalledTimes(4)
})
it('cancels in-flight metadata and disables live reads when the page is inactive', async () => {
 vi.mocked(api).mockImplementation((_method, _path, _body, options) => new Promise((_resolve, reject) => options.signal.addEventListener('abort', () => reject(new Error('aborted')))))
 const { rerender } = renderHook(({ active }) => useModelMemberFacts(model, undefined, catalog, active), { initialProps: { active: true } })
 expect(api).toHaveBeenCalledTimes(3)
 await act(async () => { rerender({ active: false }) })
 expect(vi.mocked(api).mock.calls.every(([, , , options]) => options.signal.aborted)).toBe(true)
 expect(useRoutingStatus).toHaveBeenLastCalledWith('', false, 'one')
 expect(useModelMonitor).toHaveBeenLastCalledWith(false, 24, '', '', 0)
})
