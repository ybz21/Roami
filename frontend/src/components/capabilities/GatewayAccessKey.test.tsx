// @vitest-environment jsdom
import { useState } from 'react'
import { App } from 'antd'
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { api } from '../../api'
import GatewayAccessKey from './GatewayAccessKey'
vi.mock('../../api', () => ({ api: vi.fn() }))
vi.mock('../../i18n', () => ({ useI18n: () => ({ t: (key: string) => key }) }))
const changed = vi.fn()
function Page() { const [value, onChange] = useState(''); return <App><GatewayAccessKey onChanged={changed} value={value} onChange={onChange} /></App> }
beforeEach(() => { window.matchMedia = vi.fn().mockReturnValue({ matches: false, addListener() {}, removeListener() {}, addEventListener() {}, removeEventListener() {} }) })
afterEach(() => { cleanup(); vi.clearAllMocks() })
it('saves an explicit client key and clears plaintext after the metadata response', async () => {
  vi.mocked(api).mockImplementation(async method => ({ data: { revision: method === 'GET' ? 'r1' : 'r2', hasKey: method !== 'GET', suffix: method === 'GET' ? '' : 'access-1' } }))
  render(<Page />)
  const input = await screen.findByLabelText('hub.gateway.key') as HTMLInputElement
  fireEvent.change(input, { target: { value: 'short' } })
  expect((screen.getByRole('button', { name: 'settings.save' }) as HTMLButtonElement).disabled).toBe(true)
  fireEvent.change(input, { target: { value: 'fixture-client-access-1' } })
  fireEvent.click(screen.getByRole('button', { name: 'settings.save' }))
  await waitFor(() => expect(api).toHaveBeenCalledWith('PUT', '/agent/model-gateway/access-key', { revision: 'r1', apiKey: 'fixture-client-access-1' }))
  await waitFor(() => expect(input.value).toBe(''))
  expect(changed).toHaveBeenCalledOnce()
})
it('keeps a key draft across a rejected save and metadata recovery', async () => {
  let reads = 0, writes = 0
  vi.mocked(api).mockImplementation(async method => {
    if (method === 'GET') return { data: { revision: reads++ ? 'r2' : 'r1', hasKey: false, suffix: '' } }
    if (writes++ === 0) throw { apiError: { code: 'MODEL_CATALOG_CHANGED' } }
    return { data: { revision: 'r3', hasKey: true, suffix: 'access-1' } }
  })
  render(<Page />)
  const input = await screen.findByLabelText('hub.gateway.key') as HTMLInputElement
  fireEvent.change(input, { target: { value: 'fixture-client-access-1' } })
  fireEvent.click(screen.getByRole('button', { name: 'settings.save' }))
  await screen.findByText('hub.error.changed')
  expect(input.value).toBe('fixture-client-access-1')
  fireEvent.click(screen.getByRole('button', { name: 'capabilities.models.reread' }))
  await waitFor(() => expect(reads).toBe(2))
  expect(input.value).toBe('fixture-client-access-1')
  fireEvent.click(screen.getByRole('button', { name: 'settings.save' }))
  await waitFor(() => expect(api).toHaveBeenCalledWith('PUT', '/agent/model-gateway/access-key', { revision: 'r2', apiKey: 'fixture-client-access-1' }))
})
it('disables a configured client key only after confirmation', async () => {
  vi.mocked(api).mockImplementation(async method => ({ data: { revision: 'r1', hasKey: method === 'GET', suffix: method === 'GET' ? 'access-1' : '' } }))
  render(<Page />)
  fireEvent.click(await screen.findByRole('button', { name: 'hub.gateway.disableKey' }))
  expect(vi.mocked(api).mock.calls.some(([method]) => method === 'DELETE')).toBe(false)
  fireEvent.click(within(await screen.findByRole('dialog')).getByRole('button', { name: 'hub.gateway.disableKey' }))
  await waitFor(() => expect(api).toHaveBeenCalledWith('DELETE', '/agent/model-gateway/access-key', { revision: 'r1' }))
})
