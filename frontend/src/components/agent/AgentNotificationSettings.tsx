import { useEffect, useRef, useState } from 'react'
import { Button, Input, InputNumber, Spin, Switch } from 'antd'
import { api } from '../../api'
import { useI18n } from '../../i18n'

type Category = 'task_result' | 'decision' | 'reminder' | 'suggestion'
type Settings = { timezone: string; enabled: Record<Category, boolean>; quietHours: { start: string; end: string } | null; attentionBypassesQuiet: boolean; hidePreview: boolean; maxSuggestionsPerHour: number }
const categories: Category[] = ['task_result', 'decision', 'reminder', 'suggestion']

export default function AgentNotificationSettings() {
  const { t } = useI18n()
  const [settings, setSettings] = useState<Settings | null>(null), [failed, setFailed] = useState(false), [saving, setSaving] = useState(false), [saved, setSaved] = useState(false)
  const [version, setVersion] = useState(0)
  const alive = useRef(true), savingRef = useRef(false)
  useEffect(() => { alive.current = true; return () => { alive.current = false } }, [])
  useEffect(() => {
    let cancelled = false
    const abort = new AbortController(), timer = setTimeout(() => abort.abort(), 10000)
    void api('GET', '/agent/notification-preferences', undefined, { signal: abort.signal })
      .then((result) => { if (!cancelled) { setSettings(result.data); setFailed(false) } })
      .catch(() => { if (!cancelled) setFailed(true) })
      .finally(() => clearTimeout(timer))
    return () => { cancelled = true; clearTimeout(timer); abort.abort() }
  }, [version])
  const change = (patch: Partial<Settings>) => { setSettings((value) => value ? { ...value, ...patch } : value); setSaved(false) }
  const save = async () => {
    if (!settings || savingRef.current) return
    savingRef.current = true; setSaving(true); setSaved(false); setFailed(false)
    try { await api('PUT', '/agent/notification-preferences', { settings }); if (alive.current) setSaved(true) }
    catch { if (alive.current) setFailed(true) }
    finally { savingRef.current = false; if (alive.current) setSaving(false) }
  }
  return <div className="agent-notifications-body agent-notification-settings">
    <p className="agent-muted">{t('agent.notification.settingsHint')}</p>
    {!settings && !failed && <Spin />}
    {failed && <p role="alert">{t('agent.notification.settingsFailed')}<button type="button" className="tt-act" onClick={() => setVersion((value) => value + 1)}>{t('agent.retry')}</button></p>}
    {settings && <fieldset disabled={saving}>
      {categories.map((category) => <div className="agent-notification-toggle" key={category}><label htmlFor={'agent-notification-' + category}>{t('agent.notification.category.' + category)}</label><Switch id={'agent-notification-' + category} aria-label={t('agent.notification.category.' + category)} checked={settings.enabled[category]} onChange={(checked) => change({ enabled: { ...settings.enabled, [category]: checked } })} /></div>)}
      <label className="agent-field">{t('agent.notification.timezone')}<Input value={settings.timezone} maxLength={100} onChange={(event) => change({ timezone: event.target.value })} aria-label={t('agent.notification.timezone')} /></label>
      <div className="agent-notification-toggle"><label htmlFor="agent-notification-quiet">{t('agent.notification.quiet')}</label><Switch id="agent-notification-quiet" aria-label={t('agent.notification.quiet')} checked={!!settings.quietHours} onChange={(checked) => change({ quietHours: checked ? { start: '22:00', end: '08:00' } : null })} /></div>
      {settings.quietHours && <div className="agent-notification-times"><label className="agent-field">{t('agent.notification.quietStart')}<Input type="time" value={settings.quietHours.start} onChange={(event) => change({ quietHours: { ...settings.quietHours!, start: event.target.value } })} aria-label={t('agent.notification.quietStart')} /></label><label className="agent-field">{t('agent.notification.quietEnd')}<Input type="time" value={settings.quietHours.end} onChange={(event) => change({ quietHours: { ...settings.quietHours!, end: event.target.value } })} aria-label={t('agent.notification.quietEnd')} /></label></div>}
      <div className="agent-notification-toggle"><label htmlFor="agent-notification-attention">{t('agent.notification.attentionBypass')}</label><Switch id="agent-notification-attention" aria-label={t('agent.notification.attentionBypass')} checked={settings.attentionBypassesQuiet} onChange={(checked) => change({ attentionBypassesQuiet: checked })} /></div>
      <div className="agent-notification-toggle"><label htmlFor="agent-notification-preview">{t('agent.notification.hidePreview')}</label><Switch id="agent-notification-preview" aria-label={t('agent.notification.hidePreview')} checked={settings.hidePreview} onChange={(checked) => change({ hidePreview: checked })} /></div>
      <label className="agent-field">{t('agent.notification.suggestionLimit')}<InputNumber min={1} max={24} precision={0} value={settings.maxSuggestionsPerHour} onChange={(value) => change({ maxSuggestionsPerHour: value ?? 1 })} aria-label={t('agent.notification.suggestionLimit')} /></label>
      <Button onClick={() => { void save() }} loading={saving} disabled={!settings.timezone.trim() || (!!settings.quietHours && (!settings.quietHours.start || !settings.quietHours.end || settings.quietHours.start === settings.quietHours.end))}>{t('agent.save')}</Button>
      {saved && <p role="status">{t('agent.notification.settingsSaved')}</p>}
    </fieldset>}
  </div>
}
