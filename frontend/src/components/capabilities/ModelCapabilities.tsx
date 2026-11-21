import { useI18n } from '../../i18n'
import type { ModelDirectoryEntry } from './model-hub-api'
import { freeGatewayModel } from './gateway-model-catalog'
import './model-capabilities.css'

export default function ModelCapabilities({ model }: { model?: ModelDirectoryEntry }) {
  const { t, locale } = useI18n()
  const aggregate = model?.kind === 'aggregate'
  const modalities = (values?: string[]) => values?.length ? values.map(value => t('directory.modality.' + value)).join(' / ') : t(aggregate ? 'gatewayOptions.byMember' : 'directory.unknown')
  const input = model?.inputModalities?.length ? model.inputModalities : ['text', 'image', 'audio', 'video'].filter(key => model?.capabilities?.[key]?.support === 'supported')
  const features = ['tools', 'reasoning', 'structuredOutput', 'streaming'].filter(key => model?.capabilities?.[key]?.support === 'supported')
  return <span className="tt-model-option-facts">
    <span>{t('directory.inputs')}: {modalities(input)}<span className="tt-model-option-separator" />{t('directory.outputs')}: {modalities(model?.outputModalities)}</span>
    <span className="tt-model-option-features"><span className={'tt-model-price' + (model && freeGatewayModel(model) ? ' is-free' : '')}>{t('gatewayOptions.price.' + (model?.freeOnly ? 'free-only' : aggregate && model?.pricing !== 'confirmed-free' ? 'by-member' : model?.pricing || 'unknown'))}</span>{features.map(key => <span key={key}>{t('modelSelection.capability.' + key)}</span>)}{!!features.length && <span className="tt-model-evidence">{t('modelCapabilities.advertised')}</span>}{!!model?.contextWindow && <span>{t('directory.context')}: {new Intl.NumberFormat(locale, { notation: 'compact', maximumFractionDigits: 1 }).format(model.contextWindow)}</span>}</span>
  </span>
}
