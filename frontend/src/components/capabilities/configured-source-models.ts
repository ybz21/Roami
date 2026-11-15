import type { CatalogModel } from './model-hub-api'

// Source membership belongs to saved primary models, never aggregate references or backups.
export const configuredSourceModels = (models: CatalogModel[], sourceId: string) => models.filter(model => !model.aggregate && model.candidates[0]?.sourceId === sourceId)
export const configuredSourceModelIds = (models: CatalogModel[], sourceId: string) => [...new Set(configuredSourceModels(models, sourceId).map(model => model.candidates[0].model))]
