import BackButton from '../BackButton'
import { useState, type ReactNode } from 'react'
import { Alert, Button, Checkbox, Form, Segmented, Select } from 'antd'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { useI18n } from '../../i18n'
import { ChevronRight, CodeIcon, FileTextIcon, GithubIcon, OpenInIcon } from '../../icons'
import type { ManagedEntry } from './capability-format'
import { skillDocument, skillFileText } from './skill-document'

export default function SkillMarketDetail({ entry, images = {}, marketUrl, repository, installs, phone, busy, targets, onTargets, installError, canInstall, onInstall, onBack, variant }: {
  entry: ManagedEntry; images?: Record<string, string>; marketUrl?: string; repository: string; installs?: string; phone: boolean; busy: boolean
  targets: string[]; onTargets: (values: string[]) => void; installError: string; canInstall: boolean
  onInstall: () => void; onBack: () => void; variant?: ReactNode
}) {
  const { t } = useI18n()
  const [tab, setTab] = useState('overview')
  const [file, setFile] = useState('SKILL.md')
  const { body, summary } = skillDocument(entry.text || '', entry.description)
  const files = ['SKILL.md', ...Object.keys(entry.files || {}).filter(name => name !== 'SKILL.md').sort()]
  const fileText = file === 'SKILL.md' ? entry.text || '' : skillFileText(entry.files?.[file] || '')
  const installButton = <Button type="primary" loading={busy} disabled={!canInstall || !targets.length} onClick={onInstall}>{t('capabilities.market.install')}</Button>
  const installChoices = <>
    <Checkbox.Group className="tt-market-targets" value={targets} disabled={busy} onChange={onTargets} options={['local', 'claude', 'opencode', 'roami'].map(value => ({ value, label: t('capabilities.market.target.' + value) }))} />
    <p className="tt-skill-note">{t('capabilities.market.installHint')}</p>
  </>
  const sourceLinks = <div className="tt-skill-links">
    {marketUrl && <a href={marketUrl} target="_blank" rel="noreferrer"><OpenInIcon size={16} />{t('capabilities.market.marketPage')}</a>}
    {entry.origin?.url && <a href={entry.origin.url} target="_blank" rel="noreferrer"><GithubIcon size={16} />{t('capabilities.market.repository')}</a>}
  </div>
  // Relative paths refer to the bundle, not to the Roami server's filesystem.
  const fileLink = (href: string) => {
    if (/^(?:[a-z][a-z\d+.-]*:|\/\/|#|\/)/i.test(href)) return null
    try {
      const url = new URL(href, 'https://bundle.invalid/')
      const path = decodeURIComponent(url.pathname.slice(1))
      return files.includes(path) ? path : null
    } catch { return null }
  }
  return <div className="tt-skill-detail">
    {!phone && <header className="tt-skill-return"><BackButton label={t('capabilities.market.backResults')} disabled={busy} onClick={onBack} autoFocus /><strong>{t('capabilities.market.details')}</strong></header>}
    <div className="tt-skill-scroll">
      <header className="tt-pagehead tt-skill-hero"><div className="ttl"><div className="tt-skill-identity"><span>{repository}</span>{installs && <span>{installs}</span>}</div><h2>{entry.displayName || entry.name}</h2>{summary && <p>{summary}</p>}</div></header>
      <div className="tt-skill-columns">
        <main className="tt-skill-content">
          <Segmented className="tt-skill-tabs" aria-label={t('capabilities.market.content')} value={tab} onChange={setTab} options={[{ value: 'overview', label: t('capabilities.market.overview'), icon: <FileTextIcon size={16} /> }, { value: 'files', label: t('capabilities.market.files', { count: files.length }), icon: <CodeIcon size={16} /> }]} />
          {tab === 'overview' ? <article className="tt-skill-document"><ReactMarkdown remarkPlugins={[remarkGfm]} components={{
            a: ({ children, href }) => {
              const path = href ? fileLink(href) : null
              return path ? <button type="button" className="tt-skill-file-link" onClick={() => { setFile(path); setTab('files') }}>{children}</button> : <a href={href && /^(?:https?:|mailto:|#)/i.test(href) ? href : entry.origin?.url} target="_blank" rel="noreferrer">{children}</a>
            },
            img: ({ src, alt }) => {
              const path = src ? fileLink(src) : null
              const extension = path?.split('.').pop()?.toLowerCase()
              const mime = extension && ({ png: 'image/png', jpg: 'image/jpeg', jpeg: 'image/jpeg', gif: 'image/gif', webp: 'image/webp' } as Record<string, string>)[extension]
              const illustration = src && /^data:image\/(?:png|jpeg|gif|webp);base64,/.test(images[src] || '') ? images[src] : null
              const url = illustration || (path && mime ? `data:${mime};base64,${entry.files?.[path]}` : src && /^https?:\/\//i.test(src) ? src : null)
              return url ? <img src={url} alt={alt} loading="lazy" /> : <span>{alt}</span>
            },
          }}>{body}</ReactMarkdown></article> : <div className="tt-skill-files">
            <Form.Item label={t('capabilities.market.file')}><Select popupClassName="tt-capability-select-popup" aria-label={t('capabilities.market.file')} value={file} onChange={setFile} options={files.map(value => ({ value, label: value }))} /></Form.Item>
            {fileText === null ? <p className="tt-skill-note">{t('capabilities.market.binaryFile')}</p> : <pre aria-label={file}>{fileText}</pre>}
          </div>}
        </main>
        <aside className="tt-skill-sidebar">
          {variant}
          {phone ? <details className="tt-skill-target-picker"><summary><ChevronRight size={16} /><span>{t('capabilities.market.installAndSource')}</span><span className="tt-skill-note">{t('capabilities.market.selectedTargets', { count: targets.length })}</span></summary>{installChoices}{sourceLinks}</details> : <section className="tt-skill-install"><h3>{t('capabilities.market.installTargets')}</h3>{installChoices}{installButton}</section>}
          {!phone && sourceLinks}
          {installError && !phone && <Alert type="error" message={installError} />}
        </aside>
      </div>
    </div>
    {phone && <footer className="tt-skill-mobile-install">{installError && <Alert type="error" message={installError} />}<span>{t('capabilities.market.selectedTargets', { count: targets.length })}</span>{installButton}</footer>}
  </div>
}
