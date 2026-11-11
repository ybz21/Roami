import { useEffect, useRef, useState } from 'react'
import { Alert, Button, Select, Spin } from 'antd'
import { api } from '../../api'
import { nodeApi } from '../cluster/node-url'
import { useI18n } from '../../i18n'
import { useLayout } from '../../layout'
import { catalogFailure } from './model-hub-api'

export type PluginProvider = { id: string; name: string; signedIn: boolean; fellBack?: boolean; methods: { type: string; label: string; keyless?: boolean; labels?: Record<string, string> }[]; options: { key: string; label: string; description: string; default: boolean; labels?: Record<string, string> }[]; models: { id: string; name: string }[] }
type Package = { id: string; name: string; version: string }
type InspectedPackage = { pkg: Package; providers?: PluginProvider[]; error?: string }
export const pluginFailure = (cause: any) => {
  const code = cause?.apiError?.code || cause?.message
  return ({ INVALID_MODEL_PLUGIN_PACKAGE: 'hub.plugin.invalid', MODEL_PLUGIN_DESKTOP_UNAVAILABLE: 'hub.plugin.desktopUnavailable', MODEL_PLUGIN_DESKTOP_APP_MISSING: 'hub.plugin.desktopMissing', MODEL_PLUGIN_DESKTOP_PACKAGE_UNTRUSTED: 'hub.plugin.desktopPackageUntrusted', MODEL_PLUGIN_BUN_UNAVAILABLE: 'hub.plugin.bunUnavailable', MODEL_PLUGIN_SANDBOX_UNAVAILABLE: 'hub.plugin.sandboxUnavailable', MODEL_PLUGIN_MODELS_REQUIRED: 'hub.plugin.refreshRequired', MODEL_PLUGIN_BUSY: 'hub.plugin.busy', MODEL_PLUGIN_FAILED: 'hub.plugin.failed' } as Record<string, string>)[code] || catalogFailure(cause)
}
export default function MagpiePluginImport({ revision, onImported, onRetry }: { revision: string; onImported: () => void; onRetry?: () => void }) {
  const { t } = useI18n(), layout = useLayout()
  const folder = useRef<HTMLInputElement>(null), zip = useRef<HTMLInputElement>(null)
  const [packages, setPackages] = useState<Package[]>([]), [selected, setSelected] = useState(''), [batch, setBatch] = useState<string[]>([]), [inspected, setInspected] = useState<InspectedPackage[]>([]), [skipped, setSkipped] = useState<string[]>([]), [scanning, setScanning] = useState(false)
  const [busy, setBusy] = useState(false), [error, setError] = useState(''), [version, setVersion] = useState(0)
  useEffect(() => {
    const abort = new AbortController()
    void api('GET', '/agent/model-gateway/plugins/packages', undefined, { signal: abort.signal }).then(({ data }) => { if (!abort.signal.aborted) setPackages(previous => [...new Map<string, Package>([...data, ...previous].map((row: Package) => [row.id, row])).values()]) }).catch(cause => { if (!abort.signal.aborted) setError(pluginFailure(cause)) })
    return () => abort.abort()
  }, [version])
  const inspectionKey = packages.filter(pkg => selected === '*' ? batch.includes(pkg.id) : pkg.id === selected).map(pkg => pkg.id).sort().join(',')
  useEffect(() => {
    if (!selected) return
    const targets = packages.filter(pkg => selected === '*' ? batch.includes(pkg.id) : pkg.id === selected)
    if (!targets.length) return
    const abort = new AbortController(); setInspected(targets.map(pkg => ({ pkg }))); setError(''); setScanning(true)
    void (async () => {
      for (const pkg of targets) {
        try {
          const { data } = await api('POST', '/agent/model-gateway/plugins/inspect', { packageId: pkg.id }, { signal: abort.signal })
          if (abort.signal.aborted) return
          setInspected(previous => previous.map(row => row.pkg.id === pkg.id ? { pkg, providers: data } : row))
        } catch (cause) {
          if (abort.signal.aborted) return
          setInspected(previous => previous.map(row => row.pkg.id === pkg.id ? { pkg, error: pluginFailure(cause) } : row))
        }
      }
      if (!abort.signal.aborted) setScanning(false)
    })()
    return () => abort.abort()
  }, [selected, version, inspectionKey])
  const upload = async (files: FileList | null, isFolder: boolean) => {
    if (!files?.length || busy) return
    const list = Array.from(files).filter(file => !isFolder || !file.webkitRelativePath.split('/').some(part => part === '.git' || part === 'node_modules' || part === '.env' || part.startsWith('.env.')))
    if (!list.length) { setError('hub.plugin.invalid'); return }
    if (list.length > 2048 || list.reduce((sum, file) => sum + file.size, 0) > (isFolder ? 64 : 32) * 1024 * 1024) { setError('hub.plugin.invalid'); return }
    setBusy(true); setError('')
    const form = new FormData()
    list.forEach(file => { form.append('files', file); form.append('paths', isFolder ? file.webkitRelativePath : '') })
    try {
      const response = await fetch(nodeApi('/agent/model-gateway/plugins/import'), { method: 'POST', body: form })
      const result = await response.json()
      if (!response.ok) throw { apiError: result.error }
      const imported = (result.data.packages || [result.data]) as Package[]
      setSkipped(result.data.skipped || []); setBatch(imported.map(pkg => pkg.id))
      setPackages(previous => [...new Map([...previous, ...imported].map(pkg => [pkg.id, pkg])).values()]); setSelected(imported.length > 1 ? '*' : imported[0].id); setVersion(previous => previous + 1)
    } catch (cause) { setError(pluginFailure(cause)) }
    finally { setBusy(false); if (folder.current) folder.current.value = ''; if (zip.current) zip.current.value = '' }
  }
  const add = async (packageId: string, provider: PluginProvider) => {
    setBusy(true); setError('')
    try { await api('POST', '/agent/model-gateway/plugins/sources', { packageId, providerId: provider.id, revision }); onImported() }
    catch (cause) { setError(pluginFailure(cause)) }
    finally { setBusy(false) }
  }
  return <section className="tt-model-hub-scroll tt-model-plugin-import">
    <p className="agent-settings-hint">{t('hub.plugin.importHint')}</p>
    <div className="tt-model-hub-actions"><Button disabled={busy} onClick={() => folder.current?.click()}>{t('hub.plugin.folder')}</Button><Button disabled={busy} loading={busy} onClick={() => zip.current?.click()}>{t('hub.plugin.zip')}</Button></div>
    <input hidden ref={folder} type="file" multiple {...{ webkitdirectory: '' }} onChange={event => void upload(event.target.files, true)} />
    <input hidden ref={zip} type="file" accept=".zip,application/zip" onChange={event => void upload(event.target.files, false)} />
    {layout.phone && <p className="agent-settings-hint">{t('hub.plugin.phoneZIP')}</p>}
    {packages.length > 0 && <label className="agent-settings-field">{t('hub.plugin.package')}<Select classNames={{ popup: { root: 'tt-capability-select-popup' } }} aria-label={t('hub.plugin.package')} virtual={false} disabled={busy} value={selected || undefined} options={[...(batch.length > 1 ? [{ value: '*', label: t('hub.plugin.importedBatch', { count: batch.length }) }] : []), ...packages.map(row => ({ value: row.id, label: row.name + (row.version ? ' · ' + row.version : '') }))]} onChange={setSelected} /></label>}
    {error && <Alert type="error" role="alert" message={t(error)} action={<Button disabled={busy} onClick={() => { setVersion(previous => previous + 1); onRetry?.() }}>{t('capabilities.models.reread')}</Button>} />}
    {!!skipped.length && <details><summary>{t('hub.plugin.skipped', { count: skipped.length })}</summary><ul>{skipped.map(name => <li key={name}>{name}</li>)}</ul></details>}
    {scanning && <Spin />}
    {inspected.map(row => <section className="tt-model-plugin-package" key={row.pkg.id} aria-label={row.pkg.name}>
      {inspected.length > 1 && <h3>{row.pkg.name}</h3>}
      {row.error && <Alert type="error" role="alert" message={t(row.error)} action={<Button disabled={busy || scanning} onClick={() => { setSelected(row.pkg.id); setVersion(previous => previous + 1) }}>{t('capabilities.models.reread')}</Button>} />}
      {row.providers?.map(provider => <article className="tt-model-hub-row" key={provider.id}><div><strong>{provider.name}</strong><small>{provider.id}</small></div><Button type="primary" disabled={busy} onClick={() => void add(row.pkg.id, provider)}>{t('hub.plugin.addSource')}</Button></article>)}
      {row.providers?.length === 0 && <p>{t('hub.plugin.noProviders')}</p>}
    </section>)}
  </section>
}
