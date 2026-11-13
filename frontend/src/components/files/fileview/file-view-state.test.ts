import { describe, it, expect, beforeEach } from 'vitest'
import { createFileViewState } from './file-view-state'
import { WorkspaceStateStore } from '../../../workspace-state'

let memory: ReturnType<typeof createFileViewState>
describe('文件视图状态记忆', () => {
  beforeEach(() => { memory = createFileViewState(new WorkspaceStateStore().scope('file-views')) })

  it('滚动位置按路径各记各的，没记过给 0', () => {
    memory.rememberScroll('/a.md', 480)
    memory.rememberScroll('/b.md', 12)
    expect(memory.recallScroll('/a.md')).toBe(480)
    expect(memory.recallScroll('/b.md')).toBe(12)
    expect(memory.recallScroll('/c.md')).toBe(0)
  })

  it('Monaco 视图状态原样存取；空值不存', () => {
    const st = { viewState: { scrollTop: 99 } }
    memory.rememberEditorView('/x.ts', st)
    memory.rememberEditorView('/y.ts', null)
    expect(memory.recallEditorView('/x.ts')).toEqual(st)
    expect(memory.recallEditorView('/y.ts')).toBeUndefined()
  })

  it('超过上限淘汰最久没用的；再记一次就算「刚用过」', () => {
    for (let i = 0; i < 200; i++) memory.rememberScroll(`/f${i}`, i + 1)
    memory.rememberScroll('/f0', 7) // 重新用到 f0
    memory.rememberScroll('/new', 1) // 挤掉一个：该是 f1，不是 f0
    expect(memory.recallScroll('/f0')).toBe(7)
    expect(memory.recallScroll('/f1')).toBe(0)
    expect(memory.recallScroll('/new')).toBe(1)
  })

  it('关掉标签可以整个忘掉', () => {
    memory.rememberScroll('/a.md', 10); memory.rememberEditorView('/a.md', { x: 1 })
    memory.forgetViewState('/a.md')
    expect(memory.recallScroll('/a.md')).toBe(0)
    expect(memory.recallEditorView('/a.md')).toBeUndefined()
  })
})
