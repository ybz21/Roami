import snapshot from './magpie-registry-snapshot.json'

export const registryURL = 'https://github.com/magpie-community/plugins/blob/main/registry.json'
const rawRepository = 'https://raw.githubusercontent.com/magpie-community/plugins/'
const mirror = 'https://cdn.jsdelivr.net/gh/magpie-community/plugins@'
const registryJSON = [rawRepository + 'main/registry.json', mirror + 'main/registry.json']
const releaseJSON = [rawRepository + 'dist/index.json', mirror + 'dist/index.json']
const fetchMetadata = globalThis.fetch.bind(globalThis)
const packageName = /^@magpie-community\/[a-z0-9][a-z0-9._-]{0,119}$/
const providerId = /^[a-zA-Z0-9._-]{1,120}$/

type RegistryItem = { package: string; name: string; providers: string[]; release?: string }
type Provider = { id: string; name: string; region: string[]; models: string[]; usage?: boolean; checkin?: boolean; calls?: boolean; renews?: boolean }
type Plugin = { id: string; package: string; path?: string; name: string; available: string; providers: Provider[] }
const demoProviders: Record<string, { id: string; path: string; providers: Provider[] }> = {
  '@magpie-community/opencode-workbuddy-auth': {
    id: 'workbuddy', path: 'packages/workbuddy',
    providers: [
      { id: 'workbuddy', name: 'WorkBuddy', region: ['国内版', 'China'], models: ['hy4-flash', 'deepseek-flash', 'hy4-free'], usage: true, checkin: true },
      { id: 'workbuddy-ai', name: 'WorkBuddy AI', region: ['国际版', 'International'], models: ['hy4-flash', 'vision-lite'], usage: true },
    ],
  },
  '@magpie-community/opencode-raccoon-auth': {
    id: 'raccoon', path: 'packages/raccoon',
    providers: [{ id: 'raccoon', name: '商汤小浣熊', region: [], models: ['raccoon-demo'], usage: true, checkin: true, renews: true }],
  },
  '@magpie-community/opencode-cursor-auth': {
    id: 'cursor', path: 'packages/cursor',
    providers: [{ id: 'cursor', name: 'Cursor', region: [], models: ['cursor-demo'], usage: true, calls: true }],
  },
  '@magpie-community/opencode-atomcode-auth': {
    id: 'atomcode', path: 'packages/atomcode',
    providers: [{ id: 'atomcode', name: 'AtomCode', region: ['Coding Plan', 'Coding Plan'], models: ['deepseek-flash'] }],
  },
}

type PluginRelease = { active: string; staged: string; previous: string; checkedAt: number | null; downloaded: string[] }
const releases = new Map<string, PluginRelease>([
  ['workbuddy', { active: '0.2.26', staged: '', previous: '', checkedAt: null, downloaded: ['0.2.26'] }],
  ['raccoon', { active: '0.1.14', staged: '', previous: '', checkedAt: null, downloaded: ['0.1.14'] }],
  ['cursor', { active: '0.2.48', staged: '', previous: '', checkedAt: null, downloaded: ['0.2.48'] }],
])
const releaseByPackage = new Map(snapshot.map(row => [row.package, row.release]))
function catalogFromRows(rows: RegistryItem[]): Plugin[] {
  return rows.map(row => {
    const demo = demoProviders[row.package]
    return {
      id: demo?.id || row.package.split('/')[1],
      package: row.package, name: row.name, path: demo?.path, available: releaseByPackage.get(row.package) || '',
      providers: row.providers.map(id => demo?.providers.find(provider => provider.id === id) || {
        id, name: row.providers.length === 1 ? row.name : id, region: [], models: [],
      }),
    }
  })
}
let catalog = catalogFromRows(snapshot)
export const readMagpiePlugins = () => catalog

async function publicMetadata(urls: string[], limit: number, timeout: number) {
  for (const url of urls) {
    try {
      const response = await fetchMetadata(url, {
        cache: 'no-cache', credentials: 'omit', referrerPolicy: 'no-referrer', redirect: 'error',
        signal: AbortSignal.timeout(timeout),
      })
      if (!response.ok || Number(response.headers.get('content-length')) > limit) continue
      const body = await response.text()
      if (body.length <= limit) return JSON.parse(body)
    } catch { /* Try the mirror before showing the bundled snapshot. */ }
  }
  throw Error('Magpie metadata unavailable')
}

let registryRequest: Promise<void> | undefined
let synchronized = false
export function loadMagpieRegistry(): Promise<void> {
  if (synchronized) return Promise.resolve()
  return registryRequest ??= publicMetadata(registryJSON, 1 << 20, 6_000).then(value => {
    if (value?.version !== 1 || !Array.isArray(value.plugins)) throw Error('Invalid Magpie registry')
    const rows = new Map<string, RegistryItem>()
    for (const row of value.plugins) {
      if (typeof row?.package !== 'string' || !packageName.test(row.package)
        || typeof row.name !== 'string' || !row.name.trim() || !Array.isArray(row.providers) || rows.has(row.package)) continue
      const providers = [...new Set<string>(row.providers.filter((id: unknown) => typeof id === 'string' && providerId.test(id)))]
      if (providers.length) rows.set(row.package, { package: row.package, name: row.name, providers })
    }
    const listed = catalogFromRows([...rows.values()])
    const retained = catalog.filter(row => !rows.has(row.package) && releases.get(row.id)?.active)
    catalog = [...listed, ...retained]
    synchronized = true
  }).finally(() => { registryRequest = undefined })
}

let releaseRequest: Promise<void> | undefined
export function loadMagpieReleases(): Promise<void> {
  return releaseRequest ??= publicMetadata(releaseJSON, 16 << 20, 12_000).then(value => {
    if (value?.version !== 1 || !value.packages || typeof value.packages !== 'object' || Array.isArray(value.packages)) {
      throw Error('Invalid Magpie release index')
    }
    releaseByPackage.clear()
    for (const [name, row] of Object.entries(value.packages)) {
      const release = row as { latest?: string; versions?: Record<string, { file?: string }> } | null
      if (packageName.test(name) && typeof release?.latest === 'string' && release.latest.length <= 100 && release.versions?.[release.latest]?.file) {
        releaseByPackage.set(name, release.latest)
      }
    }
    catalog = catalog.map(row => ({ ...row, available: releaseByPackage.get(row.package) || '' }))
  }).finally(() => { releaseRequest = undefined })
}

type PluginAccount = { sourceId: string; authId: string; pluginId: string; providerId: string; authorized: boolean; claimed: boolean }
export const pluginAccounts: PluginAccount[] = [
  { sourceId: 'workbuddy', authId: 'workbuddy-demo', pluginId: 'workbuddy', providerId: 'workbuddy', authorized: true, claimed: false },
  { sourceId: 'raccoon', authId: 'raccoon-demo', pluginId: 'raccoon', providerId: 'raccoon', authorized: true, claimed: false },
  { sourceId: 'cursor', authId: 'cursor-demo', pluginId: 'cursor', providerId: 'cursor', authorized: true, claimed: false },
]

export function pluginRelease(id: string) {
  const known = releases.get(id)
  if (known) return known
  const release: PluginRelease = { active: '', staged: '', previous: '', checkedAt: null, downloaded: [] }
  releases.set(id, release)
  return release
}
export const pluginProvider = (pluginId: string, id: string) => catalog.find(row => row.id === pluginId)?.providers.find(row => row.id === id)
export const inspectPlugin = (packageId: string) => catalog.find(row => packageId.split('@')[0] === row.id)
export const downloadedPackages = () => catalog.flatMap(plugin => pluginRelease(plugin.id).downloaded.map(version => ({
  id: plugin.id + '@' + version, name: plugin.package, version,
})))

export function stagePluginRelease(id: string) {
  const plugin = catalog.find(row => row.id === id)
  if (!plugin?.available) return
  const release = pluginRelease(id)
  if (release.active !== plugin.available) release.staged = plugin.available
  if (!release.downloaded.includes(plugin.available)) release.downloaded.push(plugin.available)
  return downloadedPackages().find(row => row.id === id + '@' + plugin.available)
}
export function applyPluginRelease(id: string) {
  const release = releases.get(id)
  if (!release?.staged) return
  release.previous = release.active
  release.active = release.staged
  release.staged = ''
}
export function rollBackPluginRelease(id: string) {
  const release = releases.get(id)
  if (!release?.previous) return
  release.active = release.previous
  release.previous = ''
  release.staged = ''
}
