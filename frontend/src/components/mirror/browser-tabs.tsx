// 浏览器页的标签：桌面一条标签条，窄档一个「⧉N + 抽屉」（设计 17 §4 / §5.4）。
//
// 从前两端共用一条 150px 的横滚标签条——360 的屏上放不下第三枚，找标签只能横着扒。
// 现在窄档换成整页卡片列表（标题 + 地址两行），点得到、看得清。
import { useI18n } from '../../i18n'
import { ConfigProvider, Dropdown, Segmented } from 'antd'
import { useEffect, useState } from 'react'
import { CloseIcon, GlobeIcon, MoreIcon, PlusIcon } from '../../icons'
import MobileSubPage from '../MobileSubPage'
import { tabCloseTargets } from '../shell/tab-actions'
import { splitUrl } from './mirror'
import type { ReactNode } from 'react'

export interface TabInfo { id: string; title: string; url: string; origin?: 'human' | 'agent'; createdBy?: 'human' | 'agent'; sleeping?: boolean; pinned?: boolean }

const label = (t: TabInfo) => t.title || splitUrl(t.url).host || 'about:blank'

/** 桌面标签条：激活的那枚底色提到 --bg-container，与下面的工具行连成一片。 */
export function TabStrip({ tabs, active, pinned, onSelect, onClose, onCloseMany, onPin, onOrigin, onAdd, extra }: {
  tabs: TabInfo[]
  active: string
  pinned: ReadonlySet<string>
  onSelect: (id: string) => void
  onClose: (id: string) => void
  onCloseMany: (ids: string[]) => void
  onOrigin?: (id: string, origin: 'human' | 'agent') => void
  onPin: (id: string) => void
  onAdd: () => void
  extra?: ReactNode
}) {
  const { t } = useI18n()
  const [group, setGroup] = useState<'human' | 'agent'>(tabs.find(tab => tab.id === active)?.origin || 'agent')
  useEffect(() => { const selected = tabs.find(tab => tab.id === active); if (selected) setGroup(selected.origin || 'agent') }, [active, tabs.find(tab => tab.id === active)?.origin])
  const grouped = tabs.filter(tab => (tab.origin || 'agent') === group)
  const groups = <Segmented aria-label={t('browser.groups')} value={group} onChange={value => { setGroup(value as 'human' | 'agent'); const first = tabs.find(tab => (tab.origin || 'agent') === value); if (first) onSelect(first.id) }}
    options={(['human', 'agent'] as const).map(origin => ({ value: origin, label: t('browser.groupCount', { group: t(`browser.group.${origin}`), count: tabs.filter(tab => (tab.origin || 'agent') === origin).length }) }))} />
  return (
    // 空白处双击新建：浏览器通用手势
    <div className="mc-tabs" onDoubleClick={(e) => { if (e.target === e.currentTarget) onAdd() }}>
      <span className="mc-tab-groups">{groups}</span>
      <div className="mc-tabs-strip">
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
        <button type="button" className="mc-ib mc-tab-add" title={t('browser.newTab')} aria-label={t('browser.newTab')}
          onClick={onAdd}><PlusIcon size={14} /></button>
      </div>
      {extra && <span className="mc-tabs-end">{extra}</span>}
    </div>
  )
}

/** 分组固定在返回栏下，页面列表独立滚动。 */
export function TabSheet({ open, tabs, active, pinned, onClose, onSelect, onCloseTab, onCloseMany, onPin, onOrigin, onAdd }: {
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
  const [group, setGroup] = useState<'human' | 'agent'>(tabs.find(tab => tab.id === active)?.origin || 'agent')
  useEffect(() => { if (open) { const selected = tabs.find(tab => tab.id === active); if (selected) setGroup(selected.origin || 'agent') } }, [open])
  const grouped = tabs.filter(tab => (tab.origin || 'agent') === group)
  const groups = <Segmented aria-label={t('browser.groups')} value={group} onChange={value => setGroup(value as 'human' | 'agent')}
    options={(['human', 'agent'] as const).map(origin => ({ value: origin, label: t('browser.groupCount', { group: t(`browser.group.${origin}`), count: tabs.filter(tab => (tab.origin || 'agent') === origin).length }) }))} />
  if (!open) return null
  return (
    <MobileSubPage title={t('browser.tabs')} dialogLabel={t('browser.tabs')} onBack={onClose} search={false}>
      <ConfigProvider getPopupContainer={trigger => trigger?.closest('[role="dialog"]') as HTMLElement || document.body}>
      <div className="mc-tab-groups">{groups}</div>
      <div className="mc-tab-list">
      {grouped.map((tb, i) => {
        const on = tb.id === active || (!active && i === 0)
        const order = grouped.map((item) => item.id)
        const targets = (scope: 'others' | 'left' | 'right') => tabCloseTargets(order, pinned, tb.id, scope)
        return (
          <div key={tb.id} className={`mc-tabcard${on ? ' is-on' : ''}`}>
            <button type="button" className="mc-tabcard-select" onClick={() => onSelect(tb.id)} aria-label={label(tb)}>
            <span className="mc-tabcard-fav" aria-hidden><GlobeIcon size={14} /></span>
            <span className="mc-tabcard-meta">
              <span className="t">{label(tb)}{tb.sleeping && <span className="mc-tab-sleep">{t('browser.sleeping')}</span>}</span>
              <span className="u">{tb.url}</span>
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
      <button type="button" className="mc-newtab" onClick={onAdd}>
        <PlusIcon size={14} />{t('browser.newTab')}
      </button>
      </div>
      </ConfigProvider>
    </MobileSubPage>
  )
}
