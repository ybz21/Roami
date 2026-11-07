import { useSettingsDraft } from './settings-draft'
import { useSettingsRead } from './settings-read'
import { useState } from 'react'
import { App as AntApp, Button, Input, Select } from 'antd'
import { api } from '../../api'
import { useI18n } from '../../i18n'

const SPEECH_DEFAULTS = {
  openai: { baseURL: 'https://api.openai.com/v1', model: 'whisper-1' },
  volcano: { resourceId: 'volc.bigasr.auc', endpoint: 'https://openspeech.bytedance.com/api/v3/auc/bigmodel/submit' },
}
function normalizeSpeech(d: any) {
  const c = d || {}
  return {
    provider: c.provider || '',
    openai: {
      baseURL: c.openai?.baseURL || SPEECH_DEFAULTS.openai.baseURL,
      apiKey: c.openai?.apiKey || '',
      model: c.openai?.model || SPEECH_DEFAULTS.openai.model,
      language: c.openai?.language || '',
    },
    volcano: {
      apiKey: c.volcano?.apiKey || '',
      appId: c.volcano?.appId || '',
      accessToken: c.volcano?.accessToken || '',
      resourceId: c.volcano?.resourceId || SPEECH_DEFAULTS.volcano.resourceId,
      endpoint: c.volcano?.endpoint || SPEECH_DEFAULTS.volcano.endpoint,
    },
  }
}
export function SpeechSettings() {
  const { message } = AntApp.useApp()
  const { t } = useI18n()
  const [cfg, setCfg] = useState<any>(() => normalizeSpeech(null))
  const [saving, setSaving] = useState(false)
  const [baseline, setBaseline] = useState(cfg)
  const readState = useSettingsRead(() => api('GET', '/speech/config').then((r) => { const next = normalizeSpeech(r?.data); setCfg(next); setBaseline(next) }))
  const draftNotice = useSettingsDraft('speech', cfg, baseline, setCfg, !readState)
  const setOpenAI = (k: string, v: string) => setCfg((c: any) => ({ ...c, openai: { ...c.openai, [k]: v } }))
  const setVolc = (k: string, v: string) => setCfg((c: any) => ({ ...c, volcano: { ...c.volcano, [k]: v } }))
  const save = async () => {
    setSaving(true)
    try { await api('PUT', '/speech/config', cfg); setBaseline(cfg); message.success(t('settings.speechSaved')) }
    catch (e: any) { message.error(e.message) }
    finally { setSaving(false) }
  }
  if (readState) return readState
  return <form className="agent-settings-form" onSubmit={event => { event.preventDefault(); void save() }}>
    {draftNotice}
    <p className="agent-settings-hint">{t('hub.speechHint')}</p>
    <label className="agent-settings-field">{t('settings.speechProvider')}
      <Select virtual={false} classNames={{ popup: { root: 'tt-capability-select-popup' } }} aria-label={t('settings.speechProvider')} value={cfg.provider} disabled={saving}
        options={[
          { value: '', label: t('settings.speechProviderNone') },
          { value: 'openai', label: 'OpenAI' },
          { value: 'volcano', label: 'Volcano Engine' },
        ]} onChange={provider => setCfg((c: any) => ({ ...c, provider }))} />
    </label>
    {cfg.provider === 'openai' && <>
      <label className="agent-settings-field">{t('settings.speechBaseUrl')}<Input aria-label={t('settings.speechBaseUrl')} disabled={saving} value={cfg.openai.baseURL} onChange={e => setOpenAI('baseURL', e.target.value)} /></label>
      <label className="agent-settings-field">{t('settings.speechApiKey')}<Input.Password aria-label={t('settings.speechApiKey')} disabled={saving} autoComplete="new-password" value={cfg.openai.apiKey} onChange={e => setOpenAI('apiKey', e.target.value)} /></label>
      <label className="agent-settings-field">{t('settings.speechModel')}<Input aria-label={t('settings.speechModel')} disabled={saving} value={cfg.openai.model} onChange={e => setOpenAI('model', e.target.value)} /></label>
      <label className="agent-settings-field">{t('settings.speechLanguage')}<Input aria-label={t('settings.speechLanguage')} disabled={saving} placeholder={t('common.optional')} value={cfg.openai.language} onChange={e => setOpenAI('language', e.target.value)} /></label>
    </>}
    {cfg.provider === 'volcano' && <>
      <label className="agent-settings-field">{t('settings.volcanoApiKey')}<Input.Password aria-label={t('settings.volcanoApiKey')} disabled={saving} autoComplete="new-password" placeholder={t('settings.volcanoApiKeyHint')} value={cfg.volcano.apiKey} onChange={e => setVolc('apiKey', e.target.value)} /></label>
      <p className="agent-settings-hint">{t('settings.volcanoLegacyHint')}</p>
      <label className="agent-settings-field">{t('settings.volcanoAppId')}<Input aria-label={t('settings.volcanoAppId')} disabled={saving} value={cfg.volcano.appId} onChange={e => setVolc('appId', e.target.value)} /></label>
      <label className="agent-settings-field">{t('settings.volcanoAccessToken')}<Input.Password aria-label={t('settings.volcanoAccessToken')} disabled={saving} autoComplete="new-password" value={cfg.volcano.accessToken} onChange={e => setVolc('accessToken', e.target.value)} /></label>
      <label className="agent-settings-field">{t('settings.volcanoResourceId')}<Input aria-label={t('settings.volcanoResourceId')} disabled={saving} value={cfg.volcano.resourceId} onChange={e => setVolc('resourceId', e.target.value)} /></label>
      <label className="agent-settings-field">{t('settings.volcanoEndpoint')}<Input aria-label={t('settings.volcanoEndpoint')} disabled={saving} value={cfg.volcano.endpoint} onChange={e => setVolc('endpoint', e.target.value)} /></label>
    </>}
    <div className="agent-settings-save"><Button type="primary" htmlType="submit" loading={saving}>{t('settings.save')}</Button></div>
  </form>
}
