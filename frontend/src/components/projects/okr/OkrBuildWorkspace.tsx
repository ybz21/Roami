import { lazy, Suspense, useState } from 'react'
import { Button, Spin, Tabs } from 'antd'
import { useI18n } from '../../../i18n'
import { useLayout } from '../../../layout'
import OkrMainChat from './OkrMainChat'
import OkrGoalMap from './OkrGoalMap'
import OkrDashboard from './OkrDashboard'
import type { Configuration, Workspace } from './okr-workspace'

const OkrProjectFiles = lazy(() => import('./OkrProjectFiles'))

type Props = {
  projectId: string; projectDir?: string; workspace: Workspace | null; draft: Configuration
  onSession: (id: string) => void; onUpdated: () => void; onClose: () => void
}
export default function OkrBuildWorkspace({ projectId, projectDir, workspace, draft, onSession, onUpdated, onClose }: Props) {
  const { t } = useI18n()
  const { phone } = useLayout()
  const [preview, setPreview] = useState(true)
  const [mobilePreview, setMobilePreview] = useState(false)
  const [tab, setTab] = useState('goal')
  const previewVisible = phone ? mobilePreview : preview
  return <section className="okr-builder" aria-label={t('okr.builder.title')}>
    <header className="okr-builder-head">
      <Button onClick={onClose}>{t('okr.builder.back')}</Button>
      <span>{t('okr.builder.main')}</span>
      <Button onClick={() => phone ? setMobilePreview(value => !value) : setPreview(value => !value)}>
        {t(phone ? mobilePreview ? 'okr.builder.chat' : 'okr.builder.preview' : preview ? 'okr.builder.hidePreview' : 'okr.builder.showPreview')}
      </Button>
    </header>
    <div className="okr-builder-body" data-preview={previewVisible} data-phone={phone}>
      <div className="okr-builder-chat" hidden={phone && mobilePreview}>
        <OkrMainChat embedded projectId={projectId} projectDir={projectDir} workspace={workspace} draft={draft} onSession={onSession} onUpdated={onUpdated} onClose={onClose} />
      </div>
      {previewVisible && <aside className="okr-builder-preview" aria-label={t('okr.builder.preview')}>
        <Tabs activeKey={tab} onChange={setTab} items={[
          { key: 'goal', label: t('okr.tab.okr'), children: workspace ? <OkrGoalMap workspace={workspace} /> : <p className="okr-muted">{t('okr.builder.noPreview')}</p> },
          { key: 'dashboard', label: t('okr.tab.dashboard'), children: workspace ? <OkrDashboard workspace={workspace} active={tab === 'dashboard'} onRefresh={onUpdated} /> : <p className="okr-muted">{t('okr.builder.noPreview')}</p> },
          { key: 'team', label: t('okr.builder.team'), children: <div><div className="okr-builder-role"><strong>{t('swarm.conversation.main')}</strong><span>Roami</span></div>{workspace?.team?.roles?.length ? workspace.team.roles.map(role => <div className="okr-builder-role" key={role.id}><div><strong>{role.name}</strong><p>{role.duty}</p></div><span>{role.executor}</span></div>) : <p className="okr-muted">{t('okr.builder.noTeam')}</p>}</div> },
          { key: 'files', label: t('okr.tab.files'), children: <Suspense fallback={<Spin />}><OkrProjectFiles dir={projectDir} active={tab === 'files'} /></Suspense> },
        ]} />
        {workspace && <small className="okr-builder-version">{t('okr.builder.saved', { revision: workspace.revision })}</small>}
      </aside>}
    </div>
    <p className="okr-builder-scope">{t('okr.builder.scope')}</p>
  </section>
}
