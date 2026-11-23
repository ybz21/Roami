import { expect, it } from 'vitest'
import { gatewayBaseURL, gatewayCallableModels, gatewayCallExample, gatewayLoopback } from './gateway-call-example'
import type { ModelCatalog } from './model-hub-api'
it('uses enabled configured routes with an available source, not drafts or unavailable plugin accounts', () => {
  const model = { id: 'live', name: 'Live', strategy: 'fixed' as const, protocol: 'openai-completions', candidates: [{ sourceId: 'a', model: 'upstream' }] }
  const catalog: ModelCatalog = { revision: 'r', baseUrl: '', uses: {}, sources: [{ id: 'a', name: 'A', baseUrl: '', protocol: '', authMode: '' }, { id: 'b', name: 'B', baseUrl: '', protocol: '', authMode: '', pluginDesktopUnavailable: true }], models: [model, { ...model, id: 'disabled', enabled: false }, { ...model, id: 'unavailable', candidates: [{ sourceId: 'b', model: 'upstream' }] }, { ...model, id: 'backup', candidates: [{ sourceId: 'b', model: 'upstream' }, ...model.candidates] }], drafts: [{ ...model, id: 'draft' }] }
  expect(gatewayCallableModels(catalog).map(model => model.id)).toEqual(['live', 'backup'])
})
it('labels only actual loopback addresses as host-only', () => {
  expect(gatewayLoopback('http://127.0.0.1:41155/v1')).toBe(true)
  expect(gatewayLoopback('http://[::1]:41155/v1')).toBe(true)
  expect(gatewayLoopback('https://localhost.evil.test/v1')).toBe(false)
  expect(gatewayLoopback('https://192.168.1.4/v1')).toBe(false)
})
it('keeps keys in environment variables and quotes model identifiers safely in both examples', () => {
  const model = "team's-model"
  const curl = gatewayCallExample('http://127.0.0.1:41155/v1', model, 'curl')
  expect(curl).toContain("team'\\''s-model")
  expect(curl).toContain('$ROAMI_GATEWAY_KEY')
  const python = gatewayCallExample('http://127.0.0.1:41155/v1', model, 'python')
  expect(python).toContain('os.environ["ROAMI_GATEWAY_KEY"]')
  expect(python).toContain(`model="team's-model"`)
})

it('uses the protocol-specific SDK bases, paths and authentication headers', () => {
  const host = 'http://192.168.1.4:41155'
  expect(gatewayBaseURL(host, 'openai')).toBe(host + '/v1')
  const base = gatewayBaseURL(host, 'anthropic')
  expect(base).toBe(host)
  const curl = gatewayCallExample(base, 'team-model', 'curl', 'anthropic')
  expect(curl).toContain(host + '/v1/messages')
  expect(curl).toContain('"x-api-key: $ROAMI_GATEWAY_KEY"')
  expect(curl).toContain('"anthropic-version: 2023-06-01"')
  expect(gatewayCallExample(base, 'team-model', 'python', 'anthropic')).toContain('client.messages.create')
})
