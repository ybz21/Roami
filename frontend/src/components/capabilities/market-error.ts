export function marketError(caught: unknown, fallback: 'loadFailed' | 'previewFailed', t: (key: string) => string) {
  const error = caught as { apiError?: { code?: unknown }; message?: string; name?: string; status?: number } | null
  const candidate = typeof error?.apiError?.code === 'string' ? error.apiError.code : error?.message
  const code = typeof candidate === 'string' && /^[A-Z][A-Z0-9_]{0,79}$/.test(candidate) ? candidate : ''
  const status = error?.status
  const httpStatus = typeof status === 'number' && Number.isInteger(status) && status >= 400 && status <= 599 ? status : undefined
  const key = 'capabilities.error.' + code
  const translated = code ? t(key) : key
  return {
    message: translated !== key ? translated : t('capabilities.market.error.' + (error?.name === 'TypeError' ? 'network' : fallback)),
    diagnostic: [code, httpStatus ? 'HTTP ' + httpStatus : ''].filter(Boolean).join(' · '),
  }
}
