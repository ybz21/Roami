import { getHashParams, setHashParams } from '../../route-hash'

export type ModelSettingsTab = 'models' | 'proxy' | 'prices'
export function readModelSettingsTab(): ModelSettingsTab {
  const value = getHashParams().get('modelTab')
  return value === 'proxy' || value === 'prices' ? value : 'models'
}
export function modelSettingsHref(tab: ModelSettingsTab): string {
  const params = getHashParams()
  params.set('modelTab', tab)
  return '#/settings/agent/runtime?' + params.toString()
}
export function writeModelSettingsTab(tab: ModelSettingsTab) {
  setHashParams({ ...Object.fromEntries(getHashParams()), modelTab: tab === 'models' ? '' : tab })
}
