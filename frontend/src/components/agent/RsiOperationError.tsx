import { useI18n } from '../../i18n'

export function RsiOperationError({ code }: { code: string }) {
  const { t } = useI18n()
  if (!code) return null
  const key = 'agent.rsi.error.' + code, text = t(key)
  return <div className="agent-rsi-error" role="alert"><p>{text === key ? t('agent.rsi.actionFailed') : text}</p><details><summary>{t('agent.rsi.errorDetails')}</summary><code>{code}</code></details></div>
}
