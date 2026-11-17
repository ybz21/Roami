import type { ModelCatalog } from './model-hub-api'

export const gatewayCallableModels = (catalog: ModelCatalog) => catalog.models.filter(model => model.enabled !== false && model.candidates.some(candidate => catalog.sources.some(source => source.id === candidate.sourceId && !source.pluginDesktopUnavailable)))
export function gatewayLoopback(endpoint: string) {
  try { const host = new URL(endpoint).hostname; return host === 'localhost' || host === '[::1]' || /^127\./.test(host) } catch { return false }
}
const shellLiteral = (value: string) => "'" + value.replace(/'/g, "'\\''") + "'"
export function gatewayCallExample(endpoint: string, model: string, language: string) {
  if (language === 'python') return `from openai import OpenAI\nimport os\n\nclient = OpenAI(\n    base_url=${JSON.stringify(endpoint)},\n    api_key=os.environ["ROAMI_GATEWAY_KEY"],\n)\nresponse = client.chat.completions.create(\n    model=${JSON.stringify(model)},\n    messages=[{"role": "user", "content": "Hello"}],\n)`
  const payload = JSON.stringify({ model, messages: [{ role: 'user', content: 'Hello' }] }, null, 2)
  return `curl ${shellLiteral(endpoint + '/chat/completions')} \\\n  -H "Authorization: Bearer $ROAMI_GATEWAY_KEY" \\\n  -H "Content-Type: application/json" \\\n  -d ${shellLiteral(payload)}`
}
