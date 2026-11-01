import { guideModules } from './guide-modules'
const steps = ['model', 'agents', 'project', 'task']
export function onboardingTitle(route: string): string {
  const [, part, selected] = route.split('/')
  if (part === 'model' && selected) return route.split('/')[3] ? route.split('/')[3] === 'source' ? 'hub.editConnection' : 'hub.editModel' : 'onboarding.step.model'
  if (part === 'agents' && selected === 'roami') return 'hub.roamiModels'
  if (part === 'tour') return guideModules.some(module => module.id === selected) ? 'onboarding.guide.' + selected + '.title' : 'onboarding.guide.title'
  return steps.includes(part) ? 'onboarding.step.' + part : 'onboarding.title'
}
export function onboardingBack(route: string): string {
  const parts = route.split('/')
  const [, part, selected] = parts
  if (part === 'model' && selected) return parts.length > 3 ? 'onboarding/model' : 'onboarding'
  if (part === 'agents' && selected === 'roami') return 'onboarding/agents'
  if (parts.length > 3) return parts.slice(0, -1).join('/')
  return selected ? 'onboarding/' + part : part ? 'onboarding' : 'home'
}
