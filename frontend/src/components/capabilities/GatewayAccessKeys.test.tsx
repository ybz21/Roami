// @vitest-environment jsdom
import { App } from 'antd'
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { api } from '../../api'
import GatewayAccessKeys from './GatewayAccessKeys'
vi.mock('../../layout', () => ({ useLayout: () => ({ phone: false }) }))
vi.mock('../../api', () => ({ api: vi.fn() }))
vi.mock('../../i18n', () => ({ useI18n: () => ({ t: (key: string) => key }) }))
const changed = vi.fn()
const row = { id: 'key-one', name: 'Laptop', suffix: 'suffix12', disabled: false }
const page = () => render(<App><GatewayAccessKeys onChanged={changed} value="" onChange={() => {}} /></App>)
beforeEach(() => { window.matchMedia = vi.fn().mockReturnValue({ matches: false, addListener() {}, removeListener() {}, addEventListener() {}, removeEventListener() {} }) })
afterEach(() => { cleanup(); vi.clearAllMocks() })
it('generates a named key and reveals the plaintext only until its dialog closes', async () => {
  vi.mocked(api).mockImplementation(async (method, path) => path.endsWith('/access-key') ? { data: { revision: 'r1', hasKey: false, suffix: '' } } : { data: { revision: method === 'GET' ? 'r1' : 'r2', keys: method === 'GET' ? [] : [row], ...(method === 'POST' ? { apiKey: 'fixture-generated-key' } : {}) } })
  const writeText = vi.fn().mockResolvedValue(undefined)
  Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText } })
  page()
  fireEvent.click(await screen.findByRole('button',{name:'gatewayWorkspace.newKey'}))
  const input = await screen.findByLabelText('hub.gateway.keyName')
  fireEvent.change(input, { target: { value: 'Laptop' } })
  fireEvent.click(screen.getByRole('button', { name: 'hub.gateway.generateKey' }))
  const dialog = await screen.findByLabelText('hub.gateway.generatedKey', { selector: 'aside' })
  expect(api).toHaveBeenCalledWith('POST', '/agent/model-gateway/access-keys', { revision: 'r1', name: 'Laptop' })
  expect((within(dialog).getByLabelText('hub.gateway.generatedKey') as HTMLInputElement).value).toBe('fixture-generated-key')
  fireEvent.click(within(dialog).getByRole('button', { name: 'gatewayWorkspace.copyKey' }))
  await waitFor(() => expect(writeText).toHaveBeenCalledWith('fixture-generated-key'))
  fireEvent.click(within(dialog).getByRole('button', { name: 'gatewayWorkspace.keySaved' }))
  await waitFor(() => expect(screen.queryByDisplayValue('fixture-generated-key')).toBeNull())
  expect(await screen.findByText('Laptop')).toBeTruthy()
})
it('requires confirmation before deleting a key and sends the current revision', async () => {
  vi.mocked(api).mockImplementation(async (method, path) => path.endsWith('/access-key') ? { data: { revision: 'r1', hasKey: false, suffix: '' } } : { data: { revision: method === 'GET' ? 'r1' : 'r2', keys: method === 'DELETE' ? [] : [row] } })
  page()
  const manage = await screen.findByRole('button',{name:'modelInteraction.manageKey'})
  fireEvent.keyDown(manage,{key:'ArrowDown'})
  fireEvent.click(await screen.findByRole('menuitem',{name:'hub.gateway.deleteKey'}))
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
  fireEvent.click(await screen.findByRole('button',{name:'gatewayWorkspace.newKey'}))
  const input = await screen.findByLabelText('hub.gateway.keyName') as HTMLInputElement
  fireEvent.change(input, { target: { value: 'Phone' } })
  fireEvent.click(screen.getByRole('button', { name: 'hub.gateway.generateKey' }))
  await screen.findByText('hub.error.changed')
  expect(input.value).toBe('Phone')
})

it('identifies the fixed key by ID, keeps it in the existing list, and preserves a create draft while renaming', async () => {
  const fixed = { ...row, id: 'fixed-key', name: '' }
  vi.mocked(api).mockImplementation(async (_method, path) => path.endsWith('/access-key') ? { data: { revision: 'r1', hasKey: true, suffix: row.suffix, id: fixed.id } } : { data: { revision: 'r1', keys: [row, fixed] } })
  page()
  fireEvent.click(await screen.findByRole('button', { name: 'gatewayWorkspace.newKey' }))
  fireEvent.change(await screen.findByLabelText('hub.gateway.keyName'), { target: { value: 'New caller draft' } })
  fireEvent.click(screen.getByRole('button', { name: 'common.cancel' }))
  expect(screen.getAllByText('gatewayWorkspace.fixedKey')).toHaveLength(1)
  expect(screen.getAllByText('****' + row.suffix)).toHaveLength(2)
  fireEvent.keyDown(screen.getAllByRole('button', { name: 'modelInteraction.manageKey' })[0], { key: 'ArrowDown' })
  fireEvent.click(await screen.findByRole('menuitem', { name: 'hub.gateway.renameKey' }))
  fireEvent.change(await screen.findByLabelText('hub.gateway.keyName'), { target: { value: 'Renamed' } })
  fireEvent.click(screen.getByRole('button', { name: 'common.cancel' }))
  fireEvent.click(screen.getByRole('button', { name: 'gatewayWorkspace.newKey' }))
  expect((screen.getByLabelText('hub.gateway.keyName') as HTMLInputElement).value).toBe('New caller draft')
})

it('does not reveal a generated key if its response arrives after leaving the gateway', async () => {
  let issue!: (value: any) => void
  vi.mocked(api).mockImplementation(async (method, path) => {
    if (method === 'POST') return new Promise(resolve => { issue = resolve })
    return path.endsWith('/access-key') ? { data: { revision: 'r1', hasKey: false, suffix: '' } } : { data: { revision: 'r1', keys: [] } }
  })
  const mounted = page()
  fireEvent.click(await screen.findByRole('button', { name: 'gatewayWorkspace.newKey' }))
  fireEvent.change(await screen.findByLabelText('hub.gateway.keyName'), { target: { value: 'Late' } })
  fireEvent.click(screen.getByRole('button', { name: 'hub.gateway.generateKey' }))
  mounted.rerender(<App><GatewayAccessKeys active={false} onChanged={changed} value="" onChange={() => {}} /></App>)
  issue({ data: { revision: 'r2', keys: [row], apiKey: 'late-secret-should-not-be-rendered' } })
  await waitFor(() => expect(changed).toHaveBeenCalled())
  mounted.rerender(<App><GatewayAccessKeys active onChanged={changed} value="" onChange={() => {}} /></App>)
  expect(screen.queryByDisplayValue('late-secret-should-not-be-rendered')).toBeNull()
})

it('updates only the label when renaming an access key', async () => {
  vi.mocked(api).mockImplementation(async (_method, path) => path.endsWith('/access-key') ? { data: { revision: 'r1', hasKey: false, suffix: '' } } : { data: { revision: 'r1', keys: [row] } })
  page()
  fireEvent.keyDown(await screen.findByRole('button', { name: 'modelInteraction.manageKey' }), { key: 'ArrowDown' })
  fireEvent.click(await screen.findByRole('menuitem', { name: 'hub.gateway.renameKey' }))
  fireEvent.change(await screen.findByLabelText('hub.gateway.keyName'), { target: { value: 'Office laptop' } })
  fireEvent.click(screen.getByRole('button', { name: 'settings.save' }))
  await waitFor(() => expect(api).toHaveBeenCalledWith('PATCH', '/agent/model-gateway/access-keys/key-one', { revision: 'r1', name: 'Office laptop' }))
})
