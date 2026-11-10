// @vitest-environment jsdom
import { App } from 'antd'
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { api } from '../../api'
import GatewayAccessKeys from './GatewayAccessKeys'
vi.mock('../../api', () => ({ api: vi.fn() }))
vi.mock('../../i18n', () => ({ useI18n: () => ({ t: (key: string) => key }) }))
const changed = vi.fn()
const row = { id: 'key-one', name: 'Laptop', suffix: 'suffix12', disabled: false }
const page = () => render(<App><GatewayAccessKeys onChanged={changed} value="" onChange={() => {}} /></App>)
beforeEach(() => { window.matchMedia = vi.fn().mockReturnValue({ matches: false, addListener() {}, removeListener() {}, addEventListener() {}, removeEventListener() {} }) })
afterEach(() => { cleanup(); vi.clearAllMocks() })
it('generates a named key and reveals the plaintext only until its dialog closes', async () => {
  vi.mocked(api).mockImplementation(async (method, path) => path.endsWith('/access-key') ? { data: { revision: 'r1', hasKey: false, suffix: '' } } : { data: { revision: method === 'GET' ? 'r1' : 'r2', keys: method === 'GET' ? [] : [row], ...(method === 'POST' ? { apiKey: 'fixture-generated-key' } : {}) } })
  page()
  const input = await screen.findByLabelText('hub.gateway.keyName')
  fireEvent.change(input, { target: { value: 'Laptop' } })
  fireEvent.click(screen.getByRole('button', { name: 'hub.gateway.generateKey' }))
  const dialog = await screen.findByRole('dialog')
  expect(api).toHaveBeenCalledWith('POST', '/agent/model-gateway/access-keys', { revision: 'r1', name: 'Laptop' })
  expect((within(dialog).getByLabelText('hub.gateway.generatedKey') as HTMLInputElement).value).toBe('fixture-generated-key')
  fireEvent.click(within(dialog).getByRole('button', { name: 'common.close' }))
  await waitFor(() => expect(screen.queryByDisplayValue('fixture-generated-key')).toBeNull())
  expect(await screen.findByText('Laptop')).toBeTruthy()
})
it('requires confirmation before deleting a key and sends the current revision', async () => {
  vi.mocked(api).mockImplementation(async (method, path) => path.endsWith('/access-key') ? { data: { revision: 'r1', hasKey: false, suffix: '' } } : { data: { revision: method === 'GET' ? 'r1' : 'r2', keys: method === 'DELETE' ? [] : [row] } })
  page()
  fireEvent.click(await screen.findByRole('button', { name: 'hub.gateway.deleteKey' }))
  expect(vi.mocked(api).mock.calls.some(([method]) => method === 'DELETE')).toBe(false)
  const dialog = await screen.findByRole('dialog')
  fireEvent.click(within(dialog).getByRole('button', { name: 'hub.gateway.deleteKey' }))
  await waitFor(() => expect(api).toHaveBeenCalledWith('DELETE', '/agent/model-gateway/access-keys/key-one', { revision: 'r1' }))
})
it('keeps a name after a conflict so recovery does not require retyping', async () => {
  vi.mocked(api).mockImplementation(async (method, path) => {
    if (method === 'POST') throw { apiError: { code: 'MODEL_CATALOG_CHANGED' } }
    return path.endsWith('/access-key') ? { data: { revision: 'r1', hasKey: false, suffix: '' } } : { data: { revision: 'r1', keys: [] } }
  })
  page()
  const input = await screen.findByLabelText('hub.gateway.keyName') as HTMLInputElement
  fireEvent.change(input, { target: { value: 'Phone' } })
  fireEvent.click(screen.getByRole('button', { name: 'hub.gateway.generateKey' }))
  await screen.findByText('hub.error.changed')
  expect(input.value).toBe('Phone')
})
