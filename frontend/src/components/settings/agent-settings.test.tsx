// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { App } from 'antd'
import { afterEach, expect, it, vi } from 'vitest'
import { AgentSettings } from './agent-settings'
import { api } from '../../api'
vi.mock('../../api', () => ({ api: vi.fn() }))
vi.mock('../cluster/node-url', () => ({ useCurrentNodeId: () => null }))
vi.mock('../../i18n', () => { const t = (key: string) => key; return { useI18n: () => ({ t }) } })
afterEach(() => { cleanup(); vi.clearAllMocks() })
const role = { baseUrl: 'https://models.example/v1', keyConfigured: true, model: 'fast', images: false }
const settings = { connection: { baseUrl: role.baseUrl, keyConfigured: true }, main: role, worker: { ...role, model: 'strong' } }
it('shows one connection and saves separate role models with the existing shared key', async () => {
  vi.mocked(api).mockResolvedValue({ data: settings })
  render(<App><AgentSettings /></App>)
  await screen.findByLabelText('agent.models.baseUrl')
  expect(screen.getAllByLabelText('agent.models.baseUrl')).toHaveLength(1)
  expect(screen.getAllByLabelText('agent.models.apiKey')).toHaveLength(1)
  fireEvent.click(screen.getByRole('button', { name: 'agent.models.save' }))
  await waitFor(() => expect(api).toHaveBeenCalledWith('PUT', '/agent/model-settings', { connection: { baseUrl: role.baseUrl }, main: { model: 'fast', images: false, contextWindow: null }, worker: { model: 'strong', images: false, contextWindow: null } }))
})
