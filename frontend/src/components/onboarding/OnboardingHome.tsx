import type { ReactNode } from 'react'
import { useOnboardingState } from './onboarding-state'
import OnboardingChecklist from './OnboardingChecklist'
export default function OnboardingHome({ active, onNav, children }: { active: boolean; onNav: (route: string) => void; children: ReactNode }) {
  const state = useOnboardingState(active)
  return active && state.visible && !state.failed ? <div className="onboarding-page"><div className="onboarding-scroll"><OnboardingChecklist onNav={onNav} /></div></div> : <>{children}</>
}
