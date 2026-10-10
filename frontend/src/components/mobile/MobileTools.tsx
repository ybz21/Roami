import { useI18n } from '../../i18n'
import { SheetRow } from '../shell/MobileSheet'
import { ICONS } from '../nav-icons'

export default function MobileTools({ onNav }: { onNav: (key: string) => void }) {
  const { t } = useI18n()
  return (
    <div className="tt-mme">
      <p className="tt-mobile-section-lead">{t('mobile.tools.lead')}</p>
      <div className="tt-mme-group">
        {(['files', 'phone', 'plugins'] as const).map((key) => (
          <SheetRow key={key} icon={ICONS[key]} title={t('nav.' + key)} desc={t('mobile.tools.' + key)} onClick={() => onNav(key)} />
        ))}
      </div>
    </div>
  )
}
