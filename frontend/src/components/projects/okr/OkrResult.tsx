import { useI18n } from '../../../i18n'
import { CheckIcon } from '../../../icons'
import { resultAttainment, type ResultOverview } from './okr-workspace'

export default function OkrResult({ result, compact = false }: { result: ResultOverview; compact?: boolean }) {
  const { t, locale } = useI18n()
  const { achieved, percent, met } = resultAttainment(result, result.baseline, result.latest)
  const number = (n: number) => new Intl.NumberFormat(locale, { maximumFractionDigits: 2 }).format(n)
  const day = (s: string) => new Intl.DateTimeFormat(locale, { month: 'short', day: 'numeric', timeZone: 'Asia/Shanghai' }).format(new Date(s + 'T00:00:00+08:00'))
  return <article className={`okr-result${compact ? ' compact' : ''}`} data-met={met}>
    <div className="okr-result-top"><span>{t('okr.horizon.' + result.horizon)}</span><span className={met ? 'okr-met' : 'okr-muted'}>{met ? <><CheckIcon size={14} />{t('okr.met')}</> : t('okr.due', { date: day(result.dueDate) })}</span></div>
    <h4>{result.title}</h4>
    <div className="okr-result-number">{achieved === null ? t('okr.waitingData') : <><strong>{number(achieved)}</strong><span>{t('okr.outOf', { target: number(result.target), unit: result.unit })}</span></>}</div>
    {percent !== null && <div className="okr-progress" role="progressbar" aria-label={result.title} aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(percent)}><i style={{ width: `${percent}%` }} /></div>}
    {!compact && <>
      <div className="okr-result-meta"><span>{t(result.mode === 'increase' ? 'okr.growth' : result.mode === 'atMost' ? 'okr.ceiling' : 'okr.threshold')}</span>{percent !== null && <b>{number(percent)}%</b>}</div>
      <p className="okr-muted">{result.latest ? t('okr.latestValue', { value: number(result.latest.value), unit: result.unit, date: day(result.latest.date) }) : t('okr.noEvidence')}</p>
      <p className="okr-delta">{result.delta === null ? t('okr.noDailyComparison') : t('okr.latestDelta', { value: new Intl.NumberFormat(locale, { signDisplay: 'always', maximumFractionDigits: 2 }).format(result.delta), unit: result.unit })}</p>
    </>}
  </article>
}
