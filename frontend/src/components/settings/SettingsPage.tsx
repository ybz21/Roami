// 设置页：搜索框 + 两级分类树 + 一类一页。
//
// 右边只画选中的那一页，**不做长流**——翻页的位置由树决定，回来时那一页还是原样，
// 而一条从主题滚到两步验证的长流只能靠肌肉记忆滚回去。代价是一页装不下就得拆二级
// （registry 的 MAX_ROWS 在 dev 下会喊），收益是每一页都有地址：#/settings/node/browser
// 可以直接发给别人，也可以被「去设置里打开它」的按钮直跳。
//
// 唯一允许滚的是搜索结果页：它天然跨类、条数不可控。
import { useEffect, useMemo, useRef, useState } from 'react'
import { App as AntApp, Button, Modal } from 'antd'
import { CloseIcon, SearchIcon } from '../../icons'
import { useI18n } from '../../i18n'
import { useLayout } from '../../layout'
import { usePreferences, saveWorkspace, getPreferences } from '../../preferences'
import { useThemeMode } from '../../theme'
import { api } from '../../api'
import { useClusterNodes, useCurrentNodeId } from '../cluster/node-url'
import MobileSubPage from '../MobileSubPage'
import { SettingRow } from './SettingRow'
import { buildSettings, itemText, rowCount, type SettingsModel, type SettingsPageDef } from './registry'

const DEFAULT_PAGE = 'common'

/** 路由片段 ↔ 页 id：URL 里用 /，id 里用 . */
export function pageFromRoute(sub: string): string { return sub.replace(/\//g, '.') }
export function routeFromPage(id: string): string { return id.replace(/\./g, '/') }

function Chevron({ open }: { open: boolean }) {
  return (
    <svg className="cv" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor"
      strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" aria-hidden
      style={{ transform: open ? 'rotate(90deg)' : 'none' }}><path d="M9 5l7 7-7 7" /></svg>
  )
}

/** 页头：面包屑 + 标题 + 写入目标徽标 + 页级动作 */
function PaneHead({ page, model, compact }: { page: SettingsPageDef; model: SettingsModel; compact?: boolean }) {
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
      : t('set.scopeMine')
  const act = page.action
  void model
  return (
    <>
      {/* 手机上子页顶栏已经写了页名，这里不再写第二遍 */}
      {!compact && page.parent && <div className="crumb">{`${page.parent} · ${page.name}`}</div>}
      <div className="ptitle">
        {!compact && <h2>{page.name}</h2>}
        <span className={`tt-set-badge${page.scope === 'node' ? ' node' : ''}`}>{where}</span>
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

export default function SettingsPage({ sub, onNav, onLogout, onInstall, fullscreen }: {
  sub?: string
  onNav?: (route: string) => void
  onLogout?: () => void
  onInstall?: () => void
  fullscreen?: { active: boolean; toggle: () => void }
}) {
  const { t, locale, setLocale } = useI18n()
  const { message, modal } = AntApp.useApp()
  const { mode, setMode } = useThemeMode()
  const [prefs, setPrefs] = usePreferences()
  const { size } = useLayout()
  const compact = size === 'compact'
  const nodes = useClusterNodes()
  const nodeId = useCurrentNodeId()
  const [q, setQ] = useState('')
  const [openParents, setOpenParents] = useState<Record<string, boolean>>({})
  const searchRef = useRef<HTMLInputElement>(null)

  const nodeLabel = nodes.find((n) => n.id === nodeId)?.name || ''
  const model = useMemo(() => buildSettings({
    t, theme: mode, setTheme: setMode, locale, setLocale, prefs, setPrefs,
    setWorkspace: saveWorkspace, nodeLabel, isHub: false, onLogout,
    onBrowserRestart: async () => {
      const r = await api('POST', '/browser/relaunch')
      if (r?.data?.attached) message.warning(t('settings.browserAttached'))
      else message.success(t('settings.browserRelaunched'))
    },
    onEnvPush: async () => { await api('POST', '/env/push'); message.success(t('env.pushed')) },
  }), [t, mode, locale, prefs, nodeLabel, onLogout])

  const routed = pageFromRoute(sub || '')
  const current = model.pages[routed] ? routed : DEFAULT_PAGE
  const go = (id: string) => {
    setQ('')
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
          {query && <span className="count">{t('set.hitCount', { n: totalHits })}</span>}
          {q && (
            <button type="button" className="clr" aria-label={t('common.clear')} onClick={() => { setQ(''); searchRef.current?.focus() }}>
              <CloseIcon size={14} />
            </button>
          )}
        </div>
        <button type="button" className="tt-act" onClick={showJson}>{t('set.jsonButton')}</button>
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
        {head}
        {query ? results : (
          <div className="tt-set-catlist">
            {onInstall && <>
              <div className="tt-set-sec">{t('mobile.settings.app')}</div>
              <button type="button" className="tt-set-cat" onClick={onInstall}><span>{t('install.meRow')}</span><Chevron open={false} /></button>
              {fullscreen && <button type="button" className="tt-set-cat" onClick={fullscreen.toggle}>
                <span>{t(fullscreen.active ? 'common.exitFullscreen' : 'mobile.fullscreenHideStatus')}</span><Chevron open={false} />
              </button>}
            </>}
            {model.nodes.map((n, i) => {
              if (n.kind === 'section') return <div key={i} className="tt-set-sec">{n.title}</div>
              const ids = n.kind === 'leaf' ? [n.page] : n.kids
              return ids.map((id) => (
                <button key={id} type="button" className="tt-set-cat" onClick={() => go(id)}>
                  <span>{model.pages[id].name}</span>
                  {rowCount(model.pages[id]) > 0 && <span className="n">{rowCount(model.pages[id])}</span>}
                  <Chevron open={false} />
                </button>
              ))
            })}
          </div>
        )}
        {openSub && (
          <MobileSubPage title={openSub.name} onBack={() => (onNav ? onNav('settings') : (location.hash = '#/settings'))}>
            <div className="tt-set-pane scroll">
              <PaneHead page={openSub} model={model} compact />
              <div className="rows">{openSub.items.map((it) => <SettingRow key={it.id} item={it} />)}</div>
            </div>
          </MobileSubPage>
        )}
      </div>
    )
  }

  const page = model.pages[current]
  return (
    <div className="tt-set">
      {head}
      <div className="tt-set-body">
        <div className="tt-set-tree">
          {model.nodes.map((n, i) => {
            if (n.kind === 'section') {
              return <div key={i} className="grp">{n.title}</div>
            }
            if (n.kind === 'leaf') {
              const p = model.pages[n.page]
              const hit = query ? hitsOf(n.page) : rowCount(p)
              return (
                <button key={n.page} type="button"
                  className={`row solo${current === n.page && !query ? ' on' : ''}${query && !hit ? ' dim' : ''}`}
                  onClick={() => go(n.page)}>
                  <span>{p.name}</span>{(hit > 0 || !!query) && <span className="n">{hit}</span>}
                </button>
              )
            }
            const open = openParents[n.id] !== false
            const kidHits = query ? n.kids.reduce((a, k) => a + hitsOf(k), 0) : 0
            return (
              <div key={n.id}>
                <button type="button" className={`row${query && !kidHits ? ' dim' : ''}`}
                  aria-expanded={open}
                  onClick={() => setOpenParents((s) => ({ ...s, [n.id]: !open }))}>
                  <Chevron open={open} /><span>{n.title}</span>
                  {query && <span className="n">{kidHits}</span>}
                </button>
                {open && n.kids.map((k) => {
                  const hit = query ? hitsOf(k) : rowCount(model.pages[k])
                  return (
                    <button key={k} type="button"
                      className={`row kid${current === k && !query ? ' on' : ''}${query && !hit ? ' dim' : ''}`}
                      onClick={() => go(k)}>
                      <span>{model.pages[k].name}</span>{(hit > 0 || !!query) && <span className="n">{hit}</span>}
                    </button>
                  )
                })}
              </div>
            )
          })}
        </div>
        {query ? results : (
          // 带自定义块的页（多机、手机、安全…）是表单不是设置行，长度不由我们决定——允许自己滚，
          // 否则超出的部分会被 overflow:hidden 直接裁掉、够不着。
          // 纯设置行拼出来的页仍然不滚：装不下就是这一类该拆（registry 的 MAX_ROWS 会喊）。
          <div className={`tt-set-pane${page.items.some((it) => it.control.kind === 'custom') ? ' scroll' : ''}`}>
            <PaneHead page={page} model={model} />
            <div className="rows">{page.items.map((it) => <SettingRow key={it.id} item={it} />)}</div>
          </div>
        )}
      </div>
    </div>
  )
}
