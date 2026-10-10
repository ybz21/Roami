import { describe, expect, it } from 'vitest'
import { tabCloseTargets } from './tab-actions'

describe('tabCloseTargets', () => {
  const order = ['p:projects', 't:one', 'f:note', 't:two', 'p:browser']
  const pinned = new Set(['p:projects', 'f:note'])

  it('keeps pinned tabs and the selected tab when closing others', () => {
    expect(tabCloseTargets(order, pinned, 't:one', 'others')).toEqual(['t:two', 'p:browser'])
  })

  it('uses visible order for left and right actions', () => {
    expect(tabCloseTargets(order, pinned, 't:two', 'left')).toEqual(['t:one'])
    expect(tabCloseTargets(order, pinned, 't:one', 'right')).toEqual(['t:two', 'p:browser'])
  })

  it('ignores tabs already removed', () => {
    expect(tabCloseTargets(order, pinned, 'missing', 'others')).toEqual([])
  })
})
