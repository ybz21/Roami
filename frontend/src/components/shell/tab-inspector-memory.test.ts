// @vitest-environment jsdom
import { beforeEach, describe, expect, it } from 'vitest'
import { nextInspector, pruneTabInspector, recallTabInspector, rememberTabInspector, tabKey } from './tab-inspector-memory'

const SESS = '2026-0914-1030-ab12'
const FILE = '/home/ai/codes/ttmux/AGENTS.md'

beforeEach(() => localStorage.clear())

describe('标签身份', () => {
  it('文件标签压过会话标签——同一条标签条上当前只有一个在前台', () => {
    expect(tabKey({ active: SESS, activeFile: FILE })).toBe(`f:${FILE}`)
  })
  it('没有文件标签时是会话标签', () => {
    expect(tabKey({ active: SESS, activeFile: '' })).toBe(`s:${SESS}`)
  })
  it('什么都没开就是空键（空键不存也不取）', () => {
    expect(tabKey({ active: '', activeFile: '' })).toBe('')
    rememberTabInspector('', { collapsed: false, panel: 'git' })
    expect(localStorage.getItem('roam.tabInspector')).toBeNull()
    expect(recallTabInspector('')).toBeNull()
  })
})

describe('记住与取回', () => {
  it('存了就取得回来', () => {
    rememberTabInspector(`s:${SESS}`, { collapsed: false, panel: 'git' })
    expect(recallTabInspector(`s:${SESS}`)).toEqual({ collapsed: false, panel: 'git' })
  })
  it('没记过的标签返回 null，由调用方保持现状', () => {
    expect(recallTabInspector(`f:${FILE}`)).toBeNull()
    expect(nextInspector(null, { collapsed: true, panel: 'files' })).toEqual({ collapsed: true, panel: 'files' })
  })
  it('记过就按记的来，哪怕和当前不一样', () => {
    expect(nextInspector({ collapsed: false, panel: 'git' }, { collapsed: true, panel: 'files' }))
      .toEqual({ collapsed: false, panel: 'git' })
  })
  it('两个标签各记各的', () => {
    rememberTabInspector(`s:${SESS}`, { collapsed: false, panel: 'git' })
    rememberTabInspector(`f:${FILE}`, { collapsed: true, panel: 'files' })
    expect(recallTabInspector(`s:${SESS}`)?.collapsed).toBe(false)
    expect(recallTabInspector(`f:${FILE}`)?.collapsed).toBe(true)
  })
  it('坏掉的 localStorage 内容当没记过，不抛', () => {
    localStorage.setItem('roam.tabInspector', '{"s:x": 3, "s:y": {"collapsed": "no"}, ][')
    expect(recallTabInspector('s:x')).toBeNull()
    expect(() => rememberTabInspector('s:z', { collapsed: true, panel: 'files' })).not.toThrow()
    expect(recallTabInspector('s:z')).toEqual({ collapsed: true, panel: 'files' })
  })
  it('面板名不认识就退回文件面板', () => {
    localStorage.setItem('roam.tabInspector', JSON.stringify({ 's:x': { collapsed: false, panel: 'wat' } }))
    expect(recallTabInspector('s:x')).toEqual({ collapsed: false, panel: 'files' })
  })
})

describe('关掉的标签不留记录', () => {
  it('只留还开着的那些', () => {
    rememberTabInspector(`s:${SESS}`, { collapsed: false, panel: 'git' })
    rememberTabInspector('s:gone', { collapsed: true, panel: 'files' })
    rememberTabInspector(`f:${FILE}`, { collapsed: false, panel: 'files' })
    pruneTabInspector([`s:${SESS}`, `f:${FILE}`])
    expect(recallTabInspector('s:gone')).toBeNull()
    expect(recallTabInspector(`s:${SESS}`)).not.toBeNull()
    expect(recallTabInspector(`f:${FILE}`)).not.toBeNull()
  })
  // 刷新后「标签还原」和「URL 回写」在同一轮里跑，回写那次手里的标签还是空的。
  // 把空当成「一个标签都没开」去清，就是每次刷新都忘光。
  it('一个键都没有时按「还没还原完」处理，表原样不动', () => {
    rememberTabInspector('s:a', { collapsed: true, panel: 'files' })
    pruneTabInspector([])
    expect(recallTabInspector('s:a')).toEqual({ collapsed: true, panel: 'files' })
  })
})
