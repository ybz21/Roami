// @vitest-environment jsdom
import { act, cleanup, renderHook, waitFor } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { api } from '../../api'
import { clearAgentDataCache } from '../agent/agent-data-cache'
import { MODEL_CATALOG_CHANGED } from './model-hub-api'
import { useGatewayModelCatalog } from './gateway-model-catalog'
vi.mock('../../api', () => ({ api: vi.fn() }))
afterEach(() => { cleanup(); clearAgentDataCache(); vi.resetAllMocks() })

it('shares discovery between the picker and gateway and hides stale revision evidence', async () => {
  let finish!: (value: any) => void
  const pending = new Promise<any>(resolve => { finish = resolve })
  vi.mocked(api).mockImplementationOnce(() => pending).mockResolvedValue({ data: { revision: 'r2', models: [], refreshFailures: [] } })
  const picker = renderHook(({ revision, active }) => useGatewayModelCatalog(revision, active), { initialProps: { revision: 'r1', active: false } })
  expect(api).not.toHaveBeenCalled()
  picker.rerender({ revision: 'r1', active: true })
  const gateway = renderHook(() => useGatewayModelCatalog('r1', true))
  expect(api).toHaveBeenCalledTimes(1)
  await act(async () => { finish({ data: { revision: 'r1', models: [{ id: 'same', inputModalities: ['image'] }], refreshFailures: [] } }); await pending })
  await waitFor(() => expect(picker.result.current.value).toBe(gateway.result.current.value))
  expect(picker.result.current.value?.models[0].inputModalities).toEqual(['image'])
  picker.rerender({ revision: 'r2', active: true })
  expect(picker.result.current.value).toBeUndefined()
  await waitFor(() => expect(picker.result.current.value?.revision).toBe('r2'))
  expect(api).toHaveBeenCalledTimes(2)
  act(() => window.dispatchEvent(new Event(MODEL_CATALOG_CHANGED)))
  await waitFor(() => expect(api).toHaveBeenCalledTimes(4))
})
