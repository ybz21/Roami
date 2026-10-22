import { ICONS } from '../components/nav-icons'
import { openPalette } from '../components/shell/palette'
import { useI18n } from '../i18n'
import { BellIcon, ChevronLeft, PlusIcon, SearchIcon } from '../icons'

import { MOBILE_NAV_KEYS, NAV, mobileNavRoot } from './navigation'
type MobileNavigationProps = {
  tab: string
  go: (route: string) => void
  unread: number
  notifications: () => void
  newTask: () => void
  search: () => void
  actionsHost: (element: HTMLSpanElement | null) => void
}
export function MobileTopBar({ tab, go, unread, notifications, newTask, search, actionsHost: setMobileActionsHost }: MobileNavigationProps) {
  const { t } = useI18n()
  const navRoot = mobileNavRoot(tab)
  const mobilePrimary = MOBILE_NAV_KEYS.includes(tab) || tab === 'sessions'
  const mobileBack = tab === 'activity' ? 'home' : tab === 'install' || tab === 'about' ? 'settings' : 'tools'
  const mobileTitle = tab === 'install' ? t('install.pageTitle')
    : tab === 'about' ? t('nav.about')
      : tab === 'sessions' || tab === 'swarm' || tab === 'w' ? t('nav.projects')
        : tab === 'hub' ? t('hub.title')
          : t(NAV.find((n) => n.key === tab)?.labelKey || 'nav.home')

  return (
    <header className="tt-mobile-topbar">
      <nav aria-label={t('mobile.nav.top')}>
        <button type="button" className="tt-mobile-topbar-icon" aria-label={t(mobilePrimary ? 'nav.home' : 'common.back')}
          onClick={() => go(mobilePrimary ? 'home' : mobileBack)}>
          {mobilePrimary ? <img src="/logo-mark.svg" alt="" /> : <ChevronLeft size={20} />}
        </button>
        <strong className="tt-mobile-topbar-title">{mobileTitle}</strong>
        <span className="tt-mobile-topbar-actions">
          {tab === 'home' && <span ref={setMobileActionsHost} className="tt-mobile-page-actions" />}
          <button type="button" className="tt-mobile-topbar-icon agent-bell" aria-label={t('agent.notifications')} onClick={notifications}><BellIcon size={20} />{!!unread && <span className="agent-badge">{unread > 99 ? '99+' : unread}</span>}</button>
          {mobilePrimary && navRoot === 'projects' && <button type="button" className="tt-mobile-topbar-icon" aria-label={t('mobile.newSession')}
            onClick={() => newTask()}><PlusIcon size={20} /></button>}
          <button type="button" className="tt-mobile-topbar-icon"
            aria-label={t(tab === 'projects' || tab === 'sessions' ? 'mobile.searchSessions' : tab === 'settings' ? 'set.searchPlaceholder' : 'workspace.search')}
            onClick={() => { if (tab === 'projects' || tab === 'sessions' || tab === 'settings') search(); else openPalette() }}>
            <SearchIcon size={20} />
          </button>
        </span>
      </nav>
    </header>
  )
}
export function MobileBottomBar({ tab, go, offline }: { tab: string; go: (route: string) => void; offline: boolean }) {
  const { t } = useI18n()
  const navRoot = mobileNavRoot(tab)
  return (
    <div className="tt-bottomnav">
      {offline && <div className="tt-offline">{t('mobile.offline')}</div>}
      <nav aria-label={t('mobile.nav.bottom')}>
        {MOBILE_NAV_KEYS.map((key) => {
          const n = NAV.find((x) => x.key === key)!
          return (
            <button key={n.key} type="button" onClick={() => go(n.key)} className="tt-bottomnav-btn"
              aria-current={navRoot === n.key ? 'page' : undefined}>
              <span className="ic">{ICONS[n.key]}</span><span>{t(n.labelKey)}</span>
            </button>
          )
        })}
      </nav>
    </div>

  )
}
