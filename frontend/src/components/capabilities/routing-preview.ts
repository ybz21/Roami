import type { CatalogModel } from './model-hub-api'
export const MAX_AGGREGATE_MEMBERS = 64
export const candidateIdentity = (candidate: { sourceId: string; model: string }) => candidate.sourceId + '/' + candidate.model

// A fresh scheduling cycle illustrates configuration; runtime account state is deliberately absent.
export function previewRounds(model: CatalogModel, excluded: string, count = 12): string[] | null {
  const members = model.candidates.filter(row => candidateIdentity(row) !== excluded)
  if (!members.length) return []
  if (!['order', 'drain', 'rotate', 'weight'].includes(model.strategy)) return null
  const scores = members.map(() => 0)
  const weights = members.map(row => model.weights?.[candidateIdentity(row)] ?? 1)
  if (weights.some(weight => !Number.isInteger(weight) || weight < 1 || weight > 1000)) return []
  const total = weights.reduce((sum, weight) => sum + weight, 0)
  return Array.from({ length: count }, (_, round) => {
    let winner = 0
    if (model.strategy === 'rotate') winner = round % members.length
    if (model.strategy === 'weight') {
      for (let index = 0; index < scores.length; index++) {
        scores[index] += weights[index]
        if (scores[index] > scores[winner]) winner = index
      }
      scores[winner] -= total
    }
    return candidateIdentity(members[winner])
  })
}
