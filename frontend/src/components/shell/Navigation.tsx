// 侧边导航 / Activity Bar（14 设计 §4.4）。
//
// 从 App.tsx 里搬出来并重做。旧版是一个平铺的 antd inline Menu：七个页面一视同仁，
// 「设置」和「概览」并排，选中项整块蓝底把注意力从内容上夺走，底部塞着五个同权重的
// 文字按钮（关于/收起/全屏/退出）——退出登录和收起侧栏长得一模一样。
//
// 新结构分三段：**工作区**（干活的地方）／**工具**（看别的东西的地方）／**账户**
// （改设置和退出的地方）。前两段是导航，第三段是操作，混在一起是旧版最大的问题。
//
// 不再用 antd Menu：3px 左强调线、分组标题、badge、轨态 Tooltip 这几样都要覆盖
// Menu 的默认结构，覆盖到最后剩下的只有它的键盘导航——不如自己写清楚。
import { Dropdown, Tooltip } from 'antd'
import type { MenuProps } from 'antd'
import type { ReactNode } from 'react'
import { PanelLeftIcon, SearchIcon } from '../../icons'
import { useI18n } from '../../i18n'

export type NavEntry = {
  key: string
  label: string
  icon: ReactNode
  /** 只显示「需要行动」的数量，不显示普通总数（14 §4.4） */
  badgeTone?: string
  badge?: number
  badgeTitle?: string
}

export type NavGroup = { label: string; items: NavEntry[] }

export function Navigation({
  rail, active, groups, onGo, settings, hubAlarm,
  node, nodeMenu, onToggleRail, tree, onSearch, searchHint,
}: {
  /** 品牌下面那行搜索：⌘K 面板的可见入口（22 设计 §3.5：顶栏撤了，搬到这） */
  onSearch?: () => void
  searchHint?: string
  /** 项目树（22 设计 §3.2）：挂在导航组下面、脚上面，吃掉原来空着的那段高度 */
  tree?: ReactNode
  /** 48px 轨态：用户收起 / Focus / 非 large 档 */
  rail: boolean
  active: string
  groups: NavGroup[]
  onGo: (key: string) => void
  /** 设置接在主导航末尾。 */
  settings: NavEntry
  /** 多机（连了中心）时给：顶部出现机器切换器；单机传 null，那一块整个不渲染 */
  node: { name: string; mark: ReactNode; dot: string; latency: string } | null
  /** 切换器下拉里的机器列表（含中心）；单机时不会用到 */
  nodeMenu: MenuProps['items']
  /** 中心不健康时的一句话原因；给了就在切换器上亮红点（见 cluster/hub-health.ts） */
  hubAlarm?: string
  onToggleRail: () => void
}) {
  const { t } = useI18n()

  const item = (n: NavEntry) => {
    const btn = (
      <button key={n.key} type="button" className={`tt-nav-item${active === n.key ? ' on' : ''}`}
        onClick={() => onGo(n.key)} aria-label={n.label} aria-current={active === n.key ? 'page' : undefined}>
        <span className="ic">{n.icon}</span>
        {!rail && <span className="nm">{n.label}</span>}
        {!!n.badge && <span className={`bd ${n.badgeTone || ''}`} title={n.badgeTitle}>{n.badge > 99 ? '99+' : n.badge}</span>}
      </button>
    )
    // 轨态下文字没了，Tooltip 是唯一的名字来源（14 §4.4「所有图标有 Tooltip」）
    return rail ? <Tooltip key={n.key} title={n.label} placement="right">{btn}</Tooltip> : btn
  }

  return (
    <div className={`tt-nav${rail ? ' rail' : ''}`}>
      <div className="tt-nav-brand">
        <img src="/logo-mark.svg" width={26} height={26} alt="" aria-hidden />
        {!rail && <strong className="wd">Roami</strong>}
        <div className="tt-nav-brand-actions">
          <button type="button" className="tt-nav-icon tt-nav-toggle" onClick={onToggleRail}
            title={t(rail ? 'common.expand' : 'common.collapse')}
            aria-label={t(rail ? 'common.expand' : 'common.collapse')} aria-expanded={!rail}>
            <PanelLeftIcon size={18} />
          </button>
        </div>
      </div>

      {/* 搜索：顶栏 Command Center 撤了（22 设计 §3.5），这一行是桌面上唯一看得见的入口 */}
      {onSearch && (
        rail
          ? <Tooltip title={t('workspace.search')} placement="right"><button type="button" className="tt-nav-search" onClick={onSearch} aria-label={t('workspace.search')}><SearchIcon size={15} /></button></Tooltip>
          : <button type="button" className="tt-nav-search" onClick={onSearch} title={t('workspace.search')}>
              <SearchIcon size={15} /><span className="ph">{t('workspace.searchPlaceholder')}</span>{searchHint && <kbd>{searchHint}</kbd>}
            </button>
      )}


      <div className={`tt-nav-list${tree && !rail ? ' has-tree' : ''}`}>
        {groups.map((g) => (
          <div key={g.label || 'all'} className="tt-nav-group">
            {!rail && g.label && <div className="gl">{g.label}</div>}
            {g.items.map(item)}
          </div>
        ))}
        {item(settings)}
      </div>

      {/* 树不进轨：轨态只有图标，树没有图标形态 */}
      {tree && !rail && <div className="tt-nav-tree">{tree}</div>}

      {node && (
        <div className="tt-nav-foot">
          <Dropdown menu={{ items: nodeMenu }} trigger={['click']} placement={rail ? 'topLeft' : 'top'}>
            <button type="button" className={`tt-nav-node${hubAlarm ? ' alarm' : ''}`}
              title={hubAlarm ? `${node.name} · ${hubAlarm}` : `${node.name} · ${node.latency}`}
              aria-label={t('node.aria.switcher', { name: node.name })}>
              <span className="av">{node.mark}</span>
              {!rail && <span className="nm">{node.name}</span>}
              {/* 中心不健康时这一枚亮红点：它常驻在每一页，是唯一能保证被看见的位置。
                  2026-08-11 中心卡死十几个小时无人发现——当时就算中心页已经存在，
                  也得先「发现打不开」才会想起去看它。 */}
              <i className={`nd${rail ? ' rail' : ''}`} style={{ background: hubAlarm ? 'var(--danger)' : node.dot }} />
              {!rail && <span className="dots">{chevronDown}</span>}
            </button>
          </Dropdown>
        </div>
      )}
    </div>
  )
}

const stroke = { fill: 'none', stroke: 'currentColor', strokeWidth: 1.8, strokeLinecap: 'round' as const, strokeLinejoin: 'round' as const }
const svg = (children: ReactNode) => <svg viewBox="0 0 24 24" width={18} height={18} {...stroke}>{children}</svg>
// 主机图标而不是姓名首字母：这里代表的是"你连着的这台机器"，不是一个人。
// 尺寸跟导航项同为 18：整列图标要落在同一条竖线、同一个视觉重量上。
const chevronDown = <svg viewBox="0 0 24 24" width={14} height={14} {...stroke}><polyline points="6 9 12 15 18 9" /></svg>

