import { describe, it, expect, beforeEach } from 'vitest'
import { rememberScroll, recallScroll, rememberEditorView, recallEditorView, forgetViewState, resetViewStateMemory } from './view-state-memory'

describe('文件视图状态记忆', () => {
  beforeEach(() => resetViewStateMemory())

  it('滚动位置按路径各记各的，没记过给 0', () => {
    rememberScroll('/a.md', 480)
    rememberScroll('/b.md', 12)
    expect(recallScroll('/a.md')).toBe(480)
    expect(recallScroll('/b.md')).toBe(12)
    expect(recallScroll('/c.md')).toBe(0)
  })

  it('Monaco 视图状态原样存取；空值不存', () => {
    const st = { viewState: { scrollTop: 99 } }
    rememberEditorView('/x.ts', st)
    rememberEditorView('/y.ts', null)
    expect(recallEditorView('/x.ts')).toBe(st)
    expect(recallEditorView('/y.ts')).toBeUndefined()
  })

  it('超过上限淘汰最久没用的；再记一次就算「刚用过」', () => {
    for (let i = 0; i < 200; i++) rememberScroll(`/f${i}`, i + 1)
    rememberScroll('/f0', 7) // 重新用到 f0
    rememberScroll('/new', 1) // 挤掉一个：该是 f1，不是 f0
    expect(recallScroll('/f0')).toBe(7)
    expect(recallScroll('/f1')).toBe(0)
    expect(recallScroll('/new')).toBe(1)
  })

  it('关掉标签可以整个忘掉', () => {
    rememberScroll('/a.md', 10); rememberEditorView('/a.md', { x: 1 })
    forgetViewState('/a.md')
    expect(recallScroll('/a.md')).toBe(0)
    expect(recallEditorView('/a.md')).toBeUndefined()
  })
})
