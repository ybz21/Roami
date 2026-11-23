import type { CatalogModel, ModelCatalog } from './model-hub-api'

export function gatewayCallableModels(catalog: ModelCatalog) {
  const groups = new Map(catalog.models.filter(model => model.aggregate).map(model => [model.id, model]))
  const sources = new Set(catalog.sources.filter(source => !source.pluginDesktopUnavailable).map(source => source.id))
  function callable(model: CatalogModel, seen: Set<string>): boolean {
    return model.enabled !== false && !seen.has(model.id) && model.candidates.some(candidate => {
      if (candidate.sourceId !== '@group') return sources.has(candidate.sourceId)
      const group = groups.get(candidate.model)
      return !!group && callable(group, new Set([...seen, model.id]))
    })
  }
  return catalog.models.filter(model => !model.gatewayHidden && callable(model, new Set()))
}
export type GatewayProtocol = 'openai' | 'anthropic'
export const gatewayBaseURL = (host: string, protocol: GatewayProtocol) => host && (protocol === 'openai' ? host + '/v1' : host)
export function gatewayLoopback(endpoint: string) {
  try { const host = new URL(endpoint).hostname; return host === 'localhost' || host === '[::1]' || /^127\./.test(host) } catch { return false }
}
const shellLiteral = (value: string) => "'" + value.replace(/'/g, "'\\''") + "'"
export function gatewayCallExample(endpoint: string, model: string, language: string, protocol: GatewayProtocol = 'openai') {
  if (protocol === 'anthropic') {
    if (language === 'python') return `from anthropic import Anthropic\nimport os\n\nclient = Anthropic(\n    base_url=${JSON.stringify(endpoint)},\n    api_key=os.environ["ROAMI_GATEWAY_KEY"],\n)\nresponse = client.messages.create(\n    model=${JSON.stringify(model)},\n    max_tokens=256,\n    messages=[{"role": "user", "content": "Hello"}],\n)`
    const payload = JSON.stringify({ model, max_tokens: 256, messages: [{ role: 'user', content: 'Hello' }] }, null, 2)
    return [
      'curl ' + shellLiteral(endpoint + '/v1/messages'),
      '  -H "x-api-key: $ROAMI_GATEWAY_KEY"',
      '  -H "anthropic-version: 2023-06-01"',
      '  -H "Content-Type: application/json"',
      '  -d ' + shellLiteral(payload),
    ].join(' \\' + '\n')
  }
  if (language === 'python') return `from openai import OpenAI\nimport os\n\nclient = OpenAI(\n    base_url=${JSON.stringify(endpoint)},\n    api_key=os.environ["ROAMI_GATEWAY_KEY"],\n)\nresponse = client.chat.completions.create(\n    model=${JSON.stringify(model)},\n    messages=[{"role": "user", "content": "Hello"}],\n)`
  const payload = JSON.stringify({ model, messages: [{ role: 'user', content: 'Hello' }] }, null, 2)
  return `curl ${shellLiteral(endpoint + '/chat/completions')} \\\n  -H "Authorization: Bearer $ROAMI_GATEWAY_KEY" \\\n  -H "Content-Type: application/json" \\\n  -d ${shellLiteral(payload)}`
}
