import { useEffect, useRef, useState } from 'react'
import { Alert, Button } from 'antd'
import { api } from '../../api'
import { useI18n } from '../../i18n'
import { useOnboardingFieldFocus } from './onboarding-field-focus'
import RoamiAgentModels from '../capabilities/RoamiAgentModels'
import { onboardingChanged, useOnboardingState } from './onboarding-state'

export default function OnboardingRoami({ onNav, onReadyChange }: { onNav: (route: string) => void; onReadyChange: (ready: boolean) => void }) {
  const { t } = useI18n(), state = useOnboardingState()
  const focus = useOnboardingFieldFocus()
  const [applied, setApplied] = useState(false), [busy, setBusy] = useState(false), [error, setError] = useState('')
  const live = useRef(true)
  useEffect(() => { live.current = true; return () => { live.current = false } }, [])
  const ready = applied && !!state.value?.models.verified && !busy && !error
  useEffect(() => { onReadyChange(ready); return () => onReadyChange(false) }, [ready, onReadyChange])
  const verify = async () => {
    if (!applied || busy) return
    setBusy(true); setError('')
    try {
      const { data } = await api('POST', '/agent/model-settings/verify')
      if (!live.current) return
      if (!data?.verified) throw new Error('MODEL_VERIFICATION_FAILED')
    } catch { if (live.current) setError(t('onboarding.modelSavedUnverified')) }
    finally { if (live.current) { setBusy(false); onboardingChanged() } }
  }
  return <div {...focus}>
    <p className="onboarding-note">{t('onboarding.mainIntro')}</p>
    <Button onClick={() => onNav('onboarding/model')}>{t('hub.manageSources')}</Button>
    <RoamiAgentModels inline onBack={() => {}} onSelectionChange={setApplied} />
    {error && <Alert type="error" message={error} />}
    <div className="onboarding-actions"><Button type="primary" disabled={!applied || state.loading} loading={busy} onClick={() => { void verify() }}>{t('onboarding.verify')}</Button><span role="status">{t(ready ? 'onboarding.verified' : 'onboarding.pending')}</span></div>
    <p className="onboarding-note">{t('onboarding.verifyHint')}</p>
  </div>
}
