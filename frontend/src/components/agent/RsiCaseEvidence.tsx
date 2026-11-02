import { useI18n } from '../../i18n'
import { ChevronRight } from '../../icons'
import RsiAudioEvidence from './RsiAudioEvidence'
type Fields = Record<string, unknown>
const fields = (value: unknown): Fields => value && typeof value === 'object' && !Array.isArray(value) ? value as Fields : {}
const score = (value: unknown): value is number => typeof value === 'number' && Number.isFinite(value) && value >= 0 && value <= 1
function CaseEvidenceBody({ evidence }: { evidence: unknown }) {
  const { t } = useI18n(), value = fields(evidence), native = fields(value.native_judgment)
  const afterTimeout = native.artifact_assessment_after_timeout === true
  const assessmentError = afterTimeout && typeof native.artifact_assessment_error === 'string' && /^[A-Z][A-Z0-9_]{0,100}$/.test(native.artifact_assessment_error) ? native.artifact_assessment_error : undefined
  const metric = native.native_verifier_ran !== false && score(native.native_metric) ? native.native_metric : undefined
  const minimum = score(native.native_metric_minimum) ? native.native_metric_minimum : undefined
  const references = native.native_verifier_ran !== false && Array.isArray(native.native_reference_results) && native.native_reference_results.length <= 8 && native.native_reference_results.every(value => value === null || score(value)) ? native.native_reference_results : []
  const partial = fields(native.native_partial)
  const hasPartial = native.native_verifier_ran !== false && Number.isInteger(partial.total_points) && Number(partial.total_points) > 0 && Number.isInteger(partial.unscored_points) && Number(partial.unscored_points) >= 0 && (partial.scored_points === null || Number.isInteger(partial.scored_points) && Number(partial.scored_points) >= 0)
  const metrics = fields(value.metrics), tools = Array.isArray(value.tools) ? value.tools.map(fields) : []
  const files = Array.isArray(value.files) ? value.files.filter((file): file is string => typeof file === 'string') : []
  return <>
    {(afterTimeout || native.native_verifier_ran === false || metric !== undefined || minimum !== undefined || references.length > 0 || hasPartial) && <dl className="rsi-result-facts rsi-native-evidence">
      {afterTimeout && <div><dt>{t('agent.rsiResults.assessmentTiming')}</dt><dd>{t('agent.rsiResults.assessmentAfterTimeout')}</dd></div>}
      {native.native_verifier_ran === false && <div><dt>{t('agent.rsiResults.nativeJudgment')}</dt><dd>{t('agent.rsiResults.nativeNotRun')}</dd></div>}
      {metric !== undefined && <div><dt>{t('agent.rsiResults.nativeScore')}</dt><dd>{String(metric)}</dd></div>}
      {minimum !== undefined && <div><dt>{t('agent.rsiResults.nativeMinimum')}</dt><dd>{String(minimum)}</dd></div>}
      {references.length > 0 && <div><dt>{t('agent.rsiResults.nativeReferences')}</dt><dd>{references.map((value, index) => <span key={index}>{t('agent.rsiResults.nativeReference', { index: index + 1, score: value === null ? t('agent.rsiResults.nativeUnscored') : String(value) })}{index < references.length - 1 ? ' · ' : ''}</span>)}</dd></div>}
      {hasPartial && <div><dt>{t('agent.rsiResults.nativePoints')}</dt><dd>{partial.scored_points === null ? t('agent.rsiResults.nativeUnscored') : t('agent.rsiResults.nativePartial', { score: Number(partial.scored_points), total: Number(partial.total_points) })}{Number(partial.unscored_points) > 0 && <p>{t('agent.rsiResults.nativeUnscoredCount', { count: Number(partial.unscored_points) })}</p>}</dd></div>}
    </dl>}
    <RsiAudioEvidence native={native} />
    {(assessmentError || tools.length > 0 || files.length > 0 || metrics.tokens !== undefined || metrics.model_calls !== undefined) && <details className="rsi-disclosure rsi-case-execution"><summary>{t('agent.rsiResults.executionRecords')}<ChevronRight size={15} /></summary>
      {assessmentError && <p>{t('agent.rsiResults.assessmentError')} <code>{assessmentError}</code></p>}
      {typeof metrics.model_calls === 'number' && <p>{t('agent.rsiResults.modelCalls', { count: metrics.model_calls })}</p>}
      {metrics.token_coverage === 'unknown' || metrics.tokens === null ? <p>{t('agent.rsiResults.usageUnknown')}</p> : typeof metrics.tokens === 'number' && <p>{t('agent.rsiResults.tokenUsage', { count: metrics.tokens })}</p>}
      {tools.length > 0 && <><h4>{t('agent.rsiResults.toolRecords')}</h4><ul>{tools.map((tool, index) => <li key={index}><code>{String(tool.name || '')}</code> · {t('agent.pipeline.nodeState.' + tool.state) === 'agent.pipeline.nodeState.' + tool.state ? String(tool.state || '') : t('agent.pipeline.nodeState.' + tool.state)}{typeof tool.error === 'string' && <code> · {tool.error}</code>}</li>)}</ul></>}
      {files.length > 0 && <><h4>{t('agent.rsiResults.workspaceFiles')}</h4><ul>{files.map(file => <li key={file}><code>{file}</code></li>)}</ul></>}
    </details>}
  </>
}

export default function RsiCaseEvidence({ evidence }: { evidence: unknown }) {
  const { t } = useI18n(), arms = fields(fields(evidence).arm_results)
  const paired = ['baseline', 'candidate'].filter(arm => arms[arm] && typeof arms[arm] === 'object')
  return paired.length ? <>{paired.map(arm => <section key={arm}><h4>{t('agent.rsiResults.' + arm + 'Arm')}</h4><CaseEvidenceBody evidence={arms[arm]} /></section>)}</> : <CaseEvidenceBody evidence={evidence} />
}
