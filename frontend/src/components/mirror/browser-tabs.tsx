// 浏览器页的标签：桌面一条标签条，窄档一个「⧉N + 抽屉」（设计 17 §4 / §5.4）。
//
// 从前两端共用一条 150px 的横滚标签条——360 的屏上放不下第三枚，找标签只能横着扒。
// 现在窄档换成整页卡片列表（标题 + 地址两行），点得到、看得清。
import { useI18n } from '../../i18n'
import { Dropdown } from 'antd'
import { CloseIcon, GlobeIcon, MoreIcon, PlusIcon } from '../../icons'
import { MobileSheet } from '../shell/MobileSheet'
import { tabCloseTargets } from '../shell/tab-actions'
import { splitUrl } from './mirror'
import type { ReactNode } from 'react'

export interface TabInfo { id: string; title: string; url: string }

const label = (t: TabInfo) => t.title || splitUrl(t.url).host || 'about:blank'

/** 桌面标签条：激活的那枚底色提到 --bg-container，与下面的工具行连成一片。 */
export function TabStrip({ tabs, active, pinned, onSelect, onClose, onCloseMany, onPin, onAdd, extra }: {
  tabs: TabInfo[]
  active: string
  pinned: ReadonlySet<string>
  onSelect: (id: string) => void
  onClose: (id: string) => void
  onCloseMany: (ids: string[]) => void
  onPin: (id: string) => void
  onAdd: () => void
  extra?: ReactNode
}) {
  const { t } = useI18n()
  return (
    // 空白处双击新建：浏览器通用手势
    <div className="mc-tabs" onDoubleClick={(e) => { if (e.target === e.currentTarget) onAdd() }}>
      <div className="mc-tabs-strip">
        {tabs.map((tb, i) => {
          const on = tb.id === active || (!active && i === 0)
          const order = tabs.map((item) => item.id)
          const targets = (scope: 'others' | 'left' | 'right') => tabCloseTargets(order, pinned, tb.id, scope)
          return (
            <Dropdown key={tb.id} trigger={['contextMenu']} menu={{ onClick: ({ domEvent }) => domEvent.stopPropagation(), items: [
              { key: 'pin', label: t(pinned.has(tb.id) ? 'tabs.unpin' : 'tabs.pin'), onClick: () => onPin(tb.id) },
              { type: 'divider' },
              { key: 'close', label: t('common.close'), onClick: () => onClose(tb.id) },
              { key: 'others', label: t('tabs.closeOthers'), disabled: !targets('others').length, onClick: () => onCloseMany(targets('others')) },
              { key: 'right', label: t('tabs.closeRight'), disabled: !targets('right').length, onClick: () => onCloseMany(targets('right')) },
              { key: 'left', label: t('tabs.closeLeft'), disabled: !targets('left').length, onClick: () => onCloseMany(targets('left')) },
            ] }}><div className={`mc-tab${on ? ' is-on' : ''}${pinned.has(tb.id) ? ' pinned' : ''}`} title={`${label(tb)} · ${tb.url}`}
              onClick={() => onSelect(tb.id)}
              // 中键关闭：跟真浏览器一致
              onAuxClick={(e) => { if (e.button === 1) { e.preventDefault(); onClose(tb.id) } }}>
              <span className="mc-tab-fav" aria-hidden>{pinned.has(tb.id) && <GlobeIcon size={14} />}</span>
              <span className="mc-tab-t">{label(tb)}</span>
              <span className="mc-tab-x" role="button" aria-label={t('common.close')}
                onClick={(e) => { e.stopPropagation(); onClose(tb.id) }}
                onMouseDown={(e) => e.stopPropagation()}>
                <CloseIcon size={12} />
              </span>
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

/** 窄档标签抽屉：一张卡 = 标题 + 地址，48 高，够手指点。 */
export function TabSheet({ open, tabs, active, pinned, onClose, onSelect, onCloseTab, onCloseMany, onPin, onAdd }: {
  open: boolean
  tabs: TabInfo[]
  active: string
  pinned: ReadonlySet<string>
  onClose: () => void
  onSelect: (id: string) => void
  onCloseTab: (id: string) => void
  onCloseMany: (ids: string[]) => void
  onPin: (id: string) => void
  onAdd: () => void
}) {
  const { t } = useI18n()
  return (
    <MobileSheet open={open} title={t('browser.tabs')} onClose={onClose}>
      {tabs.map((tb, i) => {
        const on = tb.id === active || (!active && i === 0)
        const order = tabs.map((item) => item.id)
        const targets = (scope: 'others' | 'left' | 'right') => tabCloseTargets(order, pinned, tb.id, scope)
        return (
          <div key={tb.id} className={`mc-tabcard${on ? ' is-on' : ''}`} onClick={() => onSelect(tb.id)}>
            <span className="mc-tabcard-fav" aria-hidden>{label(tb).slice(0, 1).toUpperCase()}</span>
            <span className="mc-tabcard-meta">
              <span className="t">{label(tb)}</span>
              <span className="u">{tb.url}</span>
            </span>
            <Dropdown trigger={['click']} menu={{ onClick: ({ domEvent }) => domEvent.stopPropagation(), items: [
              { key: 'pin', label: t(pinned.has(tb.id) ? 'tabs.unpin' : 'tabs.pin'), onClick: () => onPin(tb.id) },
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
    </MobileSheet>
  )
}
