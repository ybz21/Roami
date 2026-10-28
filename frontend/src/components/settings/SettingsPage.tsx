// 分类共享同一份清单；页头固定，内容在页内滚动。
import { useEffect, useMemo, useRef, useState } from 'react'
import { App as AntApp, Button } from 'antd'
import { ChevronRight, CloseIcon, SearchIcon } from '../../icons'
import { useI18n } from '../../i18n'
import { useLayout } from '../../layout'
import { usePreferences, saveWorkspace, getPreferences, usePreferenceSaveState, flushPreferences } from '../../preferences'
import { useThemeMode } from '../../theme'
import { useClusterNodes, useCurrentNodeId } from '../cluster/node-url'
import MobileSubPage from '../MobileSubPage'
import MobilePageSearch from '../mobile/MobilePageSearch'
import { SettingRow } from './SettingRow'
import { useEnvPush } from './env-vars'
import { buildSettings, itemText, type SettingsPageDef } from './registry'
import { useAgentData } from '../agent/useAgentData'

const DEFAULT_PAGE = 'ui.look'

/** 路由片段 ↔ 页 id：URL 里用 /，id 里用 . */
export function pageFromRoute(sub: string): string { return sub === 'experiments' ? 'experiments.rsi' : sub.replace(/\//g, '.') }
export function routeFromPage(id: string): string { return id.replace(/\./g, '/') }

function Chevron() { return <span className="cv"><ChevronRight size={12} /></span> }

/** 页头只展示分类、范围与当前动作。 */
function PaneHead({ page, compact }: { page: SettingsPageDef; compact?: boolean }) {
  const { t } = useI18n()
  const { message } = AntApp.useApp()
  const [busy, setBusy] = useState(false)
  const nodes = useClusterNodes()
  const nodeId = useCurrentNodeId()
  const here = nodes.find((n) => n.id === nodeId)
  const where = page.scope === 'cluster'
    ? t('set.scopeCluster')
    : page.scope === 'node'
      ? (here ? t('set.scopeNodeNamed', { node: here.name || here.id }) : t('set.scopeNode'))
      : t(page.scope === 'browser' ? 'set.scopeBrowser' : 'set.scopeMine')
  const act = page.action
  if (compact && page.hideScope && !act && !page.note) return null
  return (
    <>
      {/* 手机上子页顶栏已经写了页名，这里不再写第二遍 */}
      <div className="tt-pagehead ptitle">
        {!compact && <h2>{page.name}</h2>}
        {!page.hideScope && <span className="tt-set-scope">{where}</span>}
        {act && (
          <>
            <span className="grow" />
            {act.hint && <span className="tt-set-badge warn">{act.hint}</span>}
            <button type="button" className="tt-act" disabled={busy} onClick={async () => {
              setBusy(true)
              try { await act.run() } catch (e: any) { message.error(e?.message || String(e)) } finally { setBusy(false) }
            }}>{act.label}</button>
          </>
        )}
      </div>
      {page.note && <p className="pnote">{page.note}</p>}
    </>
  )
}

export default function SettingsPage({ sub, onNav, onLogout, onInstall, fullscreen, searchNonce = 0 }: {
  sub?: string
  onNav?: (route: string) => void
  onLogout?: () => void
  onInstall?: () => void
  fullscreen?: { active: boolean; toggle: () => void }
  searchNonce?: number
}) {
  const { t, locale, setLocale } = useI18n()
  const { modal } = AntApp.useApp()
  const { mode, setMode } = useThemeMode()
  const [prefs, setPrefs] = usePreferences()
  const pushEnv = useEnvPush()
  const saveState = usePreferenceSaveState()
  const saveStatus = saveState === 'idle' ? null : <div role={saveState === 'failed' ? 'alert' : 'status'} className="tt-set-save-state">{t('settings.preference.' + saveState)}{saveState === 'failed' && <Button onClick={() => { void flushPreferences() }}>{t('agent.retry')}</Button>}</div>
  const { phone: compact } = useLayout()
  const nodeId = useCurrentNodeId()
  const [q, setQ] = useState('')
  const channel = useAgentData<{ developmentRsi: boolean }>('/agent/status', 60000)
  const [mobileSearchOpen, setMobileSearchOpen] = useState(false)
  const searchRef = useRef<HTMLInputElement>(null)
  const lastSearchNonce = useRef(searchNonce)
  useEffect(() => {
    if (!compact || searchNonce === lastSearchNonce.current) return
    lastSearchNonce.current = searchNonce
    setMobileSearchOpen(true)
  }, [compact, searchNonce])
  useEffect(() => {
    if (!compact || !mobileSearchOpen) return
    const frame = requestAnimationFrame(() => searchRef.current?.focus())
    return () => cancelAnimationFrame(frame)
  }, [compact, mobileSearchOpen, searchNonce])

  const browserRestart = useRef<(() => Promise<void>) | null>(null)
  const registerBrowserRestart = useRef((run: (() => Promise<void>) | null) => { browserRestart.current = run }).current
  const runId = sub?.startsWith('experiments/rsi/') ? sub.slice('experiments/rsi/'.length) : ''
  const model = useMemo(() => buildSettings({
    t, theme: mode, setTheme: setMode, locale, setLocale, prefs, setPrefs,
    setWorkspace: saveWorkspace, onLogout, onInstall, fullscreen,
    onBrowserReady: registerBrowserRestart,
    onBrowserRestart: async () => {
      if (!browserRestart.current) throw new Error(t('settings.readFailed'))
      await browserRestart.current()
    },
    onEnvPush: pushEnv,
    onMemoryBack: () => { if (onNav) onNav('settings'); else location.hash = '#/settings' },
    developmentRsi: channel.value?.developmentRsi === true, nodeId, experimentRunId: runId,
    onExperimentRun: id => { const route = 'settings/experiments/rsi' + (id ? '/' + encodeURIComponent(id) : ''); if (onNav) onNav(route); else location.hash = '#/' + route },
  }), [t, mode, locale, prefs, onLogout, nodeId, channel.value?.developmentRsi, runId, onNav, onInstall, fullscreen?.active, fullscreen?.toggle])

  const routed = pageFromRoute(runId ? 'experiments/rsi' : sub || '')
  const current = model.pages[routed] ? routed : DEFAULT_PAGE
  const go = (id: string) => {
    setQ('')
    setMobileSearchOpen(false)
    if (onNav) onNav('settings/' + routeFromPage(id))
    else location.hash = '#/settings/' + routeFromPage(id)
  }

  const query = q.trim().toLowerCase()
  const hitsOf = (id: string) => model.pages[id].items.filter((it) => itemText(it, model.pages[id]).includes(query)).length
  const totalHits = query ? model.order.reduce((a, id) => a + hitsOf(id), 0) : 0

  // 桌面进页面聚焦搜索框：五十多项设置，从搜索进比从目录进快。手机不抢焦点，
  // 否则一进设置就吊起软键盘、把列表挤没。
  useEffect(() => { if (!compact) searchRef.current?.focus() }, [compact])

  const showJson = () => modal.info({
    title: t('set.jsonTitle'),
    width: 560,
    content: (
      <pre style={{
        maxHeight: '50vh', overflow: 'auto', margin: 0, padding: 'var(--sp-2)',
        background: 'var(--bg-base)', border: '1px solid var(--border-subtle)',
        borderRadius: 'var(--r-xs)', fontSize: 'var(--fs-meta)', lineHeight: 1.6,
      }}>{JSON.stringify(getPreferences(), null, 2)}</pre>
    ),
  })

  const advanced = <details className="tt-set-advanced"><summary>{t('agent.models.advanced')}</summary>
    <button type="button" className="tt-act" onClick={showJson}>{t('set.jsonButton')}</button>
  </details>

  // 页名并进这一行，不另起眉标 + 大标题：眉标「SETTINGS」+ 22px 标题 + 第二行搜索是三层，
  // 而侧栏此刻正高亮着「设置」——它已经把「这是哪一页」说完了。会话页与项目页同一套
  // （.tt-pagename + .tt-pagedivider，见 index.css「页名并进工具条」）。
  const head = (
    <div className="tt-set-head">
      <div className="tt-set-headrow">
        <span className="tt-pagename">{t('nav.env')}</span>
        <span className="tt-pagedivider" aria-hidden="true" />
        <div className={`tt-set-search${q ? ' has' : ''}`}>
          <SearchIcon size={15} />
          <input
            ref={searchRef} value={q} onChange={(e) => setQ(e.target.value)}
            placeholder={t('set.searchPlaceholder')} aria-label={t('set.searchPlaceholder')}
            autoComplete="off" spellCheck={false}
          />
          {query && totalHits > 0 && <span className="count">{t('set.hitCount', { n: totalHits })}</span>}
          {q && (
            <button type="button" className="clr" aria-label={t('common.clear')} onClick={() => { setQ(''); searchRef.current?.focus() }}>
              <CloseIcon size={14} />
            </button>
          )}
        </div>
      </div>
    </div>
  )

  const results = (
    <div className="tt-set-pane scroll">
      <div className="crumb">{t('set.searchCrumb')}</div>
      <div className="ptitle"><h2>{q.trim()}</h2></div>
      <div className="rows">
        {totalHits === 0
          ? <div className="tt-set-empty">{t('set.noHit')}</div>
          : model.order.map((id) => {
            const page = model.pages[id]
            const list = page.items.filter((it) => itemText(it, page).includes(query))
            if (!list.length) return null
            return (
              <div key={id}>
                <div className="crumb tt-set-resulthead">
                  {page.parent ? `${page.parent} · ${page.name}` : page.name}
                  <button type="button" className="tt-set-jump" onClick={() => go(id)}>{t('set.openPage')}</button>
                </div>
                {/* 整页一块的（多机、关于…）在结果里只留这一行标题：把整块渲染进结果，
                    等于把一页塞进另一页；要改就点「打开这一页」。 */}
                {list.filter((it) => !it.bare).map((it) => <SettingRow key={it.id} item={it} q={query} />)}
              </div>
            )
          })}
      </div>
    </div>
  )

  // ── 手机档：树摊成一页列表，点进去是子页（返回手势已由 MobileSubPage 接好）──
  if (compact) {
    const openSub = sub ? model.pages[routed] : null
    return (
      <div className="tt-set">
        {!openSub && saveStatus}
        {(mobileSearchOpen || q) && <div className="tt-set-mobile-head">
          <MobilePageSearch inputRef={searchRef} value={q} onChange={setQ}
            placeholder={t('set.searchPlaceholder')} resultCount={query && totalHits > 0 ? t('set.hitCount', { n: totalHits }) : undefined}
            onDismiss={() => { setQ(''); setMobileSearchOpen(false) }} />
        </div>}
        {query ? results : (
          <div className="tt-set-catlist">
            {model.groups.map(group => <section key={group.title}>
              <h3 className="tt-set-sec">{group.title}</h3>
              {group.pages.map(id => <button key={id} type="button" className="tt-set-cat" onClick={() => go(id)}>
                <span>{model.pages[id].name}</span><Chevron />
              </button>)}
            </section>)}
          </div>
        )}
        {openSub?.id === 'agent.memory' ? <>{openSub.items.map(it => <SettingRow key={it.id} item={it} />)}</> : openSub && (
          <MobileSubPage title={openSub.name} onBack={() => { const route = runId ? 'settings/experiments/rsi' : 'settings'; if (onNav) onNav(route); else location.hash = '#/' + route }} manageHistory={false} keepBottomNav>
            <div className="tt-set-pane scroll">
              {openSub.id !== 'experiments.rsi' && <PaneHead page={openSub} compact />}
              {saveStatus}
              <div className="rows">{openSub.items.map((it) => <SettingRow key={it.id} item={it} />)}{openSub.id === 'about' && advanced}</div>
            </div>
          </MobileSubPage>
        )}
      </div>
    )
  }

  const page = model.pages[current]
  return (
    <div className="tt-set">
        {saveStatus}
      {head}
      <div className="tt-set-body">
        <nav className="tt-set-tree" aria-label={t('nav.env')}>
          {model.groups.map(group => <section key={group.title}>
            <h3 className="grp">{group.title}</h3>
            {group.pages.map(id => <button key={id} type="button"
              aria-current={current === id && !query ? 'page' : undefined}
              className={`row${current === id && !query ? ' on' : ''}${query && !hitsOf(id) ? ' dim' : ''}`}
              onClick={() => go(id)}>{model.pages[id].name}</button>)}
          </section>)}
        </nav>
        {query ? results : (
          <div className={`tt-set-pane scroll${page.id === 'agent.memory' ? ' tt-set-memory' : ''}`}>
            {page.id !== 'experiments.rsi' && <PaneHead page={page} />}
            <div className="rows">{page.items.map((it) => <SettingRow key={it.id} item={it} />)}{page.id === 'about' && advanced}</div>
          </div>
        )}
      </div>
    </div>
  )
}
