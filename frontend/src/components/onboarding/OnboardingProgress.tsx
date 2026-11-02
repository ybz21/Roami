import { CheckIcon } from '../../icons'
import { useI18n } from '../../i18n'
import { steps, type OnboardingStep } from './onboarding-state'
export function OnboardingProgress({ current, done, onSelect }: { current: OnboardingStep; done: boolean[]; onSelect: (step: OnboardingStep) => void }) {
  const { t, locale } = useI18n()
  return <nav className="onboarding-progress" aria-label={t('onboarding.progress')}>{steps.map((step, index) => <button key={step} type="button" aria-label={t('onboarding.step.' + step)} aria-current={current === step ? 'step' : undefined} onClick={() => onSelect(step)}><span className={done[index] ? 'onboarding-done' : ''}>{done[index] ? <CheckIcon size={14} /> : new Intl.NumberFormat(locale).format(index + 1)}</span><strong>{t('onboarding.step.' + step)}</strong></button>)}</nav>
}
