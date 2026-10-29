export const rsiModelErrors = new Set(['MODEL_NOT_CONFIGURED', 'MODEL_IMAGES_UNSUPPORTED', 'RSI_INDEPENDENT_RATERS_REQUIRED', 'RSI_ARTIFACT_CALIBRATION_CHANGED', 'RSI_ARTIFACT_PROFILE_CHANGED', 'RSI_ARTIFACT_SETTINGS_REQUIRED'])
export function rsiErrorMessage(code: string, t: (key: string, vars?: Record<string, string | number>) => string) {
  const key = 'agent.rsi.error.' + code, message = t(key)
  return message === key ? t('agent.rsi.operationFailed', { code }) : message
}
