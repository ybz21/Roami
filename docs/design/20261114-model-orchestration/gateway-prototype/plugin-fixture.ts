export const registryURL = 'https://github.com/magpie-community/plugins/blob/main/registry.json'
export const magpiePlugins = [
  {
    id: 'workbuddy', name: 'WorkBuddy', path: 'packages/workbuddy', available: '0.2.27',
    providers: [
      { id: 'workbuddy', name: 'WorkBuddy', region: ['国内版', 'China'], models: ['hy4-flash', 'deepseek-flash', 'hy4-free'] },
      { id: 'workbuddy-ai', name: 'WorkBuddy AI', region: ['国际版', 'International'], models: ['hy4-flash', 'vision-lite'] },
    ],
  },
  {
    id: 'atomcode', name: 'AtomCode', path: 'packages/atomcode', available: '0.1.12',
    providers: [{ id: 'atomcode', name: 'AtomCode', region: ['Coding Plan', 'Coding Plan'], models: ['deepseek-flash'] }],
  },
]

type PluginRelease = { active: string; staged: string; previous: string; checkedAt: number | null; downloaded: string[] }
const releases: Record<string, PluginRelease> = {
  workbuddy: { active: '0.2.26', staged: '', previous: '', checkedAt: null, downloaded: ['0.2.26'] },
  atomcode: { active: '', staged: '', previous: '', checkedAt: null, downloaded: [] },
}
type PluginAccount = { sourceId: string; authId: string; pluginId: string; providerId: string; authorized: boolean; claimed: boolean }
export const pluginAccounts: PluginAccount[] = [
  { sourceId: 'workbuddy', authId: 'workbuddy-demo', pluginId: 'workbuddy', providerId: 'workbuddy', authorized: true, claimed: false },
]

export const pluginRelease = (id: string) => releases[id]
export const pluginProvider = (id: string) => magpiePlugins.flatMap(plugin => plugin.providers).find(row => row.id === id)
export const inspectPlugin = (packageId: string) => magpiePlugins.find(row => packageId.split('@')[0] === row.id)
export const downloadedPackages = () => magpiePlugins.flatMap(plugin => releases[plugin.id].downloaded.map(version => ({
  id: plugin.id + '@' + version, name: plugin.path, version,
})))

export function stagePluginRelease(id: string) {
  const plugin = magpiePlugins.find(row => row.id === id)
  if (!plugin) return
  const release = releases[id]
  if (release.active !== plugin.available) release.staged = plugin.available
  if (!release.downloaded.includes(plugin.available)) release.downloaded.push(plugin.available)
  return downloadedPackages().find(row => row.id === id + '@' + plugin.available)
}
export function applyPluginRelease(id: string) {
  const release = releases[id]
  if (!release?.staged) return
  release.previous = release.active
  release.active = release.staged
  release.staged = ''
}
export function rollBackPluginRelease(id: string) {
  const release = releases[id]
  if (!release?.previous) return
  release.active = release.previous
  release.previous = ''
  release.staged = ''
}
