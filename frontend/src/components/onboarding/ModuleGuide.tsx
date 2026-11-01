import { Button } from 'antd'
import { useI18n } from '../../i18n'
import { useLayout } from '../../layout'
import { BotIcon, ChevronRight } from '../../icons'
import { guideModules } from './guide-modules'

export default function ModuleGuide({ selected, onSelect, onNav }: { selected?: string; onSelect: (id: string) => void; onNav: (route: string) => void }) {
  const { t } = useI18n(), { phone } = useLayout()
  const current = guideModules.find(module => module.id === selected) || (phone ? null : guideModules[0])
  const key = current ? 'onboarding.guide.' + current.id + '.' : ''
  const targets: Record<string, string> = { home: 'home', projects: 'projects', capabilities: 'capabilities/agents', files: 'files', browser: 'browser', phone: 'phone', settings: 'settings' }
  return <div className="onboarding-guide">
    {!phone && <header className="tt-pagehead"><div className="ttl"><h2>{t('onboarding.guide.title')}</h2><p>{t('onboarding.guide.intro')}</p></div></header>}
    {phone && !current && <p>{t('onboarding.guide.pick')}</p>}
    <div className="onboarding-guide-layout">
      {(!phone || !current) && <nav className="onboarding-guide-list" aria-label={t('onboarding.readTour')}>{guideModules.map(module => <button type="button" key={module.id} aria-current={current?.id === module.id ? 'page' : undefined} onClick={() => onSelect(module.id)}><module.icon size={22} /><span><strong>{t('onboarding.guide.' + module.id + '.title')}</strong><small>{t('onboarding.guide.' + module.id + '.summary')}</small></span><ChevronRight size={16} /></button>)}</nav>}
      {current && <article className="onboarding-guide-detail"><div className="onboarding-guide-identity"><current.icon size={28} /><div>{!phone && <h3>{t(key + 'title')}</h3>}<p>{t(key + 'summary')}</p></div></div>
        <dl><dt>{t('onboarding.guide.when')}</dt><dd>{t(key + 'when')}</dd><dt>{t('onboarding.guide.location')}</dt><dd>{t(key + 'location')}</dd></dl>
        <section aria-label={t('onboarding.guide.features')}>{Array.from({ length: current.features }, (_, index) => <div className="onboarding-guide-feature" key={index}><h4>{t(key + 'feature.' + index + '.title')}</h4><p>{t(key + 'feature.' + index + '.description')}</p></div>)}</section>
        <section className="onboarding-guide-example"><BotIcon size={18} /><div><h4>{t('onboarding.guide.example')}</h4><p>{t(key + 'example')}</p></div></section><p className="onboarding-note">{t(key + 'note')}</p><Button onClick={() => onNav(targets[current.id])}>{t('set.openPage')}</Button>
      </article>}
    </div>{phone && !current && <p className="onboarding-note">{t('onboarding.guide.phoneTools')}</p>}
  </div>
}
