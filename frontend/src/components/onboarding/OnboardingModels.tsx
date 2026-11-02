import { useI18n } from '../../i18n'
import ModelHub from '../capabilities/ModelHub'
import { useOnboardingFieldFocus } from './onboarding-field-focus'

export default function OnboardingModels({ sub, onNav }: { sub: string; onNav: (route: string) => void }) {
  const { t } = useI18n(), focus = useOnboardingFieldFocus()
  const navigate = (route: string) => onNav(route.startsWith('capabilities/models/') ? 'onboarding/model/' + route.slice('capabilities/models/'.length) : route.startsWith('capabilities/agents/roami') ? 'onboarding/agents/roami' : route.startsWith('capabilities/agents') ? route.replace('capabilities/agents', 'onboarding/agents') : route)
  return <div {...focus}>
    <p className="onboarding-note">{t('onboarding.modelHubIntro')}</p>
    <ModelHub sub={sub || 'catalog'} onNav={navigate} embedded />
  </div>
}
