import { expect, it } from 'vitest'
import type { CatalogModel } from './model-hub-api'
import { previewRounds } from './routing-preview'
const model: CatalogModel = { id: 'pool', name: 'Pool', protocol: 'openai-completions', aggregate: true, strategy: 'weight', weights: { 'a/one': 3, 'b/two': 1 }, candidates: [{ sourceId: 'a', model: 'one' }, { sourceId: 'b', model: 'two' }] }
it('illustrates smooth weighted distribution and skips unavailable members', () => {
 const rounds = previewRounds(model, '')!
 expect(rounds.filter(id => id === 'a/one')).toHaveLength(9)
 expect(rounds.filter(id => id === 'b/two')).toHaveLength(3)
 expect(rounds.slice(0, 4)).toEqual(['a/one', 'a/one', 'b/two', 'a/one'])
 expect(new Set(previewRounds(model, 'a/one'))).toEqual(new Set(['b/two']))
 expect(previewRounds({ ...model, strategy: 'rotate' }, '')?.slice(0, 4)).toEqual(['a/one', 'b/two', 'a/one', 'b/two'])
 expect(previewRounds({ ...model, strategy: 'smart' }, '')).toBeNull()
})
