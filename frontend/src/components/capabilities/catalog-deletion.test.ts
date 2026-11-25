import { expect, it } from 'vitest'
import { planCatalogDeletion } from './catalog-deletion'
import type { CatalogModel, ModelCatalog, ModelSource } from './model-hub-api'

const source: ModelSource = { id: 'primary', name: 'Primary', baseUrl: 'https://example.test', protocol: 'openai-completions', authMode: 'bearer' }
const backup = { ...source, id: 'backup' }
const direct: CatalogModel = {
  id: 'coding', name: 'Coding', protocol: source.protocol, strategy: 'fixed', gatewayAlias: 'current', aliases: ['old'],
  candidates: [{ sourceId: source.id, model: 'upstream' }],
}
const pool: CatalogModel = { ...direct, id: 'pool', name: 'Free pool', strategy: 'smart', aggregate: true, gatewayAlias: 'free', aliases: ['old-pool'] }
const catalog: ModelCatalog = { revision: 'r1', baseUrl: '', sources: [source, backup], models: [direct], drafts: [], uses: {} }

it('preserves cross-source routes and reports consumers through aliases', () => {
  const failover: CatalogModel = { ...direct, id: 'fallback', name: 'Fallback', strategy: 'failover', candidates: [...direct.candidates, { sourceId: backup.id, model: 'upstream' }] }
  const plan = planCatalogDeletion({ ...catalog, models: [direct, failover, pool], uses: { old: ['roami'], current: ['roami', 'codex'] } }, { kind: 'source', item: source })
  expect(plan.models).toEqual(['Fallback', 'Free pool'])
  expect(new Set(plan.clients)).toEqual(new Set(['roami', 'codex']))
  expect([...plan.removedIds]).toEqual([direct.id])
})

it('detects a nested pool reference through an alias, including when the parent is disabled', () => {
  const parent = { ...pool, id: 'parent', name: 'Parent', enabled: false, candidates: [{ sourceId: '@group', model: 'old-pool' }] }
  const plan = planCatalogDeletion({ ...catalog, models: [direct, pool, parent] }, { kind: 'model', item: pool })
  expect(plan.models).toEqual(['Parent'])
})

it('deletes a standalone gateway route without removing its upstream candidate from pools', () => {
  const plan = planCatalogDeletion({ ...catalog, models: [direct, pool] }, { kind: 'model', item: direct })
  expect(plan.models).toEqual([])
  expect(plan.next.models).toEqual([pool])
  expect(plan.next.sources).toEqual(catalog.sources)
})
