import { useState } from 'react'
import { Button, Input, Select, Spin } from 'antd'
import { useI18n } from '../../i18n'
import { useAgentData } from '../agent/useAgentData'
import './magpie-community-catalog.css'

export type MagpiePackage = { id: string; name: string; version: string }
type CommunityPlugin = { package: string; name: string; providers: string[]; version: string; summary?: Record<string, string> }
const channels = ['github', 'china', 'gh-hk'] as const
type Channel = typeof channels[number]
type ReleaseFilter = 'all' | 'downloaded' | 'available'
export const communityPath = '/agent/model-gateway/plugins/community'
const registryURL = 'https://github.com/magpie-community/plugins/blob/main/registry.json'

export default function MagpieCommunityCatalog({ packages, busy, onInspect, onDownload }: {
  packages: MagpiePackage[]
  busy: boolean
  onInspect: (id: string) => void
  onDownload: (request: { channel: Channel; package: string; version: string }) => void
}) {
  const { t, locale } = useI18n()
  const [channel, setChannel] = useState<Channel>('github')
  const [query, setQuery] = useState('')
  const [filter, setFilter] = useState<ReleaseFilter>('all')
  const registry = useAgentData<CommunityPlugin[]>(communityPath + '?channel=' + channel, 300_000)
  const term = query.trim().toLowerCase().replace(/^https:\/\/github\.com\/magpie-community\/plugins\/tree\/[^/]+\//, '').replace(/^packages\//, '').replace(/\/$/, '')
  const packagesByName = new Map<string, MagpiePackage[]>()
  for (const pkg of packages) packagesByName.set(pkg.name, [...(packagesByName.get(pkg.name) || []), pkg])
  const visible = (Array.isArray(registry.value) ? registry.value : []).flatMap(plugin => {
    const local = packagesByName.get(plugin.package) || []
    const exact = local.find(row => row.version === plugin.version)
    if (term && ![plugin.name, plugin.package, ...plugin.providers, ...Object.values(plugin.summary || {})].join(' ').toLowerCase().includes(term)) return []
    if (filter === 'downloaded' && !local.length || filter === 'available' && (!plugin.version || !!exact)) return []
    return [{ plugin, local, exact }]
  })
  return <section className="tt-magpie-community" aria-label={t('hub.plugin.community')}>
    <div className="tt-model-directory-heading"><h3>{t('hub.plugin.community')}</h3><a className="tt-act" href={registryURL} target="_blank" rel="noopener noreferrer">{t('hub.plugin.viewRegistry')}</a></div>
    <div className="tt-magpie-community-fields">
      <Input aria-label={t('hub.plugin.communitySearch')} allowClear disabled={busy} placeholder={t('hub.plugin.communitySearch')} value={query} onChange={event => setQuery(event.target.value)} />
      <Select aria-label={t('hub.plugin.releaseFilter')} value={filter} options={(['all', 'downloaded', 'available'] as const).map(value => ({ value, label: t('hub.plugin.releaseFilter.' + value) }))} onChange={setFilter} />
      <Select aria-label={t('hub.plugin.communityChannel')} disabled={busy} value={channel} options={channels.map(value => ({ value, label: t('hub.plugin.channel.' + value) }))} onChange={setChannel} />
    </div>
    {registry.failed && <div className="tt-model-hub-actions"><span role="status">{t('hub.plugin.communityUnavailable')}</span><Button disabled={busy} onClick={registry.refresh}>{t('agent.retry')}</Button></div>}
    {registry.loading && <Spin />}
    {!!visible.length && <ul className="tt-magpie-list">{visible.map(({ plugin, local, exact }) => <li key={plugin.package}>
      <div><strong>{plugin.name}</strong><small>{plugin.summary?.[locale.split('-')[0]] || plugin.package}</small></div>
      <div className="tt-magpie-list-state">
        <span>{t(plugin.version ? 'hub.plugin.onlineVersion' : 'hub.plugin.noOnlineVersion', { version: plugin.version })}</span>
        {!!local.length && <small>{t('hub.plugin.localVersions', { versions: [...new Set(local.map(row => row.version))].join(', ') })}</small>}
      </div>
      <Button type={exact ? 'default' : 'primary'} disabled={busy || !plugin.version} onClick={() => exact ? onInspect(exact.id) : onDownload({ channel, package: plugin.package, version: plugin.version })}>{t(exact ? 'hub.plugin.inspectDownload' : 'hub.plugin.download')}</Button>
    </li>)}</ul>}
    {!registry.loading && !registry.failed && !visible.length && <p className="agent-settings-hint">{t('hub.plugin.noMatches')}</p>}
  </section>
}
