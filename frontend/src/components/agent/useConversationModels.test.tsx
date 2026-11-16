// @vitest-environment jsdom
import { act, cleanup, renderHook, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { api } from '../../api'
import { useConversationModels } from './useConversationModels'
const state = vi.hoisted(() => ({ selection: undefined as any, settings: { main: { model: 'main-default' }, worker: { model: 'worker-default' } }, refresh: () => {} }))
vi.mock('../../api', () => ({ api: vi.fn() }))
vi.mock('../../i18n', () => ({ useI18n: () => ({ t: (key: string) => key }) }))
vi.mock('../../page-activity', () => ({ usePageEffect: () => {} }))
vi.mock('./useAgentData', () => ({ useAgentData: (path: string) => ({ value: path === '/agent/model-settings' ? state.settings : path === '/agent/model-gateway/models' ? { models: [] } : state.selection, loading: false, failed: false, refresh: state.refresh }) }))
beforeEach(() => { state.selection = undefined; vi.mocked(api).mockReset().mockImplementation(async (_method, _path, body) => ({ data: body })) })
afterEach(cleanup)
it('waits for the saved free restriction before allowing a model change', async () => {
 const { result, rerender } = renderHook(() => useConversationModels(null, 'native-cid', 'worker'))
 expect(result.current.settings).toBeNull()
 expect(await result.current.apply('other', 'default')).toBe(false)
 expect(api).not.toHaveBeenCalled()
 state.selection = { model: 'free-pool', freeOnly: true }; rerender()
 await act(async () => { expect(await result.current.apply('free-model', 'default')).toBe(true) })
 expect(api).toHaveBeenCalledWith('PUT', '/agent/conversations/native-cid/model', { model: 'free-model', freeOnly: true })
 expect(state.settings.worker.model).toBe('worker-default')
 expect(result.current.settings?.worker.model).toBe('free-model')
})
it('accepts the next authoritative saved choice after an optimistic update', async () => {
 state.selection = { model: 'free-pool', freeOnly: true }
 const { result, rerender } = renderHook(() => useConversationModels(null, 'cid', 'worker'))
 await act(async () => { await result.current.apply('first', 'default') })
 expect(result.current.choice.model).toBe('first')
 state.selection = { model: 'external-change', freeOnly: true }; rerender()
 await waitFor(() => expect(result.current.choice.model).toBe('external-change'))
})
it('does not apply a late save result to a different conversation', async () => {
 state.selection = { model: 'free-pool', freeOnly: true }
 let resolve!: (value: any) => void
 vi.mocked(api).mockImplementation(() => new Promise(done => { resolve = done }))
 const { result, rerender } = renderHook(({ cid }) => useConversationModels(null, cid, 'worker'), { initialProps: { cid: 'first' } })
 let pending!: Promise<boolean>
 act(() => { pending = result.current.apply('chosen', 'default') })
 rerender({ cid: 'second' })
 await act(async () => { resolve({ data: { model: 'chosen', freeOnly: true } }); expect(await pending).toBe(false) })
 expect(result.current.choice.model).toBe('free-pool')
})
