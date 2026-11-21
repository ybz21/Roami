import type { ModelCatalog, ModelSource } from '../../../../frontend/src/components/capabilities/model-hub-api'
import type { PriceRule, SourcePricing } from '../../../../frontend/src/components/capabilities/model-routing-api'
import type { GatewayConfiguration } from '../../../../frontend/src/components/settings/local-model-gateway'
import { checkSource, now, reconcileCall, requestMonitor, requestObservation, sourceMonitor, traces, usage } from './activity-fixture'
import { downloadedPackages, inspectPlugin, readMagpiePlugins, pluginAccounts, pluginProvider, stagePluginRelease } from './plugin-fixture'
export { traceCases } from './activity-fixture'

const protocol = 'openai-completions'
const origins: ModelSource[] = [
  { id: 'demo-api', name: 'Demo API', baseUrl: 'https://models.example.invalid/v1', protocol, authMode: 'bearer', hasKey: true },
  { id: 'workbuddy', name: 'WorkBuddy · Demo', baseUrl: 'https://magpie.invalid/workbuddy', protocol, authMode: 'plugin', pluginSourceId: 'workbuddy-demo' },
  { id: 'raccoon', name: '商汤小浣熊 · Demo', baseUrl: 'https://magpie.invalid/raccoon', protocol, authMode: 'plugin', pluginSourceId: 'raccoon-demo' },
  { id: 'cursor', name: 'Cursor · Demo', baseUrl: 'https://magpie.invalid/cursor', protocol, authMode: 'plugin', pluginSourceId: 'cursor-demo' },
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
    { id: 'free', name: 'free', aggregate: true, enabled: true, protocol, strategy: 'order', onLimit: true, onExhausted: true, cooldownSeconds: 60, weights: { 'openrouter/ernie-flash:free': 3, 'workbuddy/hy4-flash': 1 }, candidates: configured.slice(0, 3).map(([sourceId, model]) => ({ sourceId, model })) },
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
const authOptions: Record<string, Record<string, boolean>> = {}
const demoProvider = (pluginId: string, id: string, signedIn: boolean) => {
  const provider = pluginProvider(pluginId, id)
  return {
    id, name: provider?.name || id, signedIn,
    usage: !!provider?.usage, checkin: !!provider?.checkin, calls: !!provider?.calls, renews: !!provider?.renews,
    methods: [{ type: 'api', label: 'Demo sign-in', keyless: true, labels: { 'zh-CN': '演示授权', en: 'Demo sign-in' } }],
    options: [],
    models: provider?.models.map(id => ({ id, name: id })) || [],
  }
}

function modelDetails(model: string, sourceId: string) {
  const vision = model.includes('vision')
  const capabilities = Object.fromEntries(['text', 'streaming', 'tools', ...(vision ? ['image'] : [])].map(key => [key, { support: 'supported', evidence: 'catalog', delivery: 'native' }]))
  const rule = settings.pricing.sources?.[sourceId]
  const mode = rule?.models?.[model]?.mode || rule?.default.mode
  const pricing = mode === 'free' ? 'confirmed-free' : mode === 'quota' || mode === 'tokens' ? 'metered' : 'unknown'
  return { id: model, name: model, protocol, pricing, capabilities, contextWindow: vision ? 128000 : 64000, maxOutputTokens: 8192, inputModalities: vision ? ['text', 'image'] : ['text'], outputModalities: ['text'] }
}
function directoryFor(source: ModelSource) {
  const account = pluginAccounts.find(row => row.sourceId === source.id)
  if (account) return account.authorized ? pluginProvider(account.pluginId, account.providerId)?.models || [] : []
  return discovery[source.id] || (source.connector ? discovery.openrouter : discovery['demo-api'])
}
function directory() {
  return { revision: catalog.revision, models: [
    ...catalog.models.map(row => ({ ...modelDetails(row.candidates[0]?.model || row.id, row.candidates[0]?.sourceId || ''), id: row.id, kind: row.aggregate ? 'aggregate' : 'single', configured: true, enabled: row.enabled !== false, candidates: row.candidates })),
    ...catalog.sources.flatMap(source => directoryFor(source).filter(model => !catalog.models.some(row => !row.aggregate && row.candidates.some(candidate => candidate.sourceId === source.id && candidate.model === model))).map(model => ({ ...modelDetails(model, source.id), kind: 'single', configured: false, enabled: false, candidates: [{ sourceId: source.id, model }] }))),
  ] }
}
function routing(model: string | null) {
  const pool = catalog.models.find(row => row.id === model)
  const candidates = pool?.candidates || []
  const members = candidates.map(row => ({ ...row, context: modelDetails(row.model, row.sourceId).contextWindow }))
  const channels = candidates.filter(row => catalog.sources.some(source => source.id === row.sourceId)).map(row => {
    const cooling = row.model === 'deepseek-flash'
    return { ...row, account: row.sourceId === 'workbuddy' ? 'WorkBuddy · Demo' : '', kind: 'token', ready: !cooling && pool?.enabled !== false, remaining: cooling ? 0 : 1, resetAt: cooling ? now + 900000 : null, expiresAt: null, restUntil: cooling ? now + 90000 : null, measuredAt: now - 30000, recentTokens: cooling ? 0 : 30000 }
  })
  return { now, available: channels.filter(row => row.ready).length, members, channels, observation: model === 'free' ? requestObservation : null }
}

export function readWorkbench(poolId: string, hours: number) {
  const pools = catalog.models.filter(row => row.aggregate)
  const pool = pools.find(row => row.id === poolId) || pools[0]
  const poolRoute = pool ? routing(pool.id) : undefined
  const requests = pool ? requestMonitor(new URLSearchParams({ routeId: pool.id, hours: String(hours) })) : null
  const ids = new Set(requests?.recent.map(row => row.requestId))
  return { pools, pool, poolRoute, requests, sources: catalog.sources, traces: traces.filter(row => ids.has(row.request.requestId)) }
}
function sourceSettings(id: string, update?: SourcePricing) {
  const policy = update || settings.pricing.sources?.[id] || { default: priceRule('inherit') }
  if (update) settings = { ...settings, pricing: { ...settings.pricing, sources: { ...settings.pricing.sources, [id]: update } } }
  const make = (model: string, rule: PriceRule, origin: string) => ({ model, rule, origin, known: ['tokens', 'free', 'quota'].includes(rule.mode), price: rule.price, multiplier: policy.multiplier || 1 })
  const source = catalog.sources.find(row => row.id === id)
  const effective = (source ? directoryFor(source) : []).map(model => make(model, policy.models?.[model] || policy.default, policy.models?.[model] ? 'model' : 'source'))
  return { data: policy, currency: settings.currency, effective, summary: make('', policy.default, 'source') }
}
export function readPluginSources() {
  return pluginAccounts.flatMap(account => {
    const source = catalog.sources.find(row => row.id === account.sourceId)
    if (!source) return []
    const models = catalog.models.filter(row => !row.aggregate && row.candidates.some(member => member.sourceId === source.id)).length
    return [{ ...account, name: source.name, models }]
  })
}
export function addDemoPluginSource(pluginId: string, providerId: string, name = '') {
  const provider = pluginProvider(pluginId, providerId)!
  const id = pluginId + '-account-' + revision
  const source: ModelSource = { id, name: name.trim() || provider.name + ' · ' + revision, pluginSourceId: id, protocol, authMode: 'plugin', baseUrl: 'https://magpie.invalid/' + id }
  pluginAccounts.push({ sourceId: id, authId: id, pluginId, providerId, authorized: false, claimed: false })
  catalog = { ...catalog, revision: 'demo-' + ++revision, sources: [...catalog.sources, source] }
  return { sourceId: id, catalog }
}
const data = (value: unknown) => Response.json({ data: value })
const missing = (code = 'DEMO_ENDPOINT_UNAVAILABLE') => Response.json({ error: { code } }, { status: 404 })

// Model and account actions use fixtures. Public Magpie metadata is read separately.
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
    if (path === 'plugins/packages') return data(downloadedPackages())
    if (path === 'plugins/community') {
      if (!write) return data(readMagpiePlugins().map(plugin => ({ package: plugin.package, name: plugin.name, providers: plugin.providers.map(row => row.id), version: plugin.available })))
      const plugin = readMagpiePlugins().find(row => row.package === body.package)
      return plugin ? data(stagePluginRelease(plugin.id)) : missing()
    }
    if (path === 'plugins/import' && init?.body instanceof FormData) {
      return data({ packages: [stagePluginRelease('workbuddy')], skipped: [] })
    }
    if (path === 'plugins/inspect') {
      const plugin = inspectPlugin(body.packageId)
      return plugin ? data(plugin.providers.map(row => demoProvider(plugin.id, row.id, false))) : missing()
    }
    if (path === 'plugins/sources') {
      const previous = pluginAccounts.find(row => row.authId === body.sourceId)
      const plugin = previous ? readMagpiePlugins().find(row => row.id === previous.pluginId) : inspectPlugin(body.packageId || '')
      const providerId = previous?.providerId || body.providerId
      return plugin?.providers.some(row => row.id === providerId) ? data(addDemoPluginSource(plugin.id, providerId)) : missing()
    }
    if (path.startsWith('plugins/sources/')) {
      const [, , id, action] = path.split('/')
      const account = pluginAccounts.find(row => row.authId === id)
      if (!account) return missing()
      const provider = demoProvider(account.pluginId, account.providerId, account.authorized)
      if (action === 'info') return data({ provider, options: authOptions[id] || {} })
      if (action === 'usage' && method === 'GET' && account.authorized && provider.usage) {
        const windows = [{ name: '周期额度', display: '120 / 500' }]
        return data({ windows: provider.checkin ? [...windows, { name: '额外积分', balance: account.claimed ? 60 : 40, unit: '积分' }] : windows })
      }
      if (action === 'check-in' && method === 'POST' && account.authorized && provider.checkin) {
        const outcome = account.claimed ? 'done' : 'claimed'
        account.claimed = true
        return data({ outcome, credit: outcome === 'claimed' ? 20 : 0, streak: 1 })
      }
      if (action === 'calls' && method === 'GET' && account.authorized && provider.calls) {
        return data([{ t: now - 30000, model: provider.models[0]?.name ?? '', in: 1200, out: 220, cost: null }])
      }
      if (action === 'auth') {
        if (body.action === 'apiKey') account.authorized = true
        return data({ ok: account.authorized })
      }
      if (action === 'options') {
        authOptions[id] = body.options
        return data({})
      }
    }
    return missing()
  }
}

export function previewSelection({ model, freeOnly }: { model: string; freeOnly: boolean }) {
  const choices = directory().models.filter(row => row.configured && row.enabled)
  const picked = model === 'auto'
    ? choices.find(row => row.kind === 'aggregate' && !freeOnly) || choices.find(row => !freeOnly || row.pricing === 'confirmed-free')
    : choices.find(row => row.id === model)
  if (!picked) return { ready: false, note: model === 'auto' ? '当前没有符合条件的候选。' : '所选模型已停用或不可用。' }
  if (freeOnly && picked.pricing !== 'confirmed-free') return { ready: false, note: '所选模型未确认免费。可改用 Auto 或选择已确认免费的模型。' }
  return { ready: true, note: '演示命中 ' + picked.id + (freeOnly ? ' · 已确认免费' : '') }
}
