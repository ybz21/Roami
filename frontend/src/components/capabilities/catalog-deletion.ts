import type { CatalogModel, ModelCatalog, ModelSource } from './model-hub-api'

export type CatalogDeletion = { kind: 'source'; item: ModelSource } | { kind: 'model'; item: CatalogModel }

const names = ({ id, gatewayAlias, aliases }: CatalogModel) => [id, ...(gatewayAlias ? [gatewayAlias] : []), ...(aliases || [])]
const displayName = ({ id, name }: CatalogModel) => name || id

export function planCatalogDeletion(catalog: ModelCatalog, { kind, item }: CatalogDeletion) {
  const source = kind === 'source'
  const usesSource = (model: CatalogModel) => model.candidates.some(candidate => candidate.sourceId === item.id)
  const removedModels = source
    ? catalog.models.filter(model => !model.aggregate && model.candidates.length && model.candidates.every(candidate => candidate.sourceId === item.id))
    : catalog.models.filter(model => model.id === item.id)
  const removedIds = new Set(removedModels.map(model => model.id))
  const retained = catalog.models.filter(model => !removedIds.has(model.id))
  const drafts = source ? catalog.drafts : catalog.drafts.filter(model => model.id !== item.id)
  const targetNames = source ? [] : names(item)
  const references = [...retained, ...drafts].filter(model => source ? usesSource(model) : item.aggregate && model.candidates.some(candidate => candidate.sourceId === '@group' && targetNames.includes(candidate.model)))
  const models = [...new Set(references.map(displayName))]
  const clients = [...new Set(removedModels.flatMap(model => names(model).flatMap(name => catalog.uses[name] || [])))]
  return {
    models, clients, removedIds,
    next: { ...catalog, sources: source ? catalog.sources.filter(row => row.id !== item.id) : catalog.sources, models: retained, drafts },
  }
}
