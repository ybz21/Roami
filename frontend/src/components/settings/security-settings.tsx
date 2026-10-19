import { useSettingsRead } from './settings-read'
// 安全：登录口令 / 两步验证 / 自签证书。
// 三块都写在这台机器上（config.yaml 与本机 CA），跟人无关——换台机器就是另一份。
import { useState } from 'react'
import { App as AntApp, Button, Form, Input, Modal, Space, Tag } from 'antd'
import { QRCodeSVG } from 'qrcode.react'
import { api } from '../../api'
import { useI18n } from '../../i18n'

// 修改登录口令：校验旧口令后写回 config.yaml，即时生效，已登录的会话不掉线。
export function ChangePasswordSettings() {
  const { message } = AntApp.useApp()
  const { t } = useI18n()
  const [busy, setBusy] = useState(false)
  const [form] = Form.useForm()
  return (
      <Form form={form} layout="vertical" style={{ maxWidth: 360 }}
        onFinish={async (v) => {
          setBusy(true)
          try {
            await api('POST', '/password', { old: v.old, new: v.new })
            message.success(t('password.changed')); form.resetFields()
          } catch (e: any) {
            message.error(/BAD_PASSWORD/.test(e.message) ? t('password.badOld') : /WEAK_PASSWORD/.test(e.message) ? t('password.weak') : e.message)
          } finally { setBusy(false) }
        }}>
        <Form.Item name="old" label={t('password.old')} rules={[{ required: true, message: t('password.oldRequired') }]}>
          <Input.Password autoComplete="current-password" />
        </Form.Item>
        <Form.Item name="new" label={t('password.new')} rules={[{ required: true, min: 6, message: t('password.weak') }]}>
          <Input.Password autoComplete="new-password" />
        </Form.Item>
        <Form.Item name="confirm" label={t('password.confirm')} dependencies={['new']} rules={[
          { required: true, message: t('password.confirmRequired') },
          ({ getFieldValue }) => ({ validator(_, value) { if (!value || getFieldValue('new') === value) return Promise.resolve(); return Promise.reject(new Error(t('password.mismatch'))) } }),
        ]}>
          <Input.Password autoComplete="new-password" />
        </Form.Item>
        <Button type="primary" htmlType="submit" loading={busy}>{t('password.submit')}</Button>
      </Form>
  )
}

export function TwoFactorSettings() {
  const { message } = AntApp.useApp()
  const { t } = useI18n()
  const [enabled, setEnabled] = useState<boolean | null>(null)
  const [setup, setSetup] = useState<{ uri: string; secret: string } | null>(null) // 开启流程中的待确认密钥
  const [code, setCode] = useState('')
  const [qr, setQr] = useState<{ uri: string; secret: string } | null>(null) // 查看当前二维码
  const [busy, setBusy] = useState(false)
  const [sensitive, setSensitive] = useState<'qr' | 'disable' | null>(null)
  const [credential, setCredential] = useState('')
  const [reauthError, setReauthError] = useState('')

  const refresh = () => api('GET', '/pubconfig').then((r) => setEnabled(!!r?.data?.totp))
  const readState = useSettingsRead(refresh)

  const startSetup = async () => {
    try { const r = await api('GET', '/2fa/gen'); setSetup({ uri: r.data.uri, secret: r.data.secret }); setCode(''); setQr(null) }
    catch (e: any) { message.error(e.message) }
  }
  const confirmEnable = async () => {
    if (!setup) return
    setBusy(true)
    try { await api('POST', '/2fa/enable', { secret: setup.secret, code: code.trim() }); message.success(t('twoFactor.enabled')); setSetup(null); setEnabled(true) }
    catch (e: any) { message.error(/BAD_CODE/.test(e.message) ? t('twoFactor.badCode') : e.message) }
    finally { setBusy(false) }
  }
  const authenticate = async () => {
    if (!sensitive || busy || !credential) return
    setBusy(true); setReauthError('')
    try {
      const r = await api('POST', sensitive === 'qr' ? '/2fa/qr' : '/2fa/disable', { password: credential, code: credential })
      if (sensitive === 'qr' && r.data?.enabled) setQr({ uri: r.data.uri, secret: r.data.secret })
      else { message.success(t('twoFactor.disabled')); setQr(null); setEnabled(false) }
      setSensitive(null); setCredential('')
    } catch { setReauthError(t('twoFactor.reauthFailed')) }
    finally { setBusy(false) }
  }
  const requestSensitive = (action: 'qr' | 'disable') => { setQr(null); setCredential(''); setReauthError(''); setSensitive(action) }
  const copy = async (s: string) => {
    try {
      if (!navigator.clipboard?.writeText) throw new Error('CLIPBOARD_UNAVAILABLE')
      await navigator.clipboard.writeText(s)
      message.success(t('common.copied'))
    } catch { message.error(t('twoFactor.copyFailed')) }
  }

  if (readState) return readState
  return (
    <>
      <Modal open={!!sensitive} title={t(sensitive === 'disable' ? 'twoFactor.disableConfirm' : 'twoFactor.showQr')} confirmLoading={busy} okButtonProps={{ disabled: !credential, danger: sensitive === 'disable' }} onOk={authenticate} onCancel={() => { if (!busy) { setSensitive(null); setCredential('') } }}>
        <p>{t('twoFactor.reauthHint')}</p>
        <Input.Password autoComplete="current-password" aria-label={t('twoFactor.reauthHint')} value={credential} onChange={e => setCredential(e.target.value)} onPressEnter={authenticate} />
        {reauthError && <p role="alert">{reauthError}</p>}
      </Modal>
      <Tag color={enabled ? 'green' : 'default'} style={{ marginBottom: 'var(--sp-2)' }}>
        {enabled === null ? '…' : enabled ? t('twoFactor.on') : t('twoFactor.off')}
      </Tag>
      <Space direction="vertical" size="middle" style={{ width: '100%' }}>
        <span style={{ color: 'var(--text-dim)', fontSize: 'var(--fs-sm)' }}>
          {t('twoFactor.helpPrefix')}<code>TTMUX_WEB_TOTP_SECRET</code>{t('twoFactor.helpSuffix')}
        </span>

        {!setup && (
          <Space>
            {enabled
              ? <>
                  <Button disabled={busy} onClick={() => requestSensitive('qr')}>{t('twoFactor.showQr')}</Button>
                  <Button danger disabled={busy} onClick={() => requestSensitive('disable')}>{t('twoFactor.disable')}</Button>
                </>
              : <Button type="primary" onClick={startSetup}>{t('twoFactor.enable')}</Button>}
          </Space>
        )}

        {/* 开启流程：扫码 → 输码确认 */}
        {setup && (
          <div style={{ padding: 16, background: 'var(--bg-base)', borderRadius: 'var(--r-sm)' }}>
            <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap', alignItems: 'flex-start' }}>
              <div style={{ background: '#fff', padding: 10, borderRadius: 'var(--r-sm)' }}><QRCodeSVG value={setup.uri} size={168} /></div>
              <div style={{ flex: 1, minWidth: 240 }}>
                <div style={{ color: 'var(--text-dim)', fontSize: 12, marginBottom: 4 }}>{t('twoFactor.scanStep')}</div>
                <Space.Compact style={{ width: '100%', marginBottom: 10 }}>
                  <Input readOnly value={setup.secret} />
                  <Button onClick={() => copy(setup.secret)}>{t('common.copy')}</Button>
                </Space.Compact>
                <div style={{ color: 'var(--text-dim)', fontSize: 12, marginBottom: 4 }}>{t('twoFactor.codeStep')}</div>
                <Space.Compact style={{ width: '100%' }}>
                  <Input value={code} onChange={(e) => setCode(e.target.value)} placeholder={t('twoFactor.codePlaceholder')} inputMode="numeric" maxLength={6} onPressEnter={confirmEnable} />
                  <Button type="primary" loading={busy} onClick={confirmEnable}>{t('twoFactor.confirmEnable')}</Button>
                </Space.Compact>
              </div>
            </div>
            <div style={{ marginTop: 10 }}><Button size="small" onClick={() => setSetup(null)}>{t('common.cancel')}</Button></div>
          </div>
        )}

        {/* 查看当前二维码（已开启时给新设备加） */}
        {qr && (
          <div style={{ padding: 16, background: 'var(--bg-base)', borderRadius: 'var(--r-sm)', display: 'flex', gap: 16, flexWrap: 'wrap', alignItems: 'center' }}>
            <div style={{ background: '#fff', padding: 10, borderRadius: 'var(--r-sm)' }}><QRCodeSVG value={qr.uri} size={168} /></div>
            <div style={{ flex: 1, minWidth: 240 }}>
              <div style={{ color: 'var(--text-dim)', fontSize: 12, marginBottom: 4 }}>{t('twoFactor.addDevice')}</div><Button onClick={() => setQr(null)}>{t('common.close')}</Button>
              <Space.Compact style={{ width: '100%' }}><Input readOnly value={qr.secret} /><Button onClick={() => copy(qr.secret)}>{t('common.copy')}</Button></Space.Compact>
            </div>
          </div>
        )}
      </Space>
    </>
  )
}

// 自签 HTTPS 下安卓 Chrome 把站点判为不安全 → 不给「安装应用」、无法全屏 PWA。
// 装成「受信任凭据」后即是安全上下文，才能装 PWA、用麦克风与剪贴板。
export function CertDownloadButton() {
  const { t } = useI18n()
  const [open, setOpen] = useState(false)
  const isHttps = typeof location !== 'undefined' && location.protocol === 'https:'
  const steps = [
    t('install.certStep1'),
    t('install.certStep2'),
    t('install.certStep3'),
    t('install.certStep4'),
  ]
  return (
    <>
      <Button onClick={() => setOpen(true)}>{t('install.downloadCert')}</Button>
      <Modal open={open} onCancel={() => setOpen(false)} title={t('install.certModalTitle')}
        footer={[
          <Button key="c" onClick={() => setOpen(false)}>{t('common.cancel')}</Button>,
          <Button key="d" type="primary" href="/cert.crt" download="ttmux-ca.crt" onClick={() => { /* 浏览器直接下载 */ }}>{t('install.downloadCert')}</Button>,
        ]}>
        <div style={{ color: 'var(--text-dim)', fontSize: 13, lineHeight: 1.7 }}>
          <p style={{ marginTop: 0 }}>{t('install.certWhy')}</p>
          <ol style={{ paddingLeft: 20, margin: '8px 0' }}>
            {steps.map((s, i) => <li key={i} style={{ marginBottom: 4 }}>{s}</li>)}
          </ol>
          {!isHttps && <p style={{ color: 'var(--warn)' }}>{t('install.certHttpNote')}</p>}
          <p style={{ marginBottom: 0, color: 'var(--text-dimmer)' }}>{t('install.certIosNote')}</p>
        </div>
      </Modal>
    </>
  )
}
