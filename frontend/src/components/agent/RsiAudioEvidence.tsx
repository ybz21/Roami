import { useI18n } from '../../i18n'
import { ChevronRight } from '../../icons'
import { audioVerificationEvidence, type AudioMeasurement } from './audio-verification-evidence'

export default function RsiAudioEvidence({ native }: { native: unknown }) {
  const { t, locale } = useI18n(), audio = audioVerificationEvidence(native)
  if (!audio) return null
  const row = ({ key, value }: AudioMeasurement) => <div key={key}>
    <dt>{t('agent.rsiResults.audio.' + key)}</dt>
    <dd>{value === null ? t('agent.rsiResults.audio.unavailable') : new Intl.NumberFormat(locale, { maximumSignificantDigits: 17, useGrouping: false, notation: value !== 0 && Math.abs(value) < 0.000001 ? 'scientific' : 'standard' }).format(value)}</dd>
  </div>
  return <>
    {audio.scores.length > 0 && <dl className="rsi-result-facts rsi-native-evidence rsi-audio-scores">{audio.scores.map(row)}</dl>}
    {audio.metrics.length > 0 && <details className="rsi-disclosure rsi-audio-details">
      <summary>{t('agent.rsiResults.audio.details')}<ChevronRight size={15} /></summary>
      <dl className="rsi-result-facts">{audio.metrics.map(row)}</dl>
    </details>}
  </>
}
