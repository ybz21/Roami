import type { ModelCatalog, ModelSource } from '../../../../frontend/src/components/capabilities/model-hub-api'
import type { PriceRule, SourcePricing } from '../../../../frontend/src/components/capabilities/model-routing-api'
import type { GatewayConfiguration } from '../../../../frontend/src/components/settings/local-model-gateway'
import { checkSource, now, reconcileCall, requestMonitor, requestObservation, sourceMonitor, traces, usage } from './activity-fixture'
export { traceCases } from './activity-fixture'

const protocol = 'openai-completions'
const origins: ModelSource[] = [
  { id: 'demo-api', name: 'Demo API', baseUrl: 'https://models.example.invalid/v1', protocol, authMode: 'bearer', hasKey: true },
  { id: 'workbuddy', name: 'WorkBuddy · Demo', baseUrl: '', protocol, authMode: 'plugin', pluginSourceId: 'workbuddy-demo' },
  { id: 'openrouter', name: 'OpenRouter · Free', baseUrl: 'https://openrouter.ai/api/v1', protocol, authMode: 'bearer', connector: 'openrouter-free', hasKey: true },
]
const discovery: Record<string, string[]> = {
  'demo-api': ['deepseek-flash', 'vision-pro', 'vision-lite'],
  workbuddy: ['hy4-flash', 'deepseek-flash', 'hy4-free'],
  openrouter: ['ernie-flash:free', 'gemma-vision:free', 'qwen-coder:free'],
}
const configured = [
  ['openrouter', 'ernie-flash:free', 'ernie-free'], ['workbuddy', 'hy4-flash', 'hy4-flash'],
  ['workbuddy', 'deepseek-flash', 'workbuddy-deepseek'], ['demo-api', 'vision-pro', 'vision-pro'],
]
let revision = 1
let catalog: ModelCatalog = {
  revision: 'demo-1', sources: origins, baseUrl: 'http://127.0.0.1:41155', drafts: [], uses: { free: ['Roami'] },
  models: [
    { id: 'free', name: 'free', aggregate: true, enabled: true, protocol, strategy: 'order', onLimit: true, onExhausted: true, cooldownSeconds: 60, candidates: configured.slice(0, 3).map(([sourceId, model]) => ({ sourceId, model })) },
    { id: 'vision', name: 'Vision fallback', aggregate: true, enabled: true, protocol, strategy: 'smart', candidates: [{ sourceId: 'demo-api', model: 'vision-pro' }] },
    ...configured.map(([sourceId, model, id]) => ({ id, name: model, protocol, strategy: 'fixed' as const, enabled: true, candidates: [{ sourceId, model }] })),
  ],
}
const zero = { input_per_million: 0, output_per_million: 0, cache_read_per_million: 0 }
const priceRule = (mode: PriceRule['mode']): PriceRule => ({ mode, confirmed: mode === 'free', price: mode === 'tokens' ? { input_per_million: 2, output_per_million: 8, cache_read_per_million: .4 } : zero })
let settings: GatewayConfiguration = {
  currency: 'CNY', timezone: 'Asia/Shanghai', dailyLimit: 20,
  pricing: { defaultConfigured: false, default: zero, models: {}, sources: {
    'demo-api': { default: priceRule('tokens') }, openrouter: { default: priceRule('free') },
    workbuddy: { default: priceRule('quota'), models: { 'hy4-flash': priceRule('free') }, accountStrategy: 'order' },
  } },
}
let speech: Record<string, unknown> = { provider: 'volcano', volcano: {} }
let keyCount = 2
let keys = [{ id: 'demo-dev', name: 'Development', suffix: '7c2a', disabled: false }, { id: 'demo-ci', name: 'CI', suffix: 'e9f0', disabled: true }]
let fixed = { hasKey: false, suffix: '', id: 'demo-fixed' }
const installed = { id: 'workbuddy', name: 'WorkBuddy', version: '0.2.26' }
const packages = [installed]
const provider = { id: 'workbuddy', name: 'WorkBuddy', signedIn: true, methods: [{ type: 'api', label: 'Demo sign-in', keyless: true }], options: [] }

function modelDetails(model: string, sourceId: string) {
  const vision = model.includes('vision')
  const capabilities = Object.fromEntries(['text', 'streaming', 'tools', ...(vision ? ['image'] : [])].map(key => [key, { support: 'supported', evidence: 'catalog', delivery: 'native' }]))
  const rule = settings.pricing.sources?.[sourceId]
  const mode = rule?.models?.[model]?.mode || rule?.default.mode
  const pricing = mode === 'free' ? 'confirmed-free' : mode === 'quota' || mode === 'tokens' ? 'metered' : 'unknown'
  return { id: model, name: model, protocol, pricing, capabilities, contextWindow: vision ? 128000 : 64000, maxOutputTokens: 8192, inputModalities: vision ? ['text', 'image'] : ['text'], outputModalities: ['text'] }
}
function directoryFor(source: ModelSource) {
  return discovery[source.id] || (source.connector ? discovery.openrouter : discovery['demo-api'])
}
function directory() {
  return { revision: catalog.revision, models: [
    ...catalog.models.map(row => ({ ...modelDetails(row.candidates[0]?.model || row.id, row.candidates[0]?.sourceId || ''), id: row.id, kind: row.aggregate ? 'aggregate' : 'single', configured: true, enabled: row.enabled !== false, candidates: row.candidates })),
    ...catalog.sources.flatMap(source => directoryFor(source).filter(model => !catalog.models.some(row => !row.aggregate && row.candidates.some(candidate => candidate.sourceId === source.id && candidate.model === model))).map(model => ({ ...modelDetails(model, source.id), kind: 'single', configured: false, enabled: false, candidates: [{ sourceId: source.id, model }] }))),
  ] }
}
function routing(model: string | null) {
  const candidates = catalog.models.find(row => row.id === model)?.candidates || []
  const members = candidates.map(row => ({ ...row, context: modelDetails(row.model, row.sourceId).contextWindow }))
  const channels = candidates.filter(row => catalog.sources.some(source => source.id === row.sourceId)).map(row => {
    const cooling = row.model === 'deepseek-flash'
    return { ...row, account: row.sourceId === 'workbuddy' ? 'WorkBuddy · Demo' : '', kind: 'token', ready: !cooling, remaining: cooling ? 0 : 1, resetAt: cooling ? now + 900000 : null, expiresAt: null, restUntil: cooling ? now + 90000 : null, measuredAt: now - 30000, recentTokens: cooling ? 0 : 30000 }
  })
  return { now, available: channels.filter(row => row.ready).length, members, channels, observation: model === 'free' ? requestObservation : null }
}
function sourceSettings(id: string, update?: SourcePricing) {
  const policy = update || settings.pricing.sources?.[id] || { default: priceRule('inherit') }
  if (update) settings = { ...settings, pricing: { ...settings.pricing, sources: { ...settings.pricing.sources, [id]: update } } }
  const make = (model: string, rule: PriceRule, origin: string) => ({ model, rule, origin, known: ['tokens', 'free', 'quota'].includes(rule.mode), price: rule.price, multiplier: policy.multiplier || 1 })
  const source = catalog.sources.find(row => row.id === id)
  const effective = (source ? directoryFor(source) : []).map(model => make(model, policy.models?.[model] || policy.default, policy.models?.[model] ? 'model' : 'source'))
  return { data: policy, currency: settings.currency, effective, summary: make('', policy.default, 'source') }
}
function addPluginSource() {
  const id = 'workbuddy-demo-' + revision
  const source = { ...origins[1], id, name: 'WorkBuddy · Demo ' + revision, pluginSourceId: id }
  catalog = { ...catalog, revision: 'demo-' + ++revision, sources: [...catalog.sources, source] }
  return { sourceId: id, catalog }
}
const data = (value: unknown) => Response.json({ data: value })
const missing = (code = 'DEMO_ENDPOINT_UNAVAILABLE') => Response.json({ error: { code } }, { status: 404 })

// The offline artifact has no network transport, including when served by the live file API.
export function installFixture() {
  window.fetch = async (input, init) => {
    init?.signal?.throwIfAborted()
    const url = new URL(input instanceof Request ? input.url : String(input), 'https://prototype.invalid')
    const method = init?.method || 'GET'
    const write = method !== 'GET'
    const body = typeof init?.body === 'string' ? JSON.parse(init.body) : {}
    const query = url.searchParams
    if (url.pathname.endsWith('/api/preferences')) return data({})
    if (url.pathname.endsWith('/api/speech/config')) {
      if (write) speech = body
      return data(speech)
    }
    if (url.pathname.endsWith('/api/agent/models')) return data({ models: catalog.models.map(row => row.id) })
    const prefix = '/api/agent/model-gateway/'
    const index = url.pathname.indexOf(prefix)
    if (index < 0) return missing()
    const path = url.pathname.slice(index + prefix.length)
    if (path === 'catalog') {
      if (write) catalog = { ...catalog, sources: body.sources.map(({ apiKey, ...row }: ModelSource) => ({ ...row, hasKey: row.hasKey || !!apiKey })), models: body.models, drafts: body.drafts || [], revision: 'demo-' + ++revision }
      return data(catalog)
    }
    if (path === 'catalog/local-sources') return data({ sources: [] })
    if (path === 'catalog/discover') {
      const models = directoryFor(body.source)
      return data({ models, details: models.map(model => modelDetails(model, body.source.id)) })
    }
    if (path === 'catalog/routing') return data(routing(query.get('model')))
    if (path === 'models') return data(directory())
    if (path === 'settings') {
      if (write) settings = { ...body, pricing: { ...body.pricing, sources: settings.pricing.sources } }
      return data(settings)
    }
    if (path.startsWith('settings/sources/')) return Response.json(sourceSettings(decodeURIComponent(path.slice('settings/sources/'.length)), write ? body : undefined))
    if (path === 'usage') return data(usage(query))
    if (path.startsWith('calls/')) {
      reconcileCall(decodeURIComponent(path.slice('calls/'.length)), body.amount, body.reason)
      return data({})
    }
    if (path === 'monitor') return data(query.get('view') === 'requests' ? requestMonitor(query) : sourceMonitor(query))
    if (path === 'monitor/check') return data(checkSource(body.sourceId, body.model, body.rule))
    if (path.startsWith('monitor/requests/')) {
      const trace = traces.find(row => row.request.requestId === decodeURIComponent(path.slice('monitor/requests/'.length)))
      return trace ? data(trace) : missing('MODEL_GATEWAY_REQUEST_NOT_FOUND')
    }
    if (path === 'access-key') {
      if (method === 'PUT') {
        fixed = { ...fixed, hasKey: true, suffix: body.apiKey.slice(-4) }
        keys = [...keys.filter(row => row.id !== fixed.id), { id: fixed.id, name: '', suffix: fixed.suffix, disabled: false }]
      }
      if (method === 'DELETE') {
        fixed = { ...fixed, hasKey: false, suffix: '' }
        keys = keys.filter(row => row.id !== fixed.id)
      }
      return data({ ...fixed, revision: 'demo' })
    }
    if (path === 'access-keys' || path.startsWith('access-keys/')) {
      const [, id, action] = path.split('/')
      if (method === 'DELETE') {
        keys = keys.filter(row => row.id !== id)
        if (id === fixed.id) fixed = { ...fixed, hasKey: false, suffix: '' }
      }
      if (method === 'PATCH') keys = keys.map(row => row.id === id ? { ...row, name: body.name ?? row.name, disabled: body.disabled ?? row.disabled } : row)
      const apiKey = 'DEMO_NOT_A_VALID_CREDENTIAL'
      if (method === 'POST' && action === 'rotate') keys = keys.map(row => row.id === id ? { ...row, suffix: apiKey.slice(-4), disabled: false } : row)
      if (method === 'POST' && !id) keys = [...keys, { id: 'demo-' + ++keyCount, name: body.name, suffix: apiKey.slice(-4), disabled: false }]
      return data({ keys, revision: 'demo', ...(method === 'POST' ? { apiKey } : {}) })
    }
    if (path === 'plugins/packages') return data(packages)
    if (path === 'plugins/community') {
      const available = { ...installed, package: 'packages/workbuddy', providers: ['WorkBuddy'], version: '0.2.27' }
      if (!write) return data([available])
      const next = { ...installed, id: 'workbuddy-update', version: available.version }
      if (!packages.some(row => row.id === next.id)) packages.push(next)
      return data(next)
    }
    if (path === 'plugins/import' && init?.body instanceof FormData) {
      return data({ packages: [installed], skipped: [] })
    }
    if (path === 'plugins/inspect') return data([provider])
    if (path === 'plugins/sources') return data(addPluginSource())
    if (path.startsWith('plugins/sources/')) {
      if (path.endsWith('/info')) return data({ provider, options: {} })
      if (path.endsWith('/auth') || path.endsWith('/options')) return data({})
    }
    return missing()
  }
}
