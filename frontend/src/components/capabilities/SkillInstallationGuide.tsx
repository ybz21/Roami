import { useState } from 'react'
import { Alert, Button, Segmented } from 'antd'
import { useI18n } from '../../i18n'
import { CheckIcon, CopyIcon, ChevronRight } from '../../icons'

export default function SkillInstallationGuide({ identifier, phone }: { identifier: string; phone: boolean }) {
  const { t } = useI18n()
  const [mode, setMode] = useState('command')
  const [copied, setCopied] = useState(false)
  const [failed, setFailed] = useState(false)
  if (!/^[\w.-]+\/[\w.-]+\/[\w.:-]+$/.test(identifier)) return null
  const [owner, repository, skill] = identifier.split('/')
  const command = `npx skills add https://github.com/${owner}/${repository} --skill ${skill}`
  const text = mode === 'command' ? command : t('capabilities.market.installPrompt', { name: skill, url: 'https://skills.sh/' + identifier })
  const copy = async () => {
    setFailed(false)
    try {
      if (navigator.clipboard?.writeText) await navigator.clipboard.writeText(text)
      else {
        const input = document.createElement('textarea')
        input.value = text; input.style.position = 'fixed'; input.style.opacity = '0'
        document.body.appendChild(input)
        try { input.select(); if (!document.execCommand('copy')) throw new Error('Copy failed') } finally { input.remove() }
      }
      setCopied(true)
    } catch { setFailed(true); setCopied(false) }
  }
  const guide = <section className="tt-skill-guide" aria-label={t('capabilities.market.installGuide')}>
    <div className="tt-skill-guide-head"><h3>{t('capabilities.market.installGuide')}</h3><Segmented aria-label={t('capabilities.market.installMethod')} value={mode} onChange={value => { setMode(value); setCopied(false); setFailed(false) }} options={[{ value: 'command', label: t('capabilities.market.command') }, { value: 'prompt', label: t('capabilities.market.prompt') }]} /></div>
    <div className="tt-skill-guide-copy"><pre>{text}</pre><Button icon={copied ? <CheckIcon size={16} /> : <CopyIcon size={16} />} onClick={() => { void copy() }}>{t(copied ? 'common.copied' : 'common.copy')}</Button></div>
    {failed && <Alert type="error" message={t('capabilities.market.copyFailed')} />}
    <p className="tt-skill-note">{t('capabilities.market.commandHint')}</p>
  </section>
  return phone ? <details className="tt-skill-guide-disclosure"><summary><ChevronRight size={16} />{t('capabilities.market.installGuide')}</summary>{guide}</details> : guide
}
