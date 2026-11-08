// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { App } from 'antd'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { api } from '../../api'
import { SpeechSettings } from './speech-settings'

vi.mock('../../api', () => ({ api: vi.fn() }))
vi.mock('../../i18n', () => ({ useI18n: () => ({ t: (key: string) => key }) }))
const config = { provider: 'volcano', openai: { baseURL: 'https://api.openai.com/v1', apiKey: '', model: 'whisper-1', language: '' }, volcano: { apiKey: '', appId: 'old-app', accessToken: 'old-token', resourceId: 'volc.bigasr.auc', endpoint: 'https://openspeech.bytedance.com/api/v3/auc/bigmodel/submit' } }
beforeEach(() => {
  window.matchMedia = vi.fn().mockImplementation(() => ({ matches: false, addListener: vi.fn(), removeListener: vi.fn(), addEventListener: vi.fn(), removeEventListener: vi.fn() }))
  vi.mocked(api).mockResolvedValue({ data: structuredClone(config) })
})
afterEach(() => { cleanup(); vi.clearAllMocks() })

it('configures current Volcano speech recognition with one key while retaining saved legacy configuration', async () => {
  render(<App><SpeechSettings /></App>)
  const key = await screen.findByLabelText('settings.volcanoApiKey') as HTMLInputElement
  expect(screen.getByText('settings.volcanoModelHint')).toBeTruthy()
  expect(document.querySelectorAll('input[type="password"]')).toHaveLength(1)
  for (const field of ['volcanoAppId', 'volcanoAccessToken', 'volcanoResourceId', 'volcanoEndpoint']) expect(screen.queryByLabelText('settings.' + field)).toBeNull()
  fireEvent.change(key, { target: { value: 'new-key' } })
  fireEvent.click(screen.getByRole('button', { name: 'settings.save' }))
  await waitFor(() => expect(api).toHaveBeenCalledWith('PUT', '/speech/config', { ...config, volcano: { ...config.volcano, apiKey: 'new-key' } }))
})
