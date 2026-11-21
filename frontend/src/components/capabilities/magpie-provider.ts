export type PluginProvider = {
  id: string
  name: string
  signedIn: boolean
  fellBack?: boolean
  usage?: boolean
  checkin?: boolean
  calls?: boolean
  renews?: boolean
  methods: { type: string; label: string; keyless?: boolean; labels?: Record<string, string> }[]
  options: { key: string; label: string; description: string; default: boolean; labels?: Record<string, string> }[]
  models: { id: string; name: string }[]
}

export function pluginCapabilityLabels(provider: PluginProvider) {
  const labels: string[] = []
  if (provider.usage) labels.push('hub.plugin.accountQuota')
  if (provider.checkin) labels.push('hub.plugin.checkIn')
  if (provider.calls) labels.push('hub.plugin.callHistory')
  if (provider.renews) labels.push('hub.plugin.renewsCredentials')
  return labels
}
