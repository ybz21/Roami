// 手机会话切换先显示后台工作区中的会话，再显示待处理与最近会话。
import { useSessionOverview, type OverviewItem } from '../../session-overview'
import { sessionLabel } from '../sessions/session-label'
import { useI18n } from '../../i18n'
import { AgentLogo, TerminalIcon, TabsIcon } from '../../icons'
import { MobileSheet, SheetRow, SheetSection } from '../shell/MobileSheet'

const RECENT = 6

export function MobileSessionSwitch({ open, active, terms, onPick, onAll, onClose }: {
  open: boolean
  active: string | null
  terms: string[]
  onPick: (name: string) => void
  onAll: () => void
  onClose: () => void
}) {
  const { t } = useI18n()
  const { value: items } = useSessionOverview(open)

  const afterSheetGone = (fn: () => void) => {
    let done = false
    const run = () => { if (done) return; done = true; window.removeEventListener('popstate', run); fn() }
    window.addEventListener('popstate', run)
    setTimeout(run, 300) // 没压过历史记录（桌面窄窗）就不会有 popstate，兜底
    onClose()
  }

  const opened = terms.map(name => items.find(item => item.name === name) || { name, label: sessionLabel(name), lastActivity: 0, dormant: false, running: false, waiting: false })
  const waiting = items.filter(s => s.waiting && s.name !== active && !terms.includes(s.name))
  const recent = items.filter(s => !s.dormant && !s.waiting && s.name !== active && !terms.includes(s.name)).slice(0, RECENT)
  const row = (s: OverviewItem) => (
    <SheetRow key={s.name} minHeight={56} active={s.name === active}
      icon={s.agent ? <AgentLogo kind={s.agent} size={16} /> : <TerminalIcon size={16} />}
      title={<span className="ttl">{s.project && <span className="pj">{s.project} ·</span>}<span className="nm">{s.label}</span></span>}
      desc={s.name === active ? t('workspace.current') : s.waiting ? (s.tail || t('mobile.st.waiting')) : s.running ? t('mobile.st.running') : t('mobile.st.idle')}
      onClick={() => afterSheetGone(() => onPick(s.name))} />
  )
  return (
    <MobileSheet open={open} title={t('mobile.switchSession')} onClose={onClose}>
      {opened.length > 0 && <><SheetSection>{t('mobile.switchOpened')}</SheetSection>{opened.map(row)}</>}
      {waiting.length > 0 && <><SheetSection>{t('inbox.waiting')}</SheetSection>{waiting.map(row)}</>}
      {recent.length > 0 && <><SheetSection>{t('mobile.switchRecent')}</SheetSection>{recent.map(row)}</>}
      <SheetRow icon={<TabsIcon size={16} />} title={t('project.allSessions')} onClick={() => afterSheetGone(onAll)} />
    </MobileSheet>
  )
}
