import { useSettingsDraft } from './settings-draft'
import { useSettingsRead } from './settings-read'
// 语音输入(ASR)配置：选服务商并填密钥，持久化到后端 speech-config.json。
// 密钥只在服务端落盘，不下发到浏览器。
import { useState } from 'react'
import { App as AntApp, Button, Input, Select, Space } from 'antd'
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
  return (
      <Space direction="vertical" size="middle" style={{ width: '100%' }}>
        {draftNotice}
        <Space align="center" wrap>
          <Select
            value={cfg.provider || ''}
            style={{ width: 220 }}
            onChange={(v) => setCfg((c: any) => ({ ...c, provider: v }))}
            options={[
              { value: '', label: t('settings.speechProviderNone') },
              { value: 'openai', label: 'OpenAI' },
              { value: 'volcano', label: 'Volcano Engine' },
            ]}
          />
          <span style={{ color: 'var(--text-dim)', fontSize: 12 }}>{t('settings.speechHelp')}</span>
        </Space>
        {cfg.provider === 'openai' && (
          <Space direction="vertical" size="small" style={{ width: '100%', maxWidth: 520 }}>
            <Input addonBefore={t('settings.speechBaseUrl')} value={cfg.openai.baseURL} onChange={(e) => setOpenAI('baseURL', e.target.value)} />
            <Input.Password addonBefore={t('settings.speechApiKey')} value={cfg.openai.apiKey} onChange={(e) => setOpenAI('apiKey', e.target.value)} />
            <Input addonBefore={t('settings.speechModel')} value={cfg.openai.model} onChange={(e) => setOpenAI('model', e.target.value)} />
            <Input addonBefore={t('settings.speechLanguage')} placeholder={t('common.optional')} value={cfg.openai.language} onChange={(e) => setOpenAI('language', e.target.value)} />
          </Space>
        )}
        {cfg.provider === 'volcano' && (
          <Space direction="vertical" size="small" style={{ width: '100%', maxWidth: 520 }}>
            <Input.Password addonBefore={t('settings.volcanoApiKey')} placeholder={t('settings.volcanoApiKeyHint')} value={cfg.volcano.apiKey} onChange={(e) => setVolc('apiKey', e.target.value)} />
            <span className="tt-hint">{t('settings.volcanoLegacyHint')}</span>
            <Input addonBefore={t('settings.volcanoAppId')} value={cfg.volcano.appId} onChange={(e) => setVolc('appId', e.target.value)} />
            <Input.Password addonBefore={t('settings.volcanoAccessToken')} value={cfg.volcano.accessToken} onChange={(e) => setVolc('accessToken', e.target.value)} />
            <Input addonBefore={t('settings.volcanoResourceId')} value={cfg.volcano.resourceId} onChange={(e) => setVolc('resourceId', e.target.value)} />
            <Input addonBefore={t('settings.volcanoEndpoint')} value={cfg.volcano.endpoint} onChange={(e) => setVolc('endpoint', e.target.value)} />
          </Space>
        )}
        <Button type="primary" loading={saving} onClick={save}>{t('settings.save')}</Button>
      </Space>
  )
}
