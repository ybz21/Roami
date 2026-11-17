import { useI18n } from '../../i18n'
import type { GatewayModel } from './gateway-model-catalog'
import './model-capabilities.css'

export default function ModelCapabilities({ model }: { model?: GatewayModel }) {
  const { t, locale } = useI18n()
  const modalities = (values?: string[]) => values?.length ? new Intl.ListFormat(locale, { style: 'short', type: 'conjunction' }).format(values.map(value => t('directory.modality.' + value))) : t('modelCapabilities.unknown')
  const features = ['tools', 'reasoning', 'structuredOutput'].filter(key => model?.capabilities?.[key]?.support === 'supported')
  return <span className="tt-model-capabilities">
    <span>{t('directory.inputs')}: {modalities(model?.inputModalities)}</span>
    <span>{t('directory.outputs')}: {modalities(model?.outputModalities)}</span>
    {!!features.length && <span>{features.map(key => t('directory.' + key)).join(' · ')} <span className="tt-model-evidence">{t('modelCapabilities.advertised')}</span></span>}
    {model?.kind === 'aggregate' && <span>{t('modelCapabilities.byMember')}</span>}
  </span>
}
