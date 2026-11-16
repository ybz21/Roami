import evidence from './model-evidence.json'

export type Model = {
  id: string
  name: string
  kind: 'single' | 'aggregate' | 'router' | 'unknown'
  upstream: string
  inputs: string[]
  tools: boolean | null
  reasoning: boolean | null
  schema: boolean | null
  free: boolean | null
  context: number | null
  configured?: boolean
  sourceId?: string
  sourceName?: string
  strategy?: 'smart' | 'weight'
  freeOnly?: boolean
  members?: { id: string; weight: number }[]
}
const identities = [
  ['or-lightning-free', 'nvidia/nemotron-3.5-lightning:free'],
  ['or-super-vl-free', 'nvidia/nemotron-3.5-super-vl:free'],
  ['or-free-router', 'openrouter/free'],
  ['or-particle-free', 'particle-ai/particle-1:free'],
  ['or-flint-free', 'recursive/flint-v1.0:free'],
  ['or-inkling-free', 'thinkingmachines/inkling-2-small:free'],
]
export const models: Model[] = identities.map(([id, upstream]) => {
  const row = evidence.models.find(item => item.id === upstream)!
  return { id, upstream, name: row.name, sourceId: 'openrouter', sourceName: 'OpenRouter', kind: upstream === 'openrouter/free' ? 'router' : 'single',
    inputs: row.architecture.input_modalities, tools: row.supported_parameters.includes('tools'),
    reasoning: row.supported_parameters.includes('reasoning'), schema: row.supported_parameters.includes('structured_outputs'),
    free: row.pricing.prompt === '0' && row.pricing.completion === '0', context: row.context_length }
})
models.push(...['hy4free', 'workbuddy-hy4'].map(id => ({ id, upstream: id, name: id === 'workbuddy-hy4' ? 'WorkBuddy Hy4' : id,
  kind: 'unknown' as const, inputs: [], tools: null, reasoning: null, schema: null, free: null, context: null })))
export const pool: Model = { id: 'free-pool', upstream: '', name: 'Auto · Free pool', kind: 'aggregate', inputs: [],
  tools: null, reasoning: null, schema: null, free: null, context: null, strategy: 'smart', freeOnly: true,
  members: [{ id: 'or-lightning-free', weight: 1 }, { id: 'or-super-vl-free', weight: 1 }, { id: 'or-particle-free', weight: 1 }] }
export const choices: Model[] = [pool, { ...pool, id: 'coding-pool', name: 'Coding pool', strategy: 'weight', freeOnly: false,
  members: [{ id: 'or-particle-free', weight: 3 }, { id: 'or-super-vl-free', weight: 1 }] }, ...models,
  { ...models[0], id: 'backup-lightning', name: 'Lightning · 备用来源', sourceId: 'openrouter-backup', sourceName: 'OpenRouter 备用（演示）', configured: false }]
export const kindLabel = { single: '具体模型', aggregate: 'Roami 聚合', router: '上游自动路由', unknown: '类型待核对' }
export const caps = [['image', '图片输入'], ['audio', '音频输入'], ['video', '视频输入'], ['file', '文件输入'],
  ['tools', '工具调用'], ['reasoning', '推理'], ['schema', 'JSON Schema'], ['free', '目录零价']]
export function supports(model: Model, cap: string): boolean {
  return cap === 'tools' ? model.tools === true : cap === 'reasoning' ? model.reasoning === true
    : cap === 'schema' ? model.schema === true : cap === 'free' ? model.free === true : model.inputs.includes(cap)
}
export function eligibleMembers(model: Model, requirements: string[], catalog: Model[], freeOnly = false): Model[] {
  return (model.members || []).flatMap(member => {
    const item = catalog.find(row => row.id === member.id)
    return item && item.configured !== false && item.kind === 'single' && requirements.every(cap => supports(item, cap)) &&
      (!(freeOnly || model.freeOnly) || item.free === true) ? [item] : []
  })
}
export function matches(model: Model, requirements: string[], catalog: Model[] = choices): boolean {
  return model.kind === 'aggregate' ? eligibleMembers(model, requirements, catalog).length > 0
    : requirements.every(cap => supports(model, cap))
}
export const findModel = (id: string, catalog: Model[] = choices) => catalog.find(model => model.id === id) || models[7]
export const capabilitySummary = (model: Model) => model.kind === 'aggregate' ? '按任务要求筛选成员'
  : model.tools === null ? '能力待核对'
  : [model.inputs.includes('image') ? '图片输入' : '文本输入', model.tools && '工具调用', model.reasoning && '推理'].filter(Boolean).join(' / ')
