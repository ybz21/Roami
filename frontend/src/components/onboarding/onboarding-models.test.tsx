// @vitest-environment jsdom
import { App } from 'antd'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { api } from '../../api'
import OnboardingModels from './OnboardingModels'

vi.mock('../../api', () => ({ api: vi.fn() }))
vi.mock('../../i18n', () => ({ useI18n: () => ({ t: (key: string) => key, locale: 'en-US' }) }))
vi.mock('../../layout', () => ({ useLayout: () => ({ phone: false, keyboard: 0 }) }))
beforeEach(() => {
  window.matchMedia = vi.fn().mockReturnValue({ matches: false, addListener: vi.fn(), removeListener: vi.fn(), addEventListener: vi.fn(), removeEventListener: vi.fn() })
  let catalog = { revision: 'first', sources: [], models: [], drafts: [], uses: {}, baseUrl: '' }
  vi.mocked(api).mockReset().mockImplementation(async (method, path, body) => {
    if (path !== '/agent/model-gateway/catalog') throw new Error('Unexpected request: ' + path)
    if (method === 'PUT') catalog = { ...catalog, ...body, revision: 'saved' }
    return { data: structuredClone(catalog) }
  })
})
afterEach(cleanup)
const show = (navigate = vi.fn()) => ({ navigate, ...render(<App><OnboardingModels sub="catalog/source/new" onNav={navigate} /></App>) })
const save = async () => {
  fireEvent.click(screen.getByRole('button', { name: 'agent.models.save' }))
  fireEvent.click((await screen.findByRole('dialog')).querySelector('.ant-btn-primary')!)
}

it('adds a connection and its models before any agent configuration or call verification', async () => {
  const page = show()
  fireEvent.change(await screen.findByLabelText('hub.name'), { target: { value: 'First connection' } })
  fireEvent.change(screen.getByLabelText('agent.models.baseUrl'), { target: { value: 'https://models.example/v1' } })
  fireEvent.change(screen.getByLabelText('agent.models.apiKey'), { target: { value: 'test-key' } })
  fireEvent.change(screen.getByLabelText('hub.upstreamModel'), { target: { value: 'shared-model' } })
  await save()
  await waitFor(() => expect(page.navigate).toHaveBeenCalledWith('onboarding/model/catalog'))
  const writes = vi.mocked(api).mock.calls.filter(([method]) => method !== 'GET')
  expect(writes).toHaveLength(1)
  expect(writes[0]).toEqual(['PUT', '/agent/model-gateway/catalog', expect.objectContaining({ sources: [expect.objectContaining({ name: 'First connection' })], models: [expect.objectContaining({ name: 'shared-model' })] })])
})

it('restores connection and model drafts together without storing the credential in browser storage', async () => {
  const first = show()
  fireEvent.change(await screen.findByLabelText('hub.name'), { target: { value: 'Draft connection' } })
  fireEvent.change(screen.getByLabelText('agent.models.baseUrl'), { target: { value: 'https://models.example/v1' } })
  fireEvent.change(screen.getByLabelText('agent.models.apiKey'), { target: { value: 'draft-key' } })
  fireEvent.change(screen.getByLabelText('hub.upstreamModel'), { target: { value: 'draft-model' } })
  first.unmount()
  const second = show()
  await waitFor(() => expect((screen.getByLabelText('hub.upstreamModel') as HTMLInputElement).value).toBe('draft-model'))
  expect((screen.getByLabelText('hub.name') as HTMLInputElement).value).toBe('Draft connection')
  expect((screen.getByLabelText('agent.models.apiKey') as HTMLInputElement).value).toBe('draft-key')
  expect(JSON.stringify(localStorage) + JSON.stringify(sessionStorage)).not.toContain('draft-key')
  await save()
  await waitFor(() => expect(second.navigate).toHaveBeenCalledWith('onboarding/model/catalog'))
})
