import { useI18n } from '../../i18n'
import { ConfigProvider, Dropdown, Input, Segmented } from 'antd'
import { useEffect, useRef, useState } from 'react'
import { CloseIcon, GlobeIcon, MoreIcon, PlusIcon, TabsIcon } from '../../icons'
import MobileSubPage from '../MobileSubPage'
import { tabCloseTargets } from '../shell/tab-actions'
import { splitUrl } from './mirror'

export interface TabInfo { id: string; title: string; url: string; origin?: 'human' | 'agent'; createdBy?: 'human' | 'agent'; sleeping?: boolean; pinned?: boolean }

const label = (t: TabInfo) => t.title || splitUrl(t.url).host || 'about:blank'

/** 桌面标签条：激活的那枚底色提到 --bg-container，与下面的工具行连成一片。 */
export function TabStrip({ tabs, active, pinned, onSelect, onClose, onCloseMany, onPin, onOrigin, onAdd, onOpenTabs, onGroupChange }: {
  tabs: TabInfo[]
  active: string
  pinned: ReadonlySet<string>
  onSelect: (id: string) => void
  onClose: (id: string) => void
  onCloseMany: (ids: string[]) => void
  onOrigin?: (id: string, origin: 'human' | 'agent') => void
  onPin: (id: string) => void
  onAdd: () => void
  onGroupChange?: () => void
  onOpenTabs: () => void
}) {
  const { t } = useI18n()
  const [group, setGroup] = useState<'human' | 'agent'>(tabs.find(tab => tab.id === active)?.origin || 'agent')
  useEffect(() => { const selected = tabs.find(tab => tab.id === active); if (selected) setGroup(selected.origin || 'agent') }, [active, tabs.find(tab => tab.id === active)?.origin])
  const recent = useRef<Partial<Record<'human' | 'agent', string>>>({})
  useEffect(() => { const selected = tabs.find(tab => tab.id === active); if (selected) recent.current[selected.origin || 'agent'] = selected.id }, [active, tabs.find(tab => tab.id === active)?.origin])
  const grouped = tabs.filter(tab => (tab.origin || 'agent') === group)
  const groups = <Segmented aria-label={t('browser.groups')} value={group} onChange={value => { onGroupChange?.(); setGroup(value as 'human' | 'agent'); const first = tabs.find(tab => tab.id === recent.current[value as 'human' | 'agent'] && (tab.origin || 'agent') === value) || tabs.find(tab => (tab.origin || 'agent') === value); if (first) onSelect(first.id) }}
    options={(['human', 'agent'] as const).map(origin => ({ value: origin, label: t('browser.groupCount', { group: t(`browser.group.${origin}`), count: tabs.filter(tab => (tab.origin || 'agent') === origin).length }) }))} />
  return (
    // 空白处双击新建：浏览器通用手势
    <div className="mc-tabs" onDoubleClick={(e) => { if (e.target === e.currentTarget) onAdd() }}>
      <div className="mc-tabs-strip">
        {!grouped.length && <span className="mc-tab-empty-inline">{t('browser.noPages')}</span>}
        {grouped.map((tb, i) => {
          const on = tb.id === active || (!active && i === 0)
          const order = grouped.map((item) => item.id)
          const targets = (scope: 'others' | 'left' | 'right') => tabCloseTargets(order, pinned, tb.id, scope)
          return (
            <Dropdown key={tb.id} trigger={['contextMenu']} menu={{ onClick: ({ domEvent }) => domEvent.stopPropagation(), items: [
              { key: 'pin', label: t(pinned.has(tb.id) ? 'tabs.unpin' : 'tabs.pin'), onClick: () => onPin(tb.id) },
              { key: 'creator', disabled: true, label: t('browser.createdBy', { creator: t(`browser.group.${tb.createdBy || tb.origin || 'agent'}`) }) },
              ...(onOrigin ? [{ key: 'origin', label: t(tb.origin === 'human' ? 'browser.moveToAgent' : 'browser.moveToHuman'), onClick: () => onOrigin(tb.id, tb.origin === 'human' ? 'agent' : 'human') }] : []),
              { type: 'divider' },
              { key: 'close', label: t('common.close'), onClick: () => onClose(tb.id) },
              { key: 'others', label: t('tabs.closeOthers'), disabled: !targets('others').length, onClick: () => onCloseMany(targets('others')) },
              { key: 'right', label: t('tabs.closeRight'), disabled: !targets('right').length, onClick: () => onCloseMany(targets('right')) },
              { key: 'left', label: t('tabs.closeLeft'), disabled: !targets('left').length, onClick: () => onCloseMany(targets('left')) },
            ] }}><div className={`mc-tab${on ? ' is-on' : ''}${pinned.has(tb.id) ? ' pinned' : ''}`} title={`${label(tb)} · ${tb.url}`}
              // 中键关闭：跟真浏览器一致
              onAuxClick={(e) => { if (e.button === 1) { e.preventDefault(); onClose(tb.id) } }}>
              <button type="button" className="mc-tab-select" aria-label={label(tb)} onClick={() => onSelect(tb.id)}>
              <span className="mc-tab-fav" aria-hidden>{pinned.has(tb.id) && <GlobeIcon size={14} />}</span>
              <span className="mc-tab-t">{label(tb)}{tb.sleeping && <span className="mc-tab-sleep">{t('browser.sleeping')}</span>}</span>
              </button>
              <button type="button" className="mc-tab-x" aria-label={t('common.close')}
                onClick={(e) => { e.stopPropagation(); onClose(tb.id) }}
                onMouseDown={(e) => e.stopPropagation()}>
                <CloseIcon size={12} />
              </button>
            </div></Dropdown>
          )
        })}
        <button type="button" className="mc-ib mc-tab-add" title={t('browser.newHumanTab')} aria-label={t('browser.newHumanTab')}
          onClick={onAdd}><PlusIcon size={14} /></button>
      </div>
      <div className="mc-tabs-end">
        <span className="mc-tab-groups">{groups}</span>
        <button type="button" className="mc-tab-directory-trigger" onClick={onOpenTabs} aria-label={t('browser.allPages')}>
          <TabsIcon size={15} /><span>{t('browser.allPages')}</span>
        </button>
      </div>
    </div>
  )
}

/** 分组固定在返回栏下，页面列表独立滚动。 */
export function TabSheet({ open, tabs, active, pinned, onClose, onSelect, onCloseTab, onCloseMany, onPin, onOrigin, onAdd, compact = true }: {
  compact?: boolean
  open: boolean
  tabs: TabInfo[]
  active: string
  pinned: ReadonlySet<string>
  onClose: () => void
  onSelect: (id: string) => void
  onCloseTab: (id: string) => void
  onCloseMany: (ids: string[]) => void
  onOrigin?: (id: string, origin: 'human' | 'agent') => void
  onPin: (id: string) => void
  onAdd: () => void
}) {
  const { t } = useI18n()
  const [group, setGroup] = useState<'all' | 'human' | 'agent'>('all')
  const [query, setQuery] = useState('')
  const directoryRef = useRef<HTMLElement>(null)
  useEffect(() => {
    if (!open || compact) return
    const previous = document.activeElement as HTMLElement | null
    directoryRef.current?.querySelector<HTMLInputElement>('input')?.focus({ preventScroll: true })
    return () => { if (previous?.isConnected) previous.focus({ preventScroll: true }) }
  }, [open, compact])
  useEffect(() => { if (open) { setGroup('all'); setQuery('') } }, [open])
  const grouped = tabs.filter(tab => (group === 'all' || (tab.origin || 'agent') === group) && `${label(tab)} ${tab.url}`.toLocaleLowerCase().includes(query.trim().toLocaleLowerCase()))
  const groups = <Segmented aria-label={t('browser.groups')} value={group} onChange={value => setGroup(value as typeof group)}
    options={['all', 'human', 'agent'].map(origin => ({ value: origin, label: origin === 'all' ? t('common.all') : t(`browser.group.${origin}`) }))} />
  if (!open) return null
  const content = (
      <ConfigProvider getPopupContainer={trigger => trigger?.closest('[data-browser-directory]') as HTMLElement || document.body}>
      <div className="mc-tab-directory-controls">
        <Input allowClear placeholder={t('browser.searchPages')} aria-label={t('browser.searchPages')}
          value={query} onChange={event => setQuery(event.target.value)} />
        <div className="mc-tab-groups">{groups}</div>
      </div>
      <div className="mc-tab-list">
      {(['human', 'agent'] as const).map(origin => {
        const members = grouped.filter(tab => (tab.origin || 'agent') === origin)
        if (!members.length) return null
        return <section key={origin} aria-label={t(`browser.group.${origin}`)}>
        <h3 className="mc-tab-group-title">{t('browser.groupCount', { group: t(`browser.group.${origin}`), count: members.length })}</h3>
      {members.map(tb => {
        const on = tb.id === active
        const order = members.map((item) => item.id)
        const targets = (scope: 'others' | 'left' | 'right') => tabCloseTargets(order, pinned, tb.id, scope)
        return (
          <div key={tb.id} className={`mc-tabcard${on ? ' is-on' : ''}`}>
            <button type="button" className="mc-tabcard-select" onClick={() => onSelect(tb.id)} aria-label={label(tb)}>
            <span className="mc-tabcard-fav" aria-hidden><GlobeIcon size={14} /></span>
            <span className="mc-tabcard-meta">
              <span className="t">{label(tb)}{tb.sleeping && <span className="mc-tab-sleep">{t('browser.sleeping')}</span>}</span>
              <span className="u" title={tb.url}>{splitUrl(tb.url).host || tb.url}</span>
            </span>
            </button>
            <Dropdown trigger={['click']} menu={{ onClick: ({ domEvent }) => domEvent.stopPropagation(), items: [
              { key: 'pin', label: t(pinned.has(tb.id) ? 'tabs.unpin' : 'tabs.pin'), onClick: () => onPin(tb.id) },
              { key: 'creator', disabled: true, label: t('browser.createdBy', { creator: t(`browser.group.${tb.createdBy || tb.origin || 'agent'}`) }) },
              ...(onOrigin ? [{ key: 'origin', label: t(tb.origin === 'human' ? 'browser.moveToAgent' : 'browser.moveToHuman'), onClick: () => onOrigin(tb.id, tb.origin === 'human' ? 'agent' : 'human') }] : []),
              { type: 'divider' },
              { key: 'close', label: t('common.close'), onClick: () => onCloseTab(tb.id) },
              { key: 'others', label: t('tabs.closeOthers'), disabled: !targets('others').length, onClick: () => onCloseMany(targets('others')) },
              { key: 'right', label: t('tabs.closeRight'), disabled: !targets('right').length, onClick: () => onCloseMany(targets('right')) },
              { key: 'left', label: t('tabs.closeLeft'), disabled: !targets('left').length, onClick: () => onCloseMany(targets('left')) },
            ] }}><button type="button" className="mc-ib" aria-label={t('common.more')}
              onClick={(e) => e.stopPropagation()}><MoreIcon size={15} /></button></Dropdown>
            <button type="button" className="mc-ib" aria-label={t('common.close')}
              onClick={(e) => { e.stopPropagation(); onCloseTab(tb.id) }}><CloseIcon size={13} /></button>
          </div>
        )
      })}
      </section>})}
      {!grouped.length && <div className="mc-tab-empty">{t(query.trim() ? 'browser.noMatchingPages' : 'browser.noPages')}</div>}
      <button type="button" className="mc-newtab" onClick={onAdd}>
        <PlusIcon size={14} />{t('browser.newHumanTab')}
      </button>
      </div>
      </ConfigProvider>
  )
  return compact ? (
    <MobileSubPage title={t('browser.allPages')} dialogLabel={t('browser.allPages')} onBack={onClose} search={false}>
      <div className="mc-tab-directory-content" data-browser-directory>{content}</div>
    </MobileSubPage>
  ) : (
    <aside ref={directoryRef} className="mc-tab-directory" data-browser-directory aria-label={t('browser.allPages')} onKeyDown={event => { if (event.key === 'Escape') { event.stopPropagation(); onClose() } }}>
      <div className="mc-tab-directory-head"><strong>{t('browser.allPages')}</strong>
        <button type="button" className="mc-ib" onClick={onClose} aria-label={t('common.close')}><CloseIcon size={16} /></button>
      </div>
      {content}
    </aside>
  )
}
