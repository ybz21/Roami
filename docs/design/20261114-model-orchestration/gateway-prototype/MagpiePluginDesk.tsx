import { useEffect, useReducer, useRef, useState } from 'react'
import { Button, Input } from 'antd'
import { BackLink } from '../../../../frontend/src/components/BackButton'
import MagpieSourceSettings from '../../../../frontend/src/components/capabilities/MagpieSourceSettings'
import { ChevronRight, SearchIcon } from '../../../../frontend/src/icons'
import { useI18n } from '../../../../frontend/src/i18n'
import { useLayout } from '../../../../frontend/src/layout'
import { addDemoPluginSource, readPluginSources } from './fixture'
import { applyPluginRelease, magpiePlugins, pluginAccounts, pluginRelease, registryURL, rollBackPluginRelease, stagePluginRelease } from './plugin-fixture'
import './magpie-plugin-desk.css'

const hub = '#/catalog/plugins'
const readChannel = ['github', 'china', 'gh-hk'] as const
type Channel = typeof readChannel[number]
const normalized = (value: string) => value.trim().toLowerCase().replace(/^https:\/\/github\.com\/magpie-community\/plugins\/tree\/[^/]+\//, '').replace(/\/$/, '')

type Props = { pluginId?: string; action?: string; itemId?: string; syncSources: () => void }

export function MagpiePluginDesk({ pluginId, action, itemId, syncSources }: Props) {
  const { t, locale } = useI18n()
  const { phone } = useLayout()
  const zh = locale === 'zh-CN'
  const word = (chinese: string, english: string) => zh ? chinese : english
  const [query, setQuery] = useState('')
  const [installedOnly, setInstalledOnly] = useState(false)
  const [channel, setChannel] = useState<Channel>('github')
  const [, refresh] = useReducer(value => value + 1, 0)
  const [receipt, setReceipt] = useState<{ plugin: string; text: string }>()
  const [rollback, setRollback] = useState('')
  const detailTitle = useRef<HTMLHeadingElement>(null)
  const detailScroll = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (pluginId) {
      if (detailScroll.current) detailScroll.current.scrollTop = 0
      detailTitle.current?.focus({ preventScroll: true })
    }
  }, [pluginId, action, itemId])
  const sources = readPluginSources()
  const term = normalized(query)
  const matches = magpiePlugins.filter(row =>
    (!installedOnly || pluginRelease(row.id).active) &&
    [row.name, row.path, ...row.providers.map(provider => provider.name)].some(value => value.toLowerCase().includes(term)))
  const selected = pluginId ? magpiePlugins.find(row => row.id === pluginId) : phone ? undefined : matches[0]
  const state = selected && pluginRelease(selected.id)
  const pluginHref = selected ? hub + '/' + selected.id : hub
  const accounts = sources.filter(row => row.pluginId === selected?.id)
  const activeAccount = action === 'account' ? accounts.find(account => account.sourceId === itemId) : undefined
  const creating = action === 'create' || action === 'add'
  const provider = creating ? selected?.providers.find(row => row.id === itemId) : undefined
  const format = new Intl.DateTimeFormat(locale, { hour: '2-digit', minute: '2-digit', second: '2-digit' })
  const [draft, setDraft] = useState<{ route: string; name: string }>({ route: '', name: '' })
  const formRoute = [pluginId, action, itemId].join('/')
  const accountName = draft.route === formRoute ? draft.name : ''
  const complete = (text: string) => { if(selected) setReceipt({ plugin: selected.id, text }); refresh() }
  const authorization = (account: typeof sources[number]) => account.authorized ? t('hub.plugin.signedIn') : t('hub.plugin.notSignedIn')
  const showDirectory = !phone || !selected
  const showDetails = !!selected && (!phone || !!pluginId)
  const actionLabel = action === 'add' ? word('添加账号', 'Add account') : word('创建模型源', 'Create source')

  return <div className="magpie-desk">
    {showDirectory && <section className="magpie-desk-directory" aria-labelledby="magpie-directory-title">
      <header className="tt-pagehead magpie-desk-head"><BackLink href="#/catalog" /><h2 id="magpie-directory-title">{word('模型源插件', 'Model-source plugins')}</h2></header>
      <div className="magpie-desk-scroll">
        <div className="magpie-directory-tools">
          <Input prefix={<SearchIcon />} aria-label={word('搜索插件或路径', 'Search plugin or path')} placeholder={word('插件名、仓库路径或链接', 'Plugin name, path, or URL')} value={query} onChange={event => setQuery(event.target.value)} allowClear />
          <Button aria-pressed={installedOnly} onClick={() => setInstalledOnly(value => !value)}>{word('仅已安装', 'Installed only')}</Button>
        </div>
        <ul className="magpie-directory-list">
          {matches.map(plugin => {
            const release = pluginRelease(plugin.id)
            const count = sources.filter(row => row.pluginId === plugin.id).length
            const status = !release.active ? word('未安装', 'Available')
              : release.active !== plugin.available ? word('可更新', 'Update available')
                : word('已安装', 'Installed')
            return <li key={plugin.id}><a href={hub + '/' + plugin.id} aria-current={selected?.id === plugin.id ? 'page' : undefined}>
              <span><strong>{plugin.name}</strong><small>{plugin.path}</small></span>
              <span className="magpie-directory-status"><small>{status}</small>{!!count && <small>{word(count + ' 个账号', count + ' accounts')}</small>}</span>
              <ChevronRight />
            </a></li>
          })}
        </ul>
        {!matches.length && <p className="magpie-desk-muted">{word('没有匹配的插件。', 'No matching plugins.')}</p>}
        <div className="magpie-desk-links">
          <a href={registryURL} target="_blank" rel="noreferrer">{word('Magpie 社区目录', 'Magpie registry')}<ChevronRight /></a>
          <a href="#/catalog/import?view=file">{word('从文件导入', 'Import from a file')}<ChevronRight /></a>
        </div>
      </div>
    </section>}
    {showDetails && selected && state && <section className="magpie-desk-detail" aria-labelledby="magpie-detail-title">
      <header className="tt-pagehead magpie-desk-head">
        {(phone || action) && <BackLink href={action ? pluginHref : hub} />}
        <h2 id="magpie-detail-title" ref={detailTitle} tabIndex={-1}>{activeAccount?.name || (creating ? actionLabel : selected.name)}</h2>
        {!action && <a href={'https://github.com/magpie-community/plugins/tree/main/' + selected.path} target="_blank" rel="noreferrer">{word('插件说明', 'Plugin guide')}<ChevronRight /></a>}
      </header>
      <div className="magpie-desk-scroll" ref={detailScroll}>
        {activeAccount ? <>
          <div className="magpie-account-title">
            <strong>{selected.providers.find(row => row.id === activeAccount.providerId)?.name}</strong>
            <span>{word('当前插件版本', 'Active plugin version')} <code>{state.active}</code></span>
          </div>
          <MagpieSourceSettings key={activeAccount.authId} sourceId={activeAccount.authId} onChanged={refresh} />
          {activeAccount.providerId === 'workbuddy' && activeAccount.authorized && <section className="magpie-desk-section">
            <h3>{word('积分与签到', 'Credits and check-in')}</h3>
            <dl className="magpie-version-facts"><div><dt>{word('周期积分', 'Cycle credits')}</dt><dd>{word('已用 120 / 500 · 11 天后重置', '120 / 500 used · resets in 11 days')}</dd></div>
              <div><dt>{word('额外积分', 'Bonus credits')}</dt><dd>{activeAccount.claimed ? 60 : 40}</dd></div></dl>
            <div className="magpie-desk-actions"><Button disabled={activeAccount.claimed} onClick={() => {
              const stored = pluginAccounts.find(row => row.sourceId === activeAccount.sourceId)
              if (stored && !stored.claimed) stored.claimed = true
              refresh()
            }}>{word('立即签到', 'Check in')}</Button>
              <span role="status">{activeAccount.claimed ? word('今日已签 · 领取 20 积分', 'Checked in · 20 credits claimed') : word('今日未签', 'Not checked in today')}</span></div>
          </section>}
          {activeAccount.authorized && <a className="magpie-source-link" href={'#/catalog/source/' + activeAccount.sourceId + '?from=plugins&plugin=' + selected.id}>{word('管理来源模型', 'Manage source models')}<ChevronRight /></a>}
        </> : creating && provider ? <form className="magpie-account-form" onSubmit={event => {
          event.preventDefault()
          if (!state.active) return
          const saved = addDemoPluginSource(selected.id, provider.id, accountName)
          setDraft({ route: '', name: '' })
          syncSources()
          location.hash = pluginHref.slice(1) + '/account/' + saved.sourceId
        }}>
          <dl className="magpie-version-facts"><div><dt>{word('供应商', 'Provider')}</dt><dd>{provider.name}</dd></div><div><dt>{word('当前插件版本', 'Active plugin version')}</dt><dd>{state.active}</dd></div></dl>
          <label className="agent-settings-field">{word('账号名称（选填）', 'Account name (optional)')}
            <Input value={accountName} maxLength={80} onChange={event => setDraft({ route: formRoute, name: event.target.value })} placeholder={provider.name} /></label>
          <Button type="primary" htmlType="submit" disabled={!state.active}>{word('创建并授权', 'Create and authorize')}</Button>
        </form> : <>
          <section className="magpie-desk-section" aria-labelledby="magpie-version-title">
            <h3 id="magpie-version-title">{word('插件版本', 'Plugin versions')}</h3>
            <dl className="magpie-version-facts">
              <div><dt>{word('当前生效', 'Active')}</dt><dd>{state.active || word('未安装', 'Not installed')}</dd></div>
              <div><dt>{word('线上版本', 'Available release')}</dt><dd>{selected.available}</dd></div>
              {state.staged && <div><dt>{word('已下载，待应用', 'Downloaded, ready to apply')}</dt><dd>{state.staged}</dd></div>}
            </dl>
            <div className="magpie-desk-actions">
              <Button onClick={() => {
                state.checkedAt = Date.now()
                complete(state.active === selected.available ? word('当前已是最新版本', 'Version is up to date') : word('发现可用版本 ', 'Release available ') + selected.available)
              }}>{word('检查更新', 'Check for updates')}</Button>
              {state.active !== selected.available && !state.staged && <>
                <label>{word('下载来源', 'Download source')} <select value={channel} onChange={event => setChannel(event.target.value as Channel)}>
                  {readChannel.map(value => <option key={value} value={value}>{t('hub.plugin.channel.' + value)}</option>)}</select></label>
                <Button type="primary" onClick={() => {
                  stagePluginRelease(selected.id)
                  complete(word('安装包已下载并通过演示校验。', 'Package downloaded and verified in the demo.'))
                }}>{state.active ? word('下载更新', 'Download update') : word('下载安装包', 'Download package')}</Button>
              </>}
              {state.staged && <Button type="primary" onClick={() => {
                applyPluginRelease(selected.id)
                complete(word('已应用版本 ', 'Applied release ') + state.active)
              }}>{word('应用版本', 'Apply release')} {state.staged}</Button>}
            </div>
            {receipt?.plugin === selected.id && <p role="status" className="magpie-desk-muted">{receipt.text}{state.checkedAt ? ' · ' + format.format(state.checkedAt) : ''}</p>}
            {state.previous && <details className="magpie-version-history">
              <summary><ChevronRight />{word('版本历史', 'Release history')}</summary>
              <p className="magpie-desk-muted">{word('上次生效版本 ', 'Previously active ') + state.previous}</p>
              {rollback === selected.id ? <div className="magpie-desk-actions">
                <Button onClick={() => setRollback('')}>{t('common.cancel')}</Button>
                <Button type="primary" onClick={() => {
                  rollBackPluginRelease(selected.id)
                  setRollback('')
                  complete(word('已回退到 ', 'Restored ') + state.active)
                }}>{word('确认回退', 'Confirm rollback')}</Button>
              </div> : <Button onClick={() => setRollback(selected.id)}>{word('回退到 ', 'Roll back to ') + state.previous}</Button>}
            </details>}
          </section>

          <section className="magpie-desk-section" aria-labelledby="magpie-provider-title">
            <h3 id="magpie-provider-title">{word('供应商', 'Providers')}</h3>
            <ul className="magpie-provider-list">
              {selected.providers.map(row => {
                const existing = accounts.some(account => account.providerId === row.id)
                return <li key={row.id}><span><strong>{row.name}</strong><small>{row.region[zh ? 0 : 1]}</small></span>
                  {state.active && <a href={pluginHref + '/' + (existing ? 'add' : 'create') + '/' + row.id}>
                    {existing ? word('添加账号', 'Add account') : word('创建模型源', 'Create source')}<ChevronRight />
                  </a>}
                </li>
              })}
            </ul>
            {!state.active && <p className="magpie-desk-muted">{word('应用插件版本后可创建来源。', 'Apply a release to create a source.')}</p>}
          </section>

          {!!accounts.length && <section className="magpie-desk-section" aria-labelledby="magpie-accounts-title">
            <h3 id="magpie-accounts-title">{word('来源账号', 'Source accounts')}</h3>
            <ul className="magpie-directory-list">
              {accounts.map(account => <li key={account.sourceId}><a href={pluginHref + '/account/' + account.sourceId}>
                <span><strong>{account.name}</strong><small>{selected.providers.find(row => row.id === account.providerId)?.name}</small></span>
                <span className="magpie-directory-status"><small>{authorization(account)}</small><small>{word(account.models + ' 个已启用模型', account.models + ' enabled models')}</small></span><ChevronRight />
              </a></li>)}
            </ul>
          </section>}
        </>}
      </div>
    </section>}
    {!selected && !phone && <p className="magpie-desk-no-selection">{word('选择一个插件。', 'Select a plugin.')}</p>}
  </div>
}
